from __future__ import annotations

from datetime import datetime, timezone

from django.db import transaction
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from vfoot.api.data_builders import build_lineup_context
from vfoot.api.serializers import (
    GoogleAuthSerializer,
    LineupContextQuerySerializer,
    LoginSerializer,
    MatchesQuerySerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ProfileUpdateSerializer,
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
from vfoot.services.password_reset import (
    reset_password,
    send_password_reset_email,
    token_generator,
)
from vfoot.services.google_auth import (
    GoogleAuthError,
    get_or_create_user,
    verify_id_token,
)
from vfoot.models import SavedLineupSnapshot, UserProfile
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


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    # Anyone can make this endpoint send mail to an address they do not own, so it
    # is rate-limited by IP. Without it, one script turns our sender into a way to
    # flood someone's inbox — and burns the domain's reputation with it, which is
    # the part that would not come back.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()

        user = User.objects.filter(email__iexact=email).first()
        if user is not None:
            send_password_reset_email(user)
        # Same answer either way, as in ResendVerificationView: saying "unknown
        # address" would turn this into a way to discover who is registered.
        return Response({"detail": "Se l'indirizzo è registrato, ti abbiamo "
                                   "inviato un link per reimpostare la password."},
                        status=status.HTTP_200_OK)


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = user_from_uid(data["uid"])
        # One message for "no such uid" and for "bad token": they are the same
        # event to whoever is allowed to be here — a link that does not work — and
        # telling them apart would confirm that a user id exists.
        invalid = Response({"detail": "Link non valido o scaduto. Chiedine uno nuovo."},
                           status=status.HTTP_400_BAD_REQUEST)
        # Checked HERE and again inside reset_password(), on purpose. This one is
        # what stops a bad token from reaching the password rules at all — without
        # it, "questa password è troppo comune" would be an answer given to someone
        # holding no valid link, about an account they only guessed the id of. The
        # one in the service is what keeps the service safe to call on its own.
        # Nothing changes the user in between, so the two always agree.
        if user is None or not token_generator.check_token(user, data["token"]):
            return invalid

        # Now that the uid is resolved, the password can be judged against its own
        # user: "the same as your username" is only answerable here.
        try:
            validate_password(data["new_password"], user)
        except DjangoValidationError as exc:
            return Response({"new_password": list(exc.messages)},
                            status=status.HTTP_400_BAD_REQUEST)

        if not reset_password(user, data["token"], data["new_password"]):
            return invalid

        # Every existing token dies. A password reset is the one moment where we
        # must assume the old session belonged to someone else — leaving it alive
        # would let whoever prompted the reset keep the access it was meant to end.
        Token.objects.filter(user=user).delete()
        token = issue_token(user)
        return Response({"token": token.key, "user": UserSerializer(user).data},
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


def resolve_login_identifier(identifier: str) -> User | None:
    """L'account a cui si riferisce quello che e' stato scritto nel campo unico
    «Email o username».

    Entrambe le ricerche sono a meno del maiuscolo. Django confronta l'username
    carattere per carattere (``ModelBackend`` chiama ``get_by_natural_key``), e
    su un nome come «PeppAndre» quel confronto esatto vuol dire che una sola
    grafia su tutte funziona, mentre ogni altra restituisce lo stesso errore di
    una password sbagliata: chi non ricorda le maiuscole va a resettare una
    password che non era il problema. La ricerca insensibile e' del resto la
    convenzione gia' adottata ovunque nel progetto — unicita' in registrazione,
    cambio username, import delle rose, nomi squadra.

    **L'email ha la precedenza sull'username, di proposito.** I due spazi di
    nomi possono in teoria sovrapporsi (qualcuno che registra l'username
    "tizio@example.com"); quando succede, deve entrare chi possiede davvero
    quella casella. L'indirizzo e' verificato e non modificabile dall'utente,
    l'username e' auto-assegnato e si cambia dal profilo: fra i due, la
    precedenza va a quello di cui abbiamo una prova.

    Restituisce una sola riga per costruzione: gli indici unici funzionali su
    ``LOWER(username)`` e ``LOWER(email)`` (migrazione 0046) rendono impossibile
    che ``iexact`` ne trovi due.
    """
    identifier = identifier.strip()
    if not identifier:
        return None
    return (User.objects.filter(email__iexact=identifier).first()
            or User.objects.filter(username__iexact=identifier).first())


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # authenticate() riceve la grafia MEMORIZZATA, non quella digitata: il
        # confronto di Django resta esatto, e' la ricerca qui sopra a essere
        # tollerante.
        candidate = resolve_login_identifier(data["username"])
        if candidate is not None:
            user = authenticate(username=candidate.username, password=data["password"])
        else:
            # Nessun account: si calcola comunque un hash, come fa il ModelBackend
            # di Django. Senza, la risposta per un indirizzo sconosciuto tornerebbe
            # molto prima di quella per uno esistente, e la differenza di tempo
            # direbbe a un estraneo chi e' iscritto.
            User().set_password(data["password"])
            user = None
        if not user:
            # authenticate() rejects inactive users too, so a correct password on
            # an unconfirmed account would otherwise read as "wrong password" and
            # send the user off resetting a password that was never the problem.
            if (candidate is not None and not candidate.is_active
                    and candidate.check_password(data["password"])):
                return Response(
                    {"detail": "Account non ancora confermato. Controlla la tua "
                               "email e apri il link di conferma.",
                     "email_unconfirmed": True},
                    status=status.HTTP_403_FORBIDDEN)
            return Response({"detail": "Email, username o password non corretti."},
                            status=status.HTTP_401_UNAUTHORIZED)

        token = issue_token(user)
        return Response({"token": token.key, "user": UserSerializer(user).data}, status=status.HTTP_200_OK)


class MeView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"user": UserSerializer(request.user).data}, status=status.HTTP_200_OK)

    def patch(self, request):
        """Update the caller's own username and/or avatar."""
        serializer = ProfileUpdateSerializer(data=request.data, user=request.user)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with transaction.atomic():
            user = request.user
            if "username" in data:
                user.username = data["username"]
                user.save(update_fields=["username"])
            if "avatar" in data:
                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.avatar = data["avatar"]
                profile.save(update_fields=["avatar", "updated_at"])

        return Response({"user": UserSerializer(request.user).data}, status=status.HTTP_200_OK)


class PasswordChangeView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, user=request.user)
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        # The password change invalidates other sessions' assumptions; re-issue a
        # fresh token and hand it back so the caller stays logged in seamlessly.
        Token.objects.filter(user=user).delete()
        token = issue_token(user)
        return Response({"token": token.key, "user": UserSerializer(user).data},
                        status=status.HTTP_200_OK)


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
