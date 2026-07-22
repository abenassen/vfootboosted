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
    GoogleAuthSerializer,
    LineupContextQuerySerializer,
    LoginSerializer,
    MatchesQuerySerializer,
    RegisterSerializer,
    ResendVerificationSerializer,
    SaveLineupRequestSerializer,
    UserSerializer,
    VerifyEmailSerializer,
)
from vfoot.services.auth_tokens import issue_token
from vfoot.services.email_verification import (
    activate,
    send_verification_email,
    user_from_uid,
)
from vfoot.services.google_auth import (
    GoogleAuthError,
    get_or_create_user,
    verify_id_token,
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

        # Inactive until the emailed link is opened, and NO token is returned:
        # handing out credentials here would make the confirmation decorative.
        user = User.objects.create_user(
            username=data["username"],
            email=data["email"],
            password=data["password"],
            is_active=False,
        )
        # Only send once the row is safely committed — otherwise a later failure
        # in this transaction would roll the user back after the mail had gone.
        transaction.on_commit(lambda: send_verification_email(user))

        return Response(
            {"detail": "Ti abbiamo inviato un'email di conferma. Apri il link "
                       "per attivare l'account.",
             "email": user.email},
            status=status.HTTP_201_CREATED,
        )


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = user_from_uid(data["uid"])
        if user is None:
            return Response({"detail": "Link di conferma non valido."},
                            status=status.HTTP_400_BAD_REQUEST)
        if user.is_active:
            # Re-opening the link (or a mail client prefetching it) must not read
            # as an error to someone whose account is already usable.
            return Response({"detail": "Account già attivo: puoi accedere.",
                             "already_active": True}, status=status.HTTP_200_OK)
        if not activate(user, data["token"]):
            return Response({"detail": "Link di conferma non valido o scaduto."},
                            status=status.HTTP_400_BAD_REQUEST)

        token = issue_token(user)
        return Response({"token": token.key, "user": UserSerializer(user).data},
                        status=status.HTTP_200_OK)


class ResendVerificationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()

        user = User.objects.filter(email__iexact=email, is_active=False).first()
        if user is not None:
            send_verification_email(user)
        # Always the same answer: differentiating would turn this endpoint into a
        # way to discover which addresses are registered.
        return Response({"detail": "Se l'indirizzo è registrato e in attesa di "
                                   "conferma, ti abbiamo inviato una nuova email."},
                        status=status.HTTP_200_OK)


class GoogleAuthView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            identity = verify_id_token(serializer.validated_data["credential"])
            user, created = get_or_create_user(identity)
        except GoogleAuthError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)

        token = issue_token(user)
        return Response({"token": token.key, "user": UserSerializer(user).data,
                         "created": created},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = authenticate(username=data["username"], password=data["password"])
        if not user:
            # authenticate() rejects inactive users too, so a correct password on
            # an unconfirmed account would otherwise read as "wrong password" and
            # send the user off resetting a password that was never the problem.
            pending = User.objects.filter(username__iexact=data["username"],
                                          is_active=False).first()
            if pending and pending.check_password(data["password"]):
                return Response(
                    {"detail": "Account non ancora confermato. Controlla la tua "
                               "email e apri il link di conferma.",
                     "email_unconfirmed": True},
                    status=status.HTTP_403_FORBIDDEN)
            return Response({"detail": "Username o password non corretti."}, status=status.HTTP_401_UNAUTHORIZED)

        token = issue_token(user)
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
