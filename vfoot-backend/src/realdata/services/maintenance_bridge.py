"""The one narrow crossing from the app to the privileged half of maintenance.

Same shape as ``egress_client``, and for the same reason: restarting a unit, arming
the rollback timer and reverting a deploy all need root, while everything that
DECIDES runs as the unprivileged ``vfoot`` user. So the boundary is crossed by one
``sudo`` call to a fixed wrapper (``/usr/local/sbin/vfoot-maintenance``), whose
sudoers rule can therefore name an exact binary with no wildcards.

THE WRAPPER VALIDATES AGAIN. Every argument that reaches it is already checked in
Python (``services/maintenance.validate``), and the wrapper checks it a second time
against its own hard-coded lists. That is not belt-and-braces for its own sake: the
Python side builds its arguments from a proposal written by a language model whose
input contains text fetched from other people's websites. Two independent gates, in
two languages, neither of which can be talked out of it.

``run`` returns (ok, output) rather than raising: a maintenance action that fails is
an ordinary outcome to record on the proposal, not an exception to propagate into
the agent's own pass.
"""
from __future__ import annotations

import logging
import subprocess

from django.conf import settings

log = logging.getLogger(__name__)


def _wrapper() -> str:
    # Fixed path so the sudoers rule is exact. See deploy/maintenance/.
    return getattr(settings, "VFOOT_MAINTENANCE_WRAPPER",
                   "/usr/local/sbin/vfoot-maintenance")


def run(args: list[str], *, timeout: float = 600.0) -> tuple[bool, str]:
    """Run ``sudo -n <wrapper> <args>``. Returns (exited zero, combined output).

    With ``VFOOT_MAINTENANCE_SIMULATED`` on, nothing is executed and every call
    reports success. That switch exists so the whole dangerous chain — apply, smoke
    check, dead-man rollback — is exercisable on a laptop with no root, no systemd
    and no production. The machinery you cannot afford to discover broken at three
    in the morning is exactly the machinery you must be able to run in a test.
    """
    if getattr(settings, "VFOOT_MAINTENANCE_SIMULATED", False):
        log.warning("maintenance bridge SIMULATO: %s", " ".join(args))
        return True, f"[simulato] {' '.join(args)}"
    cmd = ["sudo", "-n", _wrapper(), *args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — sudo/wrapper missing, timeout
        return False, f"{type(exc).__name__}: {exc}"
    return r.returncode == 0, (r.stdout + r.stderr).strip()


# -- the four verbs ----------------------------------------------------------

def restart_unit(unit: str) -> tuple[bool, str]:
    """Restart one systemd unit (the wrapper re-checks the name)."""
    return run(["restart", unit])


def smoke_check() -> tuple[bool, str]:
    """Is the server alive and are its parts still talking to each other?

    Four cheap questions, ~10 seconds. It answers "is it up", NOT "was the patch
    correct" — a wrong-but-harmless fix passes every one of them, and is caught the
    next morning by ``health_report`` raising the same alarm again.
    """
    return run(["check"], timeout=120.0)


def arm_rollback(tag: str, delay_seconds: int) -> tuple[bool, str]:
    """Schedule root to re-check and, unless healthy, revert to ``tag``.

    ARMED BEFORE ANYTHING IS APPLIED, so that a crash between arming and applying
    still ends in a revert (a no-op if nothing changed) rather than in a half-applied
    deploy nobody is watching. See deploy/maintenance/vfoot-maintenance for why the
    timer re-runs the check itself instead of reading a flag someone wrote earlier.
    """
    return run(["arm-rollback", tag, str(int(delay_seconds))])


def rollback(tag: str) -> tuple[bool, str]:
    """Revert the checkout to ``tag`` and restart. Also usable by hand."""
    return run(["rollback", tag], timeout=300.0)
