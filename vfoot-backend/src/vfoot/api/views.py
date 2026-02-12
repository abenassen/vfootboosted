from __future__ import annotations

from datetime import datetime, timezone

from django.db import transaction
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from vfoot.api.data_builders import build_lineup_context
from vfoot.api.serializers import (
    LineupContextQuerySerializer,
    LoginSerializer,
    MatchesQuerySerializer,
    RegisterSerializer,
    SaveLineupRequestSerializer,
    UserSerializer,
)
from vfoot.models import SavedLineupSnapshot
from vfoot.services.duel_engine import compute_match_zone_duels


class RegisterView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = User.objects.create_user(
            username=data["username"],
            email=data.get("email", ""),
            password=data["password"],
        )
        token, _ = Token.objects.get_or_create(user=user)

        return Response(
            {"token": token.key, "user": UserSerializer(user).data},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = authenticate(username=data["username"], password=data["password"])
        if not user:
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": UserSerializer(user).data}, status=status.HTTP_200_OK)


class MeView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"user": UserSerializer(request.user).data}, status=status.HTTP_200_OK)


class LogoutView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LineupContextView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = LineupContextQuerySerializer(data=request.query_params)
        qs.is_valid(raise_exception=True)
        payload = build_lineup_context(
            league_id=qs.validated_data["league_id"],
            matchday_id=qs.validated_data["matchday_id"],
        )
        return Response(payload)


class SaveLineupView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        s = SaveLineupRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        lineup_id = f"LU-{int(datetime.now(timezone.utc).timestamp())}"
        obj, _ = SavedLineupSnapshot.objects.update_or_create(
            league_id=data["league_id"],
            matchday_id=data["matchday_id"],
            defaults={
                "lineup_id": lineup_id,
                "gk_player_id": data.get("gk_player_id"),
                "starter_player_ids": data["starter_player_ids"],
                "bench_player_ids": data["bench_player_ids"],
                "starter_backups": data.get("starter_backups", []),
                "saved_at": datetime.now(timezone.utc),
            },
        )

        context = build_lineup_context(data["league_id"], data["matchday_id"])
        roster_by_id = {p["player_id"]: p for p in context["roster"]}

        warnings = []
        for pid in data["starter_player_ids"]:
            p = roster_by_id.get(pid)
            if p and p["status"]["minutes_expectation"]["label"] == "low":
                warnings.append(
                    {
                        "code": "LOW_MINUTES_RISK",
                        "player_id": pid,
                        "message": f"{p['name']}: low expected minutes",
                    }
                )

        resp = {
            "lineup_id": obj.lineup_id,
            "saved_at": obj.saved_at.isoformat(),
            "coverage_preview": context["coverage_preview"],
        }
        if warnings:
            resp["warnings"] = warnings

        return Response(resp, status=status.HTTP_200_OK)


class MatchListView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = MatchesQuerySerializer(data=request.query_params)
        qs.is_valid(raise_exception=True)

        league_id = qs.validated_data["league_id"]
        matchday_id = qs.validated_data["matchday_id"]

        items = [
            {
                "match_id": f"{matchday_id}-M1",
                "home": {"team_id": "T12", "name": "Casa FC"},
                "away": {"team_id": "T55", "name": "Trasferta FC"},
                "status": "finished",
                "score": {"home_total": 70.2, "away_total": 67.8},
            },
            {
                "match_id": f"{matchday_id}-M2",
                "home": {"team_id": "T33", "name": "Aurora"},
                "away": {"team_id": "T12", "name": "Casa FC"},
                "status": "finished",
                "score": {"home_total": 66.1, "away_total": 69.0},
            },
        ]

        return Response(items)


class MatchDetailView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, match_id: str):
        qs = MatchesQuerySerializer(data=request.query_params)
        qs.is_valid(raise_exception=True)

        league_id = qs.validated_data["league_id"]
        matchday_id = qs.validated_data["matchday_id"]

        home_ctx = build_lineup_context(league_id, matchday_id)
        away_ctx = build_lineup_context(league_id, f"{matchday_id}-opp")

        grid = home_ctx["zone_grid"]
        home_lineup = home_ctx["saved_lineup"]
        away_lineup = away_ctx["saved_lineup"]

        home_starters = set(home_lineup["starter_player_ids"])
        away_starters = set(away_lineup["starter_player_ids"])

        home_team = {
            "team_id": "T12",
            "name": "Casa FC",
            "colors": {"primary": "#0f172a", "secondary": "#38bdf8"},
            "players": [p for p in home_ctx["roster"] if p["player_id"] in home_starters],
        }
        away_team = {
            "team_id": "T55",
            "name": "Trasferta FC",
            "colors": {"primary": "#7c2d12", "secondary": "#fb7185"},
            "players": [p for p in away_ctx["roster"] if p["player_id"] in away_starters],
        }

        duel = compute_match_zone_duels(match_id, league_id, matchday_id, grid, home_team, away_team)

        payload = {
            "match": duel["match"],
            "teams": {
                "home": {
                    "team_id": home_team["team_id"],
                    "name": home_team["name"],
                    "colors": home_team["colors"],
                },
                "away": {
                    "team_id": away_team["team_id"],
                    "name": away_team["name"],
                    "colors": away_team["colors"],
                },
            },
            "zone_grid": grid,
            "score": duel["score"],
            "story": duel["story"],
            "zone_results": duel["zone_results"],
            "zone_maps": duel["zone_maps"],
            "line_summaries": duel["line_summaries"],
            "provenance": {
                "source": "vfoot-backend zone duel engine",
                "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "confidence": 0.72,
            },
        }

        return Response(payload)
