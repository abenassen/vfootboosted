"""Repair-market REST endpoints (classic mode): offer-based sessions on free
agents. Legality and roster application live in services/market_engine.py; these
views are thin — auth, session lifecycle, and serialization for the Mercato page.
"""

from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from realdata.models import Player
from vfoot.api.league_serializers import (
    CreateMarketSessionSerializer,
    PlaceOfferSerializer,
)
from vfoot.api.league_views import _ensure_admin, _membership_or_404
from vfoot.models import (
    FantasyLeague,
    FantasyTeam,
    LeagueMembership,
    MarketEvent,
    MarketOffer,
    MarketSession,
)
from vfoot.services.auction_engine import league_role_map
from vfoot.services.listone import snapshot_league_listone
from vfoot.services.market_engine import (
    OfferApplyError,
    OfferError,
    apply_offer,
    close_session,
    free_agent_ids,
    market_states,
    place_offer,
    recovery_for,
    reject_offer,
    record_event,
    sync_session,
)


def _label(player: Player) -> str:
    return player.short_name or player.full_name


def _full_label(player: Player) -> str:
    """The unabbreviated name, sent alongside the short one so a search can match
    it. The lists show "L. Martínez"; plenty of players are known by the first
    name, and typing "Lautaro" found nothing."""
    return player.full_name or player.short_name or ""


def _my_team(league: FantasyLeague, membership: LeagueMembership) -> FantasyTeam | None:
    return FantasyTeam.objects.filter(league=league, manager=membership).first()


def _live_session(league: FantasyLeague) -> MarketSession | None:
    """La sessione viva della lega, gia' portata al presente. Passa di qui ogni
    vista del mercato: cosi' la scadenza programmata scatta alla prima richiesta
    che la incontra, senza dipendere da un processo esterno che la sorvegli."""
    session = (MarketSession.objects
               .filter(league=league, status__in=(MarketSession.STATUS_OPEN,
                                                  MarketSession.STATUS_SUSPENDED))
               .order_by("-created_at").first())
    return None if session is None else sync_session(session)


def _offer_row(offer: MarketOffer, names: dict[int, str]) -> dict:
    return {
        "offer_id": offer.id,
        "team_id": offer.team_id,
        "target_player_id": offer.target_player_id,
        "target_name": names.get(offer.target_player_id),
        "release_player_id": offer.release_player_id,
        "release_name": names.get(offer.release_player_id),
        "amount": offer.amount,
        "recovery": offer.recovery_amount,
        "role": offer.role,
        "status": offer.status,
        "deadline_at": offer.deadline_at.isoformat() if offer.deadline_at else None,
        "created_at": offer.created_at.isoformat(),
    }


def _pending_queue(league: FantasyLeague) -> list[MarketOffer]:
    """Le offerte che aspettano l'admin, cercate per LEGA e non per sessione.

    Alla chiusura ogni offerta in testa passa in `accepted`, ma la sessione esce
    dalle "vive" e con essa spariva la coda: le offerte restavano da decidere e
    nessuna pagina sapeva piu' mostrarle. La coda non appartiene alla sessione,
    appartiene alla lega — e non si svuota da sola."""
    return list(MarketOffer.objects.filter(
        session__league=league, status=MarketOffer.STATUS_ACCEPTED,
    ).select_related("session").order_by("resolved_at"))


def _queue_rows(league: FantasyLeague, offers: list[MarketOffer]) -> list[dict]:
    """Righe della coda, col nome della squadra: senza, l'admin legge "undefined
    svincola X" e non sa di chi sta decidendo la rosa."""
    if not offers:
        return []
    need: set[int] = set()
    for o in offers:
        need.add(o.target_player_id)
        need.add(o.release_player_id)
    names = {p.id: _label(p) for p in Player.objects.filter(id__in=need)}
    team_names = dict(FantasyTeam.objects.filter(league=league)
                      .values_list("id", "name"))
    rows = []
    for o in offers:
        row = _offer_row(o, names)
        row["team_name"] = team_names.get(o.team_id)
        row["session_name"] = o.session.name
        row["session_closed"] = o.session.status == MarketSession.STATUS_CLOSED
        rows.append(row)
    return rows


class MarketSessionCreateView(APIView):
    """Open a new market session (admin, classic-only). At most one live session."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)
        if league.mode != FantasyLeague.MODE_CLASSIC:
            return Response(
                {"detail": "Il mercato a offerte e' disponibile solo in modalita' classic."},
                status=status.HTTP_400_BAD_REQUEST)
        if _live_session(league) is not None:
            return Response(
                {"detail": "Esiste gia' una sessione di mercato aperta o sospesa."},
                status=status.HTTP_400_BAD_REQUEST)

        s = CreateMarketSessionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        # Catch up with the real market before opening, so a mid-season signing has
        # a frozen role and can be offered/released (same reasoning as MarketToggle).
        snapshot_league_listone(league)

        session = MarketSession.objects.create(
            league=league,
            name=data["name"],
            status=MarketSession.STATUS_OPEN,
            opens_at=timezone.now(),
            closes_at=data.get("closes_at"),
            credit_recovery_mode=data["credit_recovery_mode"],
            fixed_recovery_amount=data.get("fixed_recovery_amount", 1),
            created_by=request.user,
        )
        record_event(session, MarketEvent.TYPE_SESSION_CREATED, request.user,
                     {"name": session.name, "recovery_mode": session.credit_recovery_mode})
        return Response({"session_id": session.id}, status=status.HTTP_201_CREATED)


class MarketSessionControlView(APIView):
    """Admin lifecycle: suspend / resume / close a session."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, league_id: int, session_id: int, action: str):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)
        session = get_object_or_404(MarketSession, id=session_id, league=league)

        if action == "suspend":
            if session.status != MarketSession.STATUS_OPEN:
                return Response({"detail": "Solo una sessione aperta puo' essere sospesa."},
                                status=status.HTTP_400_BAD_REQUEST)
            session.status = MarketSession.STATUS_SUSPENDED
            session.save(update_fields=["status"])
            record_event(session, MarketEvent.TYPE_SESSION_SUSPENDED, request.user)
        elif action == "resume":
            if session.status != MarketSession.STATUS_SUSPENDED:
                return Response({"detail": "Solo una sessione sospesa puo' essere riattivata."},
                                status=status.HTTP_400_BAD_REQUEST)
            session.status = MarketSession.STATUS_OPEN
            session.save(update_fields=["status"])
            record_event(session, MarketEvent.TYPE_SESSION_RESUMED, request.user)
        elif action == "close":
            if session.status == MarketSession.STATUS_CLOSED:
                return Response({"detail": "Sessione gia' chiusa."},
                                status=status.HTTP_400_BAD_REQUEST)
            close_session(session, actor=request.user)
        else:
            return Response({"detail": "Azione sconosciuta."},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response({"session_id": session.id, "status": session.status})


class MarketOfferCreateView(APIView):
    """A manager places (or rebids) an offer on a free agent."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        membership = _membership_or_404(league, request.user.id)
        session = _live_session(league)
        if session is None or session.status != MarketSession.STATUS_OPEN:
            return Response({"detail": "Nessuna sessione di mercato aperta."},
                            status=status.HTTP_400_BAD_REQUEST)
        team = _my_team(league, membership)
        if team is None:
            return Response({"detail": "Non hai una squadra in questa lega."},
                            status=status.HTTP_400_BAD_REQUEST)

        s = PlaceOfferSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        try:
            offer = place_offer(
                session, team,
                data["target_player_id"], data["release_player_id"], data["amount"],
                actor=request.user)
        except OfferError as exc:
            return Response({"detail": exc.check.reason, "max_amount": exc.check.max_amount},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response({"offer_id": offer.id, "deadline_at": offer.deadline_at.isoformat()},
                        status=status.HTTP_201_CREATED)


class MarketOfferAdminView(APIView):
    """Admin validation of a single offer: accept (apply the swap) / reject / cancel."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, league_id: int, offer_id: int, action: str):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)
        _live_session(league)
        offer = get_object_or_404(MarketOffer, id=offer_id, session__league=league)

        if action == "accept":
            try:
                apply_offer(offer, actor=request.user)
            except OfferApplyError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        elif action == "reject":
            try:
                reject_offer(offer, actor=request.user)
            except OfferApplyError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        elif action == "cancel":
            # Admin discards an undecided (leading/accepted) offer without a swap.
            if offer.status not in MarketOffer.LIVE_STATUSES:
                return Response({"detail": "Offerta gia' risolta."},
                                status=status.HTTP_400_BAD_REQUEST)
            offer.status = MarketOffer.STATUS_CANCELLED
            offer.resolved_at = timezone.now()
            offer.resolved_by = request.user
            offer.save(update_fields=["status", "resolved_at", "resolved_by"])
            record_event(offer.session, MarketEvent.TYPE_OFFER_CANCELLED, request.user,
                         {"offer_id": offer.id}, offer=offer)
        else:
            return Response({"detail": "Azione sconosciuta."},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response({"offer_id": offer.id, "status": offer.status})


class MarketActiveView(APIView):
    """State of the league's live market session for the Mercato page: free agents,
    my roster (with recovery preview), my budget/reservations, my offers, and — for
    the admin — the validation queue. Lazily promotes expired offers on read."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        membership = _membership_or_404(league, request.user.id)
        is_admin = membership.role == LeagueMembership.ROLE_ADMIN
        team = _my_team(league, membership)
        session = _live_session(league)
        pending = _pending_queue(league)

        if session is None:
            # Niente sessione viva non vuol dire niente da fare: la coda di
            # validazione sopravvive alla chiusura, ed e' l'unico posto da cui
            # si puo' svuotare.
            return Response({
                "session": None, "is_admin": is_admin, "mode": league.mode,
                "my_team_id": team.id if team else None,
                "admin_queue": _queue_rows(league, pending) if is_admin else [],
            })

        states = market_states(league, session)
        my_state = states.get(team.id) if team else None

        pool = free_agent_ids(league)
        role_map = league_role_map(league, list(pool))

        # Leading offer per target (for the pool listing) and outbid history omitted.
        leading = {
            o.target_player_id: o
            for o in MarketOffer.objects.filter(
                session=session, status=MarketOffer.STATUS_LEADING)
        }
        locked = set(MarketOffer.objects.filter(
            session=session,
            status__in=(MarketOffer.STATUS_ACCEPTED, MarketOffer.STATUS_SETTLED),
        ).values_list("target_player_id", flat=True))
        # Anche chi e' in coda da una sessione PRECEDENTE: finche' l'admin non
        # decide resta svincolato, e senza questo la sessione nuova lo rimetterebbe
        # all'asta come se fosse libero.
        locked |= {o.target_player_id for o in pending}

        # Collect every player id we need a name for in one query.
        need_ids = set(pool) | set(leading.keys()) | locked
        my_offers = list(MarketOffer.objects.filter(session=session, team=team)
                         .order_by("-created_at")) if team else []
        for o in my_offers:
            need_ids.add(o.target_player_id)
            need_ids.add(o.release_player_id)
        if my_state:
            for pid in my_state.roster:
                need_ids.add(pid)
        _players = list(Player.objects.filter(id__in=need_ids))
        names = {p.id: _label(p) for p in _players}
        full_names = {p.id: _full_label(p) for p in _players}
        team_names = dict(FantasyTeam.objects.filter(league=league)
                          .values_list("id", "name"))

        free_agents = []
        for pid in pool:
            lead = leading.get(pid)
            free_agents.append({
                "player_id": pid,
                "name": names.get(pid),
                "full_name": full_names.get(pid),
                "role": role_map.get(pid),
                "locked": pid in locked,
                "leading": None if not lead else {
                    "offer_id": lead.id,
                    "amount": lead.amount, "team_id": lead.team_id,
                    "team_name": team_names.get(lead.team_id),
                    "deadline_at": lead.deadline_at.isoformat() if lead.deadline_at else None,
                    "mine": bool(team and lead.team_id == team.id),
                },
            })
        free_agents.sort(key=lambda r: (r["role"] or "", r["name"] or ""))

        my_roster = []
        if my_state:
            for pid, info in my_state.roster.items():
                my_roster.append({
                    "player_id": pid, "name": names.get(pid),
                    "full_name": full_names.get(pid), "role": info["role"],
                    "price": info["price"],
                    "recovery": recovery_for(session, info["price"]),
                })
            my_roster.sort(key=lambda r: (r["role"] or "", r["name"] or ""))

        payload = {
            "session": {
                "id": session.id, "name": session.name, "status": session.status,
                "opens_at": session.opens_at.isoformat() if session.opens_at else None,
                "closes_at": session.closes_at.isoformat() if session.closes_at else None,
                "credit_recovery_mode": session.credit_recovery_mode,
                "fixed_recovery_amount": session.fixed_recovery_amount,
            },
            "is_admin": is_admin,
            "mode": league.mode,
            "my_team_id": team.id if team else None,
            "my_budget": None if not my_state else {
                "remaining": my_state.remaining,
                "reserved": my_state.reserved_net,
                "available": my_state.available(),
            },
            "free_agents": free_agents,
            "my_roster": my_roster,
            "my_offers": [_offer_row(o, names) for o in my_offers],
            "admin_queue": _queue_rows(league, pending),
        }
        return Response(payload)


class MarketSessionListView(APIView):
    """History: every session of the league plus its offers (visible to all members)."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _membership_or_404(league, request.user.id)
        _live_session(league)  # la scadenza vale anche per chi guarda lo storico

        sessions = list(MarketSession.objects.filter(league=league).order_by("-created_at"))
        offers = list(MarketOffer.objects.filter(session__league=league)
                      .order_by("-created_at"))
        need_ids: set[int] = set()
        for o in offers:
            need_ids.add(o.target_player_id)
            need_ids.add(o.release_player_id)
        _players = list(Player.objects.filter(id__in=need_ids))
        names = {p.id: _label(p) for p in _players}
        full_names = {p.id: _full_label(p) for p in _players}
        team_names = dict(FantasyTeam.objects.filter(league=league)
                          .values_list("id", "name"))

        by_session: dict[int, list] = {}
        for o in offers:
            row = _offer_row(o, names)
            row["team_name"] = team_names.get(o.team_id)
            by_session.setdefault(o.session_id, []).append(row)

        return Response({
            "sessions": [{
                "id": s.id, "name": s.name, "status": s.status,
                "opens_at": s.opens_at.isoformat() if s.opens_at else None,
                "closes_at": s.closes_at.isoformat() if s.closes_at else None,
                "closed_at": s.closed_at.isoformat() if s.closed_at else None,
                "credit_recovery_mode": s.credit_recovery_mode,
                "fixed_recovery_amount": s.fixed_recovery_amount,
                "offers": by_session.get(s.id, []),
            } for s in sessions],
        })
