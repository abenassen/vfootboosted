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
from vfoot.api.league_views import _club_by_player, _ensure_admin, _membership_or_404
from vfoot.models import (
    FantasyLeague,
    FantasyTeam,
    LeagueMembership,
    MarketEvent,
    MarketOffer,
    MarketSession,
)
from vfoot.services import matchday_state
from vfoot.services.auction_engine import league_role_map
from vfoot.services.listone import snapshot_league_listone
from vfoot.services.market_engine import (
    OfferApplyError,
    OfferError,
    apply_offer,
    cancel_offer,
    check_restore,
    close_session,
    free_agent_ids,
    market_states,
    place_offer,
    recovery_for,
    reject_offer,
    record_event,
    restore_previous_offer,
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


def _freeze_row(league: FantasyLeague) -> dict:
    """La giornata vera, per la coda di validazione.

    Applicare un'offerta muove due rose, e ``apply_offer`` lo vieta mentre il
    campionato e' in campo (R3). Senza dirlo qui, il pannello dell'admin non
    aveva modo di saperlo: il bottone «Accetta» restava acceso, il rifiuto
    arrivava come un 400 dopo il click, e il messaggio compariva in cima al
    pannello — spesso fuori schermo rispetto alla riga su cui si era cliccato.
    Il 400 resta: questa e' la stessa verita', detta prima."""
    playing = matchday_state.playing_matchday(league)
    return {"matchday_in_progress": playing is not None, "playing_matchday": playing}


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

        # Catch up with the real market, so a mid-season signing has a frozen role
        # and can be offered/released. Vale anche per una sessione programmata: da
        # subito la lega puo' guardare chi sara' libero, e all'apertura vera il
        # listone si aggiorna di nuovo (market_engine.open_session).
        snapshot_league_listone(league)

        now = timezone.now()
        opens_at = data.get("opens_at") or now
        # Un'ora di apertura gia' passata vuol dire "adesso": non si fa aspettare
        # nessuno per un momento gia' suonato.
        immediate = opens_at <= now
        session = MarketSession.objects.create(
            league=league,
            name=data["name"],
            status=MarketSession.STATUS_OPEN,
            opens_at=now if immediate else opens_at,
            # La sessione che parte subito e' aperta da questo istante; quella
            # programmata non e' ancora aperta, e lo sara' quando scattera' l'ora.
            opened_at=now if immediate else None,
            closes_at=data.get("closes_at"),
            credit_recovery_mode=data["credit_recovery_mode"],
            fixed_recovery_amount=data.get("fixed_recovery_amount", 1),
            created_by=request.user,
        )
        record_event(session, MarketEvent.TYPE_SESSION_CREATED, request.user,
                     {"name": session.name, "recovery_mode": session.credit_recovery_mode,
                      "opens_at": session.opens_at.isoformat()})
        return Response({"session_id": session.id, "opens_at": session.opens_at.isoformat()},
                        status=status.HTTP_201_CREATED)


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
    """Admin validation of a single offer: accept (apply the swap) / reject / cancel.

    Il GET sulla stessa rotta non decide niente: racconta cosa succederebbe. Serve
    a "reject" e "cancel", le due azioni che tolgono di mezzo un'offerta — se
    quella era un RILANCIO, sotto c'e' un'offerta superata, e cosa farne non e'
    una scelta che il server puo' prendere per conto dell'admin."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    DISCARDING = ("reject", "cancel")

    def get(self, request, league_id: int, offer_id: int, action: str):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)
        _live_session(league)
        offer = get_object_or_404(MarketOffer, id=offer_id, session__league=league)
        if action not in self.DISCARDING:
            return Response({"detail": "Azione sconosciuta."},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(_discard_preview(league, offer, action))

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
            return Response({"offer_id": offer.id, "status": offer.status})

        if action not in self.DISCARDING:
            return Response({"detail": "Azione sconosciuta."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Cosa c'e' sotto si guarda PRIMA di togliere l'offerta: dopo, `outbid` e
        # l'offerta annullata si confonderebbero fra loro.
        restore = check_restore(offer)
        choice = request.data.get("restore_previous", None)
        if restore.is_rebid and choice is None:
            # Un client che non sa dell'offerta sotto non deve poterla seppellire
            # per distrazione: qui si torna indietro senza aver toccato niente.
            return Response(
                {"detail": "Questa offerta era un rilancio: decidi cosa fare "
                           "dell'offerta che aveva superato.",
                 "requires_decision": True,
                 **_discard_preview(league, offer, action, restore=restore)},
                status=status.HTTP_409_CONFLICT)

        try:
            # Savepoint suo: un `atomic` esterno non torna indietro da solo se
            # l'eccezione la intercettiamo noi per rispondere 400, e l'offerta
            # resterebbe annullata con l'altra ancora sepolta. O tutt'e due le
            # cose, o nessuna.
            with transaction.atomic():
                if action == "reject":
                    reject_offer(offer, actor=request.user)
                else:
                    cancel_offer(offer, actor=request.user)
                restored = (restore_previous_offer(offer, actor=request.user)
                            if (restore.is_rebid and choice) else None)
        except OfferApplyError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "offer_id": offer.id, "status": offer.status,
            "restored": None if restored is None else {
                "offer_id": restored.id, "status": restored.status,
                "team_id": restored.team_id, "amount": restored.amount,
            },
        })


def _discard_preview(league: FantasyLeague, offer: MarketOffer, action: str,
                     restore=None) -> dict:
    """Cosa comporta togliere di mezzo questa offerta.

    Senza un'offerta sotto e' una domanda oziosa (il giocatore torna libero e
    basta); con un'offerta sotto e' la sola cosa che l'admin deve sapere prima di
    cliccare, perche' quella superata NON torna in testa da sola e il giocatore
    tornerebbe offribile dal minimo, come se nessuno l'avesse mai voluto."""
    restore = check_restore(offer) if restore is None else restore
    names = {p.id: _label(p) for p in Player.objects.filter(
        id__in={offer.target_player_id, offer.release_player_id}
        | ({restore.previous.release_player_id} if restore.previous else set()))}
    team_names = dict(FantasyTeam.objects.filter(league=league)
                      .values_list("id", "name"))
    out = {
        "offer_id": offer.id,
        "action": action,
        "status": offer.status,
        "target_name": names.get(offer.target_player_id),
        "team_name": team_names.get(offer.team_id),
        "amount": offer.amount,
        "is_rebid": restore.is_rebid,
        "previous": None,
    }
    prev = restore.previous
    if prev is not None:
        out["previous"] = {
            "offer_id": prev.id,
            "team_id": prev.team_id,
            "team_name": team_names.get(prev.team_id),
            "amount": prev.amount,
            "release_player_id": prev.release_player_id,
            "release_name": names.get(prev.release_player_id),
            "created_at": prev.created_at.isoformat(),
            "deadline_at": prev.deadline_at.isoformat() if prev.deadline_at else None,
            "restorable": restore.ok,
            "blocker": restore.blocker,
            "expired": restore.expired,
            # Ripristinata, va dritta in coda di validazione invece di tornare
            # in testa: il suo tempo era gia' finito (o la sessione e' chiusa).
            "would_queue": restore.would_queue,
        }
    return out


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
                **_freeze_row(league),
            })

        states = market_states(league, session)
        my_state = states.get(team.id) if team else None

        pool = free_agent_ids(league)
        role_map = league_role_map(league, list(pool))
        # Il club vero, dalla stessa funzione del listone e dell'asta: si cerca
        # per squadra ("chi e' libero del Lecce?") tanto quanto per nome, e i tre
        # schermi non possono dire tre maglie diverse per lo stesso giocatore.
        clubs = _club_by_player(league.reference_season_id, list(pool))

        # Leading offer per target (for the pool listing) and outbid history omitted.
        leading = {
            o.target_player_id: o
            for o in MarketOffer.objects.filter(
                session=session, status=MarketOffer.STATUS_LEADING)
        }
        locked = set(MarketOffer.objects.filter(
            session__league=league,
            status=MarketOffer.STATUS_ACCEPTED,
        ).values_list("target_player_id", flat=True))
        # Sono le offerte davvero da validare: un `settled` non e' un blocco.
        # Finche' l'acquisto resta in rosa non entra comunque nel pool; quando
        # viene svincolato torna offribile, senza ereditare il suo vecchio badge.
        # E chi se l'e' aggiudicato, in attesa che l'admin decida. Era pubblico un
        # istante prima — la stessa offerta stava in testa, con squadra e cifra a
        # schermo — e torna pubblico appena la validazione passa: sparire proprio
        # nel frattempo era una svista, non una riservatezza. `pending` e' di lega,
        # quindi copre anche le code rimaste da una sessione precedente.
        pending_by_target = {o.target_player_id: o for o in pending}

        # Collect every player id we need a name for in one query. Il promesso
        # svincolo compreso, di chi e' in testa e di chi ha gia' vinto: un'offerta
        # e' uno scambio, e leggerne solo la meta' che entra nasconde meta' della
        # trattativa.
        need_ids = (set(pool) | set(leading.keys()) | locked
                    | {o.release_player_id for o in leading.values()}
                    | {o.release_player_id for o in pending})
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
            pend = pending_by_target.get(pid)
            free_agents.append({
                "player_id": pid,
                "name": names.get(pid),
                "full_name": full_names.get(pid),
                "real_team": clubs.get(pid),
                "role": role_map.get(pid),
                "locked": pid in locked,
                "leading": None if not lead else {
                    "offer_id": lead.id,
                    "amount": lead.amount, "team_id": lead.team_id,
                    "team_name": team_names.get(lead.team_id),
                    "deadline_at": lead.deadline_at.isoformat() if lead.deadline_at else None,
                    "mine": bool(team and lead.team_id == team.id),
                    "release_player_id": lead.release_player_id,
                    "release_name": names.get(lead.release_player_id),
                },
                "pending": None if not pend else {
                    "amount": pend.amount, "team_id": pend.team_id,
                    "team_name": team_names.get(pend.team_id),
                    "release_player_id": pend.release_player_id,
                    "release_name": names.get(pend.release_player_id),
                    "mine": bool(team and pend.team_id == team.id),
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
                "opened_at": session.opened_at.isoformat() if session.opened_at else None,
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
            **_freeze_row(league),
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
                "opened_at": s.opened_at.isoformat() if s.opened_at else None,
                "closes_at": s.closes_at.isoformat() if s.closes_at else None,
                "closed_at": s.closed_at.isoformat() if s.closed_at else None,
                "credit_recovery_mode": s.credit_recovery_mode,
                "fixed_recovery_amount": s.fixed_recovery_amount,
                "offers": by_session.get(s.id, []),
            } for s in sessions],
        })
