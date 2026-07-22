"""Issuing an API token, in one place.

DRF's TokenAuthentication never goes through django.contrib.auth.login(), so
last_login is never written and the field stays empty forever — which makes it
impossible to answer "who is still using this?". Every place that hands out a
token goes through here, so the answer stays true.
"""
from __future__ import annotations

from django.contrib.auth.models import update_last_login
from rest_framework.authtoken.models import Token


def issue_token(user) -> Token:
    token, _ = Token.objects.get_or_create(user=user)
    update_last_login(None, user)
    return token
