"""Le segnalazioni: cosa si accetta, cosa si scarta, e cosa non deve rompersi.

Il valore di questo endpoint sta tutto nel non perdere niente, quindi le prove
che contano sono ai bordi: il messaggio vuoto che non deve entrare, il tetto
orario che non deve chiudere la porta a chi ha una cosa sola da dire, e — la più
importante — il relay di posta che cade mentre l'utente sta guardando lo schermo.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from vfoot.models import Feedback

URL = "/api/v1/feedback"


class FeedbackApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("mario", password="x", email="mario@example.com")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_a_signed_in_user_can_leave_one(self):
        res = self.client.post(
            URL,
            {"kind": "bug", "message": "Il pulsante Salva non fa niente.",
             "page": "/squad/formation", "viewport": "390x844"},
            format="json",
            HTTP_USER_AGENT="Mozilla/5.0 (iPhone)")
        self.assertEqual(res.status_code, 201)

        fb = Feedback.objects.get()
        self.assertEqual(fb.user, self.user)
        self.assertEqual(fb.kind, "bug")
        self.assertEqual(fb.page, "/squad/formation")
        self.assertEqual(fb.viewport, "390x844")
        # Il browser lo racconta l'intestazione, non il corpo.
        self.assertIn("iPhone", fb.user_agent)
        self.assertEqual(fb.status, Feedback.STATUS_NEW)

    def test_anonymous_cannot(self):
        anon = APIClient()
        res = anon.post(URL, {"message": "ciao"}, format="json")
        self.assertIn(res.status_code, (401, 403))
        self.assertFalse(Feedback.objects.exists())

    def test_an_empty_message_is_refused(self):
        for text in ("", "   ", "ah"):
            res = self.client.post(URL, {"message": text}, format="json")
            self.assertEqual(res.status_code, 400, text)
        self.assertFalse(Feedback.objects.exists())

    def test_the_hourly_cap_counts_only_the_last_hour(self):
        # Venti vecchie di ieri non devono chiudere la porta a chi scrive oggi.
        old = timezone.now() - timedelta(days=1)
        for _ in range(25):
            Feedback.objects.create(user=self.user, message="vecchia", created_at=old)
        res = self.client.post(URL, {"message": "una cosa nuova"}, format="json")
        self.assertEqual(res.status_code, 201)

        for i in range(19):
            self.assertEqual(
                self.client.post(URL, {"message": f"numero {i}"}, format="json").status_code,
                201)
        # La ventunesima nell'ora si ferma, e si ferma con una frase, non con un 500.
        res = self.client.post(URL, {"message": "e un'altra ancora"}, format="json")
        self.assertEqual(res.status_code, 429)
        self.assertIn("detail", res.json())

    @override_settings(VFOOT_FEEDBACK_EMAIL="io@example.com")
    def test_it_is_emailed_to_whoever_runs_the_site(self):
        self.client.post(URL, {"kind": "idea", "message": "Metteteci il buio."},
                         format="json")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["io@example.com"])
        self.assertIn("Metteteci il buio.", mail.outbox[0].body)
        self.assertIn("mario", mail.outbox[0].subject)

    @override_settings(VFOOT_FEEDBACK_EMAIL="")
    def test_without_an_address_it_is_still_stored(self):
        res = self.client.post(URL, {"message": "una segnalazione"}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Feedback.objects.count(), 1)

    @override_settings(VFOOT_FEEDBACK_EMAIL="io@example.com")
    def test_a_dead_relay_does_not_lose_the_message(self):
        """Il gesto dell'utente è riuscito: la posta è un problema nostro."""
        with patch("vfoot.api.feedback_views.send_mail", side_effect=OSError("relay giù")):
            res = self.client.post(URL, {"message": "il sito è lento la domenica"},
                                   format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Feedback.objects.count(), 1)
