"""What the maintenance agent is allowed to propose, and who actually does it.

THE RULE THIS MODULE EXISTS TO ENFORCE: **the agent proposes, the code executes.**
The agent never touches systemd, never runs git, never restarts anything. It emits a
proposal whose ``kind`` comes from a closed set, and everything below re-validates
that proposal from scratch before a single side effect happens.

Why the paranoia is proportionate: the agent's input contains error strings and
diagnostics that originated on somebody else's website. That is a prompt-injection
surface, and no amount of careful wording in a system prompt closes it. What closes
it is that the permitted actions live in the ``ALLOWED_*`` tuples below — in an
``if``, in Python, where no sentence can argue with them — and that the privileged
wrapper checks them a second time in a different language (``maintenance_bridge``).

So a fully hijacked model can, at most, propose one of five things, three of which a
human must still approve.

THE ONE ASYMMETRY WORTH KNOWING: ``apply_patch`` is never auto-executable, at any
setting, and its diff may not touch ``migrations/``. Reverting a deploy restores the
CODE and not the schema, so a patch that migrated on the way in leaves a database the
reverted code does not expect — a worse failure than the one being escaped.
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from realdata.models import MaintenanceProposal
from realdata.services import maintenance_bridge

log = logging.getLogger(__name__)

# Units the agent may PROPOSE restarting — the scheduled jobs, all of which are
# idempotent oneshots.
#
# The wrapper's own list is deliberately WIDER: it also contains `vfoot` (the web
# server), because applying a patch has to restart the app. That asymmetry is the
# point and not an oversight — the executor may restart the app as the last step of
# a flow a human approved; the agent may never ask for it as an action in itself.
# Do not "fix" the two lists into agreement.
ALLOWED_UNITS = (
    "vfoot-tick", "vfoot-calendar", "vfoot-tm-poll", "vfoot-egress-refill",
    "vfoot-market", "vfoot-nudge", "vfoot-health",
)

# Management commands the agent may ask to re-run. Read-mostly and idempotent by
# construction — nothing here can destroy data if it runs twice, or ten times.
ALLOWED_COMMANDS = (
    "sync_calendar", "tick", "poll_transfermarkt", "health_report",
)

# How long the executor waits before the dead-man timer re-checks and, unless the
# server is healthy, reverts. Long enough for a restart plus one tick (the tick's
# own timer fires every minute); short enough that a broken production is broken for
# five minutes, not all night.
ROLLBACK_DELAY_SECONDS = 300


class Refused(Exception):
    """The proposal did not survive validation. Never executed, always recorded."""


# -- the repository ----------------------------------------------------------

def _repo_root() -> Path:
    return Path(getattr(settings, "VFOOT_REPO_ROOT", settings.REPO_ROOT))


def git(*args: str, timeout: float = 120.0) -> tuple[bool, str]:
    """Run git in the checkout as the app user. No sudo: the repo is vfoot's."""
    try:
        r = subprocess.run(["git", *args], cwd=str(_repo_root()),
                           capture_output=True, text=True, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    return r.returncode == 0, (r.stdout + r.stderr).strip()


# -- validation --------------------------------------------------------------

def fingerprint(kind: str, payload: dict) -> str:
    """Stable identity for "this exact proposal", used to avoid re-proposing
    something already rejected. Keys are sorted so a reordered dict is the same
    proposal — the agent regenerates its JSON every pass and key order is noise."""
    blob = json.dumps({"kind": kind, "payload": payload}, sort_keys=True,
                      ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def _validate_restart_unit(payload: dict) -> dict:
    unit = str(payload.get("unit", "")).strip()
    # Accept both 'vfoot-tick' and 'vfoot-tick.service'; normalise to the bare name.
    unit = unit.removesuffix(".service").removesuffix(".timer")
    if unit not in ALLOWED_UNITS:
        raise Refused(f"unita' non permessa: {unit!r} "
                      f"(permesse: {', '.join(ALLOWED_UNITS)})")
    return {"unit": unit}


def _validate_rerun_command(payload: dict) -> dict:
    command = str(payload.get("command", "")).strip()
    if command not in ALLOWED_COMMANDS:
        raise Refused(f"comando non permesso: {command!r} "
                      f"(permessi: {', '.join(ALLOWED_COMMANDS)})")
    # Arguments are refused outright rather than filtered. A flag is a whole second
    # grammar to validate, and every command here does something sensible with none.
    if payload.get("args"):
        raise Refused("i comandi si rilanciano senza argomenti")
    return {"command": command}


def _validate_clear_cache_file(payload: dict) -> dict:
    raw = str(payload.get("path", "")).strip()
    if not raw:
        raise Refused("percorso mancante")
    cache = Path(settings.VFOOT_SOFASCORE_CACHE).resolve()
    # resolve() BEFORE comparing: '..' and symlinks are exactly how a path escapes a
    # prefix check that only looks at the string it was handed.
    target = Path(raw).resolve()
    if not target.is_relative_to(cache):
        raise Refused(f"il percorso e' fuori dalla cache dell'egress: {target}")
    if target.suffix != ".json":
        raise Refused("si cancellano solo file .json della cache")
    return {"path": str(target)}


def _validate_apply_patch(payload: dict) -> dict:
    branch = str(payload.get("branch", "")).strip()
    if not branch:
        raise Refused("branch mancante")
    if not branch.startswith("fix/"):
        # A namespace the agent owns: it can never propose merging something a human
        # was working on, and a stray 'main' in the field is refused rather than run.
        raise Refused(f"il branch dell'agente deve stare sotto fix/: {branch!r}")
    ok, _ = git("rev-parse", "--verify", f"{branch}^{{commit}}")
    if not ok:
        raise Refused(f"il branch {branch} non esiste nel checkout")

    ok, diff = git("diff", "--name-only", f"main...{branch}")
    if not ok:
        raise Refused(f"impossibile leggere il diff di {branch}: {diff}")
    files = [f for f in diff.splitlines() if f.strip()]
    if not files:
        raise Refused(f"{branch} non cambia niente rispetto a main")

    # The migration ban, and the reason it is absolute: the rollback restores the
    # code, not the schema.
    migrations = [f for f in files if "/migrations/" in f]
    if migrations:
        raise Refused(
            f"il diff tocca delle migrazioni ({', '.join(migrations[:3])}): il "
            f"ripristino rimette il codice e non lo schema, quindi questa patch "
            f"aspetta un umano al computer, non un click dal telefono")
    return {"branch": branch, "files": files}


_VALIDATORS = {
    MaintenanceProposal.KIND_RESTART_UNIT: _validate_restart_unit,
    MaintenanceProposal.KIND_RERUN_COMMAND: _validate_rerun_command,
    MaintenanceProposal.KIND_CLEAR_CACHE_FILE: _validate_clear_cache_file,
    MaintenanceProposal.KIND_APPLY_PATCH: _validate_apply_patch,
    MaintenanceProposal.KIND_NONE: lambda payload: {},
}


def validate(kind: str, payload: dict) -> dict:
    """Return the cleaned payload, or raise :class:`Refused`.

    Called twice on purpose: once when the proposal is recorded, and again
    immediately before execution. Between those two moments a human may have
    approved it, hours may have passed, and the repository may have moved — so the
    check that matters is the one nearest the side effect.
    """
    if kind not in _VALIDATORS:
        raise Refused(f"kind sconosciuto: {kind!r}")
    if not isinstance(payload, dict):
        raise Refused("payload non e' un oggetto")
    return _VALIDATORS[kind](payload)


# -- recording ---------------------------------------------------------------

def record(run, raw: dict) -> MaintenanceProposal:
    """Store one proposal from the agent's JSON, validated. A proposal that fails
    validation is stored as ``refused`` rather than dropped: a model that keeps
    proposing forbidden things is itself a finding, and silently swallowing them
    would hide it."""
    kind = str(raw.get("kind", "")).strip()
    payload = raw.get("payload") or {}
    proposal = MaintenanceProposal(
        run=run, kind=kind if kind in _VALIDATORS else MaintenanceProposal.KIND_NONE,
        payload=payload, rationale=str(raw.get("rationale", ""))[:8000],
        evidence=raw.get("evidence") or {},
    )
    try:
        cleaned = validate(kind, payload)
    except Refused as exc:
        proposal.status = MaintenanceProposal.STATUS_REFUSED
        proposal.result = str(exc)
        proposal.save()
        return proposal

    proposal.payload = cleaned
    proposal.fingerprint = fingerprint(kind, cleaned)
    if kind == MaintenanceProposal.KIND_NONE:
        proposal.status = MaintenanceProposal.STATUS_DONE
        proposal.result = "nessuna azione proposta"
    elif (not proposal.needs_human
            and getattr(settings, "VFOOT_MAINTENANCE_AUTO", False)):
        proposal.status = MaintenanceProposal.STATUS_APPROVED
        proposal.result = "livello automatico"
    proposal.save()
    return proposal


def rejected_fingerprints(limit: int = 50) -> list[dict]:
    """What the human has already said no to — fed back to the agent so it does not
    propose it again tomorrow, and the day after."""
    rows = (MaintenanceProposal.objects
            .filter(status=MaintenanceProposal.STATUS_REJECTED)
            .order_by("-decided_at")[:limit])
    return [{"kind": p.kind, "payload": p.payload, "fingerprint": p.fingerprint}
            for p in rows]


# -- execution ---------------------------------------------------------------

def execute(proposal: MaintenanceProposal) -> bool:
    """Do what the proposal says. Returns whether it went through.

    Re-validates first: the proposal may have been written hours ago by a model, and
    approved minutes ago by a human who read prose, not a payload.
    """
    try:
        cleaned = validate(proposal.kind, proposal.payload)
    except Refused as exc:
        proposal.status = MaintenanceProposal.STATUS_REFUSED
        proposal.result = f"respinta alla seconda validazione: {exc}"
        proposal.executed_at = timezone.now()
        proposal.save()
        return False

    handlers = {
        MaintenanceProposal.KIND_RESTART_UNIT: _do_restart_unit,
        MaintenanceProposal.KIND_RERUN_COMMAND: _do_rerun_command,
        MaintenanceProposal.KIND_CLEAR_CACHE_FILE: _do_clear_cache_file,
        MaintenanceProposal.KIND_APPLY_PATCH: _do_apply_patch,
        MaintenanceProposal.KIND_NONE: lambda _p: (True, "niente da fare"),
    }
    try:
        ok, output = handlers[proposal.kind](cleaned)
    except Exception as exc:  # noqa: BLE001 — an action that explodes is a result
        ok, output = False, f"{type(exc).__name__}: {exc}"
        log.exception("proposta %s esplosa", proposal.id)

    proposal.status = (MaintenanceProposal.STATUS_DONE if ok
                       else MaintenanceProposal.STATUS_FAILED)
    proposal.result = str(output)[:8000]
    proposal.executed_at = timezone.now()
    proposal.save()
    return ok


def _do_restart_unit(payload: dict) -> tuple[bool, str]:
    return maintenance_bridge.restart_unit(payload["unit"])


def _do_rerun_command(payload: dict) -> tuple[bool, str]:
    from django.core.management import call_command
    from io import StringIO

    out = StringIO()
    try:
        call_command(payload["command"], stdout=out, stderr=out)
    except Exception as exc:  # noqa: BLE001
        return False, f"{out.getvalue()}\n{type(exc).__name__}: {exc}"
    return True, out.getvalue()[-4000:]


def _do_clear_cache_file(payload: dict) -> tuple[bool, str]:
    target = Path(payload["path"])
    try:
        target.unlink(missing_ok=True)
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    # Deleting a cache entry is safe precisely because the egress rewrites it on the
    # next warm; that is why this kind is in the auto tier at all.
    return True, f"cancellato {target.name}; l'egress lo riscarica alla prossima passata"


def _do_apply_patch(payload: dict) -> tuple[bool, str]:
    """The dangerous one. The order of these steps is the safety property.

    Tag first, arm the dead-man SECOND, and only then touch anything: a crash
    anywhere after the arming still ends in a revert to the tag, which is a no-op if
    nothing was applied. Arming after applying would leave a window in which broken
    code is live and nothing is scheduled to undo it.
    """
    branch = payload["branch"]
    steps: list[str] = []

    ok, head = git("rev-parse", "--short", "HEAD")
    if not ok:
        return False, f"HEAD illeggibile: {head}"
    tag = f"pre-agent-{timezone.now():%Y%m%d-%H%M%S}"
    ok, out = git("tag", tag, "HEAD")
    if not ok:
        return False, f"impossibile marcare {head}: {out}"
    steps.append(f"marcato {head} come {tag}")

    ok, out = maintenance_bridge.arm_rollback(tag, ROLLBACK_DELAY_SECONDS)
    if not ok:
        # No net, so no jump. Refusing here is the whole point of arming first.
        return False, (f"impossibile armare il ripristino ({out}): "
                       f"la patch NON e' stata applicata")
    steps.append(f"ripristino armato su {tag} fra {ROLLBACK_DELAY_SECONDS}s")

    # The agent claimed the suite passes. That sentence was written by a model, so
    # it is a hint, not a proof — the gate is this run, here, on our side.
    ok, out = _run_tests(branch)
    steps.append(f"test su {branch}: {'ok' if ok else 'FALLITI'}")
    if not ok:
        return False, "\n".join(steps) + f"\n{out[-2000:]}"

    ok, out = git("merge", "--ff-only", branch)
    if not ok:
        ok, out = git("merge", "--no-edit", branch)
    if not ok:
        return False, "\n".join(steps) + f"\nmerge fallito: {out}"
    steps.append(f"applicato {branch}")

    ok, out = maintenance_bridge.restart_unit("vfoot")
    steps.append(f"riavvio: {'ok' if ok else out}")

    ok, out = maintenance_bridge.smoke_check()
    steps.append(f"controllo di fumo: {'passato' if ok else out}")
    if not ok:
        # Don't wait for the timer when we already know: revert now, and let the
        # timer find a healthy server and do nothing.
        rb_ok, rb_out = maintenance_bridge.rollback(tag)
        steps.append(f"ripristino immediato: {'ok' if rb_ok else rb_out}")
        return False, "\n".join(steps)

    return True, "\n".join(steps)


def _run_tests(branch: str) -> tuple[bool, str]:
    """Run the suite against ``branch`` without touching the working tree.

    A worktree rather than a checkout: the live server is reading these files, and
    swapping them under a running process to run tests is how a maintenance action
    causes the outage it was sent to prevent.
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="vfoot_patch_") as tmp:
        work = str(Path(tmp) / "tree")
        ok, out = git("worktree", "add", "--detach", work, branch, timeout=300.0)
        if not ok:
            return False, f"worktree fallito: {out}"
        try:
            venv = _repo_root() / "vfoot-backend" / ".venv" / "bin" / "python"
            r = subprocess.run(
                [str(venv), "manage.py", "test", "realdata", "vfoot", "-v", "0"],
                cwd=str(Path(work) / "vfoot-backend" / "src"),
                capture_output=True, text=True, timeout=1800.0)
            return r.returncode == 0, (r.stdout + r.stderr)
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"
        finally:
            git("worktree", "remove", "--force", work)
