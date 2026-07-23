"""The FIXED per-role calibration the voto puro is scored against.

Why fixed, and not computed from the running season: the vote centres each role
on 6 by z-scoring a player's index against his peers' mean and spread. If that
mean and spread came from the season in progress, two things would break, both of
them the user's objection:

* cold start — on matchday 1 there is no season to average, so there is no scale;
* drift — the reference would move as results arrive, so the same performance
  would earn a different vote in September and in May, and a 6 would not mean the
  same thing across matchdays, let alone across seasons.

So mean/std per role (and the per-feature averages the explanation subtracts) are
calibrated ONCE on a COMPLETED season, frozen to a file in the repo, and read
from there forever after. They are a parameter of the model, exactly like the
weights, and are re-derived only when the model itself changes — never during a
season. The stored ``weights_fingerprint`` records which weights produced them,
so a silent mismatch (someone edits a weight, forgets to recalibrate) surfaces as
a warning instead of as quietly wrong votes.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from django.conf import settings

log = logging.getLogger(__name__)

# Versioned in the repo next to the code whose behaviour it fixes.
REFERENCE_PATH = Path(settings.BASE_DIR) / "vfoot" / "data" / "vote_reference.json"


def weights_fingerprint() -> str:
    """A short hash of every number the reference depends on. If any weight, the
    spread constant, or the shrinkage changes, so does this — which is how a
    recalibration-needed state is detected rather than assumed away."""
    from vfoot.services import classic_rating as cr
    payload = {
        "total": cr.TOTAL_WEIGHTS, "per90": cr.PER90_WEIGHTS,
        "gk_total": cr.GK_TOTAL_WEIGHTS, "gk_per90": cr.GK_PER90_WEIGHTS,
        "def_exposure": cr.DEF_EXPOSURE_WEIGHT,
        "spread_k": cr.VOTE_SPREAD_K, "center": cr.VOTE_CENTER,
        "extrap_floor": cr.EXTRAP_FLOOR_MINUTES, "shrinkage": cr.SHRINKAGE_MINUTES,
        "min_ref": cr.MIN_MINUTES_REFERENCE,
    }
    blob = json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def save(reference: dict, role_averages: dict, *, season_id: int) -> None:
    REFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE_PATH.write_text(json.dumps({
        "calibrated_on_season": season_id,
        "weights_fingerprint": weights_fingerprint(),
        "reference": reference,
        "role_averages": role_averages,
    }, indent=2, sort_keys=True))


_cache: dict | None = None


def _load() -> dict | None:
    global _cache
    if _cache is not None:
        return _cache
    if not REFERENCE_PATH.exists():
        return None
    data = json.loads(REFERENCE_PATH.read_text())
    if data.get("weights_fingerprint") != weights_fingerprint():
        # Loud on purpose: the votes are now being scored against a scale that no
        # longer matches the weights producing the indices. Still usable — better
        # a slightly stale scale than none — but someone must recalibrate.
        log.warning("vote_reference.json was calibrated for different weights "
                    "(%s != %s); run `manage.py calibrate_vote_reference`.",
                    data.get("weights_fingerprint"), weights_fingerprint())
    _cache = data
    return data


def clear_cache() -> None:
    """Drop the in-process copy (after a recalibration, or in tests)."""
    global _cache
    _cache = None


def fixed_reference() -> dict | None:
    data = _load()
    return data["reference"] if data else None


def fixed_role_averages() -> dict | None:
    data = _load()
    return data["role_averages"] if data else None
