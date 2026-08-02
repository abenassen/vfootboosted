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

WHAT SENDS. The ``live_import`` step of the tick, after an import that changed
something, and the two finalization steps. Not the light poll: it only moves the
scoreline, which is not the information anyone is here for.

THE TRAP, IN DEVELOPMENT. With no ``REDIS_URL`` the channel layer is
``InMemoryChannelLayer``, which does not fan out ACROSS PROCESSES. The tick is a
separate process from the web server, so the nudge is written into the tick's own
memory and nobody ever hears it — the page simply never refreshes, with no error
anywhere. Either run a Redis (``REDIS_URL=redis://127.0.0.1:6379/1``) or accept
that in dev the page updates on reload; see ``vfoot-sim``, which starts one.
"""
from __future__ import annotations

GROUP_PREFIX = "live_league_"


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
    try:
        async_to_sync(layer.group_send)(
            group_name(league_id),
            {"type": "live.update", "kind": kind, "league_id": league_id},
        )
    except Exception:  # noqa: BLE001
        return
