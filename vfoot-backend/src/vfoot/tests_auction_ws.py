"""WebSocket wiring for the auction room: ASGI routing, DRF-token auth over the
query string, and the broadcast push. Uses the in-memory channel layer (no Redis)."""
from __future__ import annotations

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import User
from django.test import TransactionTestCase
from rest_framework.authtoken.models import Token

from config.asgi import application
from realdata.models import Competition, CompetitionSeason, Season
from vfoot.models import AuctionSession, FantasyLeague, LeagueMembership
from vfoot.services.auction_realtime import broadcast_auction


class AuctionWebSocketTests(TransactionTestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2025-2026"),
            name="Serie A 2025-2026")
        self.admin = User.objects.create_user("admin", password="x")
        self.outsider = User.objects.create_user("outsider", password="x")
        self.league = FantasyLeague.objects.create(
            name="Lega", owner=self.admin, mode="classic", reference_season=cs)
        LeagueMembership.objects.create(
            league=self.league, user=self.admin, role=LeagueMembership.ROLE_ADMIN)
        self.session = AuctionSession.objects.create(
            league=self.league, status=AuctionSession.STATUS_ACTIVE, created_by=self.admin)
        self.token = Token.objects.create(user=self.admin)
        self.outsider_token = Token.objects.create(user=self.outsider)

    async def test_member_connects_and_receives_pushes(self):
        comm = WebsocketCommunicator(
            application, f"/ws/auctions/{self.session.id}/?token={self.token.key}")
        connected, _ = await comm.connect()
        self.assertTrue(connected)
        # Initial nudge on connect.
        first = await comm.receive_json_from()
        self.assertEqual(first["type"], "update")
        # A broadcast reaches the socket (broadcast is sync -> run off the loop).
        await sync_to_async(broadcast_auction)(self.session.id)
        pushed = await comm.receive_json_from()
        self.assertEqual(pushed["type"], "update")
        await comm.disconnect()

    async def test_missing_token_is_refused(self):
        comm = WebsocketCommunicator(application, f"/ws/auctions/{self.session.id}/")
        connected, _ = await comm.connect()
        self.assertFalse(connected)

    async def test_non_member_is_refused(self):
        comm = WebsocketCommunicator(
            application, f"/ws/auctions/{self.session.id}/?token={self.outsider_token.key}")
        connected, _ = await comm.connect()
        self.assertFalse(connected)
