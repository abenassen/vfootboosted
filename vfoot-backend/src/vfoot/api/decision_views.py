"""API for the league decision queue: see, consult, vote, settle.

Split from league_views (already 2800 lines) because this is a self-contained
mechanism that other decision kinds will reuse.
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from vfoot.models import (
    FantasyLeague, LeagueDecision, LeagueDecisionVote, LeagueMembership,
)
from vfoot.services.league_decisions import (
    accept_all_proposals, attention_count, cast_vote, market_blocked_reason,
    open_role_decisions, resolve,
)


def _membership(league, user_id):
    m = LeagueMembership.objects.filter(league=league, user_id=user_id).first()
    if m is None:
        from django.http import Http404
        raise Http404("Not a member of this league")
    return m


def _is_admin(league, user_id) -> bool:
    m = LeagueMembership.objects.filter(league=league, user_id=user_id).first()
    return bool(m and m.role == LeagueMembership.ROLE_ADMIN) or league.owner_id == user_id


def _serialize(d: LeagueDecision, user) -> dict:
    my = LeagueDecisionVote.objects.filter(decision=d, user=user).first()
    return {
        "id": d.id, "kind": d.kind, "title": d.title, "question": d.question,
        "options": d.options, "proposed": d.proposed, "rationale": d.rationale,
        "blocks_market": d.blocks_market, "consultation_open": d.consultation_open,
        "status": d.status, "outcome": d.outcome,
        "player_id": d.player_id,
        "player_name": ((d.player.short_name or d.player.full_name)
                        if d.player_id else None),
        "my_vote": my.option if my else None,
        # The tally is shown to everyone: a consultation people cannot see the
        # result of is a survey, not a conversation.
        "tally": d.tally(),
        "votes_total": sum(d.tally().values()),
    }


class LeagueDecisionListView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _membership(league, request.user.id)
        qs = (LeagueDecision.objects.filter(league=league)
              .select_related("player").prefetch_related("votes"))
        if request.query_params.get("status", "open") != "all":
            qs = qs.filter(status=request.query_params.get("status", "open"))
        admin = _is_admin(league, request.user.id)
        items = [_serialize(d, request.user) for d in qs.order_by("-blocks_market", "id")]
        if not admin:
            # A member's queue is what he has been ASKED about; the admin's
            # sign-off backlog is not everyone's business.
            items = [i for i in items if i["consultation_open"] or i["status"] != "open"]
        return Response({
            "is_admin": admin,
            "blocked_reason": market_blocked_reason(league),
            "blocking_open": sum(1 for i in items
                                 if i["blocks_market"] and i["status"] == "open"),
            "attention": attention_count(league, request.user),
            "decisions": items,
        })


class LeagueDecisionVoteView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, league_id: int, decision_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _membership(league, request.user.id)
        d = get_object_or_404(LeagueDecision, id=decision_id, league=league)
        try:
            cast_vote(d, request.user, str(request.data.get("option", "")))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_serialize(d, request.user))


class LeagueDecisionResolveView(APIView):
    """Admin settles one decision. The members' votes are advisory, so nothing
    here reads the tally — it is the admin's call, on the record."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, league_id: int, decision_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        if not _is_admin(league, request.user.id):
            return Response({"detail": "Solo l'amministratore puo' decidere."},
                            status=status.HTTP_403_FORBIDDEN)
        d = get_object_or_404(LeagueDecision, id=decision_id, league=league)
        try:
            resolve(d, str(request.data.get("option", "")), user=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_serialize(d, request.user))


class LeagueDecisionConsultView(APIView):
    """Admin opens (or closes) a consultation on a decision, making it visible to
    every member with a notification."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, league_id: int, decision_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        if not _is_admin(league, request.user.id):
            return Response({"detail": "Solo l'amministratore puo' aprire una consultazione."},
                            status=status.HTTP_403_FORBIDDEN)
        d = get_object_or_404(LeagueDecision, id=decision_id, league=league)
        d.consultation_open = bool(request.data.get("open", True))
        d.save(update_fields=["consultation_open"])
        return Response(_serialize(d, request.user))


class LeagueDecisionAcceptAllView(APIView):
    """Accept the proposal on every open blocking decision that is not under
    consultation — the bulk sign-off that keeps a 49-item queue from being 49
    clicks."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        if not _is_admin(league, request.user.id):
            return Response({"detail": "Solo l'amministratore puo' decidere."},
                            status=status.HTTP_403_FORBIDDEN)
        n = accept_all_proposals(league, user=request.user)
        return Response({"resolved": n,
                         "blocked_reason": market_blocked_reason(league)})


class LeagueDecisionRefreshView(APIView):
    """Re-scan the listone for players that still need a human decision."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        if not _is_admin(league, request.user.id):
            return Response({"detail": "Solo l'amministratore."},
                            status=status.HTTP_403_FORBIDDEN)
        n = open_role_decisions(league, opened_by=request.user)
        return Response({"opened": n,
                         "blocked_reason": market_blocked_reason(league)})
