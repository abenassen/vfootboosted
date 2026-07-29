"""Where a user's browser can be reached with a push notification.

One row per INSTALLATION, not per user: the same person with the app on the
phone and the site open on the laptop is two subscriptions, and both want the
notification. The endpoint is the natural key — it is the URL the browser
vendor's push service handed out, and re-subscribing on the same install returns
the same one.

Nothing secret of ours lives here. ``p256dh`` and ``auth`` are the browser's own
public key material, used to encrypt the payload so that Google or Apple carry
our messages without being able to read them; our signing key stays in settings.

A subscription dies without telling us: the user clears site data, removes the
installed app, or the push service rotates it. The only way to find out is to
send and be told 404/410, so ``last_error_at``/``failures`` exist to make that
visible rather than to accumulate silent ghosts.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class PushSubscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE,
                             related_name="push_subscriptions")
    # The vendor's push endpoint (FCM for Chrome, APNs for Safari, autopush for
    # Firefox). Long on purpose: FCM's are ~200 chars and there is no stated cap.
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    # Free-text hint for the user ("Chrome su Android"), so a subscription list
    # is something a person can recognise and revoke.
    user_agent = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    failures = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["user", "created_at"])]
        ordering = ["-created_at"]

    def as_subscription_info(self) -> dict:
        """The shape pywebpush expects, i.e. the browser's own PushSubscription."""
        return {"endpoint": self.endpoint,
                "keys": {"p256dh": self.p256dh, "auth": self.auth}}

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.endpoint[:40]}…"
