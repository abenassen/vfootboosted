from __future__ import annotations

import csv
import io
from random import Random

from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from realdata.models import (
    CompetitionSeason,
    Match,
    MatchAppearance,
    Player,
    PlayerTeamStint,
)
from vfoot.api.league_serializers import (
    AddRosterPlayerSerializer,
    BulkAssignRosterSerializer,
    CompetitionStageBuildSerializer,
    CompetitionStageCreateSerializer,
    CompetitionStageUpdateSerializer,
    CompetitionStageRuleCreateSerializer,
    CompetitionScheduleSerializer,
    CompetitionSchedulePreviewSerializer,
    CompetitionPrizeCreateSerializer,
    CompetitionUpdateSerializer,
    CompetitionTemplateSerializer,
    CreateAuctionSerializer,
    CreateLeagueSerializer,
    ImportRosterCSVSerializer,
    JoinLeagueSerializer,
    MarketToggleSerializer,
    MatchdayConcludeSerializer,
    PlaceBidSerializer,
    QualificationRuleCreateSerializer,
    RemoveRosterPlayerSerializer,
    UpdateMemberRoleSerializer,
)
from vfoot.models import (
    AuctionBid,
    AuctionNomination,
    AuctionSession,
    CompetitionQualificationRule,
    CompetitionStage,
    CompetitionStageParticipant,
    CompetitionStageRule,
    CompetitionTeam,
    CompetitionPrize,
    FantasyCompetition,
    FantasyFixture,
    FantasyLeague,
    FantasyMatchday,
    FantasyRosterSlot,
    FantasyTeam,
    LeagueMembership,
    LeaguePlayerRole,
    SavedLineupSnapshot,
)
import os as _os
from functools import lru_cache as _lru_cache

from django.conf import settings as _settings

from vfoot.services.player_profiles import player_profiles
from vfoot.services.vector_zone_scoring import load_calibration
from vfoot.services.fantasy_simulation import (
    bulk_assign_players_to_teams,
    generate_knockout_fixtures,
    generate_round_robin_fixtures,
)
from vfoot.services.competition_stages import build_default_stage_graph, resolve_stage
from vfoot.services.formation_rules import CLASSIC_CONSTRAINTS, validate_classic_lineup
from vfoot.services.classic_pagella import get_reference, pagella_for_match
from vfoot.services.league_decisions import (
    accept_all_proposals, attention_count, cast_vote, market_blocked_reason,
    open_role_decisions, resolve as resolve_decision, unavailable_players,
    undecided_player_ids,
)
from vfoot.services.listone import snapshot_league_listone
from vfoot.services.listone import eligible_player_ids
from vfoot.services.player_ratings import (
    latest_market_values, player_values, previous_season_with_data,
)
from vfoot.services.match_resolver import matchday_fixtures_by_team

# Frozen listone role (POR/DIF/CEN/ATT) -> frontend lineup taxonomy (GK/DEF/MID/ATT).
_CLASSIC_ROLE_TO_LINEUP = {"POR": "GK", "DIF": "DEF", "CEN": "MID", "ATT": "ATT"}


def _membership_or_404(league: FantasyLeague, user_id: int) -> LeagueMembership:
    m = LeagueMembership.objects.filter(league=league, user_id=user_id).first()
    if not m:
        raise Http404("Not a member of this league")
    return m


def _ensure_admin(league: FantasyLeague, user_id: int) -> LeagueMembership:
    m = _membership_or_404(league, user_id)
    if m.role != LeagueMembership.ROLE_ADMIN:
        raise Http404("Admin privileges required")
    return m


class LeagueListCreateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        memberships = (LeagueMembership.objects.filter(user=request.user)
                       .select_related("league", "team",
                                       "league__reference_season__competition",
                                       "league__reference_season__season"))
        data = []
        for m in memberships:
            season = m.league.reference_season
            data.append(
                {
                    "league_id": m.league_id,
                    "name": m.league.name,
                    "role": m.role,
                    "invite_code": m.league.invite_code,
                    "market_open": m.league.market_open,
                    "team_name": m.team.name if hasattr(m, "team") else None,
                    "reference_season": (
                        {
                            "id": season.id,
                            "name": str(season),
                            "competition": season.competition.name,
                            "season": season.season.code,
                        }
                        if season else None
                    ),
                }
            )
        return Response(data)

    @transaction.atomic
    def post(self, request):
        s = CreateLeagueSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        reference_season = get_object_or_404(
            CompetitionSeason, id=data["reference_season_id"])
        league = FantasyLeague.objects.create(
            name=data["name"], owner=request.user, reference_season=reference_season)
        membership = LeagueMembership.objects.create(
            league=league,
            user=request.user,
            role=LeagueMembership.ROLE_ADMIN,
        )
        team = FantasyTeam.objects.create(league=league, manager=membership, name=data["team_name"])

        return Response(
            {
                "league_id": league.id,
                "name": league.name,
                "invite_code": league.invite_code,
                "invite_link": f"/join/{league.invite_code}",
                "team_id": team.id,
            },
            status=status.HTTP_201_CREATED,
        )


class LeagueJoinView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        s = JoinLeagueSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        league = get_object_or_404(FantasyLeague, invite_code=data["invite_code"])

        if LeagueMembership.objects.filter(league=league, user=request.user).exists():
            return Response({"detail": "Sei già iscritto a questa lega."}, status=status.HTTP_200_OK)

        membership = LeagueMembership.objects.create(
            league=league,
            user=request.user,
            role=LeagueMembership.ROLE_MANAGER,
        )
        team = FantasyTeam.objects.create(league=league, manager=membership, name=data["team_name"])

        return Response(
            {
                "league_id": league.id,
                "team_id": team.id,
                "name": league.name,
                "role": membership.role,
            },
            status=status.HTTP_201_CREATED,
        )


class LeagueDetailView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _membership_or_404(league, request.user.id)

        members = LeagueMembership.objects.filter(league=league).select_related("user")
        teams = FantasyTeam.objects.filter(league=league).select_related("manager__user")
        records = _league_wide_records(league)

        season = league.reference_season
        return Response(
            {
                "league_id": league.id,
                "name": league.name,
                "mode": league.mode,
                "market_open": league.market_open,
                "max_substitutions": league.max_substitutions,
                "defense_bonus_enabled": league.defense_bonus_enabled,
                "defense_bonus_mode": league.defense_bonus_mode,
                "invite_code": league.invite_code,
                "invite_link": f"/join/{league.invite_code}",
                "reference_season": (
                    {
                        "id": season.id,
                        "name": str(season),
                        "competition": season.competition.name,
                        "season": season.season.code,
                    }
                    if season
                    else None
                ),
                "members": [
                    {
                        "membership_id": m.id,
                        "user_id": m.user_id,
                        "username": m.user.username,
                        "role": m.role,
                    }
                    for m in members
                ],
                "teams": [
                    {
                        "team_id": t.id,
                        "name": t.name,
                        "manager_user_id": t.manager.user_id,
                        "manager_username": t.manager.user.username,
                        # Record aggregated across ALL competitions, not one chosen
                        # implicitly: a league has no single table, so points and
                        # rank would be a lie. Wins/draws/losses and goals for/against
                        # are the format-agnostic summary that always makes sense.
                        "record": records.get(t.id, {"played": 0, "wins": 0, "draws": 0,
                                                     "losses": 0, "goals_for": 0,
                                                     "goals_against": 0}),
                    }
                    for t in teams
                ],
            }
        )


def _league_wide_records(league) -> dict:
    """Per-team W/D/L and goals across EVERY competition in the league.

    A league is a set of competitions of possibly different shapes (championship,
    knockout), with no designated one — so a per-competition table read out of
    context (points, rank) misleads. This sums finished fixtures league-wide, and
    reports goals rather than points, which mean the same thing in every format.
    ``home_total``/``away_total`` on a fixture ARE the goals (the readable score);
    the fantasy vote total lives on the detail as ``vfoot_home``. So the goals are
    those fields directly — no threshold conversion, which would double-count."""
    rec: dict[int, dict] = {}

    def row(tid: int) -> dict:
        return rec.setdefault(tid, {"played": 0, "wins": 0, "draws": 0, "losses": 0,
                                    "goals_for": 0, "goals_against": 0})

    for fx in (FantasyFixture.objects
               .filter(competition__league=league, status=FantasyFixture.STATUS_FINISHED)
               .values_list("home_team_id", "away_team_id", "home_total", "away_total")):
        htid, atid, ht, at = fx
        hg, ag = int(round(ht)), int(round(at))
        h, a = row(htid), row(atid)
        h["played"] += 1; a["played"] += 1
        h["goals_for"] += hg; h["goals_against"] += ag
        a["goals_for"] += ag; a["goals_against"] += hg
        if ht > at:
            h["wins"] += 1; a["losses"] += 1
        elif ht < at:
            a["wins"] += 1; h["losses"] += 1
        else:
            h["draws"] += 1; a["draws"] += 1
    return rec


class MemberRoleUpdateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, league_id: int, membership_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)

        target = get_object_or_404(LeagueMembership, id=membership_id, league=league)
        s = UpdateMemberRoleSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        new_role = s.validated_data["role"]

        # Safety invariant: a league must always keep at least one admin.
        if target.role == LeagueMembership.ROLE_ADMIN and new_role != LeagueMembership.ROLE_ADMIN:
            admin_count = LeagueMembership.objects.filter(league=league, role=LeagueMembership.ROLE_ADMIN).count()
            if admin_count <= 1:
                return Response(
                    {"detail": "Non puoi rimuovere l'ultimo amministratore della lega."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        target.role = new_role
        target.save(update_fields=["role"])

        return Response({"membership_id": target.id, "role": target.role})


def _ensure_players_decided(league, player_ids):
    """Guard the money moments, PER PLAYER.

    A role settled after the bidding changes what people paid for, so a player
    whose role is still an open question cannot be auctioned or put on a roster.
    But only HE waits: freezing the whole market was tolerable for the opening
    listone and wrong for the rest of the season, where a single January signing
    would otherwise stop everyone else from trading.

    Names the players rather than only refusing — a gate that says "no" without
    saying who is a gate nobody can act on. Returns a 400 Response, or None.
    """
    blocked = unavailable_players(league, player_ids)
    if not blocked:
        return None
    names = ", ".join(b["name"] for b in blocked[:6])
    more = f" e altri {len(blocked) - 6}" if len(blocked) > 6 else ""
    return Response(
        {"detail": f"Ruolo ancora da decidere per {names}{more}: "
                   "non sono disponibili finche' l'amministratore non decide.",
         "code": "pending_decisions", "players": blocked},
        status=status.HTTP_400_BAD_REQUEST)


class MarketToggleView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)
        s = MarketToggleSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if s.validated_data["is_open"]:
            # Catch up with the real market first. Roles are frozen but the roster
            # is not, and a player who arrived after the listone was drawn has no
            # frozen role: seeding him here is what stops a January signing from
            # slipping past the gate and being priced before anyone has agreed
            # what he is. Additive — nothing already decided is touched.
            # Catch up with the real market. Roles are frozen but the roster is
            # not, and a player who arrived after the listone was drawn has no
            # frozen role. Opening the market is NOT refused for it: only the
            # players still in limbo are, one by one, where they are used.
            if league.mode == FantasyLeague.MODE_CLASSIC:
                snapshot_league_listone(league)
        league.market_open = s.validated_data["is_open"]
        league.save(update_fields=["market_open"])
        return Response({"league_id": league.id, "market_open": league.market_open})


class LeagueSettingsUpdateView(APIView):
    """Admin-editable league settings (currently the max number of bench
    substitutions applied at scoring time)."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)
        fields: list[str] = []

        if "max_substitutions" in request.data:
            try:
                value = int(request.data.get("max_substitutions"))
            except (TypeError, ValueError):
                return Response({"detail": "max_substitutions non valido."}, status=status.HTTP_400_BAD_REQUEST)
            if not (0 <= value <= 11):
                return Response({"detail": "max_substitutions deve essere tra 0 e 11."}, status=status.HTTP_400_BAD_REQUEST)
            league.max_substitutions = value
            fields.append("max_substitutions")

        if "defense_bonus_enabled" in request.data:
            league.defense_bonus_enabled = bool(request.data.get("defense_bonus_enabled"))
            fields.append("defense_bonus_enabled")

        if "defense_bonus_mode" in request.data:
            mode = request.data.get("defense_bonus_mode")
            valid = {c[0] for c in FantasyLeague.DEF_BONUS_MODE_CHOICES}
            if mode not in valid:
                return Response({"detail": f"defense_bonus_mode deve essere in {sorted(valid)}."},
                                status=status.HTTP_400_BAD_REQUEST)
            league.defense_bonus_mode = mode
            fields.append("defense_bonus_mode")

        if not fields:
            return Response({"detail": "Nessuna impostazione fornita."}, status=status.HTTP_400_BAD_REQUEST)
        league.save(update_fields=fields)
        return Response({
            "league_id": league.id,
            "max_substitutions": league.max_substitutions,
            "defense_bonus_enabled": league.defense_bonus_enabled,
            "defense_bonus_mode": league.defense_bonus_mode,
        })


class RealSeasonListView(APIView):
    """Real competition seasons available to use as a league's reference."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from realdata.models import CompetitionSeason

        seasons = (
            CompetitionSeason.objects.select_related("competition", "season")
            .annotate(
                _matchdays=Count(
                    "matches__matchday",
                    filter=Q(matches__matchday__isnull=False),
                    distinct=True,
                )
            )
            .order_by("-season__code", "competition__name")
        )
        return Response(
            [
                {
                    "id": cs.id,
                    "name": str(cs),
                    "competition": cs.competition.name,
                    "season": cs.season.code,
                    "matchdays": int(cs._matchdays or 0),
                }
                for cs in seasons
            ]
        )


class LeagueReferenceSeasonView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)
        season_id = request.data.get("reference_season_id")

        # IMMUTABLE once set: rosters, frozen listone and the calendar all hang off
        # the reference season, so changing it mid-life would invalidate them. Only
        # legacy leagues that never got one can still have it assigned here.
        if league.reference_season_id is not None:
            same = (season_id not in (None, "", 0)
                    and int(season_id) == league.reference_season_id)
            if not same:
                return Response(
                    {"detail": "La stagione di riferimento non è modificabile: "
                               "rose, listone e calendario dipendono da essa."},
                    status=status.HTTP_400_BAD_REQUEST)
        elif season_id in (None, "", 0):
            return Response({"detail": "Stagione di riferimento obbligatoria."},
                            status=status.HTTP_400_BAD_REQUEST)
        else:
            league.reference_season = get_object_or_404(CompetitionSeason, id=season_id)
            league.save(update_fields=["reference_season"])
        season = league.reference_season
        return Response(
            {
                "league_id": league.id,
                "reference_season": (
                    {
                        "id": season.id,
                        "name": str(season),
                        "competition": season.competition.name,
                        "season": season.season.code,
                    }
                    if season
                    else None
                ),
            }
        )


class TeamRosterView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, league_id: int, team_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _membership_or_404(league, request.user.id)

        team = get_object_or_404(FantasyTeam, id=team_id, league=league)
        slots = FantasyRosterSlot.objects.filter(team=team, released_at__isnull=True).select_related("player")

        return Response(
            {
                "team_id": team.id,
                "team_name": team.name,
                "players": [
                    {
                        "player_id": s.player_id,
                        "name": s.player.short_name or s.player.full_name,
                        "price": s.purchase_price,
                    }
                    for s in slots
                ],
            }
        )


class TeamRosterAddView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, league_id: int, team_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)
        if not league.market_open:
            return Response({"detail": "Market is closed."}, status=status.HTTP_400_BAD_REQUEST)
        team = get_object_or_404(FantasyTeam, id=team_id, league=league)
        s = AddRosterPlayerSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        blocked = _ensure_players_decided(league, [data["player_id"]])
        if blocked:
            return blocked

        player = get_object_or_404(Player, id=data["player_id"])

        already = FantasyRosterSlot.objects.filter(team__league=league, player=player, released_at__isnull=True).first()
        if already:
            return Response({"detail": "Player already assigned in this league."}, status=status.HTTP_400_BAD_REQUEST)

        slot = FantasyRosterSlot.objects.create(team=team, player=player, purchase_price=data["purchase_price"])
        return Response({"slot_id": slot.id, "player_id": player.id}, status=status.HTTP_201_CREATED)


class TeamRosterRemoveView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, league_id: int, team_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)
        if not league.market_open:
            return Response({"detail": "Market is closed."}, status=status.HTTP_400_BAD_REQUEST)
        # No role gate here: releasing a player never depends on his role. Nor
        # should the case arise — anyone on a roster was bought, so he had a role
        # at the time, and a role settled in a league never becomes an open
        # question again (see open_role_decisions).
        team = get_object_or_404(FantasyTeam, id=team_id, league=league)
        s = RemoveRosterPlayerSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        player_id = s.validated_data["player_id"]

        slot = FantasyRosterSlot.objects.filter(team=team, player_id=player_id, released_at__isnull=True).first()
        if not slot:
            return Response({"detail": "Player not in active roster."}, status=status.HTTP_404_NOT_FOUND)

        slot.released_at = timezone.now()
        slot.save(update_fields=["released_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class LeagueRosterBulkAssignView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)
        if not league.market_open:
            return Response({"detail": "Market is closed."}, status=status.HTTP_400_BAD_REQUEST)

        s = BulkAssignRosterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        assignments = data.get("assignments")
        if assignments:
            # Same per-player gate as a single add: a bulk import must not be a
            # side door around a role nobody has agreed on yet.
            blocked = _ensure_players_decided(
                league, [r.get("player_id") for r in assignments if r.get("player_id")])
            if blocked:
                return blocked
            teams_by_id = {t.id: t for t in FantasyTeam.objects.filter(league=league).select_related("manager__user")}
            teams_by_name = {t.name.lower(): t for t in teams_by_id.values()}
            teams_by_manager = {t.manager.user.username.lower(): t for t in teams_by_id.values()}

            created = 0
            for row in assignments:
                target_team = None
                if "team_id" in row and str(row["team_id"]).isdigit():
                    target_team = teams_by_id.get(int(row["team_id"]))
                if not target_team and row.get("team_name"):
                    target_team = teams_by_name.get(str(row["team_name"]).strip().lower())
                if not target_team and row.get("manager_username"):
                    target_team = teams_by_manager.get(str(row["manager_username"]).strip().lower())
                if not target_team:
                    continue

                try:
                    player_id = int(row.get("player_id"))
                except (TypeError, ValueError):
                    continue
                player = Player.objects.filter(id=player_id).first()
                if not player:
                    continue

                if FantasyRosterSlot.objects.filter(team__league=league, player=player, released_at__isnull=True).exists():
                    continue

                price_raw = row.get("purchase_price", row.get("price", data.get("purchase_price", 1)))
                try:
                    price = max(1, int(price_raw))
                except (TypeError, ValueError):
                    price = 1

                FantasyRosterSlot.objects.create(team=target_team, player=player, purchase_price=price)
                created += 1

            return Response({"assigned_players": created, "mode": "explicit"})

        if not data.get("player_ids"):
            return Response(
                {
                    "detail": "Provide deterministic assignments using team_name or manager_username. "
                    "Random distribution is available only via player_ids fallback."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        count = bulk_assign_players_to_teams(
            league_id=league.id,
            player_ids=data["player_ids"],
            purchase_price=data.get("purchase_price", 1),
            random_seed=data.get("random_seed", 42),
        )
        return Response({"assigned_players": count, "mode": "random"})


class LeagueRosterImportCSVView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)

        s = ImportRosterCSVSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        csv_text = s.validated_data.get("csv_text", "")
        if not csv_text and "file" in request.FILES:
            csv_text = request.FILES["file"].read().decode("utf-8")
        if not csv_text.strip():
            return Response({"detail": "No CSV content provided."}, status=status.HTTP_400_BAD_REQUEST)

        reader = csv.DictReader(io.StringIO(csv_text))
        headers = set(reader.fieldnames or [])
        if "player_id" not in headers:
            return Response({"detail": "CSV headers must include player_id."}, status=status.HTTP_400_BAD_REQUEST)
        if "team_name" not in headers and "manager_username" not in headers:
            return Response(
                {"detail": "CSV headers must include team_name or manager_username (plus player_id, optional price)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        teams = {t.name: t for t in FantasyTeam.objects.filter(league=league)}
        teams_by_manager = {
            t.manager.user.username: t
            for t in FantasyTeam.objects.filter(league=league).select_related("manager__user")
        }
        created = 0
        for row in reader:
            team = teams.get((row.get("team_name") or "").strip())
            if not team:
                team = teams_by_manager.get((row.get("manager_username") or "").strip())
            if not team:
                continue
            try:
                player_id = int(row.get("player_id", "0"))
                price = int((row.get("price") or row.get("purchase_price") or "1"))
            except ValueError:
                continue

            player = Player.objects.filter(id=player_id).first()
            if not player:
                continue

            if FantasyRosterSlot.objects.filter(team__league=league, player=player, released_at__isnull=True).exists():
                continue

            FantasyRosterSlot.objects.create(team=team, player=player, purchase_price=max(1, price))
            created += 1

        return Response({"imported": created})


class PlayerSearchView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        if len(query) < 2:
            return Response([])

        try:
            limit = max(1, min(50, int(request.query_params.get("limit", "20"))))
        except ValueError:
            limit = 20

        league_id = request.query_params.get("league_id")
        assigned_in_league = []
        if league_id and str(league_id).isdigit():
            assigned_in_league = FantasyRosterSlot.objects.filter(
                team__league_id=int(league_id),
                released_at__isnull=True,
            ).values_list("player_id", flat=True)

        players = (
            Player.objects.filter(
                Q(full_name__icontains=query) | Q(short_name__icontains=query)
            )
            .exclude(id__in=assigned_in_league)
            .order_by("short_name", "full_name")[:limit]
        )

        return Response(
            [
                {
                    "player_id": p.id,
                    "name": p.short_name or p.full_name,
                    "full_name": p.full_name,
                }
                for p in players
            ]
        )


class CompetitionTemplateCreateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)

        s = CompetitionTemplateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        if FantasyCompetition.objects.filter(league=league, name=data["name"]).exists():
            return Response(
                {"detail": "A competition with this name already exists in this league."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        comp = FantasyCompetition.objects.create(
            league=league,
            name=data["name"],
            competition_type=data["competition_type"],
            status=FantasyCompetition.STATUS_DRAFT if data.get("container_only", False) else FantasyCompetition.STATUS_ACTIVE,
            starts_at=data.get("starts_at"),
            ends_at=data.get("ends_at"),
        )

        fixtures = 0
        team_ids = []
        if not data.get("container_only", False):
            team_ids = data.get("team_ids")
            if team_ids is None:
                team_ids = list(FantasyTeam.objects.filter(league=league).values_list("id", flat=True))
            entries = [CompetitionTeam(competition=comp, team_id=tid) for tid in team_ids]
            CompetitionTeam.objects.bulk_create(entries)

            if comp.competition_type == FantasyCompetition.TYPE_ROUND_ROBIN:
                fixtures = generate_round_robin_fixtures(comp)
            else:
                fixtures = generate_knockout_fixtures(comp)
        else:
            team_ids = []

        return Response(
            {
                "competition_id": comp.id,
                "name": comp.name,
                "competition_type": comp.competition_type,
                "status": comp.status,
                "starts_at": comp.starts_at.isoformat() if comp.starts_at else None,
                "ends_at": comp.ends_at.isoformat() if comp.ends_at else None,
                "participants": len(team_ids),
                "fixtures_created": fixtures,
                "container_only": bool(data.get("container_only", False)),
            },
            status=status.HTTP_201_CREATED,
        )


def _result_view(comp: FantasyCompetition) -> str:
    """Which results view a competition needs: a round-robin → 'classifica' (table),
    a knockout → 'tabellone' (bracket), a mix of stages → 'risultati' (both)."""
    types = set(comp.stages.values_list("stage_type", flat=True))
    if not types:
        return "tabellone" if comp.competition_type == FantasyCompetition.TYPE_KNOCKOUT else "classifica"
    if len(types) == 1:
        return "tabellone" if next(iter(types)) == CompetitionStage.TYPE_KNOCKOUT else "classifica"
    return "risultati"


def _serialize_competition(comp: FantasyCompetition) -> dict:
    participants = list(comp.participants.select_related("team", "team__manager__user"))
    rules = list(comp.qualification_rules.select_related("source_competition"))
    prizes = list(comp.prizes.select_related("source_stage"))
    fixture_count = comp.fixtures.count()
    finished_count = comp.fixtures.filter(status=FantasyFixture.STATUS_FINISHED).count()
    return {
        "competition_id": comp.id,
        "name": comp.name,
        "competition_type": comp.competition_type,
        "result_view": _result_view(comp),
        "status": comp.status,
        "points": {
            "win": comp.points_win,
            "draw": comp.points_draw,
            "loss": comp.points_loss,
        },
        "starts_at": comp.starts_at.isoformat() if comp.starts_at else None,
        "ends_at": comp.ends_at.isoformat() if comp.ends_at else None,
        "start_matchday": comp.start_matchday,
        "end_matchday": comp.end_matchday,
        "participants": [
            {
                "team_id": p.team_id,
                "team_name": p.team.name,
                "source": p.source,
                "manager_username": p.team.manager.user.username,
                "seed": p.seed,
            }
            for p in participants
        ],
        "qualification_rules": [
            {
                "rule_id": r.id,
                "source_competition_id": r.source_competition_id,
                "source_competition_name": r.source_competition.name,
                "source_stage": r.source_stage,
                "source_round": r.source_round,
                "mode": r.mode,
                "rank_from": r.rank_from,
                "rank_to": r.rank_to,
            }
            for r in rules
        ],
        "prizes": [
            {
                "prize_id": p.id,
                "name": p.name,
                "condition_type": p.condition_type,
                "source_stage_id": p.source_stage_id,
                "source_stage_name": p.source_stage.name if p.source_stage_id else None,
                "rank_from": p.rank_from,
                "rank_to": p.rank_to,
            }
            for p in prizes
        ],
        "fixtures": {"total": fixture_count, "finished": finished_count},
    }


def _serialize_stage(stage: CompetitionStage) -> dict:
    participants = list(stage.participants.select_related("team", "team__manager__user"))
    rules = list(stage.rules_in.select_related("source_stage", "source_stage__competition"))
    fixtures_total = stage.fixtures.count()
    fixtures_finished = stage.fixtures.filter(status=FantasyFixture.STATUS_FINISHED).count()
    return {
        "stage_id": stage.id,
        "competition_id": stage.competition_id,
        "name": stage.name,
        "stage_type": stage.stage_type,
        "status": stage.status,
        "order_index": stage.order_index,
        "double_round": stage.double_round,
        "participants": [
            {
                "team_id": p.team_id,
                "team_name": p.team.name,
                "source": p.source,
                "manager_username": p.team.manager.user.username,
                "seed": p.seed,
            }
            for p in participants
        ],
        "rules_in": [
            {
                "rule_id": r.id,
                "source_stage_id": r.source_stage_id,
                "source_stage_name": r.source_stage.name,
                "source_competition_id": r.source_stage.competition_id,
                "source_competition_name": r.source_stage.competition.name,
                "mode": r.mode,
                "rank_from": r.rank_from,
                "rank_to": r.rank_to,
            }
            for r in rules
        ],
        "fixtures": {"total": fixtures_total, "finished": fixtures_finished},
    }


class CompetitionStageListView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, competition_id: int):
        comp = get_object_or_404(FantasyCompetition, id=competition_id)
        _membership_or_404(comp.league, request.user.id)
        stages = (
            CompetitionStage.objects.filter(competition=comp)
            .prefetch_related("participants__team__manager__user", "rules_in__source_stage__competition", "fixtures")
            .order_by("order_index", "id")
        )
        return Response([_serialize_stage(s) for s in stages])


class CompetitionStageBuildDefaultView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, competition_id: int):
        comp = get_object_or_404(FantasyCompetition, id=competition_id)
        _ensure_admin(comp.league, request.user.id)
        s = CompetitionStageBuildSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        result = build_default_stage_graph(
            comp,
            allow_repechage=data.get("allow_repechage", False),
            seed=data.get("random_seed", 42),
            double_round=data.get("double_round", False),
        )
        return Response(result, status=status.HTTP_201_CREATED)


class CompetitionStageCreateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, competition_id: int):
        comp = get_object_or_404(FantasyCompetition, id=competition_id)
        _ensure_admin(comp.league, request.user.id)
        s = CompetitionStageCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        stage = CompetitionStage.objects.create(
            competition=comp,
            name=data["name"],
            stage_type=data["stage_type"],
            order_index=data.get("order_index", 1),
            double_round=data.get("double_round", False),
        )
        team_ids = data.get("team_ids") or []
        valid_team_ids = list(FantasyTeam.objects.filter(league=comp.league, id__in=team_ids).values_list("id", flat=True))
        CompetitionStageParticipant.objects.bulk_create(
            [
                CompetitionStageParticipant(stage=stage, team_id=tid, source=CompetitionStageParticipant.SOURCE_MANUAL)
                for tid in valid_team_ids
            ]
        )

        seed_raw = request.data.get("random_seed", 42)
        try:
            seed = int(seed_raw)
        except (TypeError, ValueError):
            seed = 42
        resolve_stage(stage, seed=seed)
        return Response(_serialize_stage(stage), status=status.HTTP_201_CREATED)


class CompetitionStageDetailUpdateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, stage_id: int):
        stage = get_object_or_404(CompetitionStage, id=stage_id)
        _ensure_admin(stage.competition.league, request.user.id)
        s = CompetitionStageUpdateSerializer(data=request.data or {})
        s.is_valid(raise_exception=True)
        data = s.validated_data

        changed_fields: list[str] = []
        for field in ["name", "stage_type", "order_index", "double_round"]:
            if field in data:
                setattr(stage, field, data[field])
                changed_fields.append(field)
        if changed_fields:
            stage.save(update_fields=changed_fields)
        # Re-generate fixtures if the leg setting changed and the stage already
        # has its participants resolved (so toggling andata/ritorno takes effect).
        if "double_round" in data and "team_ids" not in data:
            resolve_stage(stage, seed=int(data.get("random_seed", 42)))

        if "team_ids" in data:
            team_ids = data.get("team_ids") or []
            valid_team_ids = list(
                FantasyTeam.objects.filter(league=stage.competition.league, id__in=team_ids).values_list("id", flat=True)
            )
            CompetitionStageParticipant.objects.filter(
                stage=stage,
                source=CompetitionStageParticipant.SOURCE_MANUAL,
            ).exclude(team_id__in=valid_team_ids).delete()

            existing_manual = set(
                CompetitionStageParticipant.objects.filter(
                    stage=stage,
                    source=CompetitionStageParticipant.SOURCE_MANUAL,
                ).values_list("team_id", flat=True)
            )
            CompetitionStageParticipant.objects.bulk_create(
                [
                    CompetitionStageParticipant(
                        stage=stage,
                        team_id=tid,
                        source=CompetitionStageParticipant.SOURCE_MANUAL,
                    )
                    for tid in valid_team_ids
                    if tid not in existing_manual
                ]
            )

            seed = int(data.get("random_seed", 42))
            resolve_stage(stage, seed=seed)

        return Response(_serialize_stage(stage))

    @transaction.atomic
    def delete(self, request, stage_id: int):
        stage = get_object_or_404(CompetitionStage, id=stage_id)
        _ensure_admin(stage.competition.league, request.user.id)

        dependent_rules = list(
            CompetitionStageRule.objects.filter(source_stage=stage)
            .select_related("target_stage", "target_stage__competition")
            .order_by("target_stage__competition_id", "target_stage__order_index", "target_stage_id")
        )
        if dependent_rules:
            return Response(
                {
                    "detail": "Cannot delete stage: it is used to derive participants for other stages.",
                    "dependent_targets": [
                        {
                            "target_stage_id": r.target_stage_id,
                            "target_stage_name": r.target_stage.name,
                            "target_competition_id": r.target_stage.competition_id,
                            "target_competition_name": r.target_stage.competition.name,
                            "mode": r.mode,
                            "rank_from": r.rank_from,
                            "rank_to": r.rank_to,
                        }
                        for r in dependent_rules
                    ],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        external_prizes = list(
            CompetitionPrize.objects.filter(source_stage=stage)
            .exclude(competition=stage.competition)
            .select_related("competition")
        )
        if external_prizes:
            return Response(
                {
                    "detail": "Cannot delete stage: it is referenced by prizes in other competitions.",
                    "dependent_prizes": [
                        {
                            "prize_id": p.id,
                            "prize_name": p.name,
                            "competition_id": p.competition_id,
                            "competition_name": p.competition.name,
                        }
                        for p in external_prizes
                    ],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        stage.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CompetitionStageAddRuleView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, stage_id: int):
        stage = get_object_or_404(CompetitionStage, id=stage_id)
        _ensure_admin(stage.competition.league, request.user.id)
        s = CompetitionStageRuleCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        source_stage = get_object_or_404(CompetitionStage, id=data["source_stage_id"])
        if source_stage.competition.league_id != stage.competition.league_id:
            return Response({"detail": "Source and target stages must belong to the same league."}, status=status.HTTP_400_BAD_REQUEST)

        rule = CompetitionStageRule.objects.create(
            target_stage=stage,
            source_stage=source_stage,
            mode=data["mode"],
            rank_from=data.get("rank_from"),
            rank_to=data.get("rank_to"),
        )
        result = resolve_stage(stage, seed=data.get("random_seed", 42))
        return Response(
            {
                "rule_id": rule.id,
                "target_stage_id": stage.id,
                "source_stage_id": source_stage.id,
                "mode": rule.mode,
                "rank_from": rule.rank_from,
                "rank_to": rule.rank_to,
                "resolve": result,
            },
            status=status.HTTP_201_CREATED,
        )


class CompetitionStageResolveView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, stage_id: int):
        stage = get_object_or_404(CompetitionStage, id=stage_id)
        _ensure_admin(stage.competition.league, request.user.id)
        seed_raw = request.data.get("random_seed", 42)
        try:
            seed = int(seed_raw)
        except (TypeError, ValueError):
            seed = 42
        result = resolve_stage(stage, seed=seed)
        return Response(result)


def _serialize_prize(prize: CompetitionPrize) -> dict:
    return {
        "prize_id": prize.id,
        "name": prize.name,
        "condition_type": prize.condition_type,
        "source_stage_id": prize.source_stage_id,
        "source_stage_name": prize.source_stage.name if prize.source_stage_id else None,
        "rank_from": prize.rank_from,
        "rank_to": prize.rank_to,
    }


class CompetitionPrizeListCreateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, competition_id: int):
        comp = get_object_or_404(FantasyCompetition, id=competition_id)
        _membership_or_404(comp.league, request.user.id)
        prizes = CompetitionPrize.objects.filter(competition=comp).select_related("source_stage")
        return Response([_serialize_prize(p) for p in prizes])

    @transaction.atomic
    def post(self, request, competition_id: int):
        comp = get_object_or_404(FantasyCompetition, id=competition_id)
        _ensure_admin(comp.league, request.user.id)
        s = CompetitionPrizeCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        cond = data["condition_type"]
        source_stage_id = data.get("source_stage_id")
        rank_from = data.get("rank_from")
        rank_to = data.get("rank_to")

        source_stage = None
        if cond in [CompetitionPrize.CONDITION_STAGE_TABLE_RANGE, CompetitionPrize.CONDITION_STAGE_WINNER, CompetitionPrize.CONDITION_STAGE_LOSER]:
            if not source_stage_id:
                return Response({"detail": "source_stage_id is required for stage-based prize conditions."}, status=status.HTTP_400_BAD_REQUEST)
            source_stage = get_object_or_404(CompetitionStage, id=source_stage_id, competition=comp)

        if cond in [CompetitionPrize.CONDITION_FINAL_TABLE_RANGE, CompetitionPrize.CONDITION_STAGE_TABLE_RANGE]:
            if rank_from is None:
                return Response({"detail": "rank_from is required for table range conditions."}, status=status.HTTP_400_BAD_REQUEST)
            if rank_to is None:
                rank_to = rank_from
            if rank_from <= 0 or rank_to <= 0 or rank_to < rank_from:
                return Response({"detail": "Invalid rank range."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            rank_from = None
            rank_to = None

        prize = CompetitionPrize.objects.create(
            competition=comp,
            name=data["name"],
            condition_type=cond,
            source_stage=source_stage,
            rank_from=rank_from,
            rank_to=rank_to,
        )
        return Response(_serialize_prize(prize), status=status.HTTP_201_CREATED)


class CompetitionPrizeDeleteView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def delete(self, request, prize_id: int):
        prize = get_object_or_404(CompetitionPrize, id=prize_id)
        _ensure_admin(prize.competition.league, request.user.id)
        prize.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _source_fixtures_for_stage(source_comp: FantasyCompetition, stage: str, source_round: int | None = None):
    qs = FantasyFixture.objects.filter(competition=source_comp, status=FantasyFixture.STATUS_FINISHED)
    if source_round is not None:
        # Explicit round cut-off: snapshot the table after this round.
        qs = qs.filter(round_no__lte=max(1, source_round))
    elif stage == CompetitionQualificationRule.STAGE_HALF:
        max_round = FantasyFixture.objects.filter(competition=source_comp).order_by("-round_no").values_list("round_no", flat=True).first()
        if max_round:
            qs = qs.filter(round_no__lte=max(1, max_round // 2))
    return qs


def _table_ranking_team_ids(source_comp: FantasyCompetition, stage: str, source_round: int | None = None) -> list[int]:
    rows: dict[int, dict] = {}
    fixtures = _source_fixtures_for_stage(source_comp, stage, source_round)
    for fx in fixtures:
        for tid in [fx.home_team_id, fx.away_team_id]:
            rows.setdefault(tid, {"pts": 0, "gf": 0.0, "ga": 0.0})
        ht, at = fx.home_team_id, fx.away_team_id
        hs, as_ = fx.home_total, fx.away_total
        rows[ht]["gf"] += hs
        rows[ht]["ga"] += as_
        rows[at]["gf"] += as_
        rows[at]["ga"] += hs
        if hs > as_:
            rows[ht]["pts"] += source_comp.points_win
            rows[at]["pts"] += source_comp.points_loss
        elif hs < as_:
            rows[at]["pts"] += source_comp.points_win
            rows[ht]["pts"] += source_comp.points_loss
        else:
            rows[ht]["pts"] += source_comp.points_draw
            rows[at]["pts"] += source_comp.points_draw

    ranking = sorted(rows.items(), key=lambda kv: (kv[1]["pts"], kv[1]["gf"] - kv[1]["ga"], kv[1]["gf"]), reverse=True)
    return [tid for tid, _ in ranking]


def _winner_loser_from_source(source_comp: FantasyCompetition, stage: str, mode: str, source_round: int | None = None) -> list[int]:
    ranking = _table_ranking_team_ids(source_comp, stage, source_round)
    if not ranking:
        return []
    if mode == CompetitionQualificationRule.MODE_WINNER:
        return [ranking[0]]
    if mode == CompetitionQualificationRule.MODE_LOSER:
        return [ranking[-1]]
    return []


@transaction.atomic
def _resolve_rule_participants_and_regenerate(competition: FantasyCompetition) -> dict:
    manual_ids = set(
        CompetitionTeam.objects.filter(competition=competition, source=CompetitionTeam.SOURCE_MANUAL).values_list("team_id", flat=True)
    )
    CompetitionTeam.objects.filter(competition=competition, source=CompetitionTeam.SOURCE_RULE).delete()

    resolved_ids: set[int] = set()
    unresolved_rules = 0
    for rule in CompetitionQualificationRule.objects.filter(competition=competition).select_related("source_competition"):
        source = rule.source_competition
        if rule.mode == CompetitionQualificationRule.MODE_TABLE_RANGE:
            ranking = _table_ranking_team_ids(source, rule.source_stage, rule.source_round)
            if not ranking:
                unresolved_rules += 1
                continue
            rf = max(1, rule.rank_from or 1)
            rt = max(rf, rule.rank_to or rf)
            ids = ranking[rf - 1 : rt]
        else:
            ids = _winner_loser_from_source(source, rule.source_stage, rule.mode, rule.source_round)
            if not ids:
                unresolved_rules += 1
                continue
        for tid in ids:
            if tid not in manual_ids and tid not in resolved_ids:
                resolved_ids.add(tid)
                CompetitionTeam.objects.create(competition=competition, team_id=tid, source=CompetitionTeam.SOURCE_RULE)

    participants = list(CompetitionTeam.objects.filter(competition=competition).values_list("team_id", flat=True))
    fixtures_created = 0
    if len(participants) >= 2:
        # Build the full stage graph (bracket + progression rules for knockout,
        # regular-season stage for round-robin) rather than flat single-round
        # fixtures — so a rule-fed competition (e.g. cup fed by championship
        # top-N) gets a proper structure once its participants resolve.
        result = build_default_stage_graph(competition)
        fixtures_created = result.get("fixtures_created", 0)

    return {
        "competition_id": competition.id,
        "resolved_rule_participants": len(resolved_ids),
        "unresolved_rules": unresolved_rules,
        "fixtures_created": fixtures_created,
    }


class CompetitionListView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _membership_or_404(league, request.user.id)
        comps = (
            FantasyCompetition.objects.filter(league=league)
            .prefetch_related(
                "participants__team__manager__user",
                "qualification_rules__source_competition",
                "prizes__source_stage",
                "fixtures",
            )
            .order_by("id")
        )
        return Response([_serialize_competition(c) for c in comps])


def _current_matchday(league: FantasyLeague):
    """The league's 'current' matchday = the earliest one not yet concluded."""
    return (
        FantasyMatchday.objects.filter(league=league)
        .exclude(status=FantasyMatchday.STATUS_CONCLUDED)
        .order_by("real_matchday", "id")
        .first()
    )


def _fixture_phase(fx: FantasyFixture, current_real_md: int | None) -> str:
    """concluded | current | future | unscheduled — drives the UI badge."""
    if fx.status == FantasyFixture.STATUS_FINISHED:
        return "concluded"
    if fx.fantasy_matchday_id is None:
        return "unscheduled"
    real_md = fx.fantasy_matchday.real_matchday
    if current_real_md is None:
        return "future"
    if real_md == current_real_md:
        return "current"
    if real_md < current_real_md:
        return "concluded"
    return "future"


def _serialize_fixture_row(fx: FantasyFixture, my_team_id: int | None, current_real_md: int | None = None) -> dict:
    return {
        "fixture_id": fx.id,
        "competition_id": fx.competition_id,
        "competition_name": fx.competition.name,
        "stage_id": fx.stage_id,
        "stage_name": fx.stage.name if fx.stage_id else None,
        "round_label": fx.stage.name if fx.stage_id else f"Round {fx.round_no}",
        "fantasy_matchday_id": fx.fantasy_matchday_id,
        "real_matchday": fx.fantasy_matchday.real_matchday if fx.fantasy_matchday_id else None,
        "round_no": fx.round_no,
        "leg_no": fx.leg_no,
        "kickoff": fx.kickoff.isoformat() if fx.kickoff else None,
        "status": fx.status,
        "phase": _fixture_phase(fx, current_real_md),
        "home_team": {"team_id": fx.home_team_id, "name": fx.home_team.name},
        "away_team": {"team_id": fx.away_team_id, "name": fx.away_team.name},
        "score": {"home_total": fx.home_total, "away_total": fx.away_total} if fx.status == FantasyFixture.STATUS_FINISHED else None,
        "is_user_involved": bool(my_team_id and (fx.home_team_id == my_team_id or fx.away_team_id == my_team_id)),
    }


class LeagueFixturesView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        membership = _membership_or_404(league, request.user.id)
        my_team_id = membership.team.id if hasattr(membership, "team") else None

        qs = (
            FantasyFixture.objects.filter(competition__league=league)
            .select_related("competition", "stage", "fantasy_matchday", "home_team", "away_team")
            .order_by("-kickoff", "-id")
        )
        competition_id = request.query_params.get("competition_id")
        if competition_id and str(competition_id).isdigit():
            qs = qs.filter(competition_id=int(competition_id))

        current = _current_matchday(league)
        current_real_md = current.real_matchday if current else None
        items = [_serialize_fixture_row(fx, my_team_id, current_real_md) for fx in qs[:200]]
        return Response(items)


def _competition_round_nos(comp: FantasyCompetition) -> list[int]:
    return sorted(set(FantasyFixture.objects.filter(competition=comp).values_list("round_no", flat=True)))


def _pick_real_competition_and_matchdays(starts_at, ends_at):
    if not starts_at or not ends_at:
        return None, []

    base = Match.objects.filter(
        kickoff__date__gte=starts_at,
        kickoff__date__lte=ends_at,
        matchday__isnull=False,
    )
    if not base.exists():
        return None, []

    top = (
        base.values("competition_season_id")
        .annotate(c=Count("id"))
        .order_by("-c", "competition_season_id")
        .first()
    )
    if not top:
        return None, []
    csid = int(top["competition_season_id"])
    matchdays = list(
        base.filter(competition_season_id=csid)
        .order_by("matchday")
        .values_list("matchday", flat=True)
        .distinct()
    )
    return csid, [int(x) for x in matchdays if x is not None]


def _reference_matchdays(comp: FantasyCompetition, start_md=None, end_md=None):
    """Real matchdays available for this competition, taken from the league's
    reference season within the [start, end] matchday span. Falls back to the
    legacy date-window inference when the league has no reference season set."""
    season = comp.league.reference_season
    if season is None:
        return _pick_real_competition_and_matchdays(comp.starts_at, comp.ends_at)
    csid = season.id
    lo = start_md if start_md is not None else comp.start_matchday
    hi = end_md if end_md is not None else comp.end_matchday
    qs = Match.objects.filter(competition_season_id=csid, matchday__isnull=False)
    if lo is not None:
        qs = qs.filter(matchday__gte=lo)
    if hi is not None:
        qs = qs.filter(matchday__lte=hi)
    matchdays = list(qs.order_by("matchday").values_list("matchday", flat=True).distinct())
    return csid, [int(x) for x in matchdays if x is not None]


def _current_round_mapping(comp: FantasyCompetition) -> dict[int, int]:
    rows = (
        FantasyFixture.objects.filter(competition=comp, fantasy_matchday__isnull=False)
        .select_related("fantasy_matchday")
        .values_list("round_no", "fantasy_matchday__real_matchday")
        .distinct()
    )
    mapping: dict[int, int] = {}
    for rno, real_md in rows:
        if rno is None or real_md is None:
            continue
        mapping[int(rno)] = int(real_md)
    return mapping


def _build_uniform_round_mapping(round_nos: list[int], real_matchdays: list[int]) -> dict[int, int]:
    mapping: dict[int, int] = {}
    if not round_nos or not real_matchdays:
        return mapping
    if len(round_nos) == 1:
        mapping[round_nos[0]] = real_matchdays[0]
        return mapping
    rm = len(real_matchdays)
    rr = len(round_nos)
    for idx, rno in enumerate(round_nos):
        ridx = int(round((idx * (rm - 1)) / max(1, rr - 1)))
        mapping[rno] = real_matchdays[min(max(ridx, 0), rm - 1)]
    return mapping


def _schedule_preview(comp: FantasyCompetition, start_md=None, end_md=None) -> dict:
    round_nos = _competition_round_nos(comp)
    csid, real_matchdays = _reference_matchdays(comp, start_md, end_md)
    uniform = _build_uniform_round_mapping(round_nos, real_matchdays)
    current = _current_round_mapping(comp)
    return {
        "competition_id": comp.id,
        "competition_name": comp.name,
        "starts_at": comp.starts_at.isoformat() if comp.starts_at else None,
        "ends_at": comp.ends_at.isoformat() if comp.ends_at else None,
        "start_matchday": start_md if start_md is not None else comp.start_matchday,
        "end_matchday": end_md if end_md is not None else comp.end_matchday,
        "rounds": round_nos,
        "available_real_matchdays": real_matchdays,
        "real_competition_season_id": csid,
        "proposed_mapping": uniform,
        "current_mapping": current,
    }


@transaction.atomic
def _schedule_competition_rounds(
    comp: FantasyCompetition,
    round_mapping: dict[int, int] | None = None,
    start_md=None,
    end_md=None,
) -> dict:
    round_nos = _competition_round_nos(comp)
    if not round_nos:
        return {"competition_id": comp.id, "scheduled_fixtures": 0, "rounds": 0, "real_matchdays": []}

    # Persist the span so later reschedules/previews are consistent.
    span_fields = []
    if start_md is not None and start_md != comp.start_matchday:
        comp.start_matchday = start_md
        span_fields.append("start_matchday")
    if end_md is not None and end_md != comp.end_matchday:
        comp.end_matchday = end_md
        span_fields.append("end_matchday")
    if span_fields:
        comp.save(update_fields=span_fields)

    csid, real_matchdays = _reference_matchdays(comp, start_md, end_md)
    if not csid or not real_matchdays:
        return {"competition_id": comp.id, "scheduled_fixtures": 0, "rounds": len(round_nos), "real_matchdays": []}

    mapping = _build_uniform_round_mapping(round_nos, real_matchdays)
    if round_mapping:
        valid = set(real_matchdays)
        for rno, md in round_mapping.items():
            if rno in round_nos and md in valid:
                mapping[rno] = md

    scheduled = 0
    for rno in round_nos:
        real_md = mapping[rno]
        fmd, _ = FantasyMatchday.objects.get_or_create(
            league=comp.league,
            real_competition_season_id=csid,
            real_matchday=real_md,
        )
        kickoff = (
            Match.objects.filter(competition_season_id=csid, matchday=real_md, kickoff__isnull=False)
            .order_by("kickoff")
            .values_list("kickoff", flat=True)
            .first()
        )
        updated = FantasyFixture.objects.filter(competition=comp, round_no=rno).update(
            fantasy_matchday=fmd,
            kickoff=kickoff,
        )
        scheduled += int(updated or 0)

    return {
        "competition_id": comp.id,
        "scheduled_fixtures": scheduled,
        "rounds": len(round_nos),
        "real_matchdays": real_matchdays,
        "mapped_rounds": mapping,
    }


def _real_matchday_stats(real_competition_season_id: int, real_matchday: int) -> dict:
    qs = Match.objects.filter(competition_season_id=real_competition_season_id, matchday=real_matchday)
    total = qs.count()
    completed = qs.exclude(home_goals__isnull=True).exclude(away_goals__isnull=True).count()
    return {
        "total": total,
        "completed": completed,
        "is_completed": total > 0 and completed == total,
    }


def _stage_is_done(stage: CompetitionStage) -> bool:
    total = stage.fixtures.count()
    if total == 0:
        return False
    finished = stage.fixtures.filter(status=FantasyFixture.STATUS_FINISHED).count()
    return finished == total


class LeagueMatchdaySyncView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)
        result = _sync_matchdays_for_league(league)
        return Response(result)


def _sync_matchdays_for_league(league: FantasyLeague) -> dict:
    fixtures = list(
        FantasyFixture.objects.filter(competition__league=league, source_real_match__isnull=False)
        .select_related("source_real_match")
        .order_by("id")
    )
    cache: dict[tuple[int, int], FantasyMatchday] = {}
    updates: list[FantasyFixture] = []
    linked = 0

    for fx in fixtures:
        if not fx.source_real_match:
            continue
        md = fx.source_real_match.matchday
        csid = fx.source_real_match.competition_season_id
        if md is None or not csid:
            continue
        key = (csid, int(md))
        fmd = cache.get(key)
        if not fmd:
            fmd, _ = FantasyMatchday.objects.get_or_create(
                league=league,
                real_competition_season_id=csid,
                real_matchday=int(md),
            )
            cache[key] = fmd
        if fx.fantasy_matchday_id != fmd.id:
            fx.fantasy_matchday_id = fmd.id
            updates.append(fx)
            linked += 1

    if updates:
        FantasyFixture.objects.bulk_update(updates, ["fantasy_matchday"], batch_size=500)

    return {"fixtures_linked": linked, "matchdays_touched": len(cache)}


class LeagueMatchdayListView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _membership_or_404(league, request.user.id)
        _sync_matchdays_for_league(league)

        rows = (
            FantasyMatchday.objects.filter(league=league)
            .select_related("real_competition_season__competition", "real_competition_season__season", "concluded_by")
            .order_by("real_matchday", "id")
        )
        current = _current_matchday(league)
        current_id = current.id if current else None
        payload = []
        for md in rows:
            real_stats = _real_matchday_stats(md.real_competition_season_id, md.real_matchday)
            fx_total = md.fixtures.count()
            fx_finished = md.fixtures.filter(status=FantasyFixture.STATUS_FINISHED).count()
            if md.status == FantasyMatchday.STATUS_CONCLUDED:
                phase = "concluded"
            elif md.id == current_id:
                phase = "current"
            else:
                phase = "future"
            payload.append(
                {
                    "fantasy_matchday_id": md.id,
                    "league_id": league.id,
                    "status": md.status,
                    "phase": phase,
                    "real_competition_season": {
                        "id": md.real_competition_season_id,
                        "name": str(md.real_competition_season),
                        "competition": md.real_competition_season.competition.name,
                        "season": md.real_competition_season.season.code,
                    },
                    "real_matchday": md.real_matchday,
                    "real_completion": real_stats,
                    "fixtures": {"total": fx_total, "finished": fx_finished},
                    "concluded_at": md.concluded_at.isoformat() if md.concluded_at else None,
                    "concluded_by": md.concluded_by.username if md.concluded_by_id else None,
                }
            )
        return Response(payload)


class LeagueMatchdayConcludeView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, league_id: int, fantasy_matchday_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)
        _sync_matchdays_for_league(league)
        md = get_object_or_404(FantasyMatchday, id=fantasy_matchday_id, league=league)

        s = MatchdayConcludeSerializer(data=request.data or {})
        s.is_valid(raise_exception=True)
        force = s.validated_data.get("force", False)

        # Conclude in order: only the current (earliest non-concluded) matchday.
        current = _current_matchday(league)
        if md.status != FantasyMatchday.STATUS_CONCLUDED and current and md.id != current.id and not force:
            return Response(
                {
                    "detail": f"Conclude matchdays in order — the current one is real matchday {current.real_matchday}.",
                    "current_matchday_id": current.id,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        real_stats = _real_matchday_stats(md.real_competition_season_id, md.real_matchday)
        if not real_stats["is_completed"] and not force:
            return Response(
                {
                    "detail": "Real matchday is not completed yet.",
                    "real_completion": real_stats,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        fixtures = list(
            FantasyFixture.objects.filter(fantasy_matchday=md)
            .select_related("source_real_match", "stage", "competition")
            .order_by("id")
        )

        missing_source = 0
        missing_goals = 0
        updated = 0
        stage_ids: set[int] = set()
        for fx in fixtures:
            src = fx.source_real_match
            if not src:
                missing_source += 1
                continue
            if src.home_goals is None or src.away_goals is None:
                missing_goals += 1
                continue
            fx.home_total = float(src.home_goals)
            fx.away_total = float(src.away_goals)
            fx.status = FantasyFixture.STATUS_FINISHED
            updated += 1
            if fx.stage_id:
                stage_ids.add(fx.stage_id)

        if (missing_source > 0 or missing_goals > 0) and not force:
            return Response(
                {
                    "detail": "Some fixtures are not scoreable yet (missing mapping or final real score).",
                    "missing_source_real_match": missing_source,
                    "missing_real_scores": missing_goals,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if fixtures:
            FantasyFixture.objects.bulk_update(fixtures, ["home_total", "away_total", "status"], batch_size=500)

        stage_ids_to_resolve: set[int] = set()
        done_stages = 0
        for sid in stage_ids:
            stage = CompetitionStage.objects.filter(id=sid).first()
            if not stage:
                continue
            if _stage_is_done(stage):
                if stage.status != CompetitionStage.STATUS_DONE:
                    stage.status = CompetitionStage.STATUS_DONE
                    stage.save(update_fields=["status"])
                done_stages += 1
                targets = stage.rules_out.values_list("target_stage_id", flat=True)
                for tid in targets:
                    stage_ids_to_resolve.add(int(tid))

        resolved_targets = []
        for tid in sorted(stage_ids_to_resolve):
            target = CompetitionStage.objects.filter(id=tid).first()
            if not target:
                continue
            result = resolve_stage(target, seed=42)
            resolved_targets.append(result)

        md.status = FantasyMatchday.STATUS_CONCLUDED
        md.concluded_at = timezone.now()
        md.concluded_by = request.user
        md.save(update_fields=["status", "concluded_at", "concluded_by"])

        return Response(
            {
                "fantasy_matchday_id": md.id,
                "status": md.status,
                "real_completion": real_stats,
                "fixtures_scored": updated,
                "fixtures_total": len(fixtures),
                "missing_source_real_match": missing_source,
                "missing_real_scores": missing_goals,
                "done_stages": done_stages,
                "resolved_target_stages": resolved_targets,
            }
        )


class CompetitionDetailUpdateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, competition_id: int):
        comp = get_object_or_404(FantasyCompetition, id=competition_id)
        _membership_or_404(comp.league, request.user.id)
        return Response(_serialize_competition(comp))

    @transaction.atomic
    def patch(self, request, competition_id: int):
        comp = get_object_or_404(FantasyCompetition, id=competition_id)
        _ensure_admin(comp.league, request.user.id)
        s = CompetitionUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        for field in [
            "name", "status", "points_win", "points_draw", "points_loss",
            "starts_at", "ends_at", "start_matchday", "end_matchday",
        ]:
            if field in data:
                setattr(comp, field, data[field])
        comp.save()

        # If a source competition advances/completes, refresh dependents.
        if "status" in data and data["status"] in [FantasyCompetition.STATUS_ACTIVE, FantasyCompetition.STATUS_DONE]:
            dependents = FantasyCompetition.objects.filter(qualification_rules__source_competition=comp).distinct()
            for dep in dependents:
                _resolve_rule_participants_and_regenerate(dep)
        return Response(_serialize_competition(comp))

    @transaction.atomic
    def delete(self, request, competition_id: int):
        comp = get_object_or_404(FantasyCompetition, id=competition_id)
        _ensure_admin(comp.league, request.user.id)

        ext_stage_rules = list(
            CompetitionStageRule.objects.filter(source_stage__competition=comp)
            .exclude(target_stage__competition=comp)
            .select_related("source_stage", "target_stage", "target_stage__competition")
            .order_by("target_stage__competition_id", "target_stage__order_index", "target_stage_id")
        )
        if ext_stage_rules:
            return Response(
                {
                    "detail": "Cannot delete competition: some stages are used as qualification sources by other competitions.",
                    "dependent_targets": [
                        {
                            "source_stage_id": r.source_stage_id,
                            "source_stage_name": r.source_stage.name,
                            "target_stage_id": r.target_stage_id,
                            "target_stage_name": r.target_stage.name,
                            "target_competition_id": r.target_stage.competition_id,
                            "target_competition_name": r.target_stage.competition.name,
                            "mode": r.mode,
                            "rank_from": r.rank_from,
                            "rank_to": r.rank_to,
                        }
                        for r in ext_stage_rules
                    ],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        ext_qual_rules = list(
            CompetitionQualificationRule.objects.filter(source_competition=comp)
            .exclude(competition=comp)
            .select_related("competition")
        )
        if ext_qual_rules:
            return Response(
                {
                    "detail": "Cannot delete competition: it is referenced by competition-level qualification rules.",
                    "dependent_competitions": [
                        {
                            "competition_id": r.competition_id,
                            "competition_name": r.competition.name,
                            "mode": r.mode,
                            "source_stage": r.source_stage,
                            "rank_from": r.rank_from,
                            "rank_to": r.rank_to,
                        }
                        for r in ext_qual_rules
                    ],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        ext_prizes = list(
            CompetitionPrize.objects.filter(source_stage__competition=comp)
            .exclude(competition=comp)
            .select_related("competition", "source_stage")
        )
        if ext_prizes:
            return Response(
                {
                    "detail": "Cannot delete competition: some of its stages are referenced by prizes in other competitions.",
                    "dependent_prizes": [
                        {
                            "prize_id": p.id,
                            "prize_name": p.name,
                            "competition_id": p.competition_id,
                            "competition_name": p.competition.name,
                            "source_stage_id": p.source_stage_id,
                            "source_stage_name": p.source_stage.name if p.source_stage_id else None,
                        }
                        for p in ext_prizes
                    ],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        comp.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CompetitionScheduleView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, competition_id: int):
        comp = get_object_or_404(FantasyCompetition, id=competition_id)
        _ensure_admin(comp.league, request.user.id)
        s = CompetitionScheduleSerializer(data=request.data or {})
        s.is_valid(raise_exception=True)
        data = s.validated_data

        changed = []
        if "starts_at" in data:
            comp.starts_at = data["starts_at"]
            changed.append("starts_at")
        if "ends_at" in data:
            comp.ends_at = data["ends_at"]
            changed.append("ends_at")
        if changed:
            comp.save(update_fields=changed)

        start_md = data.get("start_matchday")
        end_md = data.get("end_matchday")

        # Scheduling needs a real-matchday source: either the league reference
        # season (preferred) or the legacy date window.
        if comp.league.reference_season is None and (not comp.starts_at or not comp.ends_at):
            return Response(
                {"detail": "Set the league reference season (or competition dates) before scheduling."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        parsed_mapping: dict[int, int] = {}
        raw_mapping = data.get("round_mapping") or {}
        if isinstance(raw_mapping, dict):
            for raw_round, raw_matchday in raw_mapping.items():
                try:
                    rno = int(raw_round)
                    md = int(raw_matchday)
                except (TypeError, ValueError):
                    continue
                parsed_mapping[rno] = md
        result = _schedule_competition_rounds(
            comp, round_mapping=parsed_mapping or None, start_md=start_md, end_md=end_md
        )
        return Response(result)


class CompetitionSchedulePreviewView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, competition_id: int):
        comp = get_object_or_404(FantasyCompetition, id=competition_id)
        _ensure_admin(comp.league, request.user.id)
        s = CompetitionSchedulePreviewSerializer(data=request.data or {})
        s.is_valid(raise_exception=True)
        data = s.validated_data
        return Response(_schedule_preview(comp, start_md=data.get("start_matchday"), end_md=data.get("end_matchday")))


class CompetitionAddQualificationRuleView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, competition_id: int):
        comp = get_object_or_404(FantasyCompetition, id=competition_id)
        _ensure_admin(comp.league, request.user.id)
        s = QualificationRuleCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        source = get_object_or_404(FantasyCompetition, id=data["source_competition_id"], league=comp.league)
        rule = CompetitionQualificationRule.objects.create(
            competition=comp,
            source_competition=source,
            source_stage=data["source_stage"],
            source_round=data.get("source_round"),
            mode=data["mode"],
            rank_from=data.get("rank_from"),
            rank_to=data.get("rank_to"),
        )
        _resolve_rule_participants_and_regenerate(comp)
        return Response(
            {
                "rule_id": rule.id,
                "competition_id": comp.id,
                "source_competition_id": source.id,
                "source_competition_name": source.name,
                "source_stage": rule.source_stage,
                "source_round": rule.source_round,
                "mode": rule.mode,
                "rank_from": rule.rank_from,
                "rank_to": rule.rank_to,
            },
            status=status.HTTP_201_CREATED,
        )


class CompetitionResolveDependenciesView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, competition_id: int):
        comp = get_object_or_404(FantasyCompetition, id=competition_id)
        _ensure_admin(comp.league, request.user.id)
        result = _resolve_rule_participants_and_regenerate(comp)
        return Response(result)


class AuctionCreateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)

        s = CreateAuctionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        player_ids = data["player_ids"]
        blocked = _ensure_players_decided(league, player_ids)
        if blocked:
            return blocked
        players = list(Player.objects.filter(id__in=player_ids).values_list("id", flat=True))
        if not players:
            return Response({"detail": "No valid players provided."}, status=status.HTTP_400_BAD_REQUEST)

        rng = Random(data["random_seed"])
        rng.shuffle(players)

        session = AuctionSession.objects.create(
            league=league,
            name=data["name"],
            status=AuctionSession.STATUS_ACTIVE,
            nomination_order=players,
            nomination_index=0,
            created_by=request.user,
        )

        return Response({"auction_id": session.id, "players": len(players)}, status=status.HTTP_201_CREATED)


class AuctionNominateNextView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, auction_id: int):
        session = get_object_or_404(AuctionSession, id=auction_id)
        league = session.league
        m = _membership_or_404(league, request.user.id)

        if session.status != AuctionSession.STATUS_ACTIVE:
            return Response({"detail": "Auction is not active."}, status=status.HTTP_400_BAD_REQUEST)

        # Ensure there isn't already an open nomination
        open_nom = AuctionNomination.objects.filter(session=session, status=AuctionNomination.STATUS_OPEN).first()
        if open_nom:
            return Response({"detail": "There is already an open nomination.", "nomination_id": open_nom.id}, status=status.HTTP_200_OK)

        if session.nomination_index >= len(session.nomination_order):
            session.status = AuctionSession.STATUS_CLOSED
            session.save(update_fields=["status"])
            return Response({"detail": "No more players to nominate."}, status=status.HTTP_200_OK)

        player_id = session.nomination_order[session.nomination_index]
        player = get_object_or_404(Player, id=player_id)

        nom = AuctionNomination.objects.create(session=session, player=player, nominator=m)
        session.nomination_index += 1
        session.save(update_fields=["nomination_index"])

        return Response(
            {
                "nomination_id": nom.id,
                "player_id": player.id,
                "player_name": player.short_name or player.full_name,
            },
            status=status.HTTP_201_CREATED,
        )


class AuctionStateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, auction_id: int):
        session = get_object_or_404(AuctionSession, id=auction_id)
        _membership_or_404(session.league, request.user.id)

        open_nom = (
            AuctionNomination.objects.filter(session=session, status=AuctionNomination.STATUS_OPEN)
            .select_related("player", "nominator__user")
            .first()
        )

        next_player = None
        if session.nomination_index < len(session.nomination_order):
            pid = session.nomination_order[session.nomination_index]
            p = Player.objects.filter(id=pid).first()
            if p:
                next_player = {"player_id": p.id, "name": p.short_name or p.full_name}

        nominations = list(
            AuctionNomination.objects.filter(session=session)
            .select_related("player", "nominator__user", "closed_winner_team")
            .order_by("-created_at")[:30]
        )

        spent_by_team: dict[int, int] = {}
        rows = []
        for n in nominations:
            top = n.bids.order_by("-amount", "created_at").first()
            top_amount = top.amount if top else 0
            if n.status == AuctionNomination.STATUS_CLOSED and n.closed_winner_team_id and top_amount > 0:
                spent_by_team[n.closed_winner_team_id] = spent_by_team.get(n.closed_winner_team_id, 0) + top_amount

            rows.append(
                {
                    "nomination_id": n.id,
                    "status": n.status,
                    "player_id": n.player_id,
                    "player_name": n.player.short_name or n.player.full_name,
                    "nominator": n.nominator.user.username,
                    "top_bid": top_amount,
                    "winner_team_id": n.closed_winner_team_id,
                    "winner_team_name": n.closed_winner_team.name if n.closed_winner_team_id else None,
                }
            )

        teams = FantasyTeam.objects.filter(league=session.league).select_related("manager__user")
        initial_budget = 500
        budgets = []
        for t in teams:
            spent = spent_by_team.get(t.id, 0)
            budgets.append(
                {
                    "team_id": t.id,
                    "team_name": t.name,
                    "manager_username": t.manager.user.username,
                    "initial_budget": initial_budget,
                    "spent_budget": spent,
                    "available_budget": max(0, initial_budget - spent),
                }
            )

        return Response(
            {
                "auction_id": session.id,
                "name": session.name,
                "status": session.status,
                "nomination_index": session.nomination_index,
                "nomination_total": len(session.nomination_order),
                "next_player": next_player,
                "open_nomination": {
                    "nomination_id": open_nom.id,
                    "player_id": open_nom.player_id,
                    "player_name": open_nom.player.short_name or open_nom.player.full_name,
                    "nominator": open_nom.nominator.user.username,
                }
                if open_nom
                else None,
                "recent_nominations": rows,
                "team_budgets": budgets,
            }
        )


class AuctionPlaceBidView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, nomination_id: int):
        nomination = get_object_or_404(AuctionNomination, id=nomination_id)
        if nomination.status != AuctionNomination.STATUS_OPEN:
            return Response({"detail": "Nomination is closed."}, status=status.HTTP_400_BAD_REQUEST)

        m = _membership_or_404(nomination.session.league, request.user.id)

        s = PlaceBidSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        amount = s.validated_data["amount"]

        top = nomination.bids.order_by("-amount", "created_at").first()
        min_required = (top.amount + 1) if top else 1
        if amount < min_required:
            return Response({"detail": f"Bid must be >= {min_required}"}, status=status.HTTP_400_BAD_REQUEST)

        bid = AuctionBid.objects.create(nomination=nomination, bidder=m, amount=amount)
        return Response({"bid_id": bid.id, "amount": bid.amount}, status=status.HTTP_201_CREATED)


class AuctionCloseNominationView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, nomination_id: int):
        nomination = get_object_or_404(AuctionNomination, id=nomination_id)
        _ensure_admin(nomination.session.league, request.user.id)

        if nomination.status == AuctionNomination.STATUS_CLOSED:
            return Response({"detail": "Already closed."}, status=status.HTTP_200_OK)

        top = nomination.bids.order_by("-amount", "created_at").first()
        winner_team_id = None
        if top:
            winner_team = top.bidder.team
            winner_team_id = winner_team.id
            FantasyRosterSlot.objects.create(
                team=winner_team,
                player=nomination.player,
                purchase_price=top.amount,
            )
            nomination.closed_winner_team = winner_team

        nomination.status = AuctionNomination.STATUS_CLOSED
        nomination.save(update_fields=["status", "closed_winner_team"])

        return Response({"nomination_id": nomination.id, "winner_team_id": winner_team_id}, status=status.HTTP_200_OK)


def _compute_standings(fixtures, pw: int, pd: int, pl: int) -> list[dict]:
    """Ranked standings from a list of FINISHED fixtures (with .detail prefetched)."""
    rows: dict[int, dict] = {}
    names: dict[int, str] = {}

    def row(team_id: int) -> dict:
        return rows.setdefault(
            team_id, {"pts": 0, "played": 0, "w": 0, "d": 0, "l": 0, "gf": 0.0, "ga": 0.0, "score_sum": 0.0}
        )

    for fx in fixtures:
        names[fx.home_team_id] = fx.home_team.name
        names[fx.away_team_id] = fx.away_team.name
        h, a = row(fx.home_team_id), row(fx.away_team_id)
        hs, as_ = fx.home_total, fx.away_total
        h["played"] += 1
        a["played"] += 1
        h["gf"] += hs
        h["ga"] += as_
        a["gf"] += as_
        a["ga"] += hs
        if hs > as_:
            h["pts"] += pw; a["pts"] += pl; h["w"] += 1; a["l"] += 1
        elif hs < as_:
            a["pts"] += pw; h["pts"] += pl; a["w"] += 1; h["l"] += 1
        else:
            h["pts"] += pd; a["pts"] += pd; h["d"] += 1; a["d"] += 1
        detail = getattr(fx, "detail", None)
        if detail is not None:
            h["score_sum"] += detail.vfoot_home
            a["score_sum"] += detail.vfoot_away

    ranked = sorted(rows.items(), key=lambda kv: (kv[1]["pts"], kv[1]["gf"] - kv[1]["ga"], kv[1]["gf"]), reverse=True)
    return [
        {
            "rank": i + 1, "team_id": tid, "team": names.get(tid, str(tid)),
            "played": r["played"], "wins": r["w"], "draws": r["d"], "losses": r["l"],
            "goals_for": int(r["gf"]), "goals_against": int(r["ga"]),
            "goal_diff": int(r["gf"] - r["ga"]), "points": r["pts"],
            "avg_score_for": round(r["score_sum"] / r["played"], 3) if r["played"] else 0.0,
        }
        for i, (tid, r) in enumerate(ranked)
    ]


_KO_ROUND_LABELS = {1: "Finale", 2: "Semifinali", 4: "Quarti di finale", 8: "Ottavi di finale"}


def _section(name, stage_type, order, fixtures, my_team_id, current_md, pw, pd, pl) -> dict:
    """One results section: a standings table (round-robin) or a bracket (knockout)."""
    fixtures = list(fixtures)
    base = {"name": name, "type": stage_type, "order": order}
    if stage_type == CompetitionStage.TYPE_KNOCKOUT:
        by_round: dict[int, list] = {}
        for f in fixtures:
            by_round.setdefault(f.round_no, []).append(f)
        rounds = []
        for rno in sorted(by_round):
            fs = by_round[rno]
            rounds.append({
                "round_no": rno,
                "label": _KO_ROUND_LABELS.get(len(fs), f"Turno {rno}"),
                "fixtures": [_serialize_fixture_row(f, my_team_id, current_md) for f in fs],
            })
        base["rounds"] = rounds
    else:
        finished = [f for f in fixtures if f.status == FantasyFixture.STATUS_FINISHED]
        base["standings"] = _compute_standings(finished, pw, pd, pl)
    return base


class CompetitionStructureView(APIView):
    """Stage-aware results for ONE competition: an ordered list of SECTIONS, each a
    standings table (round-robin) or a bracket (knockout). A flat competition (no
    stages) yields a single section from its own type. Handles group+KO cups."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, league_id: int, competition_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        membership = _membership_or_404(league, request.user.id)
        my_team_id = membership.team.id if hasattr(membership, "team") else None
        comp = get_object_or_404(FantasyCompetition, id=competition_id, league=league)
        current = _current_matchday(league)
        current_md = current.real_matchday if current else None
        pw, pd, pl = comp.points_win, comp.points_draw, comp.points_loss
        rel = ("competition", "stage", "fantasy_matchday", "home_team", "away_team", "detail")

        stages = list(comp.stages.order_by("order_index", "id"))
        if stages:
            sections = [
                _section(s.name, s.stage_type, s.order_index,
                         s.fixtures.select_related(*rel), my_team_id, current_md, pw, pd, pl)
                for s in stages
            ]
        else:
            sections = [
                _section(comp.name, comp.competition_type, 1,
                         comp.fixtures.select_related(*rel), my_team_id, current_md, pw, pd, pl)
            ]
        return Response({
            "competition_id": comp.id, "name": comp.name,
            "result_view": _result_view(comp), "sections": sections,
        })


class LeagueStandingsView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _membership_or_404(league, request.user.id)
        # A standings table is COMPETITION-scoped, not league-scoped. Use the given
        # competition; default to the first round-robin (a knockout has no table).
        comp_param = request.query_params.get("competition_id")
        comp = None
        if comp_param:
            comp = league.competitions.filter(id=comp_param).first()
        if comp is None:
            comp = (league.competitions.filter(competition_type=FantasyCompetition.TYPE_ROUND_ROBIN)
                    .order_by("id").first()
                    or league.competitions.order_by("id").first())
        pw, pd, pl = (comp.points_win, comp.points_draw, comp.points_loss) if comp else (3, 1, 0)

        fixtures = (
            FantasyFixture.objects.filter(status=FantasyFixture.STATUS_FINISHED)
            .filter(competition=comp if comp else None)
            .select_related("home_team", "away_team", "detail")
        ) if comp else FantasyFixture.objects.none()
        rows: dict[int, dict] = {}
        names: dict[int, str] = {}

        def row(team_id: int) -> dict:
            return rows.setdefault(
                team_id,
                {"pts": 0, "played": 0, "w": 0, "d": 0, "l": 0, "gf": 0.0, "ga": 0.0, "score_sum": 0.0},
            )

        for fx in fixtures:
            names[fx.home_team_id] = fx.home_team.name
            names[fx.away_team_id] = fx.away_team.name
            h, a = row(fx.home_team_id), row(fx.away_team_id)
            hs, as_ = fx.home_total, fx.away_total
            h["played"] += 1
            a["played"] += 1
            h["gf"] += hs
            h["ga"] += as_
            a["gf"] += as_
            a["ga"] += hs
            if hs > as_:
                h["pts"] += pw
                a["pts"] += pl
                h["w"] += 1
                a["l"] += 1
            elif hs < as_:
                a["pts"] += pw
                h["pts"] += pl
                a["w"] += 1
                h["l"] += 1
            else:
                h["pts"] += pd
                a["pts"] += pd
                h["d"] += 1
                a["d"] += 1
            detail = getattr(fx, "detail", None)
            if detail is not None:
                h["score_sum"] += detail.vfoot_home
                a["score_sum"] += detail.vfoot_away

        ranked = sorted(
            rows.items(),
            key=lambda kv: (kv[1]["pts"], kv[1]["gf"] - kv[1]["ga"], kv[1]["gf"]),
            reverse=True,
        )
        standings = [
            {
                "rank": i + 1,
                "team_id": tid,
                "team": names.get(tid, str(tid)),
                "played": r["played"],
                "wins": r["w"],
                "draws": r["d"],
                "losses": r["l"],
                "goals_for": int(r["gf"]),
                "goals_against": int(r["ga"]),
                "goal_diff": int(r["gf"] - r["ga"]),
                "points": r["pts"],
                "avg_score_for": round(r["score_sum"] / r["played"], 3) if r["played"] else 0.0,
            }
            for i, (tid, r) in enumerate(ranked)
        ]
        return Response({"competition_id": comp.id if comp else None, "standings": standings})


class FixtureDetailView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, fixture_id: int):
        fx = get_object_or_404(
            FantasyFixture.objects.select_related("competition__league", "detail"), id=fixture_id
        )
        _membership_or_404(fx.competition.league, request.user.id)
        detail = getattr(fx, "detail", None)
        if detail is None:
            return Response({"detail": "No rich detail for this fixture."}, status=status.HTTP_404_NOT_FOUND)
        return Response(detail.payload)


def _zone_grid_keys(cols: int = 5, rows: int = 4) -> list[str]:
    return [f"Z_{c}_{r}" for c in range(cols) for r in range(rows)]


@_lru_cache(maxsize=1)
def _vector_calibration() -> dict:
    path = _os.path.join(_os.path.dirname(str(_settings.BASE_DIR)), "calibration/vector_zone_duel_v1.json")
    try:
        return load_calibration(path)
    except Exception:
        return {"params": {}, "feature_scales": {}}


class LeagueTeamLineupView(APIView):
    """Real lineup context for a team: its roster with spatial profiles
    (role/footprint/minutes), the league matchdays, and — for the caller's OWN
    team — the saved lineup for the chosen matchday.

    With ``?team_id=`` any league member can read ANOTHER participant's structured
    roster (the same view the Squad page renders), so squads are no longer only
    visible in the flat name+price list. The saved lineup is withheld for other
    people's teams: the roster is public within the league, the chosen XI is not."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        membership = _membership_or_404(league, request.user.id)
        own_team = getattr(membership, "team", None)

        team_param = request.query_params.get("team_id")
        if team_param:
            # Any member may see any team in the league — but only the roster, and
            # the client is told whose team it is and whether it is the caller's.
            team = get_object_or_404(FantasyTeam, id=team_param, league=league)
        else:
            team = own_team
        if team is None:
            return Response({"detail": "Nessuna squadra associata in questa lega."}, status=status.HTTP_404_NOT_FOUND)
        is_own = own_team is not None and team.id == own_team.id

        # A lineup is referred to a COMPETITION (a set of league fixtures mapped to
        # real matchdays). Default to the first competition; its matchdays come
        # from its fixtures.
        competitions = list(league.competitions.order_by("id").values("id", "name"))
        comp_param = request.query_params.get("competition")
        competition_id: int | None = None
        if comp_param:
            try:
                competition_id = int(comp_param)
            except (TypeError, ValueError):
                competition_id = None
        if competition_id is None and competitions:
            competition_id = competitions[0]["id"]

        matchdays: list[int] = []
        if competition_id is not None:
            matchdays = sorted(
                {
                    int(md)
                    for md in FantasyFixture.objects.filter(
                        competition_id=competition_id, fantasy_matchday__isnull=False
                    ).values_list("fantasy_matchday__real_matchday", flat=True)
                    if md is not None
                }
            )
        if not matchdays:
            matchdays = list(
                FantasyMatchday.objects.filter(league=league).order_by("real_matchday").values_list("real_matchday", flat=True)
            )
        # When a matchday is given we treat it as an "as-of" cutoff: profiles use
        # only matches BEFORE it, so setting a lineup mid-season never peeks at
        # future results (no leakage). No matchday -> full-season profiles.
        matchday_param = request.query_params.get("matchday")
        as_of: int | None = None
        if matchday_param is not None:
            try:
                matchday = int(matchday_param)
            except (TypeError, ValueError):
                matchday = matchdays[0] if matchdays else 1
            as_of = matchday
        else:
            matchday = matchdays[0] if matchdays else 1

        slots = list(
            FantasyRosterSlot.objects.filter(team=team, released_at__isnull=True).select_related("player")
        )
        player_ids = [s.player_id for s in slots]
        cal = _vector_calibration()

        # Which season should the playing-time stats describe? The reference season
        # while it is under way, but BEFORE it starts it has no games at all — and
        # reporting "poco impiegato" for everybody because nobody has played yet is
        # simply wrong. In that case fall back to the last season with data.
        ref_cs = league.reference_season
        stats_cs, stats_as_of = None, as_of
        if ref_cs is not None:
            played_here = MatchAppearance.objects.filter(
                player_id__in=player_ids,
                match__competition_season=ref_cs,
                **({"match__matchday__lt": as_of} if as_of is not None else {}),
            ).exists()
            if played_here:
                stats_cs = ref_cs
            else:
                prev = previous_season_with_data(ref_cs)
                stats_cs, stats_as_of = (prev, None) if prev else (ref_cs, as_of)

        total_matches = (
            Match.objects.filter(competition_season=stats_cs)
            .values("matchday").distinct().count()
            if stats_cs is not None
            else Match.objects.values("matchday").distinct().count()
        )
        profiles = player_profiles(
            player_ids,
            total_matches=total_matches,
            as_of_matchday=stats_as_of,
            params=cal.get("params", {}),
            scales=cal.get("feature_scales", {}),
            competition_season_id=stats_cs.id if stats_cs is not None else None,
        )

        # Average voto (measured, or estimated from the market): a number a manager
        # can actually read. The zone-duel "form" stays for aura, where it belongs.
        values_by_player: dict[int, dict] = {}
        if ref_cs is not None:
            # Calibrate on the WHOLE pool, not just this roster: 25 players are too
            # few an overlap to fit the market->voto relation, which would leave
            # every newcomer without a value.
            values_by_player, _pcs, _fit = player_values(
                ref_cs, latest_market_values(eligible_player_ids(ref_cs.id)))

        # The REAL fixture each player's club plays on this matchday — far more useful
        # than a zone map when picking a lineup (who plays, against whom, and when).
        next_match_by_player: dict[int, dict] = {}
        if ref_cs is not None and as_of is not None:
            fixtures = matchday_fixtures_by_team(ref_cs.id, as_of)
            stints = dict(PlayerTeamStint.objects
                          .filter(player_id__in=player_ids,
                                  team_season__competition_season=ref_cs,
                                  end_date__isnull=True)
                          .values_list("player_id", "team_season_id"))
            for pid, ts_id in stints.items():
                m = fixtures.get(ts_id)
                if m is None:
                    continue
                at_home = m.home_team_id == ts_id
                opp = (m.away_team if at_home else m.home_team).team
                own = (m.home_team if at_home else m.away_team).team
                next_match_by_player[pid] = {
                    "team": own.short_name or own.name,
                    "opponent": opp.short_name or opp.name,
                    "home": at_home,
                    "kickoff": m.kickoff.isoformat() if m.kickoff else None,
                    "kickoff_provisional": m.kickoff_provisional,
                    "status": m.status,
                }

        # In CLASSIC mode the role that governs the formation is the FROZEN listone
        # role (LeaguePlayerRole), not the spatially-inferred one — classic fantacalcio
        # pins roles at season start. Fall back to the player's global seed, then to
        # the spatial guess, so a roster is never roleless.
        is_classic = league.mode == FantasyLeague.MODE_CLASSIC
        frozen_roles: dict[int, str] = {}
        if is_classic:
            frozen_roles = {
                lpr.player_id: _CLASSIC_ROLE_TO_LINEUP.get(lpr.role, "MID")
                for lpr in LeaguePlayerRole.objects.filter(league=league, player_id__in=player_ids)
            }
            seed_roles = dict(
                Player.objects.filter(id__in=player_ids).exclude(classic_role="").values_list("id", "classic_role")
            )

        # Real club each player belongs to, in the season the stats come from — so a
        # player row can name his team, not just his fantasy price.
        real_team = dict(PlayerTeamStint.objects
                         .filter(player_id__in=player_ids,
                                 team_season__competition_season=stats_cs,
                                 end_date__isnull=True)
                         .values_list("player_id", "team_season__team__name")) \
            if stats_cs is not None else {}

        roster = []
        for s in slots:
            p = profiles.get(s.player_id, {})
            role = p.get("role", "MID")
            if is_classic:
                role = frozen_roles.get(s.player_id) or _CLASSIC_ROLE_TO_LINEUP.get(
                    seed_roles.get(s.player_id, ""), role
                )
            roster.append(
                {
                    "player_id": s.player_id,
                    "name": s.player.short_name or s.player.full_name,
                    "price": s.purchase_price,
                    "role": role,
                    "avg_col": p.get("avg_col", 0.0),
                    "footprint": p.get("footprint", {}),
                    "appearances": p.get("appearances", 0),
                    "starts": p.get("starts", 0),
                    "avg_minutes": p.get("avg_minutes", 0.0),
                    "minutes_label": p.get("minutes_label", "unknown"),
                    "real_team": real_team.get(s.player_id),
                    "form": p.get("form", 0.0),
                    "stats_season": str(stats_cs) if stats_cs is not None else None,
                    "next_match": next_match_by_player.get(s.player_id),
                    "value": (values_by_player.get(s.player_id) or {}).get("estimated_value"),
                    "value_basis": (values_by_player.get(s.player_id) or {}).get("basis"),
                }
            )
        roster.sort(key=lambda r: (r["avg_col"], -r["price"]))

        lineup_key = f"team{team.id}" + (f":comp{competition_id}" if competition_id is not None else "")
        snap = SavedLineupSnapshot.objects.filter(
            league_id=str(league_id), matchday_id=str(matchday), lineup_id=lineup_key
        ).first()
        saved_lineup = (
            {
                "gk_player_id": int(snap.gk_player_id) if snap.gk_player_id else None,
                "starter_player_ids": snap.starter_player_ids,
                "bench_player_ids": snap.bench_player_ids,
                "starter_backups": snap.starter_backups,
            }
            if snap
            else None
        )

        return Response(
            {
                "team": {"team_id": team.id, "name": team.name,
                         "manager": team.manager.user.username},
                "is_own": is_own,
                "competitions": [{"competition_id": c["id"], "name": c["name"]} for c in competitions],
                "competition": competition_id,
                "matchdays": matchdays,
                "matchday": matchday,
                "as_of_matchday": as_of,
                "prior_matches": (as_of - 1) if as_of is not None else total_matches,
                "zone_grid": {"cols": 5, "rows": 4, "zone_keys": _zone_grid_keys()},
                "rules": {
                    "starters": 11,
                    "gk_separate_slot": True,
                    "mode": league.mode,
                    # classic role constraints (also used client-side to validate);
                    # null in aura where any shape is legal.
                    "classic_constraints": CLASSIC_CONSTRAINTS if is_classic else None,
                },
                "mode": league.mode,
                "roster": roster,
                # Spending summary: a fixed 500 budget (as used elsewhere), what
                # this squad cost, and per-role breakdown — so the manager reads
                # where his money went without adding it up by hand.
                "budget": _roster_budget(roster),
                # Which season the appearances/minutes/label describe. The client
                # must say so: pre-season these are LAST year's, and a silent
                # "poco impiegato" from stale data is exactly the confusion to avoid.
                "stats_season": str(stats_cs) if stats_cs is not None else None,
                "stats_is_reference": bool(stats_cs is not None
                                           and ref_cs is not None
                                           and stats_cs.id == ref_cs.id),
                "saved_lineup": saved_lineup if is_own else None,
            }
        )


def _roster_budget(roster: list) -> dict:
    initial = 500
    spent = sum(r["price"] for r in roster)
    by_role: dict[str, int] = {}
    for r in roster:
        by_role[r["role"]] = by_role.get(r["role"], 0) + r["price"]
    return {"initial": initial, "spent": spent, "remaining": max(0, initial - spent),
            "by_role": by_role}


class LeagueTeamLineupSaveView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        membership = _membership_or_404(league, request.user.id)
        team = getattr(membership, "team", None)
        if team is None:
            return Response({"detail": "Nessuna squadra associata in questa lega."}, status=status.HTTP_400_BAD_REQUEST)

        matchday = request.data.get("matchday")
        if matchday is None:
            return Response({"detail": "matchday richiesto."}, status=status.HTTP_400_BAD_REQUEST)
        gk = request.data.get("gk_player_id")

        # Classic mode: enforce the role constraints server-side using the FROZEN
        # listone roles, so a hand-crafted request can't bypass the client validator.
        if league.mode == FantasyLeague.MODE_CLASSIC:
            outfield_ids = [int(x) for x in request.data.get("starter_player_ids", []) if x is not None]
            starter_ids = ([int(gk)] if gk else []) + outfield_ids
            frozen = {
                lpr.player_id: _CLASSIC_ROLE_TO_LINEUP.get(lpr.role, "MID")
                for lpr in LeaguePlayerRole.objects.filter(league=league, player_id__in=starter_ids)
            }
            seed = dict(
                Player.objects.filter(id__in=starter_ids).exclude(classic_role="").values_list("id", "classic_role")
            )
            starter_roles = [
                frozen.get(pid) or _CLASSIC_ROLE_TO_LINEUP.get(seed.get(pid, ""), "MID")
                for pid in starter_ids
            ]
            errors = validate_classic_lineup(starter_roles)
            if errors:
                return Response(
                    {"detail": "Formazione non valida (classic).", "errors": errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # The lineup is referred to a competition; optionally apply it to all the
        # league's competitions at once (same matchday) to streamline.
        if request.data.get("all_competitions"):
            target_comp_ids: list[int | None] = list(league.competitions.values_list("id", flat=True)) or [None]
        else:
            comp = request.data.get("competition")
            target_comp_ids = [int(comp)] if comp else [None]

        defaults = {
            "gk_player_id": str(gk) if gk else None,
            "starter_player_ids": request.data.get("starter_player_ids", []),
            "bench_player_ids": request.data.get("bench_player_ids", []),
            "starter_backups": request.data.get("starter_backups", []),
        }
        for cid in target_comp_ids:
            SavedLineupSnapshot.objects.update_or_create(
                league_id=str(league_id),
                matchday_id=str(matchday),
                lineup_id=f"team{team.id}" + (f":comp{cid}" if cid is not None else ""),
                defaults=defaults,
            )
        return Response({"ok": True, "saved_competitions": len([c for c in target_comp_ids if c is not None]) or 1})


# -- Real reference-championship calendar & results ---------------------------


class LeagueRealFixturesView(APIView):
    """Calendar + results of the league's REAL reference championship (e.g. Serie
    A), grouped by matchday. Read model over the Match rows the calendar-sync
    keeps fresh. Optional ?matchday=N to fetch a single round."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _membership_or_404(league, request.user.id)
        cs = league.reference_season
        if cs is None:
            return Response({"season": None, "matchdays": []})

        qs = (Match.objects.filter(competition_season=cs)
              .select_related("home_team__team", "away_team__team")
              .annotate(_apps=Count("appearances"))
              .order_by("matchday", "kickoff", "id"))
        md_param = request.query_params.get("matchday")
        if md_param:
            try:
                qs = qs.filter(matchday=int(md_param))
            except ValueError:
                return Response({"detail": "matchday must be an integer"},
                                status=status.HTTP_400_BAD_REQUEST)

        # SofaScore keeps a postponed fixture AND its rescheduled replay as TWO
        # events with different ids. Hide a postponed row once a non-postponed
        # sibling (same teams, i.e. same leg) exists — but keep a genuinely
        # postponed-and-not-yet-replayed match visible.
        matches = list(qs)
        played_legs = {(m.home_team_id, m.away_team_id)
                       for m in matches if m.status != Match.STATUS_POSTPONED}
        matches = [m for m in matches
                   if not (m.status == Match.STATUS_POSTPONED
                           and (m.home_team_id, m.away_team_id) in played_legs)]

        groups: dict = {}
        for m in matches:
            has_detail = (m.status == Match.STATUS_FINISHED and m._apps > 0)
            item = {
                "id": m.id,
                "matchday": m.matchday,
                "kickoff": m.kickoff.isoformat() if m.kickoff else None,
                "kickoff_provisional": m.kickoff_provisional,
                "status": m.status,
                "home_team": m.home_team.team.name,
                "away_team": m.away_team.team.name,
                "home_short": m.home_team.team.short_name or m.home_team.team.name,
                "away_short": m.away_team.team.short_name or m.away_team.team.name,
                "home_goals": m.home_goals,
                "away_goals": m.away_goals,
                "has_detail": has_detail,
            }
            groups.setdefault(m.matchday, []).append(item)

        matchdays = [{"matchday": md, "fixtures": fx}
                     for md, fx in sorted(groups.items(),
                                          key=lambda kv: (kv[0] is None, kv[0]))]
        # A rough "current matchday": the earliest with any non-finished fixture,
        # else the last one — lets the frontend open on the live round.
        current = None
        for g in matchdays:
            if any(f["status"] != Match.STATUS_FINISHED for f in g["fixtures"]):
                current = g["matchday"]
                break
        if current is None and matchdays:
            current = matchdays[-1]["matchday"]

        return Response({
            "season": {"id": cs.id, "name": str(cs),
                       "competition": cs.competition.name},
            "current_matchday": current,
            "matchdays": matchdays,
        })


class LeagueRealMatchDetailView(APIView):
    """Vote-relevant detail of a single REAL match: the per-player pagella
    (voto puro + bonus/malus = fantavoto) for both squads, shaped as a classic
    fixture detail so the frontend ClassicMatchDetail renders it. (Aura zone
    breakdown enrichment is a planned follow-up.)"""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, league_id: int, match_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _membership_or_404(league, request.user.id)
        cs = league.reference_season
        match = get_object_or_404(
            Match.objects.select_related("home_team__team", "away_team__team",
                                         "competition_season"),
            id=match_id)
        if cs is not None and match.competition_season_id != cs.id:
            raise Http404("Match is not in this league's reference season")
        if not MatchAppearance.objects.filter(match=match).exists():
            return Response({"detail": "Nessun dato disponibile per questa partita."},
                            status=status.HTTP_404_NOT_FOUND)

        pag = pagella_for_match(match, get_reference(match.competition_season_id),
                                league=league)
        hg, ag = int(match.home_goals or 0), int(match.away_goals or 0)
        result = "home" if hg > ag else "away" if ag > hg else "draw"
        return Response({
            "mode": "classic",
            "fixture_id": match.id,
            "fantasy_round": match.matchday,
            "real_matchday": match.matchday,
            "stage": None,
            "home_team": match.home_team.team.name,
            "away_team": match.away_team.team.name,
            "home_goals": hg,
            "away_goals": ag,
            "home_total": pag["home"]["total"],
            "away_total": pag["away"]["total"],
            "defense_bonus_mode": None,
            "result": result,
            "home": pag["home"],
            "away": pag["away"],
        })


class LeagueChampionshipPlayersView(APIView):
    """Full player pool of the league's reference championship (the 'listone').

    One row per currently-eligible player (open real-club stint), with role, real
    club, ownership in THIS league (free agent vs owned + owner), and a value
    signal (average voto puro from the latest season with data). The frontend does
    role / free-agent / search filtering and value sorting over this list."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _membership_or_404(league, request.user.id)
        cs = league.reference_season
        if cs is None:
            return Response({"value_season": None, "players": []})

        pool = eligible_player_ids(cs.id)

        # real club per player (open stint on this season)
        team_by_player = {}
        for pid, tname in (PlayerTeamStint.objects
                           .filter(team_season__competition_season=cs,
                                   end_date__isnull=True, player_id__in=pool)
                           .select_related("team_season__team")
                           .values_list("player_id", "team_season__team__name")):
            team_by_player[pid] = tname

        # frozen listone role, fallback to the global classic role
        lpr = dict(LeaguePlayerRole.objects.filter(league=league)
                   .values_list("player_id", "role"))
        # ownership in this league
        owner_by_player = dict(
            FantasyRosterSlot.objects
            .filter(team__league=league, released_at__isnull=True)
            .values_list("player_id", "team__name"))

        # Value blends last season's average with current-season form as the
        # championship progresses (see player_values).
        market = latest_market_values(pool)
        values, prev_cs, fit = player_values(cs, market)

        players = (Player.objects.filter(id__in=pool)
                   .values("id", "full_name", "short_name", "classic_role"))
        # Players whose role is still an open question: shown, but marked, so
        # nobody plans an auction around someone they cannot actually buy.
        undecided = undecided_player_ids(league)
        rows = []
        for p in players:
            pid = p["id"]
            v = values.get(pid)
            rows.append({
                "market_value": market.get(pid),
                "player_id": pid,
                "name": p["short_name"] or p["full_name"] or str(pid),
                "role": lpr.get(pid) or p["classic_role"] or "",
                "team": team_by_player.get(pid),
                "owned": pid in owner_by_player,
                "owner": owner_by_player.get(pid),
                "role_undecided": pid in undecided,
                "value": v["value"] if v else None,
                "estimated_value": v["estimated_value"] if v else None,
                "value_basis": v["basis"] if v else None,
                "appearances": v["n_cur"] if v else 0,
                "prev_appearances": v["n_prev"] if v else 0,
            })
        # Default order = the HOMOGENEOUS estimated value, so newcomers rank among
        # the rated players instead of forming an alphabetical tail. The frontend
        # also offers the measured-voto-then-market order.
        rows.sort(key=lambda x: (x["estimated_value"] is None,
                                 -(x["estimated_value"] or 0),
                                 -(x["market_value"] or 0), x["name"]))
        return Response({
            "value_season": str(prev_cs) if prev_cs else None,
            "current_season": str(cs),
            "count": len(rows),
            # How the market->voto estimate was calibrated (r = fit quality on the
            # players having both signals), so the UI can be honest about it.
            "value_fit": ({"intercept": round(fit[0], 3), "slope": round(fit[1], 3),
                           "r": round(fit[2], 3), "n": fit[3]} if fit else None),
            "players": rows,
        })
