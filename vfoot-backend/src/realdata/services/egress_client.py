"""Bridge from the DB-aware side (calendar sync + tick) to the root egress.

The egress must run as root (netns + WireGuard tunnel); this app runs as the
unprivileged ``vfoot`` user. So we cross the privilege boundary with ONE narrow
``sudo`` call to a fixed wrapper that runs the egress and warms the shared cache
(``settings.VFOOT_SOFASCORE_CACHE``). This module NEVER touches the network itself
— it asks the egress to warm the cache, and the existing OFFLINE import / calendar
sync then read that cache. The single ``run_egress`` seam is what tests mock, so
the DB-aware wiring is exercised without root or a tunnel.

Returns a plain bool: True = cache warmed (proceed to the offline read), False =
the egress was blocked / unavailable (skip this cycle, try again next tick — the
on-disk cache makes a later retry free).
"""
from __future__ import annotations

import subprocess
from collections.abc import Iterable

from django.conf import settings


def _wrapper() -> str:
    # A fixed path so the sudoers rule can be exact (no wildcards on the binary).
    return getattr(settings, "VFOOT_EGRESS_WRAPPER", "/usr/local/sbin/vfoot-egress")


def run_egress(args: list[str], *, timeout: float = 900.0) -> bool:
    """Run ``sudo -n <wrapper> <args>``. True iff it exits 0 (cache warmed)."""
    cmd = ["sudo", "-n", _wrapper(), *args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:  # noqa: BLE001 - sudo/wrapper missing, timeout, etc.
        return False
    return r.returncode == 0


def warm_matches(event_ids: Iterable[int], kind: str) -> bool:
    """Warm the cache for these SofaScore event ids (kind: 'live' | 'final')."""
    ids = ",".join(str(i) for i in event_ids)
    if not ids:
        return True
    return run_egress(["fetch", "--match-ids", ids, "--kind", kind,
                       "--cache-dir", str(settings.VFOOT_SOFASCORE_CACHE)])


def warm_schedule(year: str) -> bool:
    """Warm the cache for a season's whole fixture list (e.g. year='26/27')."""
    return run_egress(["schedule", "--year", year,
                       "--cache-dir", str(settings.VFOOT_SOFASCORE_CACHE)])
