"""Subscribing a browser to push, and letting it go.

Four endpoints and no cleverness. Due sono deliberatamente leggibili senza
token, per lo stesso motivo: chi li chiama non ha ancora, o non ha proprio, un
utente da presentare. La chiave VAPID pubblica identifica il nostro server al
servizio di push e non autorizza niente, e il front end la vuole prima ancora di
poter chiedere il permesso; il controllo di pertinenza lo chiama il service
worker, che al token dell'utente non arriva (v. ``push_relevance``) e porta al
suo posto un gettone firmato.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from vfoot.services import push_channel, push_relevance


class PushConfigView(APIView):
    """What the browser needs to subscribe, and whether it is worth trying."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"enabled": push_channel.configured(),
                         "public_key": push_channel.public_key()})


class PushSubscribeView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not push_channel.configured():
            return Response(
                {"detail": "Le notifiche push non sono configurate su questo server."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            sub = push_channel.save_subscription(
                request.user, request.data.get("subscription") or request.data,
                user_agent=request.META.get("HTTP_USER_AGENT", ""))
        except ValueError as exc:
            return Response({"detail": str(exc)},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response({"id": sub.id, "created": True},
                        status=status.HTTP_201_CREATED)


class PushUnsubscribeView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        n = push_channel.drop_subscription(
            request.user, str(request.data.get("endpoint", "")))
        return Response({"removed": n})


class PushRelevanceView(APIView):
    """«Questa notifica ha ancora senso?», chiesto mentre la si sta per mostrare.

    Il gettone e' la credenziale: firmato, a scadenza, e buono per questa sola
    domanda su un solo utente. Senza gettone, o con uno che non torna, la
    risposta e' che la notifica va mostrata — non un errore, perche' chi chiede
    ha gia' una push in mano e l'unica cosa peggiore di una notifica di troppo e'
    una notifica in meno.

    Contata: la firma costa nulla, ma dietro c'e' un giro di database su una
    macchina con una vCPU, e un gettone valido resta valido per un giorno.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "push_relevance"

    def get(self, request):
        return Response({
            "stale": push_relevance.is_stale(request.query_params.get("t", "")),
        })
