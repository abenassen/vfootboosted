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

Budget is read from the team's CONTRACTS, never from a separate ledger that could
drift from the roster — players assigned by any means (auction close, direct-assign,
bulk import) are accounted for by the same sum. Two terms, not one:

    remaining = initial_budget
              - sum(purchase_price) over OPEN contracts        # what is still owned
              - sum(purchase_price - sale_price) over CLOSED   # what was burned

The second term is the one that had to be added. Reading only the open contracts
meant that closing one gave back every credit paid for that player, whatever had
actually been agreed on the way out: the offer market enforced its ceiling when the
offer was placed and then, on settlement, refunded the difference out of thin air
(bought at 100, agreed recovery 1 -> the team came out 99 credits richer). A closed
contract leaves exactly the hole between what it cost and what came back — zero when
the recovery was full, which is what every pre-``sale_price`` release is backfilled to.
"""

from __future__ import annotations

from dataclasses import dataclass

from realdata.models import Player
from vfoot.models import FantasyLeague, FantasyRosterSlot, FantasyTeam, LeaguePlayerRole
from vfoot.services import currency

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

    # What the closed contracts took away for good. A sale above the purchase price
    # is a NEGATIVE hole — it gives credits back — and that is deliberate: a manager
    # who resells at a profit is ordinary, and the admin is transcribing a deal.
    sunk: dict[int, int] = {}
    for team_id, price, sale in (
        FantasyRosterSlot.objects.filter(team__league=league, released_at__isnull=False)
        .values_list("team_id", "purchase_price", "sale_price")
    ):
        # sale_price NULL on a closed contract can only be a row written before the
        # field existed and missed by the backfill; full recovery is what it meant.
        recovered = int(price) if sale is None else int(sale)
        sunk[team_id] = sunk.get(team_id, 0) + int(price) - recovered

    out: dict[int, TeamBudget] = {}
    for t in teams:
        t_spent = spent.get(t.id, 0)
        remaining = league.initial_budget - t_spent - sunk.get(t.id, 0)
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
        return LegalityResult(False, f"Un giocatore va pagato almeno {currency.amount(1)}.")

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
        # "Prezzo" e non "offerta": la stessa regola vale al rilancio in asta e
        # quando l'admin scrive a mano un acquisto, dove di offerte non ce n'e'
        # nessuna e la frase parlava di una cosa che non stava succedendo.
        return LegalityResult(
            False,
            f"Prezzo troppo alto: al massimo {currency.price(max_bid)} "
            f"(devi lasciarne almeno 1 per ciascuno degli altri "
            f"{tb.slots_remaining_total - 1} slot da riempire).",
            max_bid,
        )
    return LegalityResult(True, "", max_bid)
