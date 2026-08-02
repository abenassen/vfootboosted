"""WebSocket URL routing (mounted by config/asgi.py)."""

from django.urls import re_path

from vfoot.consumers import AuctionConsumer, LiveConsumer

websocket_urlpatterns = [
    re_path(r"^ws/auctions/(?P<session_id>\d+)/$", AuctionConsumer.as_asgi()),
    re_path(r"^ws/leagues/(?P<league_id>\d+)/live/$", LiveConsumer.as_asgi()),
]
