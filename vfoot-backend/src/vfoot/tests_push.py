"""Web Push: subscriptions, sending, and dying quietly.

The network is never touched here — pywebpush is patched. What is worth testing
is our own behaviour around it: that a dead subscription is deleted rather than
retried forever, that a failure upstream does not become a failure in the caller,
and that "not configured" is a normal state and not a crash.

The wire itself (VAPID signature, RFC 8291 encryption, FCM, the worker waking up)
is covered end-to-end by `npm run test:pwa:roundtrip` in the frontend, which does
leave the machine. See docs/PWA_TESTING.md.
"""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from vfoot.models import PushSubscription
from vfoot.services import push_channel

KEYS = dict(VFOOT_VAPID_PUBLIC_KEY="BPub", VFOOT_VAPID_PRIVATE_KEY="priv")

SUB = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc",
       "keys": {"p256dh": "p256dh-value", "auth": "auth-value"}}


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = ""


def _webpush_raising(status):
    """A pywebpush stand-in that fails the way the real one does."""
    from pywebpush import WebPushException

    def _fn(*a, **kw):
        raise WebPushException("boom", response=_Response(status))
    return _fn


@override_settings(**KEYS)
class PushSubscriptionStoreTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("mario", password="x")

    def test_a_subscription_is_stored_once_per_installation(self):
        push_channel.save_subscription(self.user, SUB, user_agent="Chrome/Android")
        push_channel.save_subscription(self.user, SUB, user_agent="Chrome/Android")
        self.assertEqual(PushSubscription.objects.count(), 1)

    def test_the_same_installation_moving_to_another_account_is_reassigned(self):
        """A shared tablet must not keep notifying whoever logged in first."""
        other = User.objects.create_user("luigi", password="x")
        push_channel.save_subscription(self.user, SUB)
        push_channel.save_subscription(other, SUB)
        self.assertEqual(PushSubscription.objects.count(), 1)
        self.assertEqual(PushSubscription.objects.get().user, other)

    def test_an_incomplete_payload_is_refused(self):
        for bad in ({}, {"endpoint": "https://x"},
                    {"endpoint": "https://x", "keys": {"p256dh": "a"}}):
            with self.assertRaises(ValueError):
                push_channel.save_subscription(self.user, bad)

    def test_unsubscribing_is_scoped_to_its_owner(self):
        other = User.objects.create_user("luigi", password="x")
        push_channel.save_subscription(self.user, SUB)
        self.assertEqual(push_channel.drop_subscription(other, SUB["endpoint"]), 0)
        self.assertEqual(push_channel.drop_subscription(self.user, SUB["endpoint"]), 1)


@override_settings(**KEYS)
class PushSendTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("mario", password="x")
        push_channel.save_subscription(self.user, SUB)

    def test_a_send_reaches_every_installation_of_the_user(self):
        second = dict(SUB, endpoint="https://fcm.googleapis.com/fcm/send/xyz")
        push_channel.save_subscription(self.user, second)
        with patch("pywebpush.webpush") as wp:
            self.assertEqual(
                push_channel.send_to_user(self.user, title="T", body="B"), 2)
        self.assertEqual(wp.call_count, 2)

    def test_a_gone_subscription_is_deleted_not_retried(self):
        """404/410 is the ONLY signal we ever get that an install disappeared."""
        for status in (404, 410):
            PushSubscription.objects.all().delete()
            push_channel.save_subscription(self.user, SUB)
            with patch("pywebpush.webpush", _webpush_raising(status)):
                self.assertEqual(
                    push_channel.send_to_user(self.user, title="T", body="B"), 0)
            self.assertFalse(PushSubscription.objects.exists())

    def test_a_transient_failure_is_counted_and_kept(self):
        with patch("pywebpush.webpush", _webpush_raising(503)):
            self.assertEqual(
                push_channel.send_to_user(self.user, title="T", body="B"), 0)
        row = PushSubscription.objects.get()
        self.assertEqual(row.failures, 1)
        self.assertIsNotNone(row.last_error_at)

    def test_an_unexpected_error_does_not_escape(self):
        """The caller was settling a decision; a broken push is not its problem."""
        with patch("pywebpush.webpush", side_effect=RuntimeError("kaboom")):
            self.assertEqual(
                push_channel.send_to_user(self.user, title="T", body="B"), 0)
        self.assertTrue(PushSubscription.objects.exists())

    def test_a_success_clears_the_failure_history(self):
        PushSubscription.objects.update(failures=3)
        with patch("pywebpush.webpush"):
            push_channel.send_to_user(self.user, title="T", body="B")
        row = PushSubscription.objects.get()
        self.assertEqual(row.failures, 0)
        self.assertIsNotNone(row.last_sent_at)

    def test_an_oversized_body_is_truncated_rather_than_dropped(self):
        with patch("pywebpush.webpush") as wp:
            push_channel.send_to_user(self.user, title="T", body="x" * 5000)
        import json
        payload = json.loads(wp.call_args.kwargs["data"])
        self.assertLessEqual(len(payload["body"]), 200)

    @override_settings(VFOOT_VAPID_PUBLIC_KEY="", VFOOT_VAPID_PRIVATE_KEY="")
    def test_not_configured_is_a_normal_state(self):
        self.assertFalse(push_channel.configured())
        with patch("pywebpush.webpush") as wp:
            self.assertEqual(
                push_channel.send_to_user(self.user, title="T", body="B"), 0)
        wp.assert_not_called()


class PushApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("mario", password="x")

    @override_settings(**KEYS)
    def test_the_config_is_readable_without_a_token(self):
        """The front end needs the public key before it can even ask permission."""
        r = self.client.get("/api/v1/push/config")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["enabled"])
        self.assertEqual(r.json()["public_key"], "BPub")

    @override_settings(VFOOT_VAPID_PUBLIC_KEY="", VFOOT_VAPID_PRIVATE_KEY="")
    def test_the_config_says_when_push_is_off(self):
        self.assertFalse(self.client.get("/api/v1/push/config").json()["enabled"])

    @override_settings(**KEYS)
    def test_subscribing_requires_a_login(self):
        r = self.client.post("/api/v1/push/subscribe", {"subscription": SUB},
                             format="json")
        self.assertEqual(r.status_code, 401)

    @override_settings(**KEYS)
    def test_subscribe_then_unsubscribe(self):
        self.client.force_authenticate(user=self.user)
        r = self.client.post("/api/v1/push/subscribe", {"subscription": SUB},
                             format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(PushSubscription.objects.count(), 1)

        r = self.client.post("/api/v1/push/unsubscribe",
                             {"endpoint": SUB["endpoint"]}, format="json")
        self.assertEqual(r.json()["removed"], 1)
        self.assertFalse(PushSubscription.objects.exists())

    @override_settings(**KEYS)
    def test_a_malformed_subscription_gets_a_readable_400(self):
        self.client.force_authenticate(user=self.user)
        r = self.client.post("/api/v1/push/subscribe",
                             {"subscription": {"endpoint": "https://x"}},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("incompleta", r.json()["detail"])

    @override_settings(VFOOT_VAPID_PUBLIC_KEY="", VFOOT_VAPID_PRIVATE_KEY="")
    def test_subscribing_to_an_unconfigured_server_says_so(self):
        self.client.force_authenticate(user=self.user)
        r = self.client.post("/api/v1/push/subscribe", {"subscription": SUB},
                             format="json")
        self.assertEqual(r.status_code, 503)


@override_settings(**KEYS)
class DecisionPushTests(TestCase):
    """The decision notifications gain a channel; they do not change their mind
    about what is worth saying."""

    def setUp(self):
        from realdata.models import (Competition, CompetitionSeason, Season, Team,
                                     TeamSeason)
        from vfoot.models import FantasyLeague, LeagueMembership
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        TeamSeason.objects.create(competition_season=self.cs,
                                  team=Team.objects.create(name="Torino"))
        self.admin = User.objects.create_user("boss", password="x",
                                              email="boss@example.com")
        self.member = User.objects.create_user("gregario", password="x",
                                               email="greg@example.com")
        self.league = FantasyLeague.objects.create(
            name="L", owner=self.admin, mode="classic", reference_season=self.cs)
        for u, role in ((self.admin, "admin"), (self.member, "manager")):
            LeagueMembership.objects.create(league=self.league, user=u, role=role)
        push_channel.save_subscription(self.member, SUB)

    def _decision(self):
        from realdata.models import Player
        from vfoot.models import LeagueDecision
        from vfoot.services.league_decisions import ROLE_OPTIONS
        player = Player.objects.create(full_name="D. Berardi", short_name="D. Berardi")
        return LeagueDecision.objects.create(
            league=self.league, kind=LeagueDecision.KIND_PLAYER_ROLE, player=player,
            title="Ruolo di D. Berardi",
            question="Che ruolo assegnare a D. Berardi?",
            options=ROLE_OPTIONS, proposed="CEN", blocks_market=True)

    def _flush(self):
        """Il click non spedisce piu' niente, ne' mail ne' push: e' il digest che
        esce, ed e' lui che va eseguito perche' il telefono squilli."""
        from vfoot.services import decision_digest
        return decision_digest.flush(force=True)

    def test_opening_a_consultation_pushes_to_the_members(self):
        from vfoot.services.league_decisions import set_consultation
        d = self._decision()
        with patch("pywebpush.webpush") as wp, self.captureOnCommitCallbacks(execute=True):
            set_consultation(d, True, user=self.admin)
            self._flush()
        self.assertEqual(wp.call_count, 1)   # the member, not the admin
        import json
        payload = json.loads(wp.call_args.kwargs["data"])
        self.assertIn("parere", payload["title"])
        self.assertEqual(payload["url"], "/decisioni")
        # Per-LEAGUE tag, not per decision: the message is now one digest for the
        # league, and a second digest replacing the first in the shade loses
        # nothing — they both point at the page that lists every open question.
        self.assertEqual(payload["tag"], f"consultations-{self.league.id}")

    def test_a_queue_of_questions_rings_once(self):
        """Il motivo per cui esiste il digest, dal lato del telefono: quaranta
        domande erano quaranta squilli."""
        from vfoot.services.league_decisions import set_consultation
        decisions = [self._decision() for _ in range(3)]
        with patch("pywebpush.webpush") as wp, self.captureOnCommitCallbacks(execute=True):
            for d in decisions:
                set_consultation(d, True, user=self.admin)
            self._flush()
        self.assertEqual(wp.call_count, 1)
        import json
        payload = json.loads(wp.call_args.kwargs["data"])
        self.assertIn("3 pareri", payload["title"])

    def test_a_routine_sign_off_pushes_nothing(self):
        from vfoot.services.league_decisions import resolve
        d = self._decision()
        with patch("pywebpush.webpush") as wp, self.captureOnCommitCallbacks(execute=True):
            resolve(d, "CEN", user=self.admin)
            self._flush()
        wp.assert_not_called()

    def test_a_broken_push_does_not_stop_the_email(self):
        """Two channels, and the weaker one cannot take the other down."""
        from django.core import mail
        from vfoot.services.league_decisions import set_consultation
        mail.outbox = []
        d = self._decision()
        with patch("pywebpush.webpush", side_effect=RuntimeError("kaboom")), \
                self.captureOnCommitCallbacks(execute=True):
            set_consultation(d, True, user=self.admin)
            self._flush()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.member.email])
