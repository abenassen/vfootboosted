"""Player VALUE signals for the championship pool (the "listone").

A player's value is an average voto puro. Which season it comes from must EVOLVE
with the calendar:

  * pre-season / early rounds -> last season's average (the only evidence);
  * as the current season progresses -> current form progressively takes over.

So the value is a Bayesian blend, weight ``n/(n+K)`` on the current season's rated
appearances, shrinking toward last season's average (the prior). At n=0 it IS last
season's value; by n=K it is half current form; late season it is essentially
current form. A player with NO history in either season has no value (None) —
typically a newcomer who hasn't played yet.

Expensive aggregates are cached under a DATA VERSION key (match count + last data
check of the season) AND the scoring fingerprint, so a cached value is reused
across restarts and workers, invalidates itself as soon as new matches are
finalized, and stops being served the moment the model that produced it changes.

That cache is a per-machine directory (``.django_cache``, gitignored, and in
production deliberately outside the checkout): it is a speed-up, never a source.
The SNAPSHOT below is the source of last resort — see ``snapshot_ratings``.
"""
from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.cache import cache

from realdata.models import CompetitionSeason, Match, Player
from vfoot.services.classic_pagella import data_version, get_reference
from vfoot.services.vote_reference import scoring_fingerprint
from vfoot.services.classic_rating import (
    _minutes_map,
    _per_match_player_totals,
    _vote_from_index,
    defensive_exposure,
    index_for_role,
    is_rated,
    current_role_map,
)

log = logging.getLogger(__name__)

# Versioned in the repo next to the code, exactly like vote_reference.json, and for
# the same reason: it is a computed artefact that has to travel with the SOURCE
# rather than with the database.
SNAPSHOT_PATH = Path(settings.BASE_DIR) / "vfoot" / "data" / "player_ratings_snapshot.json"

# Rated appearances at which current form and last season's value weigh the same.
SHRINKAGE_APPEARANCES = 5

# A season average built on 1-2 games is nearly meaningless: one great night would
# otherwise top the whole listone. Shrink each season average toward the neutral 6
# in proportion to the evidence — n/(n+K) — so a regular's average survives almost
# intact while a cameo regresses to the middle. Same Bayesian idea already used for
# minutes inside classic_rating.
SEASON_SHRINKAGE_N = 5
NEUTRAL_VOTE = 6.0


def _shrunk(avg: float, n: int) -> float:
    """Season average pulled toward the neutral vote when it rests on few games."""
    return (n * avg + SEASON_SHRINKAGE_N * NEUTRAL_VOTE) / (n + SEASON_SHRINKAGE_N)

VALUE_CURRENT = "corrente"
VALUE_PREVIOUS = "precedente"
VALUE_MIXED = "misto"
VALUE_ESTIMATED = "stimato"

# An estimate inferred from a transfer valuation is far weaker evidence than a
# measured performance, so it is kept inside the central band: it must place a
# newcomer sensibly in the list, never crown him above proven top performers.
VOTE_MIN_EST, VOTE_MAX_EST = 5.0, 6.6


def _compute_season_player_ratings(cs_id: int) -> dict:
    """Bulk pass: per-match features, minutes and the role table are each loaded
    ONCE for the whole season (a handful of queries)."""
    match_ids = list(Match.objects
                     .filter(competition_season_id=cs_id,
                             status=Match.STATUS_FINISHED)
                     .values_list("id", flat=True))
    if not match_ids:
        return {}
    ref = get_reference(cs_id)
    totals = _per_match_player_totals(match_ids)
    if not totals:
        # No zone coverage at all (see the guard in _per_match_player_totals).
        # Everything below reads the same tables, so there is nothing to gain by
        # going on — and defensive_exposure alone is several queries.
        return {}
    minutes = _minutes_map(match_ids)
    # The defensive exposure is an ARGUMENT to the index, not something read from
    # the totals, so leaving it out does not omit a detail — it silently scores
    # every outfield player as if the opponent had created nothing in his zones.
    # It used to be missing here while ``build_reference`` and
    # ``voto_puro_for_match`` both pass it, so the listone z-scored an index built
    # one way against a scale calibrated on another. Cost: +0.157 of a vote on
    # defenders (who carry the most exposure), +0.063 on midfielders, +0.015 on
    # attackers and exactly 0 on keepers, whose channel has no exposure term —
    # which is why POR was the one role landing on a mean of 6.00 while the
    # listone average sat at 6.09 against the 5.98 of the real pagelle.
    exposure = defensive_exposure(match_ids, minutes)
    # Canonical scoring role source (k-means disambiguated), NOT the raw TM seed.
    roles = current_role_map(only_declared=True)

    agg: dict[int, list] = defaultdict(lambda: [0.0, 0])
    for (mid, pid), feats in totals.items():
        role = roles.get(pid)
        if not role:
            continue
        mins = minutes.get((mid, pid), 0)
        if mins <= 0 or not is_rated(mins, feats):
            continue
        # index_for_role dispatches to the goalkeeper channel for POR, so keepers
        # now get a season value too (they used to be skipped entirely).
        vote = _vote_from_index(
            index_for_role(role, feats, mins, exposure.get((mid, pid), 0.0)),
            role, mins, ref)
        a = agg[pid]
        a[0] += vote
        a[1] += 1
    return {pid: {"avg": round(s / n, 2), "n": n}
            for pid, (s, n) in agg.items() if n}


_snapshot_memo: dict | None = None


def clear_snapshot_cache() -> None:
    """Drop the in-process copy of the snapshot (after regenerating it, or in tests)."""
    global _snapshot_memo
    _snapshot_memo = None


def _snapshot() -> dict:
    global _snapshot_memo
    if _snapshot_memo is None:
        try:
            _snapshot_memo = json.loads(SNAPSHOT_PATH.read_text())
        except (OSError, ValueError):
            # A missing or unreadable snapshot is not an error: a full database
            # never needs it.
            _snapshot_memo = {}
    return _snapshot_memo


def snapshot_ratings(cs_id: int) -> dict:
    """Season ratings read from the versioned snapshot, or {} if it cannot serve.

    The reason this file exists rather than a database table: the slim copy from
    ``export_dev_db`` has no zone features, so a table shipped inside it would have
    to be populated BEFORE the export — which does nothing for the copies people
    already downloaded. Shipping the numbers with the SOURCE fixes those too, with
    a plain ``git pull`` and without replacing anyone's database (and the local
    leagues, rosters and test data in it). 9 KB of JSON against 54 MB of SQLite.

    Used ONLY when computing from zone features yields nothing, so a real database
    always wins: this can never mask fresh data with a stale figure. Both the
    scoring fingerprint and the played-data version are checked and any mismatch is
    logged — a snapshot from a different model, or from a different set of matches,
    is still better than an empty listone, but nobody should discover that silently.
    """
    season = (_snapshot().get("seasons") or {}).get(str(cs_id))
    if not season:
        return {}
    stored_fp = _snapshot().get("scoring_fingerprint")
    if stored_fp != scoring_fingerprint():
        log.warning("player_ratings snapshot was built by a different scoring model "
                    "(%s != %s); rebuild it with `manage.py "
                    "build_player_ratings_snapshot`.", stored_fp, scoring_fingerprint())
    if season.get("data_version") != data_version(cs_id):
        log.warning("player_ratings snapshot for season %s describes a different set "
                    "of played matches (%s != %s).", cs_id,
                    season.get("data_version"), data_version(cs_id))
    return {int(pid): {"avg": avg, "n": n}
            for pid, (avg, n) in (season.get("ratings") or {}).items()}


def season_player_ratings(cs_id: int) -> dict:
    """{player_id: {"avg", "n"}} for a season, version-cached across restarts.

    Keyed on the SCORING fingerprint as well as the played-data version. Keying
    on the data alone was wrong in the one case that matters most: a CONCLUDED
    season never plays another match, so its key was frozen and the entry, stored
    with no expiry, outlived every change to the model. The 25-26 listone served
    ratings computed on 2026-07-21 straight through the v3 retuning — believable
    numbers, silently pre-tuning, and no way to tell from the outside.
    """
    key = (f"vfoot:player_ratings:{cs_id}:{data_version(cs_id)}"
           f":{scoring_fingerprint()}")
    hit = cache.get(key)
    if hit is not None:
        return hit
    data = _compute_season_player_ratings(cs_id)
    if not data:
        # Nothing computable: either a season this model cannot score at all, or a
        # database whose zone features were stripped. The snapshot answers the
        # second case and stays empty for the first.
        data = snapshot_ratings(cs_id)
        if data:
            log.info("season %s scored from the versioned snapshot (%d players): "
                     "no zone features in this database.", cs_id, len(data))
    cache.set(key, data, None)
    return data


def previous_season_with_data(reference_cs) -> CompetitionSeason | None:
    """Most recent PRIOR edition of the same competition that has played data."""
    return (CompetitionSeason.objects
            .filter(competition=reference_cs.competition,
                    matches__status=Match.STATUS_FINISHED,
                    matches__appearances__isnull=False)
            .exclude(id=reference_cs.id)
            .filter(season__code__lt=reference_cs.season.code)
            .distinct()
            .order_by("-season__code")
            .first())


def fit_value_from_market(values: dict, market: dict):
    """Least-squares fit of the measured voto on log10(market value), using only
    players that have BOTH signals. Returns (a, b, r, n) for value ≈ a + b·log10(mv),
    or None when there is too little overlap to fit responsibly."""
    pts = [(math.log10(mv), values[pid]["value"])
           for pid, mv in market.items()
           if mv and mv > 0 and pid in values]
    n = len(pts)
    if n < 30:
        return None
    mx = sum(x for x, _ in pts) / n
    my = sum(y for _, y in pts) / n
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    syy = sum((y - my) ** 2 for _, y in pts)
    sxy = sum((x - mx) * (y - my) for x, y in pts)
    if sxx <= 0 or syy <= 0:
        return None
    b = sxy / sxx
    return (my - b * mx, b, sxy / math.sqrt(sxx * syy), n)


def player_values(reference_cs, market: dict | None = None):
    """Blended value per player for a league on ``reference_cs``.

    Each entry carries:
      * ``value``           – the MEASURED voto (None when he has never been rated);
      * ``estimated_value`` – a HOMOGENEOUS figure for every player: the measured
        voto when there is one, otherwise a voto ESTIMATED from the market value via
        a fit calibrated on players who have both. This is what lets the listone be
        a single ranked list instead of dumping newcomers at the bottom.
      * ``basis``           – corrente | precedente | misto | stimato.

    Returns (values, previous_season, fit) where ``fit`` describes the market→voto
    calibration (or None if it could not be fitted).
    """
    current = season_player_ratings(reference_cs.id)
    prev_cs = previous_season_with_data(reference_cs)
    previous = season_player_ratings(prev_cs.id) if prev_cs else {}

    out: dict[int, dict] = {}
    for pid in set(current) | set(previous):
        cur, pre = current.get(pid), previous.get(pid)
        n_cur = cur["n"] if cur else 0
        # Each season average is first shrunk by its own sample size, so a player
        # with a single brilliant game cannot outrank a season-long performer.
        cur_avg = _shrunk(cur["avg"], cur["n"]) if cur else None
        pre_avg = _shrunk(pre["avg"], pre["n"]) if pre else None
        if cur and pre:
            w = n_cur / (n_cur + SHRINKAGE_APPEARANCES)
            value, basis = w * cur_avg + (1 - w) * pre_avg, VALUE_MIXED
        elif cur:
            value, basis = cur_avg, VALUE_CURRENT
        else:
            value, basis = pre_avg, VALUE_PREVIOUS
        v = round(value, 2)
        out[pid] = {"value": v, "estimated_value": v, "n_cur": n_cur,
                    "n_prev": pre["n"] if pre else 0, "basis": basis}

    fit = fit_value_from_market(out, market or {})
    if fit and market:
        a, b, _r, _n = fit
        for pid, mv in market.items():
            if pid in out or not mv or mv <= 0:
                continue
            est = a + b * math.log10(mv)
            # An estimate must not out-rank measured performance at the extremes.
            est = max(VOTE_MIN_EST, min(VOTE_MAX_EST, est))
            out[pid] = {"value": None, "estimated_value": round(est, 2),
                        "n_cur": 0, "n_prev": 0, "basis": VALUE_ESTIMATED}
    return out, prev_cs, fit


def latest_market_values(player_ids, provider: str = "transfermarkt") -> dict:
    """{player_id: value_eur} from the most recent quote per player.

    External-source signal (provenanced in PlayerMarketValue), used ONLY as a
    secondary ordering hint for players with no on-pitch history — never as a
    substitute for a performance voto.
    """
    from realdata.models import PlayerMarketValue

    out: dict[int, int | None] = {}
    for pid, val in (PlayerMarketValue.objects
                     .filter(player_id__in=player_ids, provider=provider)
                     .order_by("player_id", "-as_of")
                     .values_list("player_id", "value_eur")):
        out.setdefault(pid, val)  # first row per player = latest quote
    return out
