"""The suggested XI — one suggester, in the backend, for the page and for the
baseline lineup.

It lived in the page only (``FormationPage.tsx``, ``suggest()``). It has to live
here because the baseline lineup (``lineup_baseline``) is written by the server
when a roster completes, with nobody's browser open; and a suggester in two places
is two suggesters the day one of them is touched. The page now receives the
server's suggestion in the lineup payload and its copy is gone.

The algorithm is the page's, unchanged: goalkeeper by form; then 4 defenders, 4
midfielders, 2 forwards by form; then top up to ten outfielders from whoever is
left, by form, never past a role's ceiling. Frozen players (their match has begun)
are a fact before they are a preference: those already in the XI keep their
places, those outside it are never reached for.

``form`` is the recent-form expected contribution from ``player_profiles`` — the
same number the page sorts the roster by — computed AS OF the matchday, i.e. from
matches strictly before it. So a suggestion for round N never sees round N,
whenever it is computed.
"""
from __future__ import annotations

import os
from functools import lru_cache

from django.conf import settings

from realdata.models import Match, MatchAppearance
from vfoot.services.formation_rules import CLASSIC_CONSTRAINTS, XI
from vfoot.services.player_profiles import player_profiles
from vfoot.services.player_ratings import previous_season_with_data
from vfoot.services.vector_zone_scoring import load_calibration

CLASSIC_ROLE_TO_LINEUP = {"POR": "GK", "DIF": "DEF", "CEN": "MID", "ATT": "ATT"}


@lru_cache(maxsize=1)
def vector_calibration() -> dict:
    path = os.path.join(os.path.dirname(str(settings.BASE_DIR)),
                        "calibration/vector_zone_duel_v1.json")
    try:
        return load_calibration(path)
    except Exception:
        return {"params": {}, "feature_scales": {}}


def stats_season_for(league, player_ids, as_of: int | None):
    """Which season the profiles should describe: the reference season while it is
    under way, the last one with data before it starts (pre-season, nobody has
    played yet, and "poco impiegato" for everybody would simply be wrong)."""
    ref_cs = league.reference_season
    if ref_cs is None:
        return None, as_of
    played_here = MatchAppearance.objects.filter(
        player_id__in=player_ids,
        match__competition_season=ref_cs,
        **({"match__matchday__lt": as_of} if as_of is not None else {}),
    ).exists()
    if played_here:
        return ref_cs, as_of
    prev = previous_season_with_data(ref_cs)
    return (prev, None) if prev else (ref_cs, as_of)


def roster_profiles(league, player_ids: list[int], as_of: int | None):
    """``(profiles, stats_cs)`` for these players, as the lineup page computes them."""
    stats_cs, stats_as_of = stats_season_for(league, player_ids, as_of)
    total_matches = (
        Match.objects.filter(competition_season=stats_cs).values("matchday").distinct().count()
        if stats_cs is not None
        else Match.objects.values("matchday").distinct().count()
    )
    cal = vector_calibration()
    profiles = player_profiles(
        player_ids,
        total_matches=total_matches,
        as_of_matchday=stats_as_of,
        params=cal.get("params", {}),
        scales=cal.get("feature_scales", {}),
        competition_season_id=stats_cs.id if stats_cs is not None else None,
    )
    return profiles, stats_cs


def lineup_roles(league, player_ids: list[int], profiles: dict) -> dict[int, str]:
    """player_id -> GK/DEF/MID/ATT. Classic: the league's frozen role, then the
    Transfermarkt seed, then the spatial guess (the page's own fallback chain).
    Aura: the spatial role."""
    from vfoot.models import FantasyLeague
    from vfoot.services.classic_matchday_scoring import role_map_for

    out = {pid: (profiles.get(pid) or {}).get("role", "MID") for pid in player_ids}
    if league.mode == FantasyLeague.MODE_CLASSIC:
        out.update(role_map_for(league, list(player_ids)))
    return out


def roster_for_suggestion(league, team, as_of: int | None) -> list[dict]:
    """[{player_id, role, form}] for the team's current roster."""
    from vfoot.models import FantasyRosterSlot

    player_ids = list(
        FantasyRosterSlot.objects.filter(team=team, released_at__isnull=True)
        .values_list("player_id", flat=True)
    )
    if not player_ids:
        return []
    profiles, _ = roster_profiles(league, player_ids, as_of)
    roles = lineup_roles(league, player_ids, profiles)
    return [{"player_id": pid, "role": roles.get(pid, "MID"),
             "form": float((profiles.get(pid) or {}).get("form", 0.0) or 0.0)}
            for pid in player_ids]


def suggest_xi(roster: list[dict], constraints: dict | None,
               pinned=(), locked=()) -> dict:
    """``{"gk_player_id", "starter_player_ids"}`` — the goalkeeper and the ten
    outfielders, from ``roster`` rows of ``{player_id, role, form}``.

    ``constraints`` is ``CLASSIC_CONSTRAINTS`` (or None in aura, where any shape is
    legal). ``pinned`` are frozen players to keep in the XI; ``locked`` are frozen
    players outside it, never to be reached for.
    """
    pinned = [int(p) for p in pinned]
    unavailable = {int(p) for p in locked}
    pool = [p for p in roster if p["player_id"] in pinned or p["player_id"] not in unavailable]
    by_id = {p["player_id"]: p for p in pool}
    by_form = lambda p: -p["form"]  # noqa: E731

    pinned_rows = [by_id[p] for p in pinned if p in by_id]
    gk = next((p for p in pinned_rows if p["role"] == "GK"), None)
    if gk is None:
        gks = sorted((p for p in pool if p["role"] == "GK"), key=by_form)
        gk = gks[0] if gks else None
    chosen: set[int] = set()
    cnt = {"GK": 0, "DEF": 0, "MID": 0, "ATT": 0}
    if gk is not None:
        chosen.add(gk["player_id"])
        cnt["GK"] = 1
    out: list[int] = []
    for p in pinned_rows:
        if p["player_id"] in chosen or p["role"] == "GK":
            continue
        chosen.add(p["player_id"])
        cnt[p["role"]] = cnt.get(p["role"], 0) + 1
        out.append(p["player_id"])
    for role, n in (("DEF", 4), ("MID", 4), ("ATT", 2)):
        cands = sorted((p for p in pool if p["role"] == role and p["player_id"] not in chosen),
                       key=by_form)
        for p in cands[: max(0, n - cnt[role])]:
            chosen.add(p["player_id"])
            cnt[role] += 1
            out.append(p["player_id"])
    ceilings = (constraints or {}).get("per_role") or {}
    for p in sorted((p for p in pool if p["role"] != "GK" and p["player_id"] not in chosen),
                    key=by_form):
        if len(out) >= XI - 1:
            break
        cap = (ceilings.get(p["role"]) or {}).get("max")
        if cap is not None and cnt.get(p["role"], 0) >= cap:
            continue
        chosen.add(p["player_id"])
        cnt[p["role"]] = cnt.get(p["role"], 0) + 1
        out.append(p["player_id"])
    return {"gk_player_id": gk["player_id"] if gk else None, "starter_player_ids": out}


def bench_after(roster: list[dict], starters: list[int]) -> list[int]:
    """Everybody else, in the page's default bench order: by role P-D-C-A, then by
    form — the order ``orderBench`` gives a bench nobody has arranged yet."""
    order = {"GK": 0, "DEF": 1, "MID": 2, "ATT": 3}
    rest = [p for p in roster if p["player_id"] not in set(starters)]
    rest.sort(key=lambda p: (order.get(p["role"], 2), -p["form"]))
    return [p["player_id"] for p in rest]


def constraints_for(league):
    from vfoot.models import FantasyLeague

    return CLASSIC_CONSTRAINTS if league.mode == FantasyLeague.MODE_CLASSIC else None
