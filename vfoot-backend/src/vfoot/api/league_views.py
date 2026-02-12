from __future__ import annotations

import csv
import io
from random import Random

from django.db import transaction
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
    CompetitionTemplateSerializer,
    CreateAuctionSerializer,
    CreateLeagueSerializer,
    ImportRosterCSVSerializer,
    JoinLeagueSerializer,
    MarketToggleSerializer,
    PlaceBidSerializer,
    RemoveRosterPlayerSerializer,
    UpdateMemberRoleSerializer,
)
from vfoot.models import (
    AuctionBid,
    AuctionNomination,
    AuctionSession,
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

        target.role = s.validated_data["role"]
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

        count = bulk_assign_players_to_teams(
            league_id=league.id,
            player_ids=data["player_ids"],
            purchase_price=data["purchase_price"],
            random_seed=data["random_seed"],
        )
        return Response({"assigned_players": count})


class LeagueRosterImportCSVView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _ensure_admin(league, request.user.id)
        if not league.market_open:
            return Response({"detail": "Market is closed."}, status=status.HTTP_400_BAD_REQUEST)

        s = ImportRosterCSVSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        csv_text = s.validated_data.get("csv_text", "")
        if not csv_text and "file" in request.FILES:
            csv_text = request.FILES["file"].read().decode("utf-8")
        if not csv_text.strip():
            return Response({"detail": "No CSV content provided."}, status=status.HTTP_400_BAD_REQUEST)

        reader = csv.DictReader(io.StringIO(csv_text))
        required = {"team_name", "player_id", "price"}
        if not required.issubset(set(reader.fieldnames or [])):
            return Response({"detail": "CSV headers must include team_name,player_id,price"}, status=status.HTTP_400_BAD_REQUEST)

        teams = {t.name: t for t in FantasyTeam.objects.filter(league=league)}
        created = 0
        for row in reader:
            team = teams.get((row.get("team_name") or "").strip())
            if not team:
                continue
            try:
                player_id = int(row.get("player_id", "0"))
                price = int(row.get("price", "1"))
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

        comp = FantasyCompetition.objects.create(
            league=league,
            name=data["name"],
            competition_type=data["competition_type"],
            status=FantasyCompetition.STATUS_ACTIVE,
        )

        team_ids = data.get("team_ids") or list(FantasyTeam.objects.filter(league=league).values_list("id", flat=True))
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
