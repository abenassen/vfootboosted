"""Sign-in with Google, by verifying the ID token the browser already obtained.

Deliberately NOT django-allauth: we need one endpoint, not a second auth stack
with its own templates, adapters, and session model. The SPA runs Google's own
button, gets an ID token, and posts it here; we verify the signature and
audience against Google's public keys and issue our normal DRF token. Nothing
about the rest of the app has to know Google exists.

Linking policy, in order:

1. by the provider's ``sub`` claim, recorded in SocialAccount. This is the
   account's immutable id, so the link survives a change of Google address.
2. only when no such link exists yet, by verified email — otherwise someone who
   signed up with a password could never use the Google button with the same
   address. The ``sub`` is stored at that point, so the fallback runs once per
   user and never again.

We refuse addresses Google reports as unverified, since accepting them would let
anyone claim an account by registering that address at a provider we do not
control.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string

from vfoot.models import SocialAccount


class GoogleAuthError(Exception):
    """The ID token could not be trusted."""


@dataclass(frozen=True)
class GoogleIdentity:
    email: str
    email_verified: bool
    name: str | None
    # OIDC "sub": immutable id of the Google account. This, not the email, is
    # what identifies the person across time.
    subject: str = ""


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
    subject = (claims.get("sub") or "").strip()
    if not subject:
        raise GoogleAuthError("Il token Google non contiene un identificativo account.")
    return GoogleIdentity(
        email=email,
        email_verified=bool(claims.get("email_verified")),
        name=claims.get("name"),
        subject=subject,
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


def _activate(user: User) -> User:
    """Google vouched for the address, so an account still waiting for our own
    confirmation email is now confirmed."""
    if not user.is_active:
        user.is_active = True
        user.save(update_fields=["is_active"])
    return user


def _remember(user: User, identity: GoogleIdentity) -> None:
    link, _ = SocialAccount.objects.get_or_create(
        provider=SocialAccount.PROVIDER_GOOGLE, subject=identity.subject,
        defaults={"user": user, "email": identity.email})
    # Refresh the reported address; it is informational, and may drift from
    # User.email once the person changes it on Google's side.
    link.email = identity.email
    link.last_used_at = timezone.now()
    link.save(update_fields=["email", "last_used_at"])


@transaction.atomic
def get_or_create_user(identity: GoogleIdentity) -> tuple[User, bool]:
    """Return (user, created). Raises GoogleAuthError for unverified addresses."""
    if not identity.subject:
        raise GoogleAuthError("Identita' Google incompleta.")

    # 1. Known identity: authoritative, whatever address it carries today.
    link = (SocialAccount.objects
            .filter(provider=SocialAccount.PROVIDER_GOOGLE, subject=identity.subject)
            .select_related("user").first())
    if link:
        user = _activate(link.user)
        _remember(user, identity)
        return user, False

    # From here on we are about to trust the email, so it must be verified.
    if not identity.email_verified:
        raise GoogleAuthError(
            "L'indirizzo email dell'account Google non risulta verificato.")

    # 2. First Google sign-in for an account that already exists locally.
    existing = User.objects.filter(email__iexact=identity.email).order_by("pk").first()
    if existing:
        # ...unless that account is already tied to a DIFFERENT Google identity.
        # This happens when an address is reassigned on a custom domain. Linking
        # would silently hand the account to its new holder; creating a second
        # user would duplicate an email we require to be unique. Refuse and say
        # so, so a human decides.
        if SocialAccount.objects.filter(provider=SocialAccount.PROVIDER_GOOGLE,
                                        user=existing).exists():
            raise GoogleAuthError(
                "Questo indirizzo e' gia' associato a un altro account Google. "
                "Accedi con quell'account, oppure contatta l'amministratore.")
        user = _activate(existing)
        _remember(user, identity)
        return user, False

    # 3. Brand new person.
    user = User.objects.create_user(
        username=_unique_username(identity.email),
        email=identity.email,
        is_active=True,
    )
    # No usable password: this account can only be entered through Google until
    # the user sets one via the password-reset flow.
    user.set_unusable_password()
    user.save(update_fields=["password"])
    _remember(user, identity)
    return user, True
