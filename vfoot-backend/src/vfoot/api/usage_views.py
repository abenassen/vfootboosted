"""Il registro delle pagine: il client manda i tratti in primo piano, qui si filtrano.

Il client non decide niente di ciò che conta: se il registro è acceso, se chi
scrive è staff, se c'è una partita in corso. Lo decide il server, così una
versione vecchia del frontend rimasta in cache non può scrivere ciò che non deve.
"""
from __future__ import annotations

import re

from django.conf import settings
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from realdata.models import Match
from vfoot.models import PageVisit

# Quanti tratti in una chiamata. Il client ne manda uno o due per cambio di
# pagina; venti coprono una coda accumulata offline, e oltre è qualcos'altro.
MAX_BATCH = 20
# Oltre le sei ore non è una persona che legge, è una scheda dimenticata con lo
# schermo acceso: si tiene la riga ma non le si lascia gonfiare le medie.
MAX_VISIBLE_MS = 6 * 3600 * 1000
# Il client toglie già gli identificativi; qui si rifiuta tutto ciò che non ha la
# forma di una rotta pulita, perché un indirizzo con dentro un'email o un codice
# non deve poter entrare nemmeno per sbaglio.
ROUTE_RE = re.compile(r"^/[a-z0-9/:_-]{0,119}$")
SESSION_RE = re.compile(r"^[A-Za-z0-9]{8,16}$")


def _clean(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    route = str(item.get("route", ""))
    session = str(item.get("session", ""))
    device = item.get("device")
    try:
        ms = int(item.get("visible_ms"))
    except (TypeError, ValueError):
        return None
    # Il codice d'invito è una credenziale: entra solo già sostituito.
    if route.startswith("/join/") and route != "/join/:code":
        return None
    if (not ROUTE_RE.match(route) or not SESSION_RE.match(session)
            or device not in (PageVisit.DEVICE_MOBILE, PageVisit.DEVICE_DESKTOP)
            or ms <= 0):
        return None
    return {"route": route, "session": session, "device": device,
            "visible_ms": min(ms, MAX_VISIBLE_MS),
            "standalone": bool(item.get("standalone"))}


class PageVisitView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [AllowAny]     # anche la pagina d'ingresso conta
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "usage"

    def post(self, request):
        # Sempre 204, anche quando si scarta: il client non ha niente da fare con
        # la risposta, e una risposta diversa direbbe a chiunque cosa registriamo.
        user = request.user
        if not settings.VFOOT_USAGE_LOG or getattr(user, "is_staff", False):
            return Response(status=204)
        items = request.data.get("visits") if isinstance(request.data, dict) else None
        if not isinstance(items, list):
            return Response(status=204)
        rows = [r for r in (_clean(i) for i in items[:MAX_BATCH]) if r]
        if rows:
            live = Match.objects.filter(status=Match.STATUS_LIVE).exists()
            signed_in = bool(user and user.is_authenticated)
            PageVisit.objects.bulk_create(
                [PageVisit(live=live, signed_in=signed_in, **r) for r in rows])
            # La scadenza si fa qui e non in un timer: una DELETE su un indice per
            # data costa niente, e un registro che si pota da solo non dipende da
            # un'unità che qualcuno deve ricordarsi di accendere.
            PageVisit.prune()
        return Response(status=204)
