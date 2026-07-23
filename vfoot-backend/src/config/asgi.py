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
