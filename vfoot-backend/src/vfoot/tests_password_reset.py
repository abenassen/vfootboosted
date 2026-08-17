"""Password recovery: the emailed link, and what it is allowed to do."""
from __future__ import annotations

from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.authtoken.models import Token
from rest_framework.throttling import ScopedRateThrottle

from vfoot.services.auth_tokens import issue_token
from vfoot.services.password_reset import token_generator

NEW = "unaAltraPassword9"


def _parts(user: User) -> tuple[str, str]:
    return (urlsafe_base64_encode(force_bytes(user.pk)),
            token_generator.make_token(user))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   VFOOT_FRONTEND_BASE_URL="https://vfoot.it")
class PasswordResetTests(TestCase):
    def setUp(self):
        # The throttle counts in the cache, which is NOT reset between tests: two
        # tests that each ask for a link would otherwise share one allowance, and
        # the suite would start failing when a test is added rather than when the
        # code breaks. Cleared here instead of overridden, because the rate cannot
        # be overridden — see PasswordResetThrottleTests.
        ScopedRateThrottle.cache.clear()
        self.user = User.objects.create_user(
            username="andrea", email="Andrea@Example.com",
            password="laVecchiaPassword9", is_active=True)

    def _request(self, email="andrea@example.com"):
        return self.client.post(reverse("auth-password-reset"), {"email": email},
                                content_type="application/json")

    def _confirm(self, uid, token, password=NEW, confirm=None):
        return self.client.post(
            reverse("auth-password-reset-confirm"),
            {"uid": uid, "token": token, "new_password": password,
             "new_password_confirm": confirm if confirm is not None else password},
            content_type="application/json")

    # -- asking for the link --------------------------------------------

    def test_request_sends_a_link_to_the_spa(self):
        r = self._request()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("https://vfoot.it/nuova-password?uid=", mail.outbox[0].body)

    def test_email_match_is_case_insensitive(self):
        # The address is stored as typed at signup, so a lowercase request must
        # still find it — otherwise recovery fails for everyone who capitalised.
        self.assertEqual(self._request("ANDREA@example.com").status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_unknown_address_answers_the_same_and_sends_nothing(self):
        known = self._request()
        unknown = self._request("nessuno@example.com")
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.json(), unknown.json())
        self.assertEqual(len(mail.outbox), 1)  # only the known one

    # -- using it -------------------------------------------------------

    def test_reset_sets_the_password_and_signs_in(self):
        uid, token = _parts(self.user)
        r = self._confirm(uid, token)
        self.assertEqual(r.status_code, 200)
        self.assertIn("token", r.json())
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW))

    def test_link_is_single_use(self):
        uid, token = _parts(self.user)
        self.assertEqual(self._confirm(uid, token).status_code, 200)
        # The hash covers the password, so changing it burns the link.
        self.assertEqual(self._confirm(uid, token, "terzaPassword9").status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW))

    def test_old_sessions_are_revoked(self):
        # The reason to reset may be that someone else holds a session.
        old = issue_token(self.user).key
        uid, token = _parts(self.user)
        r = self._confirm(uid, token)
        self.assertNotEqual(r.json()["token"], old)
        self.assertFalse(Token.objects.filter(key=old).exists())

    def test_tampered_token_is_rejected(self):
        uid, _ = _parts(self.user)
        self.assertEqual(self._confirm(uid, "non-valido").status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.check_password(NEW))

    def test_token_of_one_user_cannot_reset_another(self):
        victim = User.objects.create_user(username="vittima", email="v@example.com",
                                          password="passwordDiVittima9")
        _, token = _parts(self.user)
        r = self._confirm(urlsafe_base64_encode(force_bytes(victim.pk)), token)
        self.assertEqual(r.status_code, 400)
        victim.refresh_from_db()
        self.assertTrue(victim.check_password("passwordDiVittima9"))

    def test_unknown_uid_and_bad_token_are_indistinguishable(self):
        uid, _ = _parts(self.user)
        missing = self._confirm(urlsafe_base64_encode(force_bytes(999999)), "x")
        bad = self._confirm(uid, "x")
        self.assertEqual(missing.status_code, bad.status_code)
        self.assertEqual(missing.json(), bad.json())

    # -- what the new password has to be --------------------------------

    def test_mismatched_confirmation_is_refused(self):
        uid, token = _parts(self.user)
        r = self._confirm(uid, token, NEW, "qualcosaAltro9")
        self.assertEqual(r.status_code, 400)
        self.assertIn("new_password_confirm", r.json())

    def test_weak_password_is_refused(self):
        uid, token = _parts(self.user)
        self.assertEqual(self._confirm(uid, token, "12345678").status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("laVecchiaPassword9"))

    def test_password_equal_to_username_is_refused(self):
        # Only answerable once the uid is resolved — the point of validating in
        # the view rather than in the serializer.
        uid, token = _parts(self.user)
        r = self._confirm(uid, token, "andrea", "andrea")
        self.assertEqual(r.status_code, 400)

    # -- the two account kinds that arrive here on purpose ---------------

    def test_reset_also_confirms_an_account_that_never_was(self):
        pending = User.objects.create_user(username="attesa", email="a@example.com",
                                           password="qualsiasiPassword9",
                                           is_active=False)
        uid, token = _parts(pending)
        r = self._confirm(uid, token)
        self.assertEqual(r.status_code, 200)
        pending.refresh_from_db()
        self.assertTrue(pending.is_active)
        self.assertTrue(pending.check_password(NEW))

    def test_google_account_without_a_password_can_set_one(self):
        google = User.objects.create_user(username="google", email="g@example.com")
        google.set_unusable_password()
        google.save(update_fields=["password"])
        uid, token = _parts(google)
        self.assertEqual(self._confirm(uid, token).status_code, 200)
        google.refresh_from_db()
        self.assertTrue(google.has_usable_password())
        self.assertTrue(google.check_password(NEW))


# A REAL cache, because the suite runs against a dummy one: throttling counts by
# remembering, and there is nothing to test when nothing is remembered. See the
# `if "test" in sys.argv` block in settings.py for why the default is dummy.
@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                        "LOCATION": "throttle-tests"}},
)
class PasswordResetThrottleTests(TestCase):
    def setUp(self):
        ScopedRateThrottle.cache.clear()
        User.objects.create_user(username="andrea", email="andrea@example.com",
                                 password="laVecchiaPassword9")

    def test_requests_are_rate_limited(self):
        # NOT override_settings(REST_FRAMEWORK=...): DRF binds THROTTLE_RATES as a
        # CLASS attribute when rest_framework.throttling is imported, so overriding
        # the setting changes api_settings and leaves the throttle reading the dict
        # it captured at startup. It fails silently — the override looks applied and
        # the real rate stays in force — which cost this test a first version that
        # passed only because 4 is less than 5.
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES,
                             {"password_reset": "2/hour"}):
            url = reverse("auth-password-reset")
            body = {"email": "andrea@example.com"}
            for _ in range(2):
                r = self.client.post(url, body, content_type="application/json")
                self.assertEqual(r.status_code, 200)
            blocked = self.client.post(url, body, content_type="application/json")
            self.assertEqual(blocked.status_code, 429)
            # And the point of it: the third one did not send anything.
            self.assertEqual(len(mail.outbox), 2)
