"""Freeze a classic-mode league's role 'listone' (per-league snapshot of roles).

Classic fantacalcio freezes a player's role PER PLAYER, at the moment he first
enters the listone (arrives in Serie A) — and it must not drift when Transfermarkt
later re-classifies him. This runs on EVERY TM poll (not once): each run seeds the
roles of players who are new to the listone and leaves every already-frozen role
untouched. So the listone MEMBERSHIP is live (players come and go with the market)
while assigned ROLES are stable.

Additive by design:
  * a player new to the listone gets a fresh ``LeaguePlayerRole`` from the current
    seed (data-driven inference, else the TM map) — so a mid-season signing is
    covered the first time he appears;
  * existing rows are never touched — admin overrides AND already-frozen seed rows
    alike — so a role, once set in a league, never moves.

Consequences of freezing per player (rules the user fixed, tested in
``tests_decisions.DepartureReturnTests``):
  * TM changing a player's role does NOT disturb a league where he is already
    present; only leagues formed afterwards seed the new role from the listone.
  * A player who LEAVES (stint closed) keeps his frozen row as history — it is not
    deleted — and on RETURN (stint re-opened) that same row is preserved, so the
    role stays the one consolidated at his first appearance.

``reset=True`` re-snapshots seed rows from the current TM roles (an explicit "redo
the listone" admin action) while still preserving admin overrides.
"""

from __future__ import annotations

from realdata.models import Player, PlayerTeamStint
from vfoot.models import LeaguePlayerRole, SeasonPlayerRole


def _open_role_decisions(league):   # thin indirection, keeps the import lazy
    from vfoot.services.league_decisions import open_role_decisions
    return open_role_decisions(league)


def eligible_player_ids(competition_season_id: int) -> set[int]:
    """Players currently fieldable in a season = those with an OPEN roster stint
    (end_date NULL) in one of the season's teams. A transfer out / abroad closes the
    stint and so removes the player here; an arrival opens one and adds them. This is
    LIVE (follows the real market) and global, unlike the per-league frozen roles."""
    return set(PlayerTeamStint.objects
               .filter(team_season__competition_season_id=competition_season_id,
                       end_date__isnull=True)
               .values_list("player_id", flat=True).distinct())


def snapshot_league_listone(league, *, reset: bool = False) -> dict:
    """Snapshot/refresh the league's frozen role listone. Returns a summary dict."""
    if league.reference_season_id is None:
        raise ValueError(
            f"League {league.id} has no reference_season; cannot build a listone.")

    cs_id = league.reference_season_id
    # Seed from the season-wide inference under THIS league's policy (mitigated =
    # an unambiguous provider position wins; data = the measured playing style
    # decides). Player.classic_role stays a last-resort fallback for players the
    # inference never saw, so a league is never left with a hole.
    seeded = {r.player_id: r.role_for(league.role_mode)
              for r in SeasonPlayerRole.objects.filter(competition_season_id=cs_id)
              if r.role_for(league.role_mode)}
    # Players the inference cannot settle get NO seeded role at all: they are in
    # limbo until a human answers, and a frozen row would be an answer. Keeping
    # the two states distinct is what lets "has a frozen role" mean "settled" —
    # which in turn is what stops a later recomputation from reopening a question
    # about someone who has since been bought.
    from vfoot.services.league_decisions import players_needing_decision
    undecidable = players_needing_decision(league)
    # Seed roles only for currently-eligible players (open stint). Departed players
    # keep any existing frozen row (history) but get no NEW seed row.
    players = list(Player.objects.filter(id__in=eligible_player_ids(cs_id)))
    existing = {r.player_id: r
                for r in LeaguePlayerRole.objects.filter(league=league)}

    summary = {"roster": len(players), "created": 0, "reset": 0,
               "preserved_admin": 0, "kept_seed": 0, "skipped_no_role": 0,
               "awaiting_decision": 0}

    for p in players:
        seed = seeded.get(p.id) or p.classic_role
        row = existing.get(p.id)
        if row is None:
            if p.id in undecidable:
                summary["awaiting_decision"] = summary.get("awaiting_decision", 0) + 1
                continue
            if not seed:
                summary["skipped_no_role"] += 1
                continue
            LeaguePlayerRole.objects.create(
                league=league, player=p, role=seed,
                source=LeaguePlayerRole.SOURCE_SEED)
            summary["created"] += 1
        elif row.source == LeaguePlayerRole.SOURCE_ADMIN:
            summary["preserved_admin"] += 1
        elif reset and seed and row.role != seed:
            row.role = seed
            row.save(update_fields=["role", "updated_at"])
            summary["reset"] += 1
        else:
            summary["kept_seed"] += 1

    # Whatever the seeding could not settle becomes an explicit question for the
    # admin, and blocks the market until answered.
    summary["decisions_opened"] = _open_role_decisions(league)
    return summary
