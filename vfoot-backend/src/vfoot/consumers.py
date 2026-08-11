"""WebSocket consumers: the live auction room, and a league's round in progress.

Read-only by design, both of them: the browser opens the socket with its DRF token
in the query string and receives a light ``{"type":"update"}`` nudge whenever
something changes; it then re-fetches the authoritative state over the REST
endpoints it already uses. No state is ever pushed down the socket, so there is
exactly one way to compute what the page shows and the two paths cannot drift.

Auth reuses the app's DRF token as a query-string parameter (browsers cannot set
Authorization headers on a WebSocket handshake). A connection is refused unless the
token is valid AND its user is a member of the league in question.

The two consumers differ in two things only — the group name and the membership
predicate — which is why the shared part lives in ``_NudgeConsumer``. An auction
and a matchday being played never happen at the same time, so the layer never
carries both loads at once.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs

from asgiref.sync import async_to_sync
from channels.generic.websocket import WebsocketConsumer

from vfoot.services.auction_realtime import group_name
from vfoot.services.live_realtime import group_name as live_group_name


class _NudgeConsumer(WebsocketConsumer):
    """Join one group, say hello, forward every nudge. Subclasses answer WHERE
    (``group_for``) and WHO (``authorised_user``)."""

    def connect(self):
        user_id = self._token_user_id()
        group = self.group_for(user_id) if user_id else None
        if group is None:
            self.close(code=4003)
            return
        self.group = group
        async_to_sync(self.channel_layer.group_add)(self.group, self.channel_name)
        self.accept()
        # Tell the freshly-connected client to pull the current state immediately.
        self.send(text_data=json.dumps({"type": "update", "kind": "connected"}))

    def disconnect(self, code):
        group = getattr(self, "group", None)
        if group:
            async_to_sync(self.channel_layer.group_discard)(group, self.channel_name)

    def _token_user_id(self) -> int | None:
        from rest_framework.authtoken.models import Token

        qs = parse_qs(self.scope.get("query_string", b"").decode())
        token_key = (qs.get("token") or [None])[0]
        if not token_key:
            return None
        token = Token.objects.filter(key=token_key).only("user_id").first()
        return token.user_id if token else None

    def group_for(self, user_id: int) -> str | None:
        raise NotImplementedError

    def _nudge(self, event):
        self.send(text_data=json.dumps(
            {"type": "update", "kind": event.get("kind", "state")}))


class AuctionConsumer(_NudgeConsumer):
    def group_for(self, user_id: int) -> str | None:
        from vfoot.models import AuctionSession, LeagueMembership

        session_id = int(self.scope["url_route"]["kwargs"]["session_id"])
        session = AuctionSession.objects.filter(id=session_id).only("league_id").first()
        if session is None:
            return None
        if not LeagueMembership.objects.filter(
                league_id=session.league_id, user_id=user_id).exists():
            return None
        return group_name(session_id)

    # Group message handler (matches the "auction.update" type sent by the bridge).
    auction_update = _NudgeConsumer._nudge


class LiveConsumer(_NudgeConsumer):
    """A league's matchday while it is being played: votes moving, matches ending."""

    def group_for(self, user_id: int) -> str | None:
        from vfoot.models import LeagueMembership

        league_id = int(self.scope["url_route"]["kwargs"]["league_id"])
        if not LeagueMembership.objects.filter(
                league_id=league_id, user_id=user_id).exists():
            return None
        return live_group_name(league_id)

    # Matches the "live.update" type sent by live_realtime.broadcast_live.
    live_update = _NudgeConsumer._nudge


class UnknownPathConsumer(WebsocketConsumer):
    """Rifiuta un percorso WebSocket che non esiste, senza fare rumore.

    Serve perche' ``URLRouter``, quando nessuna rotta combacia, **solleva**
    ``ValueError("No route found for path ...")``: la connessione viene rifiutata
    con un 500 e nel journal resta un traceback completo. Con un sito pubblico
    quel traceback lo scrive chiunque provi un indirizzo a caso, e il costo non e'
    il 500 -- e' che il journal si riempie di eccezioni identiche e innocue, cioe'
    esattamente il posto dove si va a cercare quella vera.

    Montata come ultima rotta in ``ws_routing``, dove intercetta cio' che le altre
    non hanno preso. Chiude prima di ``accept()``, quindi l'handshake finisce con
    un rifiuto pulito invece che con un errore del server.
    """

    def connect(self):
        self.close(code=4404)
