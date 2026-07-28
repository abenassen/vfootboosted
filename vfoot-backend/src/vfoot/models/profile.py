"""Per-user profile data that is not part of Django's auth.User.

Right now this holds only the avatar. The avatar is stored as an OPAQUE string:
the client (SPA) owns the avatar schema — it composes a set of illustration
options (skin tone, hair, clothing colour, …) and renders the SVG entirely in the
browser. The server never parses, validates, or renders it; it only persists and
echoes it back. Keeping it opaque means new avatar options can ship in the
frontend without a single backend change or migration.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    # Opaque, client-defined avatar descriptor (a JSON string of avataaars
    # options). Empty string => no avatar chosen yet (frontend falls back to a
    # deterministic default from the username).
    avatar = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:  # pragma: no cover - admin/debug convenience
        return f"Profile({self.user_id})"
