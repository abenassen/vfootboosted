"""WebSocket wiring for a league's matchday in progress: routing, DRF-token auth
over the query string, and the nudge. Uses the in-memory channel layer (no Redis).

Note what that means for a real run: the in-memory layer does NOT fan out across
processes, and the tick lives in a process of its own. These tests pass either way
because everything here happens in one process; a live simulation needs a Redis.
See ``vfoot/services/live_realtime.py``.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import User
from django.test import TransactionTestCase
from rest_framework.authtoken.models import Token

from config.asgi import application
from realdata.models import Competition, CompetitionSeason, Season
from vfoot.models import FantasyLeague, LeagueMembership
from vfoot.services.live_realtime import broadcast_live


class LiveWebSocketTests(TransactionTestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        self.member = User.objects.create_user("member", password="x")
        self.outsider = User.objects.create_user("outsider", password="x")
        self.league = FantasyLeague.objects.create(
            name="Lega", owner=self.member, mode="classic", reference_season=cs)
        LeagueMembership.objects.create(
            league=self.league, user=self.member, role=LeagueMembership.ROLE_ADMIN)
        self.token = Token.objects.create(user=self.member)
        self.outsider_token = Token.objects.create(user=self.outsider)

    def _url(self, token=None, league_id=None):
        league_id = league_id or self.league.id
        suffix = f"?token={token}" if token else ""
        return f"/ws/leagues/{league_id}/live/{suffix}"

    async def test_member_connects_and_receives_the_nudge(self):
        comm = WebsocketCommunicator(application, self._url(self.token.key))
        connected, _ = await comm.connect()
        self.assertTrue(connected)
        # Pull the state immediately on connect, so a page that was open through a
        # disconnection catches up on whatever it missed.
        first = await comm.receive_json_from()
        self.assertEqual(first["type"], "update")
        await sync_to_async(broadcast_live)(self.league.id)
        pushed = await comm.receive_json_from()
        self.assertEqual(pushed["type"], "update")
        await comm.disconnect()

    async def test_missing_token_is_refused(self):
        comm = WebsocketCommunicator(application, self._url())
        connected, _ = await comm.connect()
        self.assertFalse(connected)

    async def test_a_non_member_cannot_watch_a_league_round(self):
        comm = WebsocketCommunicator(application, self._url(self.outsider_token.key))
        connected, _ = await comm.connect()
        self.assertFalse(connected)

    async def test_a_league_that_does_not_exist_is_refused(self):
        comm = WebsocketCommunicator(
            application, self._url(self.token.key, league_id=99999))
        connected, _ = await comm.connect()
        self.assertFalse(connected)
