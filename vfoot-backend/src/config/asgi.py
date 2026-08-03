"""
ASGI config for config project.

Exposes the ASGI callable as ``application``. HTTP is served by Django as usual;
the ``websocket`` protocol is routed to the Channels consumers (the live auction
room). The deploy already runs under uvicorn (ASGI) precisely so this works without
a server-layer change — see deploy/DEPLOY.md.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# The Django app must be initialised before importing anything that touches models
# (the consumers do, transitively), so build the HTTP app first.
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from vfoot.ws_routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # Consumers do their own DRF-token auth from the query string; the session
        # middleware stack is harmless and lets us fall back to it later if needed.
        "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)


# --------------------------------------------------------------------------- #
# Development only: the in-process tick needs THIS loop                        #
# --------------------------------------------------------------------------- #
# Without a Redis, the tick can be run as a thread of this very process so that the
# in-memory channel layer reaches the browser (realdata/services/tick_thread.py).
# But that thread has no loop of its own worth having: the queues the consumers
# wait on belong to the loop running right here, and a nudge sent from a private
# loop is deposited and never heard. So the loop is captured on the first ASGI call
# — the one place where it certainly exists and certainly is the right one.
#
# Wrapped ONLY when the flag is on: with a separate tick process, or in production,
# `application` is exactly the router above and this code never runs.
if os.environ.get("VFOOT_TICK_IN_PROCESS", "").strip().lower() in {"1", "true", "yes", "on"}:
    _router = application
    _captured = False

    async def application(scope, receive, send):  # noqa: F811
        # A flag and not a rebinding of `application`: the server holds its own
        # reference to this callable from startup, so reassigning the name here
        # would change nothing and only read as if it did.
        global _captured
        if not _captured:
            import asyncio

            from vfoot.services.live_realtime import use_server_loop

            use_server_loop(asyncio.get_running_loop())
            _captured = True
        await _router(scope, receive, send)
