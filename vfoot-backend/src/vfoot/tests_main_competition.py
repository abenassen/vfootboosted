"""Which competition a league means when nobody says.

The old answer was "the first round-robin BY ID" — whichever was created first —
and it was wrong in a way nothing on screen could reveal: a league with two
championships got one of the two, a league whose cup was created first got the cup,
and in both cases the page showed a table without naming it.

The rule now is THE MOST MATCHES, which measures the thing that makes a competition
principal: everybody plays everybody, twice, for a whole season.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from vfoot.models import (
    FantasyCompetition, FantasyFixture, FantasyLeague, FantasyTeam, LeagueMembership,
)
from vfoot.services.league_competitions import main_competition


class MainCompetitionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("boss", password="x")
        self.league = FantasyLeague.objects.create(name="L", owner=self.owner)
        membership = LeagueMembership.objects.create(
            league=self.league, user=self.owner, role=LeagueMembership.ROLE_ADMIN)
        self.a = FantasyTeam.objects.create(league=self.league, manager=membership, name="A")
        other = LeagueMembership.objects.create(
            league=self.league, user=User.objects.create_user("due", password="x"),
            role=LeagueMembership.ROLE_MANAGER)
        self.b = FantasyTeam.objects.create(league=self.league, manager=other, name="B")

    def _comp(self, name, kind=FantasyCompetition.TYPE_ROUND_ROBIN, matches=0):
        comp = FantasyCompetition.objects.create(
            league=self.league, name=name, competition_type=kind)
        for i in range(matches):
            FantasyFixture.objects.create(
                competition=comp, home_team=self.a, away_team=self.b,
                round_no=i + 1, leg_no=1)
        return comp

    def test_the_competition_with_more_matches_wins(self):
        """Created LATER and still principal. Creation order carried no meaning; it
        only decided the answer because nothing else was being looked at."""
        self._comp("Coppa breve", matches=3)
        championship = self._comp("Campionato", matches=38)
        self.assertEqual(main_competition(self.league), championship)

    def test_a_cup_created_first_does_not_win(self):
        """The case that used to be silently wrong: the cup came first by id, so the
        league's 'standings' were the cup's group table."""
        self._comp("Coppa", kind=FantasyCompetition.TYPE_KNOCKOUT, matches=7)
        championship = self._comp("Campionato", matches=38)
        self.assertEqual(main_competition(self.league), championship)

    def test_two_championships_pick_the_bigger_one(self):
        """The case the user asked about: ambiguity resolved by size, not by age."""
        self._comp("Campionato minore", matches=10)
        big = self._comp("Campionato maggiore", matches=38)
        self.assertEqual(main_competition(self.league), big)

    def test_a_tie_is_broken_by_age_and_is_stable(self):
        """Two round-robins of the same size are genuinely ambiguous, and no order
        here is more correct — what matters is that it does not change between two
        requests, or the page would flip tables on reload."""
        first = self._comp("Uno", matches=10)
        self._comp("Due", matches=10)
        self.assertEqual(main_competition(self.league), first)
        self.assertEqual(main_competition(self.league), first)

    def test_knockouts_only_still_answer(self):
        """Half an answer beats an empty page: the caller is told which competition
        it got, and can say so."""
        small = self._comp("Coppa piccola", kind=FantasyCompetition.TYPE_KNOCKOUT, matches=3)
        big = self._comp("Coppa grande", kind=FantasyCompetition.TYPE_KNOCKOUT, matches=15)
        self.assertEqual(main_competition(self.league), big)
        self.assertNotEqual(main_competition(self.league), small)

    def test_a_league_without_competitions_returns_none(self):
        self.assertIsNone(main_competition(self.league))

    def test_a_competition_without_fixtures_loses_to_one_with(self):
        """A container created and never filled is not the league's championship,
        however early it was made."""
        self._comp("Vuota", matches=0)
        played = self._comp("Vera", matches=5)
        self.assertEqual(main_competition(self.league), played)

    # --- the endpoint that had the guess inside it -------------------------

    def test_standings_default_to_the_principal_competition(self):
        self._comp("Coppa", kind=FantasyCompetition.TYPE_KNOCKOUT, matches=7)
        championship = self._comp("Campionato", matches=38)
        client = APIClient()
        client.force_authenticate(user=self.owner)
        res = client.get(f"/api/v1/leagues/{self.league.id}/standings")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["competition_id"], championship.id)

    def test_an_explicit_competition_still_wins_over_the_guess(self):
        cup = self._comp("Coppa", matches=3)
        self._comp("Campionato", matches=38)
        client = APIClient()
        client.force_authenticate(user=self.owner)
        res = client.get(
            f"/api/v1/leagues/{self.league.id}/standings?competition_id={cup.id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["competition_id"], cup.id)
