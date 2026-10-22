"""Il registro delle pagine: cosa entra, cosa no, e chi decide."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from vfoot.models import PageVisit

URL = "/api/v1/usage/visits"


def _visit(**over):
    v = {"route": "/matches/:id", "visible_ms": 4200, "device": "mobile",
         "standalone": True, "session": "abcd1234efgh"}
    v.update(over)
    return v


@override_settings(VFOOT_USAGE_LOG=True)
class RegistroDellePagine(TestCase):
    def setUp(self):
        cache.clear()       # il limite di frequenza conta nella cache
        self.client = APIClient()

    def _post(self, *visits, user=None):
        if user is not None:
            token, _ = Token.objects.get_or_create(user=user)
            self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return self.client.post(URL, {"visits": list(visits)}, format="json")

    def test_un_tratto_entra_senza_utente_ne_ora(self):
        user = User.objects.create_user("mario", password="x")
        self.assertEqual(self._post(_visit(), user=user).status_code, 204)
        row = PageVisit.objects.get()
        self.assertEqual((row.route, row.visible_ms, row.device), ("/matches/:id", 4200, "mobile"))
        self.assertTrue(row.signed_in and row.standalone)
        self.assertEqual(row.day, timezone.localdate())

    def test_anche_chi_non_e_entrato(self):
        self._post(_visit(route="/"))
        self.assertFalse(PageVisit.objects.get().signed_in)

    def test_lo_staff_non_si_registra(self):
        admin = User.objects.create_user("io", password="x", is_staff=True)
        self.assertEqual(self._post(_visit(), user=admin).status_code, 204)
        self.assertFalse(PageVisit.objects.exists())

    def test_una_rotta_sporca_non_entra(self):
        """Un indirizzo con dentro un codice, un'email o una query non deve
        poter entrare nemmeno se un client vecchio lo manda."""
        self._post(_visit(route="/join/abc9xyz"), _visit(route="/x?email=a@b.it"),
                   _visit(route="nessuna-barra"), _visit(device="frigorifero"),
                   _visit(visible_ms=0), _visit(session="corta"))
        self.assertFalse(PageVisit.objects.exists())
        self._post(_visit(route="/join/:code"))
        self.assertTrue(PageVisit.objects.exists())

    def test_una_scheda_dimenticata_non_gonfia_le_medie(self):
        self._post(_visit(visible_ms=50 * 3600 * 1000))
        self.assertEqual(PageVisit.objects.get().visible_ms, 6 * 3600 * 1000)

    def test_le_righe_vecchie_scadono_da_sole(self):
        PageVisit.objects.create(day=timezone.localdate() - timedelta(days=200),
                                 route="/home", visible_ms=1, device="desktop",
                                 session="vecchia123")
        self._post(_visit())
        self.assertEqual(list(PageVisit.objects.values_list("route", flat=True)),
                         ["/matches/:id"])

    @override_settings(VFOOT_USAGE_LOG=False)
    def test_spento_non_scrive_niente(self):
        self.assertEqual(self._post(_visit()).status_code, 204)
        self.assertFalse(PageVisit.objects.exists())
