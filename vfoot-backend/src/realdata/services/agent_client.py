"""The seam to the maintenance agent: JSON in on stdin, JSON out on stdout.

Same figure as ``egress_client``: one narrow crossing to something slow, external
and unreliable, with a switch that fakes it. Everything on this side of the seam is
deterministic and testable; everything on the other side is a subprocess we neither
trust nor need to understand.

WHY THE CONTRACT AND NOT THE VENDOR IS THE ABSTRACTION. Making the model swappable
by parameterising SDK calls would tie us to whichever SDK we picked. Making the
*contract* the abstraction means the other side can be a CLI, a different CLI, a
shell script, or a person with a text editor — and a fake, which is the one that
matters: it lets the rollback machinery be exercised in the test suite, in half a
second, without spending a cent or waiting for a model.

WHAT WE FEED IT, AND WHAT WE DO NOT. The context is the DIGESTED health report plus
the journal — never the raw scraped payloads. The agent is being asked to reason
about text that ultimately originated on somebody else's website, so the less of
that text reaches it verbatim, the smaller the prompt-injection surface. It also
receives the closed list of things it is allowed to propose, which is a courtesy
rather than a control: the real gate is ``services/maintenance.validate``.
"""
from __future__ import annotations

import json
import logging
import subprocess

from django.conf import settings

from realdata.models import MaintenanceProposal
from realdata.services import health, maintenance

log = logging.getLogger(__name__)


class AgentError(Exception):
    """The agent failed to produce a usable proposal. Recorded, never fatal."""


def build_context(*, trigger: str, report=None,
                  journal: list[dict] | None = None) -> dict:
    """Everything the agent gets. Assembled here so a test can assert on it.

    ``report`` is passed in by the caller that already computed one: the shape canary
    reads a handful of files off disk, and running it twice a pass to answer the same
    question is a small waste that shows up on a server doing nothing else.
    """
    report = report if report is not None else health.report()
    return {
        "trigger": trigger,
        "verdict": report.verdict,
        "checks": report.as_dict()["checks"],
        "journal": journal if journal is not None else recent_journal(),
        "already_rejected": maintenance.rejected_fingerprints(),
        "allowed_kinds": [k for k, _ in MaintenanceProposal.KIND_CHOICES],
        "allowed_units": list(maintenance.ALLOWED_UNITS),
        "allowed_commands": list(maintenance.ALLOWED_COMMANDS),
        "max_actions": int(getattr(settings, "VFOOT_MAINTENANCE_MAX_ACTIONS", 2)),
        "repo": str(getattr(settings, "VFOOT_REPO_ROOT", settings.REPO_ROOT)),
    }


def recent_journal(limit: int = 8) -> list[dict]:
    """The agent's memory. Without it, every night is the first night."""
    from realdata.models import MaintenanceRun

    out = []
    for run in MaintenanceRun.objects.order_by("-started_at")[:limit]:
        out.append({
            "date": run.started_at.isoformat(),
            "trigger": run.trigger,
            "summary": run.summary,
            "proposals": [
                {"kind": p.kind, "payload": p.payload, "status": p.status,
                 "result": p.result[:300]}
                for p in run.proposals.all()
            ],
        })
    return out


# -- the crossing ------------------------------------------------------------

def ask(context: dict, *, timeout: float | None = None) -> dict:
    """Run the configured adapter and return its parsed proposal object."""
    if getattr(settings, "VFOOT_AGENT_SIMULATED", False):
        return _simulated(context)

    cmd = str(getattr(settings, "VFOOT_AGENT_CMD", "") or "").strip()
    if not cmd:
        raise AgentError("VFOOT_AGENT_CMD non e' impostata: nessun agente da chiamare.")
    limit = timeout or float(getattr(settings, "VFOOT_AGENT_TIMEOUT", 1800))

    try:
        r = subprocess.run([cmd], input=json.dumps(context, ensure_ascii=False),
                           capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired:
        raise AgentError(f"l'agente non ha risposto entro {limit:.0f}s") from None
    except Exception as exc:  # noqa: BLE001 — adapter missing, not executable
        raise AgentError(f"{type(exc).__name__}: {exc}") from exc

    if r.returncode != 0:
        raise AgentError(f"l'adattatore e' uscito con {r.returncode}: "
                         f"{(r.stderr or r.stdout)[-1000:]}")
    return parse(r.stdout)


def parse(raw: str) -> dict:
    """Pull the proposal object out of whatever the adapter printed.

    Deliberately forgiving about the WRAPPING and strict about the CONTENT. Different
    CLIs wrap their answer differently — a fenced code block, a envelope object with
    the real payload as a string inside it, a line of preamble — and none of that is
    the contract. The contract is the keys, and those are checked by the validator.
    """
    text = (raw or "").strip()
    if not text:
        raise AgentError("l'agente non ha stampato niente")

    obj = _first_json_object(text)
    if obj is None:
        raise AgentError(f"nessun oggetto JSON nell'uscita dell'agente: {text[:300]}")

    # Envelope unwrapping: some CLIs return {"result": "<the real JSON as a string>"}.
    if "proposals" not in obj and isinstance(obj.get("result"), str):
        inner = _first_json_object(obj["result"])
        if inner is not None:
            obj = inner

    if not isinstance(obj.get("proposals"), list):
        raise AgentError("la risposta non contiene una lista 'proposals'")
    return obj


def _first_json_object(text: str) -> dict | None:
    """The outermost balanced {...} in ``text``, parsed. None if there isn't one."""
    start = text.find("{")
    while start != -1:
        depth, in_str, escaped = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start:i + 1])
                    except ValueError:
                        break
                    if isinstance(parsed, dict):
                        return parsed
                    break
        start = text.find("{", start + 1)
    return None


def _simulated(context: dict) -> dict:
    """A canned answer shaped by the verdict. Not a model — a stand-in, so the
    executor, the approval path and the rollback can be tested end to end."""
    if context.get("verdict") == "ok":
        return {"summary": "niente da fare", "diagnosis": "", "proposals": []}
    return {
        "summary": "[simulato] anomalia rilevata",
        "diagnosis": "risposta finta: nessun modello e' stato interpellato.",
        "proposals": [{
            "kind": MaintenanceProposal.KIND_RESTART_UNIT,
            "payload": {"unit": "vfoot-egress-refill"},
            "rationale": "[simulato]",
        }],
    }
