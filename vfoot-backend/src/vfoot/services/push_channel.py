"""Sending a Web Push, and forgetting the subscriptions that have died.

Web Push is not a socket. The device keeps ONE connection to its vendor's push
service (FCM for Chrome, APNs for Safari, autopush for Firefox), shared by every
site and app on it; we POST an encrypted payload to the endpoint that service
handed out, signed with our VAPID key so it knows who is asking. That is why a
notification arrives with nothing of ours open — and why there is no server here
holding connections.

Two things this module exists to get right:

* **a dead subscription is deleted, not retried forever.** The user clears site
  data or removes the installed app and nobody tells us; the push service answers
  404 or 410 on the next send, and that answer is the only signal we will ever
  get. Anything else (a 5xx, a timeout) is transient and only counted.
* **a failure here is not a failure upstream.** The caller was doing something
  real — settling a decision, closing a session; a push that does not go out must
  not turn that into an error on someone's screen.

Not configured (no VAPID keys) is a normal state, not a broken one: the feature
is simply off, and the email channel carries everything on its own.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings
from django.utils import timezone

from vfoot.models import PushSubscription

log = logging.getLogger(__name__)

# The push services reject anything much bigger once encrypted; keep the payload
# a pointer to the app, never the content itself.
MAX_PAYLOAD_BYTES = 3000
# HTTP answers that mean "this subscription no longer exists". Anything else is
# treated as weather.
GONE_STATUSES = (404, 410)


def configured() -> bool:
    return bool(getattr(settings, "VFOOT_VAPID_PUBLIC_KEY", "")
                and getattr(settings, "VFOOT_VAPID_PRIVATE_KEY", ""))


def public_key() -> str:
    """The applicationServerKey the browser needs to subscribe. Public by
    design — it is what identifies us, not what authorises us."""
    return str(getattr(settings, "VFOOT_VAPID_PUBLIC_KEY", ""))


def _claims() -> dict:
    return {"sub": str(getattr(settings, "VFOOT_VAPID_SUBJECT",
                               "mailto:no-reply@vfoot.it"))}


def send_to_user(user, *, title: str, body: str, url: str = "/",
                 tag: str = "") -> int:
    """Push to every live installation of one user. Returns how many got through.

    Never raises: see the module docstring.
    """
    if not configured():
        return 0
    subs = list(PushSubscription.objects.filter(user=user))
    if not subs:
        return 0
    payload = json.dumps({"title": title, "body": body, "url": url,
                          "tag": tag or "vfoot"})
    if len(payload.encode()) > MAX_PAYLOAD_BYTES:
        # Truncating the body beats being dropped by the push service.
        body = body[:200]
        payload = json.dumps({"title": title, "body": body, "url": url,
                              "tag": tag or "vfoot"})
    sent = 0
    for sub in subs:
        if _send_one(sub, payload):
            sent += 1
    return sent


def _send_one(sub: PushSubscription, payload: str) -> bool:
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:                                   # pragma: no cover
        log.warning("pywebpush non installato: notifiche push disattivate.")
        return False
    try:
        webpush(subscription_info=sub.as_subscription_info(), data=payload,
                vapid_private_key=str(settings.VFOOT_VAPID_PRIVATE_KEY),
                vapid_claims=_claims(), ttl=int(
                    getattr(settings, "VFOOT_PUSH_TTL_SECONDS", 86400)))
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in GONE_STATUSES:
            # The only authoritative "this install is gone" we ever receive.
            log.info("Subscription push non più valida (%s), la rimuovo.", status)
            sub.delete()
            return False
        PushSubscription.objects.filter(id=sub.id).update(
            failures=sub.failures + 1, last_error_at=timezone.now())
        log.warning("Push non consegnata (stato %s): %s", status, exc)
        return False
    except Exception:                                     # noqa: BLE001
        PushSubscription.objects.filter(id=sub.id).update(
            failures=sub.failures + 1, last_error_at=timezone.now())
        log.exception("Errore inatteso nell'invio push")
        return False
    PushSubscription.objects.filter(id=sub.id).update(
        last_sent_at=timezone.now(), failures=0, last_error_at=None)
    return True


def save_subscription(user, data: dict, *, user_agent: str = "") -> PushSubscription:
    """Store what the browser handed us. Idempotent on the endpoint, and it
    REASSIGNS the row if the same install now belongs to another account —
    otherwise a shared family tablet would keep notifying whoever logged in
    first. Raises ValueError on a payload that is not a PushSubscription."""
    endpoint = str((data or {}).get("endpoint") or "").strip()
    keys = (data or {}).get("keys") or {}
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()
    if not endpoint or not p256dh or not auth:
        raise ValueError("Subscription incompleta: servono endpoint, p256dh e auth.")
    sub, _ = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={"user": user, "p256dh": p256dh, "auth": auth,
                  "user_agent": user_agent[:300], "failures": 0,
                  "last_error_at": None})
    return sub


def drop_subscription(user, endpoint: str) -> int:
    """Unsubscribe. Scoped to the user so an endpoint cannot be revoked by
    whoever happens to know it."""
    deleted, _ = PushSubscription.objects.filter(
        user=user, endpoint=str(endpoint or "").strip()).delete()
    return deleted
