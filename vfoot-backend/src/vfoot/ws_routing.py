"""WebSocket URL routing (mounted by config/asgi.py)."""

from django.urls import re_path

from vfoot.consumers import AuctionConsumer, LiveConsumer, UnknownPathConsumer

websocket_urlpatterns = [
    re_path(r"^ws/auctions/(?P<session_id>\d+)/$", AuctionConsumer.as_asgi()),
    re_path(r"^ws/leagues/(?P<league_id>\d+)/live/$", LiveConsumer.as_asgi()),
    # ULTIMA, e catch-all: senza, un percorso che non combacia fa sollevare a
    # URLRouter un ValueError, che diventa un 500 con traceback nel journal a ogni
    # tentativo. Le rotte qui sopra finiscono con "$" e vengono quindi confrontate
    # con `fullmatch`, percio' questa non le puo' scavalcare: raccoglie solo cio'
    # che non ha gia' trovato casa. Va tenuta in fondo.
    re_path(r"", UnknownPathConsumer.as_asgi()),
]
