"""Accesso con l'username o con l'email, senza guardare le maiuscole.

Il caso che ha originato tutto: un iscritto con username «PeppAndre» non riusciva
piu' a entrare. L'account era regolare e l'indirizzo confermato, ma il confronto
di Django e' esatto, e ogni grafia diversa da quella memorizzata restituiva lo
stesso errore di una password sbagliata — al punto che si e' resettato la password
per un problema che non era la password.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

PASSWORD = "unaPasswordSolida9"


class LoginIdentifierTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="PeppAndre", email="mrwolf.pulp01@example.com",
            password=PASSWORD, is_active=True)

    def _login(self, identifier, password=PASSWORD):
        return self.client.post(reverse("auth-login"),
                                {"username": identifier, "password": password},
                                content_type="application/json")

    def test_username_in_any_case(self):
        for typed in ("PeppAndre", "peppandre", "Peppandre", "PEPPANDRE", "peppAndre"):
            with self.subTest(typed=typed):
                r = self._login(typed)
                self.assertEqual(r.status_code, 200, typed)
                self.assertEqual(r.json()["user"]["username"], "PeppAndre")

    def test_email_in_any_case(self):
        for typed in ("mrwolf.pulp01@example.com", "MrWolf.Pulp01@Example.com"):
            with self.subTest(typed=typed):
                self.assertEqual(self._login(typed).status_code, 200, typed)

    def test_stored_spelling_is_untouched(self):
        """Si entra scrivendo minuscolo, ma il nome resta come l'ha scelto lui."""
        self._login("peppandre")
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "PeppAndre")

    def test_wrong_password_still_fails(self):
        self.assertEqual(self._login("peppandre", "sbagliata").status_code, 401)
        self.assertEqual(self._login("mrwolf.pulp01@example.com", "sbagliata").status_code, 401)

    def test_unknown_identifier_fails(self):
        self.assertEqual(self._login("nessuno").status_code, 401)
        self.assertEqual(self._login("nessuno@example.com").status_code, 401)

    def test_blank_identifier_is_a_validation_error_not_a_credential_one(self):
        # DRF toglie gli spazi ai bordi, quindi un campo di soli spazi arriva
        # vuoto: e' il modulo a essere incompleto, non le credenziali sbagliate.
        self.assertEqual(self._login("   ").status_code, 400)

    def test_unconfirmed_account_says_so_by_username_and_by_email(self):
        User.objects.create_user(username="Attesa", email="attesa@example.com",
                                 password=PASSWORD, is_active=False)
        for typed in ("attesa", "ATTESA@example.com"):
            with self.subTest(typed=typed):
                r = self._login(typed)
                self.assertEqual(r.status_code, 403, typed)
                self.assertTrue(r.json()["email_unconfirmed"])

    def test_unconfirmed_with_wrong_password_does_not_leak(self):
        User.objects.create_user(username="Attesa", email="attesa@example.com",
                                 password=PASSWORD, is_active=False)
        self.assertEqual(self._login("attesa", "sbagliata").status_code, 401)

    def test_google_account_without_password_cannot_be_entered_with_one(self):
        u = User.objects.create_user(username="SoloGoogle", email="g@example.com",
                                     is_active=True)
        u.set_unusable_password()
        u.save(update_fields=["password"])
        self.assertEqual(self._login("sologoogle", "").status_code, 400)
        self.assertEqual(self._login("sologoogle", "qualsiasi").status_code, 401)

    def test_email_wins_over_a_username_that_looks_like_one(self):
        """Se i due spazi di nomi si sovrappongono, entra chi possiede la casella.

        Username con la @ ora sono vietati in registrazione, ma il login non puo'
        dipendere da quella guardia: qui l'utente e' creato di lato, come farebbe
        un comando di gestione.
        """
        impostore = User.objects.create_user(
            username="vittima@example.com", email="impostore@example.com",
            password="unAltraPassword9", is_active=True)
        vittima = User.objects.create_user(
            username="Vittima", email="vittima@example.com",
            password=PASSWORD, is_active=True)

        r = self._login("vittima@example.com", PASSWORD)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["user"]["id"], vittima.id)
        self.assertNotEqual(r.json()["user"]["id"], impostore.id)


class CaseInsensitiveUniquenessTests(TestCase):
    """Gli indici della migrazione 0046: sono loro a garantire che la ricerca
    del login trovi una riga sola, anche per le strade che i serializer non
    vedono (createsuperuser, comandi di gestione)."""

    def setUp(self):
        User.objects.create_user(username="Marco", email="marco@example.com",
                                 password=PASSWORD)

    def test_username_differing_only_by_case_is_refused_by_the_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(username="marco", email="altro@example.com",
                                         password=PASSWORD)

    def test_email_differing_only_by_case_is_refused_by_the_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(username="Altro", email="Marco@Example.com",
                                         password=PASSWORD)

    def test_accounts_without_an_email_do_not_collide(self):
        """L'indice sull'email e' parziale: due superutenti senza indirizzo sono
        legittimi, e non devono farsi la guerra sulla stringa vuota."""
        User.objects.create_user(username="admin1", password=PASSWORD)
        User.objects.create_user(username="admin2", password=PASSWORD)
        self.assertEqual(User.objects.filter(email="").count(), 2)


class UsernameAtSignTests(TestCase):
    def test_registration_refuses_an_at_sign(self):
        r = self.client.post(
            reverse("auth-register"),
            {"username": "tizio@example.com", "email": "tizio@example.com",
             "password": PASSWORD, "password_confirm": PASSWORD},
            content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("@", r.json()["username"][0])

    def test_profile_rename_refuses_an_at_sign(self):
        user = User.objects.create_user(username="Tizio", email="t@example.com",
                                        password=PASSWORD, is_active=True)
        self.client.force_login(user)
        token = self.client.post(reverse("auth-login"),
                                 {"username": "tizio", "password": PASSWORD},
                                 content_type="application/json").json()["token"]
        r = self.client.patch(reverse("auth-me"), {"username": "tizio@altro.com"},
                              content_type="application/json",
                              HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(r.status_code, 400)


class GoogleUsernameCollisionTests(TestCase):
    """La strada che una collisione la poteva davvero creare: la parte locale di
    un indirizzo arriva minuscola, e il controllo esatto non vedeva «Marco»."""

    def test_generated_username_avoids_a_case_variant(self):
        from vfoot.services.google_auth import _unique_username

        User.objects.create_user(username="Marco", email="marco@altro.example.com",
                                 password=PASSWORD)
        generated = _unique_username("marco@example.com")
        self.assertNotEqual(generated.lower(), "marco")
        self.assertTrue(generated.startswith("marco-"))
