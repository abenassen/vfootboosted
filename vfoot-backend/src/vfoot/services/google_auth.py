"""Sign-in with Google, by verifying the ID token the browser already obtained.

Deliberately NOT django-allauth: we need one endpoint, not a second auth stack
with its own templates, adapters, and session model. The SPA runs Google's own
button, gets an ID token, and posts it here; we verify the signature and
audience against Google's public keys and issue our normal DRF token. Nothing
about the rest of the app has to know Google exists.

Linking policy: an ID token from Google carries an ``email_verified`` flag. When
it is true we treat the address as proof of ownership and attach to the existing
account with that email — otherwise a user who signed up with a password would
be unable to use the Google button with the same address. We refuse unverified
Google addresses outright, since accepting them would let anyone claim an
account by registering that address at an identity provider we do not control.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.utils.crypto import get_random_string


class GoogleAuthError(Exception):
    """The ID token could not be trusted."""


@dataclass(frozen=True)
class GoogleIdentity:
    email: str
    email_verified: bool
    name: str | None


def verify_id_token(raw_token: str) -> GoogleIdentity:
    client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", None)
    if not client_id:
        raise GoogleAuthError("Login con Google non configurato su questo server.")
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token
    except ImportError as exc:  # pragma: no cover - depends on env
        # Report the ACTUAL missing module: google-auth pulls its HTTP transport
        # from `requests`, and a generic "install google-auth" message sends you
        # chasing a package that is already there.
        raise GoogleAuthError(f"Dipendenza mancante ({exc}).") from exc

    try:
        claims = google_id_token.verify_oauth2_token(
            raw_token, google_requests.Request(), client_id)
    except ValueError as exc:
        # Covers bad signature, wrong audience, and expiry.
        raise GoogleAuthError(f"Token Google non valido: {exc}") from exc

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise GoogleAuthError("Il token Google non contiene un indirizzo email.")
    return GoogleIdentity(
        email=email,
        email_verified=bool(claims.get("email_verified")),
        name=claims.get("name"),
    )


def _unique_username(email: str) -> str:
    base = "".join(ch for ch in email.split("@")[0] if ch.isalnum() or ch in "._-")
    base = (base or "utente")[:140]
    if not User.objects.filter(username=base).exists():
        return base
    # A counter would leak how many people share a local part, and races between
    # two concurrent signups would collide; a short random suffix does neither.
    while True:
        candidate = f"{base}-{get_random_string(5).lower()}"
        if not User.objects.filter(username=candidate).exists():
            return candidate


@transaction.atomic
def get_or_create_user(identity: GoogleIdentity) -> tuple[User, bool]:
    """Return (user, created). Raises GoogleAuthError for unverified addresses."""
    if not identity.email_verified:
        raise GoogleAuthError(
            "L'indirizzo email dell'account Google non risulta verificato.")

    existing = User.objects.filter(email__iexact=identity.email).order_by("pk").first()
    if existing:
        # Google vouched for the address, so an account that was still waiting
        # for our own confirmation email is now confirmed.
        if not existing.is_active:
            existing.is_active = True
            existing.save(update_fields=["is_active"])
        return existing, False

    user = User.objects.create_user(
        username=_unique_username(identity.email),
        email=identity.email,
        is_active=True,
    )
    # No usable password: this account can only be entered through Google until
    # the user sets one via the password-reset flow.
    user.set_unusable_password()
    user.save(update_fields=["password"])
    return user, True
