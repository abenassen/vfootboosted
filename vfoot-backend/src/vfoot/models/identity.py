"""Links between a local account and an external identity provider.

Why this exists: matching on email alone is fragile. An email address is a
mutable attribute of a Google account, not its identity — change it and the next
sign-in would look like a brand new person, silently orphaning the user from
their leagues. Worse, on a custom domain an address can be reassigned to someone
else entirely, who would then inherit the account.

The provider's ``sub`` claim is the stable, immutable identifier for the account.
Storing it means the link survives every change of email, name, or avatar.

Note what is deliberately NOT here: no access token, no refresh token. We only
ever authenticate a person, never act on their behalf against Google's APIs, so
there is nothing here worth stealing beyond what the user table already holds.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class SocialAccount(models.Model):
    PROVIDER_GOOGLE = "google"
    PROVIDER_CHOICES = [(PROVIDER_GOOGLE, "Google")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="social_accounts")
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES)
    # The provider's immutable account id (the OIDC "sub" claim).
    subject = models.CharField(max_length=255)
    # Last address the provider reported, kept for support/debugging only. It is
    # NOT what identifies the account, so it may legitimately drift from
    # User.email.
    email = models.EmailField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # One local account per provider identity: without this, a race
            # between two simultaneous first sign-ins could create duplicates.
            models.UniqueConstraint(fields=["provider", "subject"],
                                    name="uniq_social_provider_subject"),
            models.UniqueConstraint(fields=["provider", "user"],
                                    name="uniq_social_provider_user"),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.subject} -> {self.user_id}"
