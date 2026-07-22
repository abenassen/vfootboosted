"""Email-confirmation for signup.

No extra model: the token is derived from user state, the way Django's own
password-reset link works. The hash includes ``is_active``, so the moment the
account is activated every previously issued link stops working — the token is
single-use without us having to store, expire, or clean up anything.

The link points at the SPA (``VFOOT_FRONTEND_BASE_URL``), not at the API: the
user lands on a page of the app, which then calls the verify endpoint.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Token that is invalidated by activation itself."""

    def _make_hash_value(self, user, timestamp: int) -> str:
        # is_active flips False -> True on success, which changes the hash and
        # burns the link. email is included so a link cannot be replayed after
        # the address is changed.
        return f"{user.pk}{user.password}{timestamp}{user.is_active}{user.email}"


token_generator = EmailVerificationTokenGenerator()


def verification_link(user: User) -> str:
    base = str(getattr(settings, "VFOOT_FRONTEND_BASE_URL", "")).rstrip("/")
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return f"{base}/verifica-email?uid={uid}&token={token_generator.make_token(user)}"


def send_verification_email(user: User) -> None:
    link = verification_link(user)
    send_mail(
        subject="Conferma il tuo indirizzo email · Vfoot Boosted",
        message=(
            f"Ciao {user.username},\n\n"
            "per completare la registrazione a Vfoot Boosted conferma il tuo "
            f"indirizzo email aprendo questo link:\n\n{link}\n\n"
            "Se non hai richiesto tu la registrazione, ignora questo messaggio: "
            "senza conferma l'account resta inattivo.\n"
        ),
        from_email=None,  # falls back to DEFAULT_FROM_EMAIL
        recipient_list=[user.email],
        fail_silently=False,
    )


def user_from_uid(uidb64: str) -> User | None:
    try:
        pk = force_str(urlsafe_base64_decode(uidb64))
        return User.objects.get(pk=pk)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return None


def activate(user: User, token: str) -> bool:
    """Activate the account if the token matches. Idempotent-safe: a second use
    of the same link fails the check, because activation changed the hash."""
    if user.is_active or not token_generator.check_token(user, token):
        return False
    user.is_active = True
    user.save(update_fields=["is_active"])
    return True
