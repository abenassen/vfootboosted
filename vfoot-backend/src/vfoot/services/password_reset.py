"""Password recovery by emailed link.

Same shape as ``email_verification``, and for the same reason: no extra model,
because the token is derived from user state. Here we do not even need a custom
generator — Django's stock ``PasswordResetTokenGenerator`` hashes the current
password and ``last_login``, so the link stops working the moment it is used.
Single-use, with nothing to store, expire or clean up.

That "or ``last_login``" has a consequence worth knowing: signing in normally
also burns any outstanding reset link. It is the right way round — remembering
the password is exactly the case where the pending link should stop mattering —
but it does mean a link cannot be tested by logging in first.

Two flavours of account arrive here on purpose:

*   accounts that never confirmed their address. Opening a link sent to that
    address proves precisely what the confirmation email proves, so a successful
    reset activates them (see ``reset_password``). Without this, someone who lost
    both the confirmation mail and the password would have no way back in at all.
*   Google accounts, which are created with an unusable password. Setting one
    here is how they gain a second way in — ``google_auth.get_or_create_user``
    already says so where it calls ``set_unusable_password()``.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

# The uid encoding is shared with the confirmation link by construction, and must
# stay shared: both links are read by the same helper, and two encodings that
# drifted apart would fail as "invalid link" rather than as a mismatch.
from vfoot.services.email_verification import user_from_uid

__all__ = ["reset_link", "send_password_reset_email", "user_from_uid",
           "reset_password", "token_generator"]

token_generator = default_token_generator


def reset_link(user: User) -> str:
    base = str(getattr(settings, "VFOOT_FRONTEND_BASE_URL", "")).rstrip("/")
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return f"{base}/nuova-password?uid={uid}&token={token_generator.make_token(user)}"


def send_password_reset_email(user: User) -> None:
    link = reset_link(user)
    send_mail(
        subject="Reimposta la tua password · Vfoot Boosted",
        message=(
            f"Ciao {user.username},\n\n"
            "hai chiesto di reimpostare la password di Vfoot Boosted. Apri "
            f"questo link per sceglierne una nuova:\n\n{link}\n\n"
            "Il link vale una volta sola e scade dopo tre giorni.\n\n"
            "Se non sei stato tu, ignora questo messaggio: la password attuale "
            "resta valida e nessuno puo' entrare senza aprire il link.\n"
        ),
        from_email=None,  # falls back to DEFAULT_FROM_EMAIL
        recipient_list=[user.email],
        fail_silently=False,
    )


def reset_password(user: User, token: str, new_password: str) -> bool:
    """Set a new password if the token matches. False if it does not."""
    if not token_generator.check_token(user, token):
        return False

    user.set_password(new_password)
    fields = ["password"]
    # The link went to the registered address and was opened, which is the same
    # proof the confirmation email asks for — so an account still waiting on that
    # email is confirmed here rather than left in a state it can never leave.
    if not user.is_active:
        user.is_active = True
        fields.append("is_active")
    user.save(update_fields=fields)
    return True
