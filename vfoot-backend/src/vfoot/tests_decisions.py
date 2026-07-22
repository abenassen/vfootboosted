"""Tests for the league decision queue and the market gate."""
from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from realdata.models import (
    Competition, CompetitionSeason, Player, PlayerTeamStint, Season, Team, TeamSeason,
)
from vfoot.models import (
    FantasyLeague, LeagueDecision, LeagueMembership, LeaguePlayerRole,
    SeasonPlayerRole,
)
from vfoot.services.league_decisions import (
    accept_all_proposals, attention_count, cast_vote, market_blocked_reason,
    open_role_decisions, resolve,
)


class DecisionQueueTests(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        self.ts = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Torino"))
        self.admin = User.objects.create_user("boss", password="x")
        self.member = User.objects.create_user("gregario", password="x")
        self.league = FantasyLeague.objects.create(
            name="L", owner=self.admin, mode="classic", reference_season=self.cs)
        for u, role in ((self.admin, LeagueMembership.ROLE_ADMIN),
                        (self.member, LeagueMembership.ROLE_MANAGER)):
            LeagueMembership.objects.create(league=self.league, user=u, role=role)

    def _player(self, name, *, method, tm_position="left winger", role="CEN"):
        p = Player.objects.create(full_name=name, short_name=name)
        PlayerTeamStint.objects.create(player=p, team_season=self.ts,
                                       tm_position=tm_position)
        SeasonPlayerRole.objects.create(
            competition_season=self.cs, player=p, method=method,
            tm_position=tm_position, role_data=role, role_mitigated=role)
        return p

    def test_only_unmeasurable_ambiguous_players_become_decisions(self):
        self._player("Misurato", method=SeasonPlayerRole.METHOD_CATEGORY)
        self._player("Centrale", method=SeasonPlayerRole.METHOD_TM,
                     tm_position="centre-back", role="DIF")
        newcomer = self._player("Esordiente", method=SeasonPlayerRole.METHOD_DEFAULT)

        self.assertEqual(open_role_decisions(self.league), 1)
        d = LeagueDecision.objects.get(league=self.league)
        self.assertEqual(d.player_id, newcomer.id)
        self.assertTrue(d.blocks_market)
        self.assertEqual(d.proposed, "CEN")
        self.assertIn("Nessun dato", d.rationale)

    def test_reseeding_does_not_duplicate_or_reopen(self):
        self._player("Esordiente", method=SeasonPlayerRole.METHOD_DEFAULT)
        self.assertEqual(open_role_decisions(self.league), 1)
        self.assertEqual(open_role_decisions(self.league), 0)
        resolve(LeagueDecision.objects.get(league=self.league), "ATT", user=self.admin)
        # a question already answered must not come back
        self.assertEqual(open_role_decisions(self.league), 0)
        self.assertEqual(LeagueDecision.objects.filter(league=self.league).count(), 1)

    def test_market_is_blocked_until_the_queue_is_empty(self):
        self._player("Esordiente", method=SeasonPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)
        self.assertIsNotNone(market_blocked_reason(self.league))
        resolve(LeagueDecision.objects.get(league=self.league), "ATT", user=self.admin)
        self.assertIsNone(market_blocked_reason(self.league))

    def test_resolving_writes_the_frozen_league_role_as_an_admin_choice(self):
        p = self._player("Esordiente", method=SeasonPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)
        resolve(LeagueDecision.objects.get(league=self.league), "ATT", user=self.admin)
        row = LeaguePlayerRole.objects.get(league=self.league, player=p)
        self.assertEqual(row.role, "ATT")
        self.assertEqual(row.source, LeaguePlayerRole.SOURCE_ADMIN)

    def test_an_outcome_outside_the_offered_options_is_refused(self):
        self._player("Esordiente", method=SeasonPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)
        d = LeagueDecision.objects.get(league=self.league)
        with self.assertRaises(ValueError):
            resolve(d, "POR", user=self.admin)   # keepers are not on offer
        with self.assertRaises(ValueError):
            resolve(d, "", user=self.admin)

    def test_bulk_accept_skips_decisions_under_consultation(self):
        """Otherwise a bulk sign-off would quietly overrule a consultation the
        admin himself opened and members are still answering."""
        self._player("Uno", method=SeasonPlayerRole.METHOD_DEFAULT)
        self._player("Due", method=SeasonPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)
        d = LeagueDecision.objects.filter(league=self.league).first()
        d.consultation_open = True
        d.save(update_fields=["consultation_open"])

        self.assertEqual(accept_all_proposals(self.league, user=self.admin), 1)
        d.refresh_from_db()
        self.assertEqual(d.status, LeagueDecision.STATUS_OPEN)
        self.assertIsNotNone(market_blocked_reason(self.league))

    def test_members_only_see_and_are_notified_of_consultations(self):
        self._player("Uno", method=SeasonPlayerRole.METHOD_DEFAULT)
        self._player("Due", method=SeasonPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)
        self.assertEqual(attention_count(self.league, self.member), 0)

        d = LeagueDecision.objects.filter(league=self.league).first()
        d.consultation_open = True
        d.save(update_fields=["consultation_open"])
        self.assertEqual(attention_count(self.league, self.member), 1)

        cast_vote(d, self.member, "ATT")
        self.assertEqual(attention_count(self.league, self.member), 0)
        self.assertEqual(d.tally()["ATT"], 1)

    def test_voting_needs_an_open_consultation_and_membership(self):
        self._player("Uno", method=SeasonPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)
        d = LeagueDecision.objects.get(league=self.league)
        with self.assertRaises(ValueError):
            cast_vote(d, self.member, "ATT")          # not consulted yet
        d.consultation_open = True
        d.save(update_fields=["consultation_open"])
        outsider = User.objects.create_user("estraneo", password="x")
        with self.assertRaises(ValueError):
            cast_vote(d, outsider, "ATT")

    def test_votes_are_advisory_the_admin_may_decide_otherwise(self):
        self._player("Uno", method=SeasonPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)
        d = LeagueDecision.objects.get(league=self.league)
        d.consultation_open = True
        d.save(update_fields=["consultation_open"])
        cast_vote(d, self.member, "ATT")
        cast_vote(d, self.admin, "ATT")
        resolve(d, "DIF", user=self.admin)
        self.assertEqual(d.outcome, "DIF")


class DecisionApiTests(DecisionQueueTests):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_market_cannot_be_opened_while_decisions_are_pending(self):
        self._player("Esordiente", method=SeasonPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)
        self.client.force_authenticate(user=self.admin)
        r = self.client.patch(f"/api/v1/leagues/{self.league.id}/market",
                              {"is_open": True}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "pending_decisions")

        r = self.client.post(
            f"/api/v1/leagues/{self.league.id}/decisions/accept-all", format="json")
        self.assertEqual(r.json()["resolved"], 1)
        r = self.client.patch(f"/api/v1/leagues/{self.league.id}/market",
                              {"is_open": True}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_member_cannot_resolve_but_can_vote_once_consulted(self):
        self._player("Uno", method=SeasonPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)
        d = LeagueDecision.objects.get(league=self.league)
        self.client.force_authenticate(user=self.member)
        r = self.client.post(
            f"/api/v1/leagues/{self.league.id}/decisions/{d.id}/resolve",
            {"option": "ATT"}, format="json")
        self.assertEqual(r.status_code, 403)

        self.client.force_authenticate(user=self.admin)
        self.client.post(f"/api/v1/leagues/{self.league.id}/decisions/{d.id}/consult",
                         {"open": True}, format="json")
        self.client.force_authenticate(user=self.member)
        r = self.client.post(f"/api/v1/leagues/{self.league.id}/decisions/{d.id}/vote",
                             {"option": "ATT"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["my_vote"], "ATT")

    def test_list_hides_the_admin_backlog_from_members(self):
        self._player("Uno", method=SeasonPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)
        self.client.force_authenticate(user=self.member)
        body = self.client.get(f"/api/v1/leagues/{self.league.id}/decisions").json()
        self.assertFalse(body["is_admin"])
        self.assertEqual(body["decisions"], [])
        self.client.force_authenticate(user=self.admin)
        body = self.client.get(f"/api/v1/leagues/{self.league.id}/decisions").json()
        self.assertTrue(body["is_admin"])
        self.assertEqual(len(body["decisions"]), 1)
        self.assertIsNotNone(body["blocked_reason"])
