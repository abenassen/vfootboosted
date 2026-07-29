"""Subscribing a browser to push, and letting it go.

Three endpoints and no cleverness. The config one is deliberately readable
without a token: the public VAPID key is what identifies the application server
to the push service, not what authorises anything, and the front end needs it
before it can even ask for permission.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from vfoot.services import push_channel


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
