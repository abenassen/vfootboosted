"""Score a fantasy matchday (classic) from the real results — the live conclusion.

Pipeline:
  1. build_matchday_index(): run pagella_for_match over ALL real matches of the
     reference real matchday → a per-player line index (voto_puro / fantavoto / sv /
     lineup_role / conceded), one entry per player who appeared.
  2. for each fantasy fixture, read both teams' saved lineups (SavedLineupSnapshot),
     compose their line lists FILTERED to players still owned (sold players become
     empty s.v. slots; the bench drops them), and score with the classic_scoring
     engine.
  3. the caller (the conclusion view) persists home_total/away_total +
     FantasyFixtureDetail.payload + the ruleset snapshot, atomically.

The composition (compose_team_lines) is pure and unit-tested without a DB; only the
index/lineup/roster lookups touch the database.
"""

from __future__ import annotations

from realdata.models import Match, Player
from vfoot.models import (
    FantasyFixture,
    FantasyFixtureDetail,
    FantasyRosterSlot,
    LeaguePlayerRole,
    SavedLineupSnapshot,
)
from vfoot.services.classic_pagella import (
    get_reference,
    get_role_averages,
    pagella_for_match,
)
from vfoot.services.classic_scoring import Ruleset, resolve_fixture, score_team

CLASSIC_ROLE_TO_LINEUP = {"POR": "GK", "DIF": "DEF", "CEN": "MID", "ATT": "ATT"}


# --------------------------------------------------------------------------- #
# Database lookups (thin).                                                     #
# --------------------------------------------------------------------------- #
def build_matchday_index(competition_season_id: int, real_matchday: int, league) -> dict:
    """player_id -> pagella line, for every player who appeared in the real matchday.

    A player plays in exactly one real match per matchday, so keys never collide.
    ``league`` is passed so the FROZEN classic roles win (a league's match detail must
    agree with its own listone)."""
    matches = Match.objects.filter(
        competition_season_id=competition_season_id, matchday=real_matchday
    )
    reference = get_reference(competition_season_id)
    averages = get_role_averages(competition_season_id)
    index: dict[int, dict] = {}
    for m in matches:
        detail = pagella_for_match(m, reference=reference, league=league, averages=averages)
        for side in ("home", "away"):
            for line in detail[side]["starters"] + detail[side]["bench"]:
                index[line["player_id"]] = line
    return index


def owned_player_ids(team) -> set:
    return set(
        FantasyRosterSlot.objects.filter(team=team, released_at__isnull=True)
        .values_list("player_id", flat=True)
    )


def role_map_for(league, player_ids: list[int]) -> dict:
    """player_id -> lineup role (GK/DEF/MID/ATT), from the league's FROZEN roles, with
    the Transfermarkt seed as a fallback (mirrors the lineup-save validation)."""
    frozen = {
        lpr.player_id: CLASSIC_ROLE_TO_LINEUP.get(lpr.role, "MID")
        for lpr in LeaguePlayerRole.objects.filter(league=league, player_id__in=player_ids)
    }
    missing = [pid for pid in player_ids if pid not in frozen]
    if missing:
        for pid, seed in Player.objects.filter(id__in=missing).exclude(
            classic_role_seed=""
        ).values_list("id", "classic_role_seed"):
            frozen[pid] = CLASSIC_ROLE_TO_LINEUP.get(seed, "MID")
    return frozen


def _lineup_key(team_id: int, competition_id: int | None) -> str:
    return f"team{team_id}" + (f":comp{competition_id}" if competition_id is not None else "")


def read_saved_lineup(league_id: int, real_matchday: int, team_id: int, competition_id: int | None):
    """The team's saved lineup for this matchday+competition, falling back to a
    competition-agnostic snapshot."""
    key = _lineup_key(team_id, competition_id)
    snap = SavedLineupSnapshot.objects.filter(
        league_id=str(league_id), matchday_id=str(real_matchday), lineup_id=key
    ).first()
    if snap is None and competition_id is not None:
        snap = SavedLineupSnapshot.objects.filter(
            league_id=str(league_id), matchday_id=str(real_matchday), lineup_id=f"team{team_id}"
        ).first()
    return snap


def read_previous_lineup(league_id: int, real_matchday: int, team_id: int, competition_id: int | None):
    """The most recent saved lineup from a matchday BEFORE this one (the 'previous'
    fallback for a team that didn't set one). Returns None if there is no earlier lineup."""
    keys = [_lineup_key(team_id, competition_id), f"team{team_id}"]
    best = None
    best_md = None
    for snap in SavedLineupSnapshot.objects.filter(league_id=str(league_id), lineup_id__in=keys):
        try:
            md = int(snap.matchday_id)
        except (TypeError, ValueError):
            continue
        if md < real_matchday and (best_md is None or md > best_md):
            best, best_md = snap, md
    return best


# --------------------------------------------------------------------------- #
# Pure composition (unit-tested without a DB).                                 #
# --------------------------------------------------------------------------- #
def _sv_line(pid: int, lineup_role: str, name: str | None = None) -> dict:
    """A senza-voto placeholder for a player with no line in the index (didn't play)
    or no longer owned (sold): no vote, so it triggers a substitution / is excluded."""
    return {
        "player_id": pid, "name": name or str(pid), "lineup_role": lineup_role,
        "role": None, "voto_puro": None, "fantavoto": None, "sv": True,
        "conceded": 0, "entered": False, "entered_for": None, "replaced_by": None,
    }


def compose_team_lines(
    gk_id: int | None,
    outfield_ids: list[int],
    bench_ids: list[int],
    index: dict,
    role_map: dict,
    owned: set,
) -> tuple[list[dict], list[dict]]:
    """Build the ordered (starters, bench) line lists for scoring.

    - starters = [gk] + outfield (the XI): each becomes its index line when the player
      is owned AND played; an owned player who didn't play, and a SOLD player, both
      become an s.v. placeholder (an empty slot that triggers substitution).
    - bench keeps its priority order but DROPS sold players (they can't come on); an
      owned bench player who didn't play stays as s.v. (useless as a sub, correctly).
    Every line's lineup_role is forced from role_map so the manager's slot role is
    authoritative and consistent between played and non-played players.
    """
    starter_ids = ([gk_id] if gk_id else []) + list(outfield_ids)

    def line_for(pid: int) -> dict:
        role = role_map.get(pid, "MID")
        if pid not in owned:
            return _sv_line(pid, role)  # sold -> empty slot
        base = index.get(pid)
        if base is None:
            return _sv_line(pid, role)  # owned but didn't play
        line = dict(base)
        line["lineup_role"] = role
        return line

    starters = [line_for(pid) for pid in starter_ids]
    bench = [line_for(pid) for pid in bench_ids if pid in owned]
    return starters, bench


def _serialize_team(team: dict) -> dict:
    """Make a score_team/resolve_fixture team dict JSON-safe (ModifierResult -> dict)."""
    out = dict(team)
    out["modifiers"] = [
        {"key": m.key, "eligible": m.eligible, "value": m.value, "scope": m.scope, "detail": m.detail}
        for m in team.get("modifiers", [])
    ]
    return out


def build_fixture_payload(fixture_meta: dict, home: dict, away: dict, ruleset: Ruleset) -> dict:
    """The FantasyFixtureDetail payload — same shape the seed produces, so the existing
    classic match-detail UI renders a concluded league fixture unchanged."""
    return {
        "mode": "classic",
        "fixture_id": fixture_meta.get("fixture_id"),
        "fantasy_round": fixture_meta.get("fantasy_round"),
        "real_matchday": fixture_meta.get("real_matchday"),
        "stage": fixture_meta.get("stage"),
        "home_team": fixture_meta.get("home_team"),
        "away_team": fixture_meta.get("away_team"),
        "home_goals": home["goals"],
        "away_goals": away["goals"],
        "home_total": home["total"],
        "away_total": away["total"],
        "defense_bonus_mode": ruleset.defense_mode,
        "result": "home" if home["goals"] > away["goals"] else "away" if away["goals"] > home["goals"] else "draw",
        "home": _serialize_team(home),
        "away": _serialize_team(away),
    }


def _snap_all_ids(snap) -> list[int]:
    if snap is None:
        return []
    ids = [int(snap.gk_player_id)] if snap.gk_player_id else []
    ids += [int(x) for x in (snap.starter_player_ids or [])]
    ids += [int(x) for x in (snap.bench_player_ids or [])]
    return ids


def team_lines_for_conclusion(league, team, competition_id, real_matchday, index, resolution):
    """Resolve a team's (starters, bench) line lists at conclusion.

    Returns (starters, bench, meta). meta["source"] is one of:
      - "lineup":  the team submitted a lineup for this matchday;
      - "previous": no lineup, admin chose to reuse the previous one (filtered to
                    still-owned players);
      - "forfait":  no lineup, admin chose forfait (empty XI -> 0);
      - "missing":  no lineup and no admin resolution yet — the caller must ask the
                    admin (meta carries has_previous_lineup + previous_lineup_stale).
    """
    owned = owned_player_ids(team)
    snap = read_saved_lineup(league.id, real_matchday, team.id, competition_id)
    source = "lineup"

    if snap is None:
        if resolution == "forfait":
            return [], [], {"source": "forfait", "stale": 0}
        if resolution == "previous":
            snap = read_previous_lineup(league.id, real_matchday, team.id, competition_id)
            if snap is None:
                return [], [], {"source": "forfait", "stale": 0}  # nothing earlier -> forfait
            source = "previous"
        else:
            prev = read_previous_lineup(league.id, real_matchday, team.id, competition_id)
            prev_ids = _snap_all_ids(prev)
            return None, None, {
                "source": "missing",
                "has_previous_lineup": prev is not None,
                "previous_lineup_stale": sum(1 for p in prev_ids if p not in owned),
            }

    gk = int(snap.gk_player_id) if snap.gk_player_id else None
    outfield = [int(x) for x in (snap.starter_player_ids or [])]
    bench = [int(x) for x in (snap.bench_player_ids or [])]
    all_ids = ([gk] if gk else []) + outfield + bench
    role_map = role_map_for(league, all_ids)
    starters, bench_lines = compose_team_lines(gk, outfield, bench, index, role_map, owned)
    stale = sum(1 for p in all_ids if p not in owned) if source == "previous" else 0
    return starters, bench_lines, {"source": source, "stale": stale}


def score_composed_fixture(
    home_lines: tuple[list[dict], list[dict]],
    away_lines: tuple[list[dict], list[dict]],
    ruleset: Ruleset,
    fixture_meta: dict,
) -> dict:
    """Score both composed teams and return the payload. Pure given the line lists."""
    home = score_team(home_lines[0], home_lines[1], ruleset)
    away = score_team(away_lines[0], away_lines[1], ruleset)
    resolve_fixture(home, away, ruleset)
    return build_fixture_payload(fixture_meta, home, away, ruleset)


def score_and_persist_matchday(md, league, ruleset, fixtures, resolutions, force, update_snapshot=True):
    """Score every fixture of a classic matchday and FREEZE the results, atomically:
    fx.home_total/away_total (classic goals) + FantasyFixtureDetail.payload (the full
    tabellino) + (optionally) md.ruleset_snapshot. Shared by the conclusion and the
    manual recompute.

    If any team has no lineup and no resolution and not ``force``, nothing is persisted
    and the return carries ``missing_teams`` (the caller should return a 400). Returns
    {"updated", "stage_ids", "missing_teams"}.
    """
    index = build_matchday_index(md.real_competition_season_id, md.real_matchday, league)
    resolutions = resolutions or {}

    # Pass 1: resolve lineups, collect teams still without one.
    team_lines: dict[tuple[int, str], tuple] = {}
    missing_teams: dict[int, dict] = {}
    for fx in fixtures:
        for side, team in (("home", fx.home_team), ("away", fx.away_team)):
            res = resolutions.get(str(team.id))
            starters, bench, meta = team_lines_for_conclusion(
                league, team, fx.competition_id, md.real_matchday, index, res)
            if meta["source"] == "missing":
                missing_teams[team.id] = {"team_id": team.id, "name": team.name, **meta}
            else:
                team_lines[(fx.id, side)] = (starters, bench)

    if missing_teams and not force:
        return {"updated": 0, "stage_ids": set(), "missing_teams": list(missing_teams.values())}

    # Pass 2: score + persist (a still-missing team under force = forfait / empty).
    updated = 0
    stage_ids: set[int] = set()
    for fx in fixtures:
        home_ln = team_lines.get((fx.id, "home")) or ([], [])
        away_ln = team_lines.get((fx.id, "away")) or ([], [])
        payload = score_composed_fixture(home_ln, away_ln, ruleset, {
            "fixture_id": fx.id, "fantasy_round": fx.round_no, "real_matchday": md.real_matchday,
            "stage": fx.stage_id, "home_team": fx.home_team.name, "away_team": fx.away_team.name,
        })
        fx.home_total = float(payload["home_goals"])
        fx.away_total = float(payload["away_goals"])
        fx.status = FantasyFixture.STATUS_FINISHED
        FantasyFixtureDetail.objects.update_or_create(
            fixture=fx,
            defaults={"vfoot_home": payload["home_total"],
                      "vfoot_away": payload["away_total"], "payload": payload},
        )
        updated += 1
        if fx.stage_id:
            stage_ids.add(fx.stage_id)

    if fixtures:
        FantasyFixture.objects.bulk_update(fixtures, ["home_total", "away_total", "status"], batch_size=500)
    if update_snapshot:
        md.ruleset_snapshot = ruleset.to_snapshot()
        md.save(update_fields=["ruleset_snapshot"])
    return {"updated": updated, "stage_ids": stage_ids, "missing_teams": []}
