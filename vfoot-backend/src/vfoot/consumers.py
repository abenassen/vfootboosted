"""WebSocket consumer for the live auction room.

Read-only by design: the browser opens ``ws://.../ws/auctions/<id>/?token=<drf-token>``
and receives a light ``{"type":"update"}`` nudge every time the room changes; it then
re-fetches the authoritative state over the existing REST endpoint. All writes (bids,
nominations, closes, undo) go through the REST API, never through this socket.

Auth reuses the app's DRF token: it is passed as a query-string parameter (browsers
cannot set Authorization headers on a WebSocket handshake). The connection is refused
unless the token is valid AND its user is a member of the auction's league.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs

from asgiref.sync import async_to_sync
from channels.generic.websocket import WebsocketConsumer

from vfoot.services.auction_realtime import group_name


class AuctionConsumer(WebsocketConsumer):
    def connect(self):
        self.session_id = int(self.scope["url_route"]["kwargs"]["session_id"])
        if not self._authorised():
            self.close(code=4003)
            return
        self.group = group_name(self.session_id)
        async_to_sync(self.channel_layer.group_add)(self.group, self.channel_name)
        self.accept()
        # Tell the freshly-connected client to pull the current state immediately.
        self.send(text_data=json.dumps({"type": "update", "kind": "connected"}))

    def disconnect(self, code):
        group = getattr(self, "group", None)
        if group:
            async_to_sync(self.channel_layer.group_discard)(group, self.channel_name)

    def _authorised(self) -> bool:
        from rest_framework.authtoken.models import Token

        from vfoot.models import AuctionSession, LeagueMembership

        qs = parse_qs(self.scope.get("query_string", b"").decode())
        token_key = (qs.get("token") or [None])[0]
        if not token_key:
            return False
        token = Token.objects.filter(key=token_key).select_related("user").first()
        if not token:
            return False
        session = AuctionSession.objects.filter(id=self.session_id).first()
        if not session:
            return False
        return LeagueMembership.objects.filter(
            league_id=session.league_id, user_id=token.user_id
        ).exists()

    # Group message handler (matches the "auction.update" type sent by the bridge).
    def auction_update(self, event):
        self.send(text_data=json.dumps({"type": "update", "kind": event.get("kind", "state")}))
