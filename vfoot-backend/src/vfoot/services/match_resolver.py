"""Resolve a fantasy player's real-match outcome for a reference-season matchday.

The league's classic scoring answers: for each fantasy player in fantasy round R
(= real matchday R of the reference season), find the ONE real match of that
matchday involving the player's club and read their outcome. A club plays exactly
one match per matchday, so the resolution is unambiguous.

Crucially this is STATUS-AWARE, distinguishing two cases a naive "no vote" lookup
conflates:
  - the club match is CONCLUDED (data_ready) and the player is senza voto -> the
    manager's bench may cover him (a normal substitution);
  - the club match is NOT concluded (postponed / scheduled / live / finished-but-
    data-not-stable) -> there is no vote yet: the league's POSTPONEMENT POLICY
    applies (wait or office vote), NOT a bench substitution.

It also resolves the SofaScore postponed-duplicate cleanly: among a club's matches
in the matchday it prefers the concluded (data_ready) row over the postponed shell,
so the empty placeholder never shadows the played game.

Phase-1 deliverable of the pipeline; the Phase-3 live classic scoring calls this.

Caveat: the club is the player's CURRENT open stint — correct for live/upcoming
scoring. Retrospective scoring of a player who transferred mid-season would want the
club AT that matchday (the concluded match's MatchAppearance already carries the true
team); a future refinement can prefer the appearance when it exists.
"""
from __future__ import annotations

from django.db.models import Q

from realdata.models import Match, PlayerTeamStint
from vfoot.services.classic_pagella import get_reference, pagella_for_match

# Outcome statuses
VOTO = "voto"          # concluded match, player rated -> fantavoto available
SENZA_VOTO = "sv"      # concluded match, player not rated -> bench-substitutable
PENDING = "pending"    # club match not concluded yet -> postponement policy
NO_MATCH = "no_match"  # club has no fixture this matchday, or player has no club

# Preference when a club has >1 match row for the matchday (postponed shell + replay).
_STATUS_RANK = {
    Match.STATUS_FINISHED: 3,
    Match.STATUS_LIVE: 2,
    Match.STATUS_SCHEDULED: 1,
    Match.STATUS_POSTPONED: 0,
    Match.STATUS_CANCELLED: 0,
}


def player_team_season_id(player_id: int, cs_id: int) -> int | None:
    """The player's current club (open stint) in the season, or None."""
    return (PlayerTeamStint.objects
            .filter(player_id=player_id,
                    team_season__competition_season_id=cs_id,
                    end_date__isnull=True)
            .values_list("team_season_id", flat=True)
            .first())


def authoritative_match(cs_id: int, matchday: int, team_season_id: int) -> Match | None:
    """The club's match for the matchday, preferring a concluded (data_ready) row
    over a postponed/scheduled shell."""
    matches = list(Match.objects.filter(
        competition_season_id=cs_id, matchday=matchday
    ).filter(Q(home_team_id=team_season_id) | Q(away_team_id=team_season_id)))
    if not matches:
        return None
    return max(matches, key=lambda m: (1 if m.data_ready else 0,
                                       _STATUS_RANK.get(m.status, 0)))


def _outcome(pid, status, match, line, matchday):
    return {"player_id": pid, "status": status,
            "match_id": match.id if match else None,
            "match_status": match.status if match else None,
            "matchday": matchday, "line": line}


def resolve_matchday(cs_id: int, matchday: int, player_ids, reference=None) -> dict:
    """Resolve every player's outcome for the matchday. Returns
    {player_id -> outcome dict}. Computes each concluded match's pagella once."""
    if reference is None:
        reference = get_reference(cs_id)
    player_ids = list(player_ids)

    ts_by_player = {pid: player_team_season_id(pid, cs_id) for pid in player_ids}
    match_by_ts = {ts: authoritative_match(cs_id, matchday, ts)
                   for ts in {t for t in ts_by_player.values() if t}}

    # One pagella per distinct concluded match -> player_id -> line.
    line_by_player: dict[int, dict] = {}
    for m in {mm.id: mm for mm in match_by_ts.values()
              if mm is not None and mm.data_ready}.values():
        pag = pagella_for_match(m, reference)
        for side in ("home", "away"):
            for group in ("starters", "bench"):
                for line in pag[side][group]:
                    line_by_player[line["player_id"]] = line

    out = {}
    for pid in player_ids:
        match = match_by_ts.get(ts_by_player.get(pid))
        if match is None:
            out[pid] = _outcome(pid, NO_MATCH, None, None, matchday)
        elif not match.data_ready:
            out[pid] = _outcome(pid, PENDING, match, None, matchday)
        else:
            line = line_by_player.get(pid)
            status = VOTO if (line and not line["sv"]) else SENZA_VOTO
            out[pid] = _outcome(pid, status, match, line, matchday)
    return out


def resolve_player(player_id: int, cs_id: int, matchday: int, reference=None) -> dict:
    """Single-player convenience wrapper around resolve_matchday."""
    return resolve_matchday(cs_id, matchday, [player_id], reference)[player_id]


def pending_player_ids(cs_id: int, matchday: int, player_ids) -> set:
    """Of these players, the ones whose club has NOT played its match of the matchday.

    The scoring path's entry point into this module: it is what lets a postponement
    stop being indistinguishable from a senza voto. A player is PENDING when his
    club's authoritative row for the matchday is not ``data_ready`` — postponed,
    still to be played, live, or finished but not yet stable. Everyone else (no
    club here, club not playing this round, match concluded) is left to the normal
    s.v. treatment, which is the correct one for them.

    Same caveat as ``resolve_matchday``: the club is the player's CURRENT open
    stint. For a pending match there is no appearance to read the true club from,
    so there is nothing better available — and the case only bites for a player who
    changed club between the postponement and the recovery.
    """
    player_ids = list(player_ids)
    if not player_ids:
        return set()
    fixtures = matchday_fixtures_by_team(cs_id, matchday)
    stints = dict(
        PlayerTeamStint.objects.filter(
            player_id__in=player_ids,
            team_season__competition_season_id=cs_id,
            end_date__isnull=True,
        ).values_list("player_id", "team_season_id")
    )
    out = set()
    for pid in player_ids:
        match = fixtures.get(stints.get(pid))
        if match is not None and not match.data_ready:
            out.add(pid)
    return out


def pending_matches(cs_id: int, matchday: int, player_ids) -> list:
    """The distinct real matches behind ``pending_player_ids`` — what the admin has
    to be told about ("Como-Milan non si è giocata"), rather than a list of players."""
    player_ids = list(player_ids)
    if not player_ids:
        return []
    fixtures = matchday_fixtures_by_team(cs_id, matchday)
    stints = dict(
        PlayerTeamStint.objects.filter(
            player_id__in=player_ids,
            team_season__competition_season_id=cs_id,
            end_date__isnull=True,
        ).values_list("player_id", "team_season_id")
    )
    seen: dict[int, Match] = {}
    for pid in player_ids:
        match = fixtures.get(stints.get(pid))
        if match is not None and not match.data_ready:
            seen[match.id] = match
    return [
        {
            "match_id": m.id,
            "status": m.status,
            "home": m.home_team.team.name,
            "away": m.away_team.team.name,
            "kickoff": m.kickoff.isoformat() if m.kickoff else None,
        }
        for m in sorted(seen.values(), key=lambda x: (x.kickoff is None, x.kickoff, x.id))
    ]


def matchday_fixtures_by_team(cs_id: int, matchday: int) -> dict:
    """{team_season_id: Match} for one matchday, keeping the authoritative row when a
    club has more than one (postponed shell + replay)."""
    def rank(m):
        return (1 if m.data_ready else 0, _STATUS_RANK.get(m.status, 0))

    out: dict[int, Match] = {}
    for m in (Match.objects
              .filter(competition_season_id=cs_id, matchday=matchday)
              .select_related("home_team__team", "away_team__team")):
        for ts_id in (m.home_team_id, m.away_team_id):
            cur = out.get(ts_id)
            if cur is None or rank(m) > rank(cur):
                out[ts_id] = m
    return out
