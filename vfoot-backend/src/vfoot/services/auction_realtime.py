"""Thin pub/sub bridge between the REST write-path and the auction WebSocket.

The REST endpoints stay the single write path (they own auth + transactions); after
a successful commit they call :func:`broadcast_auction` to push the fresh state to
everyone watching the room. The consumer itself is read-only.

Everything here degrades to a no-op when there is no channel layer configured (the
in-memory test settings, or a deploy that hasn't enabled Redis yet), so the auction
keeps working over plain polling and the test-suite needs no Redis.
"""

from __future__ import annotations

GROUP_PREFIX = "auction_"


def group_name(session_id: int) -> str:
    return f"{GROUP_PREFIX}{session_id}"


def broadcast_auction(session_id: int, kind: str = "state") -> None:
    """Notify the room that ``session_id`` changed. Clients re-fetch the state.

    We deliberately push only a light signal ("something changed") rather than the
    full serialized state: the state view already exists, does the auth/legality
    computation, and clients call it on connect anyway — so a nudge keeps the
    socket path and the polling path returning identical data with zero drift.
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
            group_name(session_id),
            {"type": "auction.update", "kind": kind, "session_id": session_id},
        )
    except Exception:
        # A broadcast failure must never break the committed transaction / response.
        return
