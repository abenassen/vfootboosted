"""Project middleware.

``SimClockHeaderMiddleware`` tells the browser what time it is for the SERVER, and
is only useful when the clock has been shifted (see ``vfoot/simclock.py``). Without
it the client stays on the real clock while the server is months ahead, and every
countdown — a market session closing, an offer maturing — would be computed between
a simulated deadline and a real now: months, where the user expects minutes.

It ships as a HEADER on every response rather than a dedicated endpoint, for two
reasons. First, the skew then refreshes itself on every request and cannot go
stale. Second, it adds no round trip at start-up: the first useful call already
carries the answer.

When the clock is not shifted the header is not set at all, so in production this
middleware costs one boolean test and nothing else — and the client, not finding
it, keeps using its own clock as it always has.
"""
from __future__ import annotations

from django.utils import timezone

from vfoot import simclock

HEADER = "X-Vfoot-Now"


class SimClockHeaderMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # Decided once at start-up: the clock does not move while the process runs.
        self.active = simclock.is_active()

    def __call__(self, request):
        response = self.get_response(request)
        if self.active:
            response[HEADER] = timezone.now().isoformat()
        return response
