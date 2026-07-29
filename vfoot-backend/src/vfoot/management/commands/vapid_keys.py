"""Generate the VAPID key pair for Web Push, once per deployment.

    python manage.py vapid_keys

Prints two lines to paste into the environment. Run it ONCE and keep the pair:
regenerating invalidates every existing subscription, because the browser bound
its subscription to the public key it was given — every installed app would go
silent until each user re-subscribed.

The pair is a plain P-256 (secp256r1) key. The public half is the uncompressed
point, base64url without padding, which is exactly what the browser wants as
``applicationServerKey``; the private half is the 32-byte scalar in the same
encoding, which is what pywebpush signs with.
"""
from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def generate_pair() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    private = key.private_numbers().private_value.to_bytes(32, "big")
    return _b64(public), _b64(private)


class Command(BaseCommand):
    help = "Genera una coppia di chiavi VAPID per le notifiche push."

    def handle(self, *args, **options):
        public, private = generate_pair()
        self.stdout.write(self.style.SUCCESS(
            "Coppia VAPID generata. Mettile nell'ambiente (.env) e NON "
            "rigenerarle:\n"))
        self.stdout.write(f"VFOOT_VAPID_PUBLIC_KEY={public}")
        self.stdout.write(f"VFOOT_VAPID_PRIVATE_KEY={private}")
        self.stdout.write(self.style.WARNING(
            "\nRigenerarle zittisce tutte le installazioni esistenti: ogni "
            "browser ha legato la propria subscription alla chiave pubblica "
            "ricevuta al momento dell'iscrizione."))
