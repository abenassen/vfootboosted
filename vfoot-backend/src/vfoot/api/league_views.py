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

from realdata.models import Match, Player
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
)
from vfoot.services.fantasy_simulation import (
    bulk_assign_players_to_teams,
    generate_knockout_fixtures,
    generate_round_robin_fixtures,
)
from vfoot.services.competition_stages import build_default_stage_graph, resolve_stage


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
        memberships = LeagueMembership.objects.filter(user=request.user).select_related("league", "team")
        data = []
        for m in memberships:
            data.append(
                {
                    "league_id": m.league_id,
                    "name": m.league.name,
                    "role": m.role,
                    "invite_code": m.league.invite_code,
                    "market_open": m.league.market_open,
                    "team_name": m.team.name if hasattr(m, "team") else None,
                }
            )
        return Response(data)

    @transaction.atomic
    def post(self, request):
        s = CreateLeagueSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        league = FantasyLeague.objects.create(name=data["name"], owner=request.user)
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
            return Response({"detail": "Already joined."}, status=status.HTTP_200_OK)

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

        return Response(
            {
                "league_id": league.id,
                "name": league.name,
                "market_open": league.market_open,
                "invite_code": league.invite_code,
                "invite_link": f"/join/{league.invite_code}",
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
                    }
                    for t in teams
                ],
            }
        )


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
                    {"detail": "Cannot remove the last admin from the league."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        target.role = new_role
        target.save(update_fields=["role"])

        return Response({"membership_id": target.id, "role": target.role})


class MarketToggleView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)
        s = MarketToggleSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        league.market_open = s.validated_data["is_open"]
        league.save(update_fields=["market_open"])
        return Response({"league_id": league.id, "market_open": league.market_open})


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
        "status": comp.status,
        "points": {
            "win": comp.points_win,
            "draw": comp.points_draw,
            "loss": comp.points_loss,
        },
        "starts_at": comp.starts_at.isoformat() if comp.starts_at else None,
        "ends_at": comp.ends_at.isoformat() if comp.ends_at else None,
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
        for field in ["name", "stage_type", "order_index"]:
            if field in data:
                setattr(stage, field, data[field])
                changed_fields.append(field)
        if changed_fields:
            stage.save(update_fields=changed_fields)

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


def _source_fixtures_for_stage(source_comp: FantasyCompetition, stage: str):
    qs = FantasyFixture.objects.filter(competition=source_comp, status=FantasyFixture.STATUS_FINISHED)
    if stage == CompetitionQualificationRule.STAGE_HALF:
        max_round = FantasyFixture.objects.filter(competition=source_comp).order_by("-round_no").values_list("round_no", flat=True).first()
        if max_round:
            qs = qs.filter(round_no__lte=max(1, max_round // 2))
    return qs


def _table_ranking_team_ids(source_comp: FantasyCompetition, stage: str) -> list[int]:
    rows: dict[int, dict] = {}
    fixtures = _source_fixtures_for_stage(source_comp, stage)
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


def _winner_loser_from_source(source_comp: FantasyCompetition, stage: str, mode: str) -> list[int]:
    ranking = _table_ranking_team_ids(source_comp, stage)
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
            ranking = _table_ranking_team_ids(source, rule.source_stage)
            if not ranking:
                unresolved_rules += 1
                continue
            rf = max(1, rule.rank_from or 1)
            rt = max(rf, rule.rank_to or rf)
            ids = ranking[rf - 1 : rt]
        else:
            ids = _winner_loser_from_source(source, rule.source_stage, rule.mode)
            if not ids:
                unresolved_rules += 1
                continue
        for tid in ids:
            if tid not in manual_ids and tid not in resolved_ids:
                resolved_ids.add(tid)
                CompetitionTeam.objects.create(competition=competition, team_id=tid, source=CompetitionTeam.SOURCE_RULE)

    participants = list(CompetitionTeam.objects.filter(competition=competition).values_list("team_id", flat=True))
    fixtures_created = 0
    if len(participants) >= 2 and (competition.competition_type != FantasyCompetition.TYPE_KNOCKOUT or len(participants) % 2 == 0):
        if competition.competition_type == FantasyCompetition.TYPE_ROUND_ROBIN:
            fixtures_created = generate_round_robin_fixtures(competition)
        else:
            fixtures_created = generate_knockout_fixtures(competition)

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


def _serialize_fixture_row(fx: FantasyFixture, my_team_id: int | None) -> dict:
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

        items = [_serialize_fixture_row(fx, my_team_id) for fx in qs[:200]]
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


def _schedule_preview(comp: FantasyCompetition, starts_at=None, ends_at=None) -> dict:
    if starts_at is None:
        starts_at = comp.starts_at
    if ends_at is None:
        ends_at = comp.ends_at
    round_nos = _competition_round_nos(comp)
    csid, real_matchdays = _pick_real_competition_and_matchdays(starts_at, ends_at)
    uniform = _build_uniform_round_mapping(round_nos, real_matchdays)
    current = _current_round_mapping(comp)
    return {
        "competition_id": comp.id,
        "competition_name": comp.name,
        "starts_at": starts_at.isoformat() if starts_at else None,
        "ends_at": ends_at.isoformat() if ends_at else None,
        "rounds": round_nos,
        "available_real_matchdays": real_matchdays,
        "real_competition_season_id": csid,
        "proposed_mapping": uniform,
        "current_mapping": current,
    }


@transaction.atomic
def _schedule_competition_rounds(comp: FantasyCompetition, round_mapping: dict[int, int] | None = None) -> dict:
    round_nos = _competition_round_nos(comp)
    if not round_nos:
        return {"competition_id": comp.id, "scheduled_fixtures": 0, "rounds": 0, "real_matchdays": []}

    csid, real_matchdays = _pick_real_competition_and_matchdays(comp.starts_at, comp.ends_at)
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
        payload = []
        for md in rows:
            real_stats = _real_matchday_stats(md.real_competition_season_id, md.real_matchday)
            fx_total = md.fixtures.count()
            fx_finished = md.fixtures.filter(status=FantasyFixture.STATUS_FINISHED).count()
            payload.append(
                {
                    "fantasy_matchday_id": md.id,
                    "league_id": league.id,
                    "status": md.status,
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

        for field in ["name", "status", "points_win", "points_draw", "points_loss", "starts_at", "ends_at"]:
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

        changed = False
        if "starts_at" in data:
            comp.starts_at = data["starts_at"]
            changed = True
        if "ends_at" in data:
            comp.ends_at = data["ends_at"]
            changed = True
        if changed:
            comp.save(update_fields=["starts_at", "ends_at"])

        if not comp.starts_at or not comp.ends_at:
            return Response(
                {"detail": "Competition starts_at and ends_at must be set before scheduling."},
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
        result = _schedule_competition_rounds(comp, round_mapping=parsed_mapping or None)
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
        starts_at = data.get("starts_at", comp.starts_at)
        ends_at = data.get("ends_at", comp.ends_at)
        return Response(_schedule_preview(comp, starts_at=starts_at, ends_at=ends_at))


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
