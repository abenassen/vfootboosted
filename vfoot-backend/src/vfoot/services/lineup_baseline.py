"""The starting lineup: written when the roster completes, never at a deadline.

The case it closes is «non ha mandato la formazione». Every matchday after the
first inherits the previous lineup (``read_previous_lineup``), so the only team
that can reach a kickoff with nothing at all is one that has NEVER had a lineup —
and for that team the admin used to decide, at conclusion time, with the votes
already known. Now the server writes one the moment there is something to write
it from.

Why "when the roster completes" and not "at the deadline":

* a complete roster (the league's quota, 3-8-8-6 by default) admits a legal XI by
  construction, so there is always something to write;
* what is written before a round begins cannot be contaminated by anything that
  happens in it. The suggester already only reads matches BEFORE the matchday, but
  "written early" is the guarantee that does not depend on anybody remembering
  that;
* written once. It is a lineup like any other from then on: the next matchday
  inherits it, the market repairs it, the manager overwrites it by saving.

``ensure_for`` is idempotent and cheap when there is nothing to do, so it is
called from every place a roster can complete — the auction, the market, the
admin endpoints — and from the lineup page as a safety net. The one thing it will
never do is write a baseline for a round that has already closed on the team:
that lineup would be chosen by a machine with the votes on the board, which is the
very thing the rule exists to prevent.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from vfoot.models import FantasyLeague, FantasyRosterSlot, SavedLineupSnapshot
from vfoot.services import matchday_state
from vfoot.services.lineup_suggest import (
    bench_after,
    constraints_for,
    roster_for_suggestion,
    suggest_xi,
)

log = logging.getLogger(__name__)


def roster_is_complete(league, team) -> bool:
    """Every slot of the league's quota filled, role by role (classic); the roster
    size reached (aura, where the quota is only a count)."""
    owned = list(
        FantasyRosterSlot.objects.filter(team=team, released_at__isnull=True)
        .values_list("player_id", flat=True)
    )
    if len(owned) < league.roster_size():
        return False
    if league.mode != FantasyLeague.MODE_CLASSIC:
        return True
    from vfoot.services.classic_matchday_scoring import role_map_for

    roles = role_map_for(league, owned)
    counts = {"GK": 0, "DEF": 0, "MID": 0, "ATT": 0}
    for pid in owned:
        counts[roles.get(pid, "MID")] = counts.get(roles.get(pid, "MID"), 0) + 1
    quota = league.roster_quota()
    return (counts["GK"] >= quota["POR"] and counts["DEF"] >= quota["DIF"]
            and counts["MID"] >= quota["CEN"] and counts["ATT"] >= quota["ATT"])


def has_any_lineup(league, team) -> bool:
    """Has this team EVER had a lineup in this league, for any matchday or
    competition? Once it has, inheritance takes over and no baseline is needed."""
    return SavedLineupSnapshot.objects.filter(
        league_id=str(league.id), lineup_id__regex=rf"^team{team.id}(:|$)"
    ).exists()


def ensure_for(team, now=None):
    """Write the team's starting lineup if — and only if — it has none at all, its
    roster is complete, and the first matchday it can still field has not closed
    on it. Returns the snapshot written, or None.

    Never raises into the caller: an auction hammer or a market settlement must
    not fail because the suggester met an edge case. The page's safety net will
    try again, and the log says what happened.
    """
    try:
        return _ensure_for(team, now or timezone.now())
    except Exception:  # pragma: no cover - defensive by design, see docstring
        log.exception("baseline lineup for team %s could not be written", team.id)
        return None


def _ensure_for(team, now):
    league = team.league
    if league.reference_season_id is None:
        return None
    if has_any_lineup(league, team) or not roster_is_complete(league, team):
        return None
    real_md = matchday_state.next_fieldable_matchday(league, now, team=team)
    if real_md is None:
        return None
    if matchday_state.is_closed_for(league, real_md, team, now):
        return None     # cannot happen by construction, kept as the guarantee
    return write_baseline(league, team, real_md)


def write_baseline(league, team, real_md: int):
    roster = roster_for_suggestion(league, team, real_md)
    xi = suggest_xi(roster, constraints_for(league))
    starters = ([xi["gk_player_id"]] if xi["gk_player_id"] else []) + xi["starter_player_ids"]
    snap, _ = SavedLineupSnapshot.objects.update_or_create(
        league_id=str(league.id), matchday_id=str(real_md), lineup_id=f"team{team.id}",
        defaults={
            "gk_player_id": str(xi["gk_player_id"]) if xi["gk_player_id"] else None,
            "starter_player_ids": xi["starter_player_ids"],
            "bench_player_ids": bench_after(roster, starters),
            "starter_backups": [],
            "origin": SavedLineupSnapshot.ORIGIN_BASELINE,
        },
    )
    log.info("baseline lineup written for team %s, matchday %s", team.id, real_md)
    return snap
