from __future__ import annotations

import csv
import io
from random import Random

from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from realdata.models import Player
from vfoot.api.league_serializers import (
    AddRosterPlayerSerializer,
    BulkAssignRosterSerializer,
    CompetitionUpdateSerializer,
    CompetitionTemplateSerializer,
    CreateAuctionSerializer,
    CreateLeagueSerializer,
    ImportRosterCSVSerializer,
    JoinLeagueSerializer,
    MarketToggleSerializer,
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
    CompetitionTeam,
    FantasyCompetition,
    FantasyFixture,
    FantasyLeague,
    FantasyRosterSlot,
    FantasyTeam,
    LeagueMembership,
)
from vfoot.services.fantasy_simulation import (
    bulk_assign_players_to_teams,
    generate_knockout_fixtures,
    generate_round_robin_fixtures,
)


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
        memberships = LeagueMembership.objects.filter(user=request.user).select_related("league")
        data = []
        for m in memberships:
            data.append(
                {
                    "league_id": m.league_id,
                    "name": m.league.name,
                    "role": m.role,
                    "invite_code": m.league.invite_code,
                    "market_open": m.league.market_open,
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
            status=FantasyCompetition.STATUS_ACTIVE,
        )

        team_ids = data.get("team_ids")
        if team_ids is None:
            team_ids = list(FantasyTeam.objects.filter(league=league).values_list("id", flat=True))
        entries = [CompetitionTeam(competition=comp, team_id=tid) for tid in team_ids]
        CompetitionTeam.objects.bulk_create(entries)

        if comp.competition_type == FantasyCompetition.TYPE_ROUND_ROBIN:
            fixtures = generate_round_robin_fixtures(comp)
        else:
            fixtures = generate_knockout_fixtures(comp)

        return Response(
            {
                "competition_id": comp.id,
                "name": comp.name,
                "competition_type": comp.competition_type,
                "participants": len(team_ids),
                "fixtures_created": fixtures,
            },
            status=status.HTTP_201_CREATED,
        )


def _serialize_competition(comp: FantasyCompetition) -> dict:
    participants = list(comp.participants.select_related("team", "team__manager__user"))
    rules = list(comp.qualification_rules.select_related("source_competition"))
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
        "fixtures": {"total": fixture_count, "finished": finished_count},
    }


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
            .prefetch_related("participants__team__manager__user", "qualification_rules__source_competition", "fixtures")
            .order_by("id")
        )
        return Response([_serialize_competition(c) for c in comps])


def _serialize_fixture_row(fx: FantasyFixture, my_team_id: int | None) -> dict:
    return {
        "fixture_id": fx.id,
        "competition_id": fx.competition_id,
        "competition_name": fx.competition.name,
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
            .select_related("competition", "home_team", "away_team")
            .order_by("-kickoff", "-id")
        )
        competition_id = request.query_params.get("competition_id")
        if competition_id and str(competition_id).isdigit():
            qs = qs.filter(competition_id=int(competition_id))

        items = [_serialize_fixture_row(fx, my_team_id) for fx in qs[:200]]
        return Response(items)


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

        for field in ["name", "status", "points_win", "points_draw", "points_loss"]:
            if field in data:
                setattr(comp, field, data[field])
        comp.save()

        # If a source competition advances/completes, refresh dependents.
        if "status" in data and data["status"] in [FantasyCompetition.STATUS_ACTIVE, FantasyCompetition.STATUS_DONE]:
            dependents = FantasyCompetition.objects.filter(qualification_rules__source_competition=comp).distinct()
            for dep in dependents:
                _resolve_rule_participants_and_regenerate(dep)
        return Response(_serialize_competition(comp))


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
