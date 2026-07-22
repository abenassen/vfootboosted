"""Real-match classic pagella — per-player voto puro + bonus/malus = fantavoto
for a single REAL match (e.g. a Serie A fixture), for the whole squad that
appeared, not a fantasy lineup.

This is the shared, reusable version of the fantavoto assembly that previously
lived (cache-coupled, path-hardcoded) inside ``seed_classic_demo_league``. It is
DB-only and portable, so it serves both the real-championship match-detail view
and, later, the live classic scoring path.

Output shape mirrors the frontend ``ClassicTeamDetail`` / ``ClassicPlayerLine``
so the existing ``ClassicMatchDetail`` component renders it directly.

Known scope note: own goals, penalty saves and penalty misses are NOT in the DB
(they were read from the provider cache by the seed); they are omitted here and
default to 0. Goals, assists (MatchAppearance) and cards (MatchDisciplinaryEvent)
— the dominant bonus/malus terms — are fully covered.
"""
from __future__ import annotations

from collections import defaultdict

from django.core.cache import cache
from django.db.models import Count, Max

from realdata.models import (
    CARD_RED,
    CARD_SECOND_YELLOW,
    CARD_YELLOW,
    Match,
    MatchAppearance,
    MatchDisciplinaryEvent,
    Player,
)
from vfoot.services.classic_rating import build_reference, voto_puro_for_match

CARD_MALUS = {CARD_YELLOW: 0.5, CARD_SECOND_YELLOW: 1.0, CARD_RED: 1.0}
ROLE_TO_LINEUP = {"POR": "GK", "DIF": "DEF", "CEN": "MID", "ATT": "ATT"}
# Pagella reading order: goalkeeper -> defence -> midfield -> attack.
ROLE_ORDER = {"POR": 0, "DIF": 1, "CEN": 2, "ATT": 3}
GOAL_THRESHOLDS = (66.0, 72.0, 78.0, 84.0, 90.0, 96.0)


def classic_goals(total: float) -> int:
    return sum(1 for t in GOAL_THRESHOLDS if total >= t)


def data_version(competition_season_id: int) -> str:
    """Cheap fingerprint of a season's played data: it changes exactly when a
    match is finalized, so anything derived from the season can be cached under it."""
    agg = (Match.objects
           .filter(competition_season_id=competition_season_id,
                   status=Match.STATUS_FINISHED)
           .aggregate(n=Count("id"), last=Max("data_checked_at")))
    last = agg["last"].isoformat() if agg["last"] else "-"
    return f"{agg['n'] or 0}:{last}"


def get_reference(competition_season_id: int) -> dict:
    """Per-season voto-puro reference (per-role mean/std). Version-cached, so it
    survives restarts and is shared across workers, and refreshes automatically
    when new matches are finalized."""
    key = f"vfoot:voto_reference:{competition_season_id}:{data_version(competition_season_id)}"
    hit = cache.get(key)
    if hit is not None:
        return hit
    data = build_reference(competition_season_id)
    cache.set(key, data, None)
    return data


def _cards_for_match(match_id: int) -> dict[int, dict]:
    cards: dict[int, dict] = defaultdict(
        lambda: {"yellow": 0, "red": 0, "second_yellow": 0, "malus": 0.0})
    for pid, ct in (MatchDisciplinaryEvent.objects
                    .filter(match_id=match_id)
                    .values_list("player_id", "card_type")):
        rec = cards[pid]
        if ct in rec:
            rec[ct] += 1
        rec["malus"] += CARD_MALUS.get(ct, 0.0)
    return cards


def _line(app: MatchAppearance, declared_role: str, vp_rows: dict,
          cards: dict, conceded: int) -> dict:
    pid = app.player_id
    c = cards.get(pid, {})
    card_malus = c.get("malus", 0.0)
    row = vp_rows.get(pid)
    # Prefer the role the rating layer actually SCORED him as: when the Player row
    # carries no classic_role it may have inferred one (a keeper gives himself
    # away through his gk_* features). Falling straight back to "CEN" used to put
    # a keeper in midfield and cost him the -1/goal conceded.
    role = declared_role or (row or {}).get("role") or ""
    role_known = bool(declared_role) or bool((row or {}).get("role_known"))
    lrole = ROLE_TO_LINEUP.get(role, "MID")
    events = {"goals": app.goals, "assists": app.assists,
              "yellow": c.get("yellow", 0),
              "red": c.get("red", 0) + c.get("second_yellow", 0),
              "own_goals": 0}
    base = {"player_id": pid,
            "name": app.player.short_name or app.player.full_name or str(pid),
            "role": role or "CEN", "role_known": role_known,
            "lineup_role": lrole,
            "minutes": app.minutes_played, "entered": False,
            "entered_for": None, "replaced_by": None, "events": events}

    # Voto puro from the heuristic. Keepers now have their OWN channel (anchored on
    # goals prevented), so they are no longer pinned to a flat baseline.
    # s.v. has exactly two legitimate causes, and they are NOT the same thing:
    # too little football played, or no data at all for this match. Say which —
    # an unexplained s.v. on a player who scored reads as a scoring bug.
    if row is None:
        return {**base, "sv": True, "sv_reason": "dati_mancanti", "voto_puro": None,
                "bonus": 0.0, "malus": 0.0, "fantavoto": None}
    if not row.get("rated") or row.get("voto_puro") is None:
        return {**base, "sv": True, "sv_reason": "impiego_insufficiente",
                "voto_puro": None, "bonus": 0.0, "malus": 0.0, "fantavoto": None}
    base["sv_reason"] = None
    vp = float(row["voto_puro"])
    bonus = 3.0 * app.goals + 1.0 * app.assists
    # A keeper also carries the classic -1 per goal conceded. This does NOT double
    # count: his voto puro measures performance against the xG ON TARGET he faced
    # (shot difficulty), the malus is the raw goal count — the usual voto-puro /
    # bonus-malus separation.
    malus = card_malus + (float(conceded) if role == "POR" else 0.0)
    return {**base, "sv": False, "voto_puro": round(vp, 1),
            "bonus": bonus, "malus": malus, "fantavoto": round(vp + bonus - malus, 1)}


def _team_detail(starters: list[dict], bench: list[dict]) -> dict:
    # Order by role (GK->DEF->MID->ATT), then by fantavoto desc within a role,
    # with senza-voto players last in their role band.
    def _sort(ls):
        return sorted(ls, key=lambda l: (ROLE_ORDER.get(l["role"], 9),
                                         l["fantavoto"] is None,
                                         -(l["fantavoto"] or 0)))

    starters, bench = _sort(starters), _sort(bench)
    total = round(sum(l["fantavoto"] for l in starters
                      if l["fantavoto"] is not None), 1)
    return {
        "starters": starters, "bench": bench, "substitutions": [],
        "base_total": total, "total": total, "goals": classic_goals(total),
        "defense": {"eligible": False, "reason": "non applicabile (partita reale)",
                    "avg": None, "bonus": 0.0, "applied": 0.0, "mode": None},
    }


def pagella_for_match(match, reference: dict | None = None) -> dict:
    """Full per-team pagella for a real match. Returns {'home': ClassicTeamDetail,
    'away': ClassicTeamDetail}. Only meaningful for a match with imported
    appearances (a finished, data-loaded fixture)."""
    if reference is None:
        reference = get_reference(match.competition_season_id)

    vp_rows = {r["player_id"]: r for r in voto_puro_for_match(match, reference)}
    cards = _cards_for_match(match.id)
    apps = list(MatchAppearance.objects.filter(match=match).select_related("player"))
    roles = dict(Player.objects.filter(id__in=[a.player_id for a in apps])
                 .values_list("id", "classic_role"))
    hg, ag = int(match.home_goals or 0), int(match.away_goals or 0)

    buckets = {"home": {"starters": [], "bench": []},
               "away": {"starters": [], "bench": []}}
    for a in apps:
        conceded = ag if a.side == "home" else hg
        line = _line(a, roles.get(a.player_id, ""), vp_rows, cards, conceded)
        buckets[a.side]["starters" if a.is_starter else "bench"].append(line)

    return {
        "home": _team_detail(buckets["home"]["starters"], buckets["home"]["bench"]),
        "away": _team_detail(buckets["away"]["starters"], buckets["away"]["bench"]),
    }
