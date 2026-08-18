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

from realdata.models import Player
from vfoot.models import (
    FantasyLeague, LeagueDecision, LeagueMembership,
)
from vfoot.services.league_decisions import (
    accept_all_proposals, attention_count, cast_vote, market_blocked_reason,
    open_manual_decision, resolve, set_consultation,
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


def _voter_names(league) -> dict[int, str]:
    """user_id -> how this league knows him.

    The team name, because that is what people call each other inside a league;
    the username only for whoever has not named a team yet.
    """
    out = {}
    for m in (LeagueMembership.objects.filter(league=league)
              .select_related("user", "team")):
        team = getattr(m, "team", None)
        out[m.user_id] = (team.name if team else "") or m.user.username
    return out


def _voters_for(league, user_id) -> dict[int, str] | None:
    """The name map for an admin, None for everyone else.

    Which is the whole visibility rule: the tally is public, the names are not.
    The admin is the one who has to weigh the opinions and then answer for the
    decision, and an opinion whose author he cannot see is hard to weigh — a
    league of ten where three say "attaccante" is a different question depending
    on WHICH three. The members keep seeing the counts only, so nobody's vote is
    put on display in front of the people he is voting with.
    """
    return _voter_names(league) if _is_admin(league, user_id) else None


def _serialize(d: LeagueDecision, user, *, voter_names: dict | None = None) -> dict:
    # One pass over the votes for all three readings — the caller's own answer,
    # the counts, and the names. `d.votes.all()` rides the list view's prefetch,
    # where `LeagueDecision.tally()` would go back to the database per decision.
    votes = list(d.votes.all())
    my = next((v for v in votes if v.user_id == user.id), None)
    tally = {o.get("value"): 0 for o in d.options}
    for v in votes:
        tally[v.option] = tally.get(v.option, 0) + 1
    out = {
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
        "tally": tally,
        "votes_total": sum(tally.values()),
    }
    if voter_names is not None:
        by_option: dict[str, list[str]] = {o.get("value"): [] for o in d.options}
        for v in votes:
            name = voter_names.get(v.user_id)
            if name:
                by_option.setdefault(v.option, []).append(name)
        out["voters"] = {k: sorted(names, key=str.lower)
                         for k, names in by_option.items()}
    return out


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
        names = _voter_names(league) if admin else None
        items = [_serialize(d, request.user, voter_names=names)
                 for d in qs.order_by("-blocks_market", "id")]
        if not admin:
            # A member's queue is what he has been ASKED about; the admin's
            # sign-off backlog is not everyone's business.
            items = [i for i in items if i["consultation_open"] or i["status"] != "open"]
        return Response({
            "is_admin": admin,
            # Whether a listone exists here at all — the refresh only means
            # something in a classic league bound to a real season.
            "has_listone": (league.mode == FantasyLeague.MODE_CLASSIC
                            and league.reference_season_id is not None),
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
        return Response(_serialize(d, request.user,
                                   voter_names=_voters_for(league, request.user.id)))


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
        return Response(_serialize(d, request.user, voter_names=_voter_names(league)))


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
        try:
            set_consultation(d, bool(request.data.get("open", True)), user=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_serialize(d, request.user, voter_names=_voter_names(league)))


class LeagueDecisionOpenView(APIView):
    """Admin raises a question about a role the system considered settled.

    The counterpart of the queue: that one asks where WE are in doubt, this one
    where the league is. Same object, same consultation, same market gate — the
    only difference is who noticed.
    """

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        if not _is_admin(league, request.user.id):
            return Response({"detail": "Solo l'amministratore puo' aprire una domanda."},
                            status=status.HTTP_403_FORBIDDEN)
        player = get_object_or_404(Player, id=request.data.get("player_id"))
        try:
            decision, created = open_manual_decision(league, player,
                                                     opened_by=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({**_serialize(decision, request.user,
                                      voter_names=_voter_names(league)),
                         "created": created},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


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


# There was a LeagueDecisionRefreshView here (POST decisions/refresh), an on-demand
# re-run of snapshot_league_listone offered to the league admin. It was removed
# because it could not do anything: every input the snapshot reads — the roster
# stints, Player.classic_role_seed, CurrentPlayerRole — is written by
# import_transfermarkt_squads and by nothing else, and that import already
# snapshots every classic league on the season in the same run. Between two
# imports the endpoint recomputed the same answer from unchanged data.
#
# The remaining entry points are the ones tied to a real change of state: league
# creation, the Transfermarkt import, opening the market, opening an offer session.
# The single input that CAN move without an import is compute_classic_roles, a
# manual command with no timer — and whoever runs it also has
# `manage.py freeze_league_listone --league N`, which is this view's exact
# equivalent, on the same shell.
