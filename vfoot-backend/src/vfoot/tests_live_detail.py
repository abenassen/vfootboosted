"""The tabellino of a league fixture while its matchday is still being played.

Two claims worth pinning down, because both are easy to break by accident:

* the round in progress ANSWERS — with votes, computed on the spot — instead of the
  404 it used to give until the admin concluded;
* it answers WITHOUT PERSISTING. The frozen payload is born at the conclusion and
  only there; a provisional one written into ``FantasyFixtureDetail`` would destroy
  the property that reopening a closed matchday is pure reading.

And the distinction the live view exists for: a player whose club has not kicked off
is NOT the same as one whose club is playing. The first has nothing to show and the
bench must not cover him; the second has a vote that is simply going to move.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dttz

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from realdata.models import (
    Competition, CompetitionSeason, Match, Player, PlayerTeamStint, Season, Team,
    TeamSeason,
)
from vfoot.models import (
    FantasyCompetition, FantasyFixture, FantasyFixtureDetail, FantasyLeague,
    FantasyMatchday, FantasyTeam, LeagueMembership, SavedLineupSnapshot,
)
from vfoot.services.classic_matchday_scoring import _live_states, _mark_unstable

SAT = datetime(2027, 1, 30, 14, 0, tzinfo=dttz.utc)


class LiveDetailTests(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        self.user = User.objects.create_user("mario", "m@x.it", "pw")
        self.league = FantasyLeague.objects.create(
            name="Lega", owner=self.user, mode=FantasyLeague.MODE_CLASSIC,
            reference_season=self.cs)
        self.membership = LeagueMembership.objects.create(
            league=self.league, user=self.user, role=LeagueMembership.ROLE_ADMIN)
        other = User.objects.create_user("luigi", "l@x.it", "pw")
        other_m = LeagueMembership.objects.create(league=self.league, user=other)
        self.mine = FantasyTeam.objects.create(
            league=self.league, manager=self.membership, name="I Miei")
        self.theirs = FantasyTeam.objects.create(
            league=self.league, manager=other_m, name="I Loro")

        # Two real clubs: one playing right now, one kicking off tonight.
        self.playing = self._club("Napoli"), self._club("Inter")
        self.later = self._club("Lazio"), self._club("Roma")
        self.live_match = Match.objects.create(
            competition_season=self.cs, matchday=22, kickoff=SAT,
            kickoff_provisional=False, home_team=self.playing[0],
            away_team=self.playing[1], status=Match.STATUS_LIVE, data_ready=False,
            home_goals=1, away_goals=0,
            external_source="sofascore", external_id="900")
        self.later_match = Match.objects.create(
            competition_season=self.cs, matchday=22, kickoff=SAT + timedelta(hours=6),
            kickoff_provisional=False, home_team=self.later[0],
            away_team=self.later[1], status=Match.STATUS_SCHEDULED, data_ready=False,
            external_source="sofascore", external_id="901")

        self.md = FantasyMatchday.objects.create(
            league=self.league, real_competition_season=self.cs, real_matchday=22)
        self.competition = FantasyCompetition.objects.create(
            league=self.league, name="Campionato")
        self.fixture = FantasyFixture.objects.create(
            competition=self.competition, fantasy_matchday=self.md, round_no=22,
            home_team=self.mine, away_team=self.theirs)

        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.user).key}")

    def _club(self, name: str) -> TeamSeason:
        return TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name=name))

    def _player(self, name: str, club: TeamSeason) -> Player:
        p = Player.objects.create(full_name=name)
        PlayerTeamStint.objects.create(player=p, team_season=club)
        return p

    # -- the two ways a vote can fail to be final --------------------------- #
    def test_a_club_in_the_field_is_unstable_and_one_still_to_play_is_not_started(self):
        on_pitch = self._player("In Campo", self.playing[0])
        tonight = self._player("Stasera", self.later[0])
        not_started, unstable = _live_states(
            self.cs.id, 22, [on_pitch.id, tonight.id])
        self.assertEqual(unstable, {on_pitch.id})
        self.assertEqual(not_started, {tonight.id})

    def test_a_settled_match_is_neither(self):
        p = self._player("Ieri", self.playing[0])
        Match.objects.filter(id=self.live_match.id).update(
            status=Match.STATUS_FINISHED, data_ready=True)
        not_started, unstable = _live_states(self.cs.id, 22, [p.id])
        self.assertEqual((not_started, unstable), (set(), set()))

    def test_full_time_is_still_unstable_until_the_data_settles(self):
        """data_ready, not the status, is the marker — the provider goes on
        correcting a match for an hour after the whistle."""
        p = self._player("Finito", self.playing[0])
        Match.objects.filter(id=self.live_match.id).update(
            status=Match.STATUS_FINISHED, data_ready=False)
        _not_started, unstable = _live_states(self.cs.id, 22, [p.id])
        self.assertEqual(unstable, {p.id})

    def test_one_unstable_line_makes_the_whole_team_total_provisional(self):
        team = {"starters": [{"player_id": 1}, {"player_id": 2}], "bench": []}
        self.assertTrue(_mark_unstable(team, {2}))
        self.assertTrue(team["provisional"])
        self.assertNotIn("provisional", team["starters"][0])
        self.assertTrue(team["starters"][1]["provisional"])

    def test_an_imposed_vote_is_never_marked_provisional(self):
        """The league has ruled; nothing the provider does afterwards moves it."""
        team = {"starters": [{"player_id": 1, "office": True}], "bench": []}
        self.assertFalse(_mark_unstable(team, {1}))
        self.assertFalse(team["provisional"])

    # -- the endpoint -------------------------------------------------------- #
    def test_a_round_in_progress_answers_and_persists_nothing(self):
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="22",
            lineup_id=f"team{self.mine.id}",
            gk_player_id=str(self._player("Portiere", self.playing[0]).id),
            starter_player_ids=[self._player("Attaccante", self.playing[1]).id],
            bench_player_ids=[])
        res = self.client.get(f"/api/v1/fixtures/{self.fixture.id}")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["live"])
        self.assertEqual(res.data["real_matchday"], 22)
        # The one thing it must NOT do.
        self.assertFalse(FantasyFixtureDetail.objects.filter(
            fixture=self.fixture).exists())

    def test_a_concluded_matchday_without_a_payload_is_still_a_404(self):
        self.md.status = FantasyMatchday.STATUS_CONCLUDED
        self.md.save(update_fields=["status"])
        res = self.client.get(f"/api/v1/fixtures/{self.fixture.id}")
        self.assertEqual(res.status_code, 404)

    def test_the_frozen_payload_wins_when_there_is_one(self):
        FantasyFixtureDetail.objects.create(
            fixture=self.fixture, vfoot_home=1.0, vfoot_away=2.0,
            payload={"mode": "classic", "frozen": True})
        res = self.client.get(f"/api/v1/fixtures/{self.fixture.id}")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["frozen"])
