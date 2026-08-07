"""Pub/sub bridge between the scheduler tick and the league's live WebSocket.

The mirror of ``auction_realtime``, and deliberately the same shape: a light
``{"type":"update"}`` nudge, never the data. The client then re-reads the
authoritative state over the REST endpoints it already calls on load, so the
socket path and the reload path cannot drift apart — there is only one way to
compute a tabellino and both go through it.

WHY A SOCKET AND NOT POLLING. Polling would work today only because the scraping
happens to run every two minutes; that is a property of this deployment, not of
the product. The cost of polling grows with users x frequency, the cost of a
socket with the number of real changes — and during a Serie A round the real
changes are a handful per minute no matter how many people are watching.

WHAT SENDS. Every live ROUND of the tick, after an import that changed something,
and the two finalization steps. A round is not a scoreline refresh: it rewrites the
per-player data, which is the information people are here for.

THE TRAP, IN DEVELOPMENT. With no ``REDIS_URL`` the channel layer is
``InMemoryChannelLayer``, which does not fan out ACROSS PROCESSES. The tick is a
separate process from the web server, so the nudge is written into the tick's own
memory and nobody ever hears it — the page simply never refreshes, with no error
anywhere. Either run a Redis (``REDIS_URL=redis://127.0.0.1:6379/1``) or accept
that in dev the page updates on reload; see ``vfoot-sim``, which starts one.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

GROUP_PREFIX = "live_league_"

# The web server's event loop, registered ONLY by the development in-process tick
# (see config/asgi.py and realdata/services/tick_thread.py). None everywhere else,
# which is every production process: there the tick is its own service and the
# fan-out is Redis's job.
_SERVER_LOOP = None


def use_server_loop(loop) -> None:
    """Deliver nudges on THIS loop instead of a private one.

    ``InMemoryChannelLayer`` is built on ``asyncio.Queue``, and those queues belong
    to the loop the consumers are waiting in. A nudge sent through
    ``async_to_sync`` from another thread runs in a NEW loop: the message is put on
    the queue and the waiting consumer's future is resolved from the wrong thread,
    so an idle server never wakes up to notice. Nothing raises — the browser simply
    stops being told anything, which is the same silence this module's docstring
    warns about for the cross-process case, arrived at by a different road.
    """
    global _SERVER_LOOP
    _SERVER_LOOP = loop
    log.warning("spinte live: registrato il loop del server (%r)", loop)


def group_name(league_id: int) -> str:
    return f"{GROUP_PREFIX}{league_id}"


def broadcast_live(league_id: int, kind: str = "scores") -> None:
    """Tell everyone watching this league's round that something moved.

    Never raises and never blocks the caller: the tick's job is to import, and a
    channel layer that is down must not turn a good import into a failed one.
    """
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
    except Exception:  # channels not installed
        return

    layer = get_channel_layer()
    if layer is None:
        return
    message = {"type": "live.update", "kind": kind, "league_id": league_id}
    try:
        if _SERVER_LOOP is not None and not _SERVER_LOOP.is_closed():
            # On the server's own loop, and NOT waited on: the tick has imported
            # what it came to import, and whether a browser hears about it is not
            # its business to block for.
            import asyncio

            asyncio.run_coroutine_threadsafe(
                layer.group_send(group_name(league_id), message), _SERVER_LOOP)
            return
        async_to_sync(layer.group_send)(group_name(league_id), message)
    except Exception:  # noqa: BLE001
        # Era un `return` muto. Un layer che non consegna e non lo dice e' il modo
        # in cui questa faccenda si nasconde: la pagina smette di aggiornarsi e non
        # c'e' niente da nessuna parte. Non risolleva -- il tick ha importato, e
        # quello resta valido -- ma lascia una traccia.
        log.exception("spinta live fallita per la lega %s", league_id)
        return
