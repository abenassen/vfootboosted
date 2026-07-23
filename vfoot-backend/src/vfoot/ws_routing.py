"""WebSocket URL routing (mounted by config/asgi.py)."""

from django.urls import re_path

from vfoot.consumers import AuctionConsumer

websocket_urlpatterns = [
    re_path(r"^ws/auctions/(?P<session_id>\d+)/$", AuctionConsumer.as_asgi()),
]
