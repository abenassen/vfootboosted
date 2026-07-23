"""Auction legality engine (classic mode).

Single source of truth for "is this purchase legal?". A classic squad must end up
with exactly the league's roster quota (default 3-8-8-6 = 25) and every player costs
at least 1 credit, so at any point a manager can only commit credits he can still
afford WITHOUT making the rest of his squad unbuyable.

The binding rule, inherited verbatim from the legacy engine:

    a bid of ``x`` on a player of role ``R`` is legal for a team iff
      - the team still has a free slot for role ``R``, and
      - ``budget_remaining - x >= (slots_remaining_total - 1)``

i.e. after paying ``x`` the team must keep at least 1 credit for each of its still
unfilled slots (the ``- 1`` is the slot being filled by this very purchase). The
largest legal bid is therefore ``budget_remaining - (slots_remaining_total - 1)``.

Budget spent is read from the team's ACTIVE roster slots (``released_at is null``),
so it naturally accounts for players already assigned by any means (auction close,
direct-assign, bulk import) — the engine never keeps a separate ledger that could
drift from the roster.
"""

from __future__ import annotations

from dataclasses import dataclass

from realdata.models import Player
from vfoot.models import FantasyLeague, FantasyRosterSlot, FantasyTeam, LeaguePlayerRole

ROLES = ("POR", "DIF", "CEN", "ATT")


@dataclass
class TeamBudget:
    team_id: int
    team_name: str
    manager_username: str
    initial_budget: int
    spent: int
    remaining: int
    # Per-role: filled / quota, and how many slots are still open.
    slots: dict[str, dict[str, int]]
    slots_remaining_total: int
    # Largest bid the team could legally place, ignoring role (i.e. for a role it
    # still has a free slot for). None of the per-role guards are applied here.
    max_bid_any: int

    def max_bid_for_role(self, role: str) -> int:
        """Largest legal bid for a player of ``role`` — 0 if no slot free for it."""
        if role not in self.slots or self.slots[role]["remaining"] <= 0:
            return 0
        return max(0, self.remaining - (self.slots_remaining_total - 1))


def league_role_map(league: FantasyLeague, player_ids: list[int]) -> dict[int, str]:
    """Frozen classic role (POR/DIF/CEN/ATT) for each player in this league."""
    return dict(
        LeaguePlayerRole.objects.filter(league=league, player_id__in=player_ids)
        .values_list("player_id", "role")
    )


def player_role(league: FantasyLeague, player: Player) -> str | None:
    row = LeaguePlayerRole.objects.filter(league=league, player=player).first()
    return row.role if row else None


def team_budgets(league: FantasyLeague) -> dict[int, TeamBudget]:
    """Compute the budget/slot state of every team in the league."""
    quota = league.roster_quota()
    quota_total = league.roster_size()
    teams = list(
        FantasyTeam.objects.filter(league=league).select_related("manager__user")
    )

    # Active roster slots for the whole league, joined to frozen roles in one pass.
    slots = list(
        FantasyRosterSlot.objects.filter(team__league=league, released_at__isnull=True)
        .values_list("team_id", "player_id", "purchase_price")
    )
    role_by_player = league_role_map(league, [pid for _, pid, _ in slots])

    spent: dict[int, int] = {}
    filled: dict[int, dict[str, int]] = {}
    for team_id, player_id, price in slots:
        spent[team_id] = spent.get(team_id, 0) + int(price)
        role = role_by_player.get(player_id)
        if role:
            filled.setdefault(team_id, {}).setdefault(role, 0)
            filled[team_id][role] += 1

    out: dict[int, TeamBudget] = {}
    for t in teams:
        t_spent = spent.get(t.id, 0)
        remaining = league.initial_budget - t_spent
        t_filled = filled.get(t.id, {})
        per_role: dict[str, dict[str, int]] = {}
        slots_remaining_total = 0
        for role in ROLES:
            q = quota.get(role, 0)
            f = t_filled.get(role, 0)
            r = max(0, q - f)
            slots_remaining_total += r
            per_role[role] = {"quota": q, "filled": f, "remaining": r}
        # If a team somehow overfilled (shouldn't happen), clamp total to >=0.
        max_bid_any = max(0, remaining - (slots_remaining_total - 1)) if slots_remaining_total > 0 else 0
        out[t.id] = TeamBudget(
            team_id=t.id,
            team_name=t.name,
            manager_username=t.manager.user.username,
            initial_budget=league.initial_budget,
            spent=t_spent,
            remaining=remaining,
            slots=per_role,
            slots_remaining_total=slots_remaining_total,
            max_bid_any=max_bid_any,
        )
    return out


@dataclass
class LegalityResult:
    ok: bool
    reason: str = ""
    max_bid: int = 0


def check_purchase(
    league: FantasyLeague, team_id: int, role: str | None, amount: int,
    budgets: dict[int, TeamBudget] | None = None,
) -> LegalityResult:
    """Is it legal for ``team_id`` to pay ``amount`` for a player of ``role``?"""
    if role is None:
        return LegalityResult(False, "Ruolo del giocatore non definito in questa lega (listone).")
    if role not in ROLES:
        return LegalityResult(False, f"Ruolo sconosciuto: {role}.")
    if amount < 1:
        return LegalityResult(False, "Un giocatore va pagato almeno 1 credito.")

    budgets = budgets if budgets is not None else team_budgets(league)
    tb = budgets.get(team_id)
    if tb is None:
        return LegalityResult(False, "Squadra non trovata nella lega.")

    slot = tb.slots.get(role, {"remaining": 0})
    if slot["remaining"] <= 0:
        return LegalityResult(
            False, f"Nessuno slot libero per il ruolo {role} (quota gia' completa)."
        )
    max_bid = tb.max_bid_for_role(role)
    if amount > max_bid:
        return LegalityResult(
            False,
            f"Offerta troppo alta: al massimo {max_bid} crediti "
            f"(devi lasciarne almeno 1 per ciascuno degli altri "
            f"{tb.slots_remaining_total - 1} slot da riempire).",
            max_bid,
        )
    return LegalityResult(True, "", max_bid)
