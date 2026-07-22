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
check of the season), so a cached value is reused across restarts and workers and
invalidates itself as soon as new matches are finalized.
"""
from __future__ import annotations

import math
from collections import defaultdict

from django.core.cache import cache

from realdata.models import CompetitionSeason, Match, Player
from vfoot.services.classic_pagella import data_version, get_reference
from vfoot.services.classic_rating import (
    _minutes_map,
    _per_match_player_totals,
    _vote_from_index,
    index_for_role,
    is_rated,
)

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
    minutes = _minutes_map(match_ids)
    roles = dict(Player.objects.exclude(classic_role="")
                 .values_list("id", "classic_role"))

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
        vote = _vote_from_index(index_for_role(role, feats, mins), role, mins, ref)
        a = agg[pid]
        a[0] += vote
        a[1] += 1
    return {pid: {"avg": round(s / n, 2), "n": n}
            for pid, (s, n) in agg.items() if n}


def season_player_ratings(cs_id: int) -> dict:
    """{player_id: {"avg", "n"}} for a season, version-cached across restarts."""
    key = f"vfoot:player_ratings:{cs_id}:{data_version(cs_id)}"
    hit = cache.get(key)
    if hit is not None:
        return hit
    data = _compute_season_player_ratings(cs_id)
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
