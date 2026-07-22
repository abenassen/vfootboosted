"""Registration by email confirmation, and sign-in with Google."""
from __future__ import annotations

from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.authtoken.models import Token

from vfoot.services import google_auth
from vfoot.services.email_verification import token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

VALID = {"username": "nuovo", "email": "Nuovo@Example.com",
         "password": "unaPasswordSolida9", "password_confirm": "unaPasswordSolida9"}


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   VFOOT_FRONTEND_BASE_URL="https://vfoot.it")
class RegistrationTests(TestCase):
    def _register(self, **over):
        # The view sends on_commit, which never fires inside TestCase's outer
        # transaction; capturing makes the callback run so we can assert on it.
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("auth-register"), {**VALID, **over},
                                    content_type="application/json")

    def test_register_creates_inactive_user_and_sends_mail(self):
        r = self._register()
        self.assertEqual(r.status_code, 201)
        user = User.objects.get(username="nuovo")
        self.assertFalse(user.is_active)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("https://vfoot.it/verifica-email?uid=", mail.outbox[0].body)

    def test_register_does_not_hand_out_a_token(self):
        # A token here would make the confirmation step decorative.
        r = self._register()
        self.assertNotIn("token", r.json())
        self.assertFalse(Token.objects.exists())

    def test_email_is_mandatory(self):
        r = self._register(email="")
        self.assertEqual(r.status_code, 400)
        self.assertIn("email", r.json())

    def test_email_must_be_unique_case_insensitively(self):
        self._register()
        r = self._register(username="altro", email="nuovo@example.com")
        self.assertEqual(r.status_code, 400)
        self.assertIn("email", r.json())

    def test_username_uniqueness_is_case_insensitive(self):
        self._register()
        r = self._register(username="NUOVO", email="altra@example.com")
        self.assertEqual(r.status_code, 400)

    # -- confirmation ---------------------------------------------------

    def _link_parts(self, user):
        return (urlsafe_base64_encode(force_bytes(user.pk)),
                token_generator.make_token(user))

    def test_verification_activates_and_returns_a_token(self):
        self._register()
        user = User.objects.get(username="nuovo")
        uid, token = self._link_parts(user)
        r = self.client.post(reverse("auth-verify-email"),
                             {"uid": uid, "token": token},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("token", r.json())
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_link_is_single_use(self):
        self._register()
        user = User.objects.get(username="nuovo")
        uid, token = self._link_parts(user)
        body = {"uid": uid, "token": token}
        self.client.post(reverse("auth-verify-email"), body,
                         content_type="application/json")
        # Second use: already active, reported as success but WITHOUT new
        # credentials, and the token itself no longer validates.
        again = self.client.post(reverse("auth-verify-email"), body,
                                 content_type="application/json")
        self.assertEqual(again.status_code, 200)
        self.assertTrue(again.json().get("already_active"))
        self.assertNotIn("token", again.json())
        user.refresh_from_db()
        self.assertFalse(token_generator.check_token(user, token))

    def test_tampered_token_is_rejected(self):
        self._register()
        user = User.objects.get(username="nuovo")
        uid, _ = self._link_parts(user)
        r = self.client.post(reverse("auth-verify-email"),
                             {"uid": uid, "token": "non-valido"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_token_of_one_user_cannot_activate_another(self):
        self._register()
        self._register(username="secondo", email="secondo@example.com")
        victim = User.objects.get(username="secondo")
        _, token = self._link_parts(User.objects.get(username="nuovo"))
        r = self.client.post(
            reverse("auth-verify-email"),
            {"uid": urlsafe_base64_encode(force_bytes(victim.pk)), "token": token},
            content_type="application/json")
        self.assertEqual(r.status_code, 400)
        victim.refresh_from_db()
        self.assertFalse(victim.is_active)

    # -- login while unconfirmed ----------------------------------------

    def test_correct_password_on_unconfirmed_account_says_so(self):
        self._register()
        r = self.client.post(reverse("auth-login"),
                             {"username": "nuovo", "password": VALID["password"]},
                             content_type="application/json")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.json().get("email_unconfirmed"))

    def test_wrong_password_is_still_a_plain_401(self):
        self._register()
        r = self.client.post(reverse("auth-login"),
                             {"username": "nuovo", "password": "sbagliata999"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("email_unconfirmed", r.json())

    # -- resend ----------------------------------------------------------

    def test_resend_does_not_reveal_whether_the_address_exists(self):
        self._register()
        mail.outbox.clear()
        known = self.client.post(reverse("auth-resend-verification"),
                                 {"email": "nuovo@example.com"},
                                 content_type="application/json")
        sent_for_known = len(mail.outbox)
        mail.outbox.clear()
        unknown = self.client.post(reverse("auth-resend-verification"),
                                   {"email": "mai-visto@example.com"},
                                   content_type="application/json")
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.json(), unknown.json())
        # ...but the mail really only goes to the address that exists.
        self.assertEqual(sent_for_known, 1)
        self.assertEqual(len(mail.outbox), 0)


class GoogleSignInTests(TestCase):
    def _post(self, identity):
        with mock.patch("vfoot.api.views.verify_id_token",
                        return_value=identity):
            return self.client.post(reverse("auth-google"),
                                    {"credential": "finto"},
                                    content_type="application/json")

    def _identity(self, email="tizio@example.com", verified=True):
        return google_auth.GoogleIdentity(email=email, email_verified=verified,
                                          name="Tizio")

    def test_new_google_user_is_created_active(self):
        r = self._post(self._identity())
        self.assertEqual(r.status_code, 201)
        user = User.objects.get(email="tizio@example.com")
        self.assertTrue(user.is_active)
        self.assertFalse(user.has_usable_password())

    def test_unverified_google_address_is_refused(self):
        r = self._post(self._identity(verified=False))
        self.assertEqual(r.status_code, 401)
        self.assertFalse(User.objects.exists())

    def test_second_sign_in_reuses_the_same_account(self):
        self._post(self._identity())
        r = self._post(self._identity())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.count(), 1)

    def test_google_links_to_an_existing_password_account(self):
        existing = User.objects.create_user(username="tizio",
                                            email="tizio@example.com",
                                            password="qualcosa123456")
        r = self._post(self._identity())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(r.json()["user"]["id"], existing.pk)

    def test_google_confirms_an_account_still_awaiting_our_email(self):
        pending = User.objects.create_user(username="tizio",
                                           email="tizio@example.com",
                                           password="qualcosa123456",
                                           is_active=False)
        r = self._post(self._identity())
        self.assertEqual(r.status_code, 200)
        pending.refresh_from_db()
        self.assertTrue(pending.is_active)

    def test_username_collision_gets_a_distinct_name(self):
        User.objects.create_user(username="tizio", email="altro@example.com")
        self._post(self._identity())
        created = User.objects.get(email="tizio@example.com")
        self.assertNotEqual(created.username, "tizio")
        self.assertTrue(created.username.startswith("tizio-"))

    @override_settings(GOOGLE_OAUTH_CLIENT_ID="")
    def test_endpoint_refuses_when_not_configured(self):
        # Real verify_id_token this time: no client id must mean refusal, never
        # accepting a token we cannot check.
        r = self.client.post(reverse("auth-google"), {"credential": "qualsiasi"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 401)
