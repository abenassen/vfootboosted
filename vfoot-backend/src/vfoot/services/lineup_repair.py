"""Keeping saved lineups true when the roster changes under them.

The rule the league plays by: **the lineup you submitted is what counts**. It is
frozen at its matchday's lock and scored exactly as sent, whatever happens to the
roster afterwards — a player sold in January still scores for the team that fielded
him in December, which is what makes a postponed round score the same whether it is
concluded on time or six weeks late.

That rule only holds if a lineup is never left holding a player its manager no
longer has AT THE MOMENT OF THE LOCK. Three invariants do it, and this module is
the second:

* **R1 — a locked lineup is immutable.** Past its matchday's first kickoff nobody
  touches it: not the manager, not a transfer.
* **R2 — a settlement repairs the lineups that are still open.** The market's
  same-role rule means every acquisition covers exactly the role the release
  empties, so the incoming player takes the outgoing one's PLACE — in the XI, in
  goal or on the bench, in the same position. The XI stays eleven, the module stays
  legal, and the manager is told.
* **R3 — no settlement while a matchday is being played** (enforced in the market
  engine, keyed on the real calendar).

A manual roster removal by an admin has no incoming player to swap in, so there the
slot is simply vacated: honest, and recoverable because the lineup is not locked.
"""
from __future__ import annotations

import logging

from vfoot.models import SavedLineupSnapshot
from vfoot.services import matchday_state

log = logging.getLogger(__name__)


def _open_snapshots(league, team_id: int, now=None) -> list:
    """This team's saved lineups whose matchday has NOT locked yet (R1)."""
    locked = (matchday_state.locked_matchdays(league.reference_season_id, now)
              if league.reference_season_id else set())
    out = []
    for snap in SavedLineupSnapshot.objects.filter(
        league_id=str(league.id), lineup_id__startswith=f"team{team_id}"
    ):
        # lineup_id is "team<id>" or "team<id>:comp<id>": startswith would also match
        # team12 when looking for team1, so confirm the boundary.
        rest = snap.lineup_id[len(f"team{team_id}"):]
        if rest and not rest.startswith(":"):
            continue
        try:
            md = int(snap.matchday_id)
        except (TypeError, ValueError):
            continue
        if md not in locked:
            out.append(snap)
    return out


def swap_player(league, team_id: int, out_pid: int, in_pid: int | None, now=None) -> list[int]:
    """Replace ``out_pid`` with ``in_pid`` (or remove him) in every open lineup.

    Returns the real matchdays actually touched — what the manager is told about.
    Position is preserved: the incoming player inherits the exact slot, so a manager
    who had him in goal still has a goalkeeper and the bench order is untouched.
    """
    touched: list[int] = []
    out_s, in_s = str(out_pid), (str(in_pid) if in_pid is not None else None)

    for snap in _open_snapshots(league, team_id, now):
        changed = False

        if snap.gk_player_id is not None and str(snap.gk_player_id) == out_s:
            snap.gk_player_id = in_s
            changed = True

        for field in ("starter_player_ids", "bench_player_ids"):
            ids = [str(x) for x in (getattr(snap, field) or [])]
            if out_s not in ids:
                continue
            if in_s is None:
                new = [x for x in ids if x != out_s]
            else:
                new = [in_s if x == out_s else x for x in ids]
            setattr(snap, field, new)
            changed = True

        # Stored but never read by the classic engine; still, leaving a ghost id in
        # a field the UI does render would be sloppy.
        backups = snap.starter_backups or []
        if backups:
            repaired = []
            for row in backups:
                if not isinstance(row, dict):
                    repaired.append(row)
                    continue
                starter = str(row.get("starter_player_id", ""))
                pool = [str(x) for x in (row.get("backup_player_ids") or [])]
                if starter == out_s:
                    if in_s is None:
                        changed = True
                        continue
                    row = {**row, "starter_player_id": in_s}
                    changed = True
                if out_s in pool:
                    row = {**row, "backup_player_ids": (
                        [x for x in pool if x != out_s] if in_s is None
                        else [in_s if x == out_s else x for x in pool])}
                    changed = True
                repaired.append(row)
            snap.starter_backups = repaired

        if changed:
            snap.save(update_fields=["gk_player_id", "starter_player_ids",
                                     "bench_player_ids", "starter_backups"])
            try:
                touched.append(int(snap.matchday_id))
            except (TypeError, ValueError):
                pass

    if touched:
        log.info("Formazioni riparate: lega=%s squadra=%s %s->%s giornate=%s",
                 league.id, team_id, out_pid, in_pid, sorted(set(touched)))
    return sorted(set(touched))
