"""Il tetto sugli endpoint che costano CPU, e su chi viene contato.

Questo livello non e' la difesa principale — quella e' `limit_req` in nginx, che
rifiuta per microsecondi invece di arrivare fino a Python (vedi
docs/rate_limit_plan.md). Serve il giorno in cui la conf di nginx si perde in una
ricostruzione del server, cioe' esattamente il giorno in cui nessuno se ne
accorgerebbe. Ed e' l'unico posto dove si puo' contare PER UTENTE.

Tutta la suite gira su una cache finta (settings.py), perche' un contatore che
sopravvive fra un test e l'altro fa fallire il test dopo. Qui serve il contrario,
quindi ogni classe si porta una cache vera in memoria.
"""
from __future__ import annotations

from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.throttling import ScopedRateThrottle

from vfoot.services.auth_tokens import issue_token

REAL_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                          "LOCATION": "throttle-tests"}}

PASSWORD = "unaPasswordValida9"


@override_settings(CACHES=REAL_CACHE)
class AuthHashThrottleTests(TestCase):
    """Login e registrazione: mezzo secondo di CPU l'uno, pagato anche quando
    l'utente non esiste."""

    def setUp(self):
        ScopedRateThrottle.cache.clear()
        User.objects.create_user(username="andrea", email="andrea@example.com",
                                 password=PASSWORD)

    def _login(self, password):
        # NOT override_settings(REST_FRAMEWORK=...): DRF binds THROTTLE_RATES as a
        # class attribute at import time, so the override applies to api_settings
        # and the throttle keeps reading the dict it captured at startup. It fails
        # silently, in the direction that makes the test pass for the wrong reason.
        return self.client.post(reverse("auth-login"),
                                {"username": "andrea", "password": password},
                                content_type="application/json")

    def test_a_burst_of_wrong_passwords_is_cut_off(self):
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"auth_hash": "3/min"}):
            for _ in range(3):
                self.assertEqual(self._login("sbagliata").status_code, 401)
            # Il quarto non arriva mai a calcolare l'hash: e' il punto di tutto.
            self.assertEqual(self._login("sbagliata").status_code, 429)

    def test_the_limit_counts_failures_and_successes_alike(self):
        """Il costo e' l'hash, e l'hash si paga anche quando la password e'
        giusta. Contare solo i fallimenti lascerebbe aperta la porta a chi manda
        credenziali valide in ciclo."""
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"auth_hash": "2/min"}):
            self.assertEqual(self._login(PASSWORD).status_code, 200)
            self.assertEqual(self._login(PASSWORD).status_code, 200)
            self.assertEqual(self._login(PASSWORD).status_code, 429)

    def test_registration_shares_the_ceiling(self):
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"auth_hash": "2/min"}):
            self._login("sbagliata")
            self._login("sbagliata")
            r = self.client.post(reverse("auth-register"),
                                 {"username": "nuovo", "email": "nuovo@example.com",
                                  "password": PASSWORD, "password_confirm": PASSWORD},
                                 content_type="application/json")
            self.assertEqual(r.status_code, 429)


@override_settings(CACHES=REAL_CACHE)
class ThrottleKeyTests(TestCase):
    """CHI viene contato. Senza NUM_PROXIES DRF usa l'INTERA stringa
    X-Forwarded-For come chiave, e nginx a quella stringa APPENDE invece di
    sostituirla: bastava variare un header che il client controlla per avere un
    contatore nuovo a ogni richiesta, e il limite non esisteva."""

    def setUp(self):
        ScopedRateThrottle.cache.clear()
        User.objects.create_user(username="andrea", email="andrea@example.com",
                                 password=PASSWORD)

    def _login(self, forwarded_for):
        return self.client.post(
            reverse("auth-login"),
            {"username": "andrea", "password": "sbagliata"},
            content_type="application/json",
            HTTP_X_FORWARDED_FOR=forwarded_for)

    def test_a_forged_forwarded_for_does_not_buy_a_fresh_counter(self):
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"auth_hash": "2/min"}):
            # Quello che scrive il client sta davanti; l'ultimo indirizzo e' quello
            # che nginx ha visto davvero, ed e' l'unico che conta.
            self.assertEqual(self._login("10.0.0.1, 203.0.113.7").status_code, 401)
            self.assertEqual(self._login("10.0.0.2, 203.0.113.7").status_code, 401)
            self.assertEqual(self._login("99.99.99.99, 203.0.113.7").status_code, 429)

    def test_two_real_clients_are_counted_apart(self):
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"auth_hash": "1/min"}):
            self.assertEqual(self._login("203.0.113.7").status_code, 401)
            self.assertEqual(self._login("203.0.113.7").status_code, 429)
            # Un altro IP vero non paga per il primo: e' il caso della stanza
            # dell'asta vista dal lato opposto — chi non ha colpe non deve pagare.
            self.assertEqual(self._login("198.51.100.4").status_code, 401)


@override_settings(CACHES=REAL_CACHE)
class PasswordChangeThrottleTests(TestCase):
    """Cambiare la propria password calcola due hash e, essendo autenticata, NON
    passa dalla location stretta di nginx: questo scope e' l'unica cosa che la
    limita. E si conta per utente, non per IP."""

    def setUp(self):
        ScopedRateThrottle.cache.clear()
        self.andrea = User.objects.create_user(
            username="andrea", email="andrea@example.com", password=PASSWORD)
        self.bruno = User.objects.create_user(
            username="bruno", email="bruno@example.com", password=PASSWORD)

    def _change(self, user, new):
        # issue_token re-reads the CURRENT token: the view rotates it on every
        # successful change, so a token captured once would give a 401 on the
        # second call and hide whatever the throttle did.
        return self.client.post(
            reverse("auth-password"),
            {"current_password": PASSWORD, "new_password": new},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {issue_token(user).key}")

    def test_one_user_hammering_is_stopped(self):
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"password_change": "1/hour"}):
            self.assertEqual(self._change(self.andrea, "primaNuova9").status_code, 200)
            self.assertEqual(self._change(self.andrea, "secondaNuova9").status_code, 429)

    def test_the_count_is_per_user_not_per_address(self):
        """Due persone dietro lo stesso IP — una casa, la stanza di un'asta — non
        devono spendersi il limite a vicenda."""
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"password_change": "1/hour"}):
            self.assertEqual(self._change(self.andrea, "primaNuova9").status_code, 200)
            self.assertEqual(self._change(self.bruno, "altraNuova9").status_code, 200)
