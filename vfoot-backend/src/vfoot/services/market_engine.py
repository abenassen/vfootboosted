"""Repair-market legality engine (classic mode).

The post-auction transfer window works by OFFERS on free agents, each pledging a
simultaneous RELEASE of one of the offerer's own players of the same classic role.
This module is the single source of truth for "is this offer legal?" and for
applying an accepted offer to the roster.

Credit model (decided with the user, see docs/offer_market_plan.md):

  * A player is released for `recovery` credits — a fixed amount, or a fraction
    (30/50/75%, rounded UP) of the price originally paid for him.
  * Since release and purchase are simultaneous and same-role (1:1), a manager's
    roster size never changes: the auction's "keep 1 credit per empty slot" guard
    is inert here. The only binding constraint is cash.
  * Credits are RESERVED: every still-live offer (leading or accepted) a manager
    holds commits its NET cost `amount - recovery`. A new offer is legal only if,
    assuming ALL the manager's live offers win, his balance stays >= 0. So the
    ceiling for a new offer releasing player p is

        max_amount = remaining - sum(net_i for other live offers) + recovery(p)

    which for a lone offer reduces to `remaining + recovery(p)` — the worked
    example (26 residui, Lautaro pagato 135, recupero 50% -> tetto 26+68 = 94).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from django.utils import timezone

from vfoot.models import (
    FantasyLeague,
    FantasyRosterSlot,
    FantasyTeam,
    LeaguePlayerRole,
    MarketOffer,
    MarketSession,
)
from vfoot.services.auction_engine import ROLES, league_role_map, team_budgets

# How long a leading offer stands before it is promoted to "accepted" absent a
# higher rebid. A rebid mints a fresh leading offer, restarting the clock.
OFFER_TTL = timedelta(hours=24)


def _ceil_pct(price: int, pct_num: int) -> int:
    """ceil(price * pct_num / 100) with pure integer math (no FP rounding)."""
    price = max(0, int(price))
    return (price * pct_num + 99) // 100


def recovery_for(session: MarketSession, purchase_price: int) -> int:
    """Credits recovered by releasing a player bought for `purchase_price`."""
    mode = session.credit_recovery_mode
    if mode == MarketSession.RECOVERY_FIXED:
        return int(session.fixed_recovery_amount)
    if mode == MarketSession.RECOVERY_FRAC30:
        return _ceil_pct(purchase_price, 30)
    if mode == MarketSession.RECOVERY_FRAC50:
        return _ceil_pct(purchase_price, 50)
    if mode == MarketSession.RECOVERY_FRAC75:
        return _ceil_pct(purchase_price, 75)
    return int(session.fixed_recovery_amount)


def free_agent_ids(league: FantasyLeague) -> set[int]:
    """Players offerable as free agents: they have a frozen classic role in this
    league (they are in the listone), they are NOT on any active roster, and — if
    the league is bound to a real season — they are still fieldable in it."""
    role_ids = set(
        LeaguePlayerRole.objects.filter(league=league).values_list("player_id", flat=True)
    )
    rostered = set(
        FantasyRosterSlot.objects.filter(team__league=league, released_at__isnull=True)
        .values_list("player_id", flat=True)
    )
    pool = role_ids - rostered
    if league.reference_season_id:
        from vfoot.services.listone import eligible_player_ids

        pool &= eligible_player_ids(league.reference_season_id)
    # Belt and braces on the limbo. Membership in the listone is already the gate
    # — someone still awaiting a role has no frozen row — but stating it here
    # means a stray seed row cannot quietly reopen the market on a player whose
    # role is an open question, and a role settled after the bidding is exactly
    # what changes what people paid for.
    from vfoot.services.league_decisions import undecided_player_ids

    return pool - undecided_player_ids(league)


@dataclass
class MarketTeamState:
    team_id: int
    remaining: int  # initial_budget - spent (cash left after the settled roster)
    # active roster: player_id -> {"price": int, "role": str|None}
    roster: dict[int, dict] = field(default_factory=dict)
    reserved_net: int = 0  # sum of (amount - recovery) over this team's live offers
    pledged_release_ids: set[int] = field(default_factory=set)
    live_target_ids: set[int] = field(default_factory=set)

    def available(self) -> int:
        """Credits still free to commit, before counting a new offer's own recovery."""
        return self.remaining - self.reserved_net

    def max_amount_releasing(self, recovery: int) -> int:
        return self.available() + int(recovery)


def market_states(
    league: FantasyLeague, session: MarketSession | None,
    *, exclude_offer_id: int | None = None,
) -> dict[int, MarketTeamState]:
    """Per-team cash / roster / live-offer reservation state for the league."""
    budgets = team_budgets(league)  # gives remaining (cash) per team

    # Active roster of every team, joined to frozen roles for role checks.
    slots = list(
        FantasyRosterSlot.objects.filter(team__league=league, released_at__isnull=True)
        .values_list("team_id", "player_id", "purchase_price")
    )
    role_by_player = league_role_map(league, [pid for _, pid, _ in slots])

    states: dict[int, MarketTeamState] = {}
    for tid, tb in budgets.items():
        states[tid] = MarketTeamState(team_id=tid, remaining=tb.remaining)
    for tid, pid, price in slots:
        st = states.get(tid)
        if st is not None:
            st.roster[pid] = {"price": int(price), "role": role_by_player.get(pid)}

    if session is not None:
        live = list(
            MarketOffer.objects.filter(
                session=session, status__in=MarketOffer.LIVE_STATUSES
            ).values_list("id", "team_id", "target_player_id", "release_player_id",
                          "amount", "recovery_amount")
        )
        for oid, tid, target_id, release_id, amount, recovery in live:
            if oid == exclude_offer_id:
                continue
            st = states.get(tid)
            if st is None:
                continue
            st.reserved_net += int(amount) - int(recovery)
            st.pledged_release_ids.add(release_id)
            st.live_target_ids.add(target_id)
    return states


@dataclass
class OfferCheck:
    ok: bool
    reason: str = ""
    max_amount: int = 0
    recovery: int = 0
    role: str | None = None


def leading_offer_for(session: MarketSession, target_player_id: int) -> MarketOffer | None:
    return (
        MarketOffer.objects.filter(
            session=session, target_player_id=target_player_id,
            status=MarketOffer.STATUS_LEADING,
        ).order_by("-amount", "created_at").first()
    )


def _target_locked(session: MarketSession, target_player_id: int) -> bool:
    """A target being resolved (accepted awaiting apply, or already settled) no
    longer accepts rebids."""
    return MarketOffer.objects.filter(
        session=session, target_player_id=target_player_id,
        status__in=(MarketOffer.STATUS_ACCEPTED, MarketOffer.STATUS_SETTLED),
    ).exists()


def check_offer(
    session: MarketSession,
    team: FantasyTeam,
    target_player_id: int,
    release_player_id: int,
    amount: int,
    *,
    states: dict[int, MarketTeamState] | None = None,
    pool: set[int] | None = None,
    role_map: dict[int, str] | None = None,
) -> OfferCheck:
    """Is this offer legal right now? Returns the ceiling and the shared role too."""
    league = session.league
    if session.status != MarketSession.STATUS_OPEN:
        return OfferCheck(False, "La sessione di mercato non e' aperta.")

    if release_player_id == target_player_id:
        return OfferCheck(False, "Il giocatore da svincolare e quello offerto coincidono.")

    if pool is None:
        pool = free_agent_ids(league)
    if target_player_id not in pool:
        return OfferCheck(False, "Il giocatore non e' uno svincolato offribile.")

    states = states if states is not None else market_states(league, session)
    st = states.get(team.id)
    if st is None:
        return OfferCheck(False, "Squadra non trovata nella lega.")

    rel = st.roster.get(release_player_id)
    if rel is None:
        return OfferCheck(False, "Il giocatore da svincolare non e' nella tua rosa.")

    if role_map is None:
        role_map = league_role_map(league, [target_player_id])
    target_role = role_map.get(target_player_id)
    release_role = rel["role"]
    if target_role is None:
        return OfferCheck(False, "Ruolo del giocatore offerto non definito nel listone.")
    if release_role != target_role:
        return OfferCheck(
            False,
            f"Ruolo diverso: offri un {target_role} svincolando un {release_role}. "
            "In modalita' classic devono coincidere.",
        )

    recovery = recovery_for(session, rel["price"])

    if _target_locked(session, target_player_id):
        return OfferCheck(False, "Offerta gia' in via di definizione per questo giocatore.",
                          recovery=recovery, role=target_role)

    if target_player_id in st.live_target_ids:
        return OfferCheck(False, "Hai gia' un'offerta aperta per questo giocatore.",
                          recovery=recovery, role=target_role)
    if release_player_id in st.pledged_release_ids:
        return OfferCheck(
            False, "Stai gia' offrendo questo stesso giocatore in svincolo su un'altra offerta.",
            recovery=recovery, role=target_role)

    max_amount = st.max_amount_releasing(recovery)

    if amount < 1:
        return OfferCheck(False, "Un'offerta vale almeno 1 credito.",
                          max_amount=max_amount, recovery=recovery, role=target_role)

    leading = leading_offer_for(session, target_player_id)
    if leading is not None and amount <= leading.amount:
        return OfferCheck(
            False,
            f"Serve un rilancio: l'offerta in testa e' {leading.amount}, "
            f"devi offrire almeno {leading.amount + 1}.",
            max_amount=max_amount, recovery=recovery, role=target_role)

    if amount > max_amount:
        return OfferCheck(
            False,
            f"Crediti insufficienti: al massimo {max_amount} "
            f"({st.available()} disponibili + {recovery} di recupero dallo svincolo).",
            max_amount=max_amount, recovery=recovery, role=target_role)

    return OfferCheck(True, "", max_amount=max_amount, recovery=recovery, role=target_role)


def offer_payload(offer: MarketOffer) -> dict:
    """Denormalised snapshot for the append-only feed."""
    return {
        "offer_id": offer.id,
        "team_id": offer.team_id,
        "target_player_id": offer.target_player_id,
        "release_player_id": offer.release_player_id,
        "amount": offer.amount,
        "recovery": offer.recovery_amount,
        "role": offer.role,
    }


def record_event(session, event_type, actor, payload=None, *, offer=None) -> "MarketEvent":
    from vfoot.models import MarketEvent

    return MarketEvent.objects.create(
        session=session, offer=offer, event_type=event_type,
        actor=actor, payload=payload or {},
    )


class OfferError(Exception):
    """Raised when place_offer is called with an illegal offer."""

    def __init__(self, check: "OfferCheck"):
        super().__init__(check.reason)
        self.check = check


def place_offer(
    session: MarketSession,
    team: FantasyTeam,
    target_player_id: int,
    release_player_id: int,
    amount: int,
    actor=None,
    now=None,
) -> MarketOffer:
    """Validate and record a new offer. A higher offer on the same target demotes
    the current leader to `outbid` and starts a fresh 24h clock. Raises OfferError
    with the failed check on illegality."""
    from vfoot.models import MarketEvent

    now = now or timezone.now()
    check = check_offer(session, team, target_player_id, release_player_id, amount)
    if not check.ok:
        raise OfferError(check)

    previous = leading_offer_for(session, target_player_id)
    if previous is not None:
        previous.status = MarketOffer.STATUS_OUTBID
        previous.resolved_at = now
        previous.save(update_fields=["status", "resolved_at"])
        record_event(session, MarketEvent.TYPE_OFFER_OUTBID, actor,
                     offer_payload(previous), offer=previous)

    offer = MarketOffer.objects.create(
        session=session, team=team,
        target_player_id=target_player_id, release_player_id=release_player_id,
        amount=amount, recovery_amount=check.recovery, role=check.role,
        status=MarketOffer.STATUS_LEADING,
        deadline_at=now + OFFER_TTL, created_at=now,
    )
    record_event(session, MarketEvent.TYPE_OFFER_PLACED, actor,
                 offer_payload(offer), offer=offer)
    return offer


def promote_expired(session: MarketSession, now=None) -> list[MarketOffer]:
    """Promote every leading offer past its deadline to `accepted` (queued for the
    admin). No-op unless the session is open. Returns the promoted offers."""
    from vfoot.models import MarketEvent

    if session.status != MarketSession.STATUS_OPEN:
        return []
    now = now or timezone.now()
    due = list(
        MarketOffer.objects.filter(
            session=session, status=MarketOffer.STATUS_LEADING, deadline_at__lte=now,
        )
    )
    promoted = []
    for offer in due:
        offer.status = MarketOffer.STATUS_ACCEPTED
        offer.resolved_at = now
        offer.save(update_fields=["status", "resolved_at"])
        record_event(session, MarketEvent.TYPE_OFFER_ACCEPTED, None,
                     offer_payload(offer), offer=offer)
        promoted.append(offer)
    return promoted


class OfferApplyError(Exception):
    """Raised when an accepted offer can no longer be applied to the roster."""


def apply_offer(offer: MarketOffer, actor=None, now=None) -> MarketOffer:
    """Settle an accepted (or leading, admin-forced) offer: release the pledged
    player and acquire the target at the offered price. Re-validates against the
    CURRENT roster/budget — state may have shifted since the offer was placed."""
    from vfoot.models import MarketEvent

    session = offer.session
    league = session.league
    now = now or timezone.now()

    if offer.status in (MarketOffer.STATUS_SETTLED, MarketOffer.STATUS_REJECTED,
                        MarketOffer.STATUS_CANCELLED):
        raise OfferApplyError("Offerta gia' risolta.")

    # Release slot must still be on the roster.
    release_slot = FantasyRosterSlot.objects.filter(
        team_id=offer.team_id, player_id=offer.release_player_id, released_at__isnull=True
    ).first()
    if release_slot is None:
        raise OfferApplyError("Il giocatore da svincolare non e' piu' in rosa.")

    # Target must still be a free agent (not grabbed by another settled offer).
    taken = FantasyRosterSlot.objects.filter(
        team__league=league, player_id=offer.target_player_id, released_at__isnull=True
    ).exists()
    if taken:
        raise OfferApplyError("Il giocatore offerto e' gia' stato acquisito.")

    # Cash re-check, ignoring THIS offer's own reservation.
    states = market_states(league, session, exclude_offer_id=offer.id)
    st = states.get(offer.team_id)
    recovery = recovery_for(session, release_slot.purchase_price)
    if st is not None and offer.amount > st.max_amount_releasing(recovery):
        raise OfferApplyError(
            f"Crediti insufficienti al momento della validazione "
            f"(max {st.max_amount_releasing(recovery)}).")

    release_slot.released_at = now
    release_slot.save(update_fields=["released_at"])
    acquire_slot = FantasyRosterSlot.objects.create(
        team_id=offer.team_id, player_id=offer.target_player_id,
        purchase_price=offer.amount, acquired_at=now,
    )
    offer.status = MarketOffer.STATUS_SETTLED
    offer.resolved_at = now
    offer.resolved_by = actor
    offer.acquire_slot = acquire_slot
    offer.recovery_amount = recovery
    offer.save(update_fields=["status", "resolved_at", "resolved_by",
                              "acquire_slot", "recovery_amount"])
    record_event(session, MarketEvent.TYPE_OFFER_SETTLED, actor,
                 offer_payload(offer), offer=offer)
    return offer


def reject_offer(offer: MarketOffer, actor=None, now=None) -> MarketOffer:
    from vfoot.models import MarketEvent

    if offer.status in (MarketOffer.STATUS_SETTLED, MarketOffer.STATUS_REJECTED,
                        MarketOffer.STATUS_CANCELLED):
        raise OfferApplyError("Offerta gia' risolta.")
    offer.status = MarketOffer.STATUS_REJECTED
    offer.resolved_at = now or timezone.now()
    offer.resolved_by = actor
    offer.save(update_fields=["status", "resolved_at", "resolved_by"])
    record_event(offer.session, MarketEvent.TYPE_OFFER_REJECTED, actor,
                 offer_payload(offer), offer=offer)
    return offer


def close_session(session: MarketSession, actor=None, now=None) -> MarketSession:
    """Close a session. Every offer still leading is promoted to `accepted` and
    finisce in coda di validazione, esattamente come se avesse compiuto le sue
    24h: la chiusura fa da scadenza per tutte insieme.

    E' una regola di gioco, non una scorciatoia — rende sensato offrire
    all'ultimo momento, perche' chi arriva in testa sul filo non ha piu' 24h da
    difendere. L'admin conserva l'ultima parola: dalla coda puo' sempre
    rifiutare. Le offerte gia' accettate restano dove sono."""
    from vfoot.models import MarketEvent

    now = now or timezone.now()
    for offer in MarketOffer.objects.filter(
        session=session, status=MarketOffer.STATUS_LEADING
    ):
        offer.status = MarketOffer.STATUS_ACCEPTED
        offer.resolved_at = now
        offer.save(update_fields=["status", "resolved_at"])
        record_event(session, MarketEvent.TYPE_OFFER_ACCEPTED, actor,
                     offer_payload(offer), offer=offer)
    session.status = MarketSession.STATUS_CLOSED
    session.closed_at = now
    session.save(update_fields=["status", "closed_at"])
    record_event(session, MarketEvent.TYPE_SESSION_CLOSED, actor)
    return session
