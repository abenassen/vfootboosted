"""Tests for a team's own identity: renaming it and giving it a crest.

Both live on the LEAGUE, not on the user profile: the avatar identifies the
manager and there is one per account, while name and crest belong to one team in
one league.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from vfoot.models import (
    FantasyCompetition, FantasyFixture, FantasyLeague, FantasyTeam, LeagueMembership,
)


class MyTeamIdentityTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("boss", password="x")
        self.other = User.objects.create_user("gregario", password="x")
        self.stranger = User.objects.create_user("estraneo", password="x")

        self.league = FantasyLeague.objects.create(name="L", owner=self.owner)
        self.my_membership = LeagueMembership.objects.create(
            league=self.league, user=self.owner, role=LeagueMembership.ROLE_ADMIN)
        self.other_membership = LeagueMembership.objects.create(
            league=self.league, user=self.other, role=LeagueMembership.ROLE_MANAGER)

        self.team = FantasyTeam.objects.create(
            league=self.league, manager=self.my_membership, name="Vecchio Nome")
        self.other_team = FantasyTeam.objects.create(
            league=self.league, manager=self.other_membership, name="Rivali FC")

        self.client = APIClient()

    def _as(self, user) -> APIClient:
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _url(self, league=None) -> str:
        return f"/api/v1/leagues/{(league or self.league).id}/team"

    # --- renaming ---------------------------------------------------------

    def test_rename_own_team(self):
        res = self._as(self.owner).patch(self._url(), {"name": "Nuovo Nome"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, "Nuovo Nome")
        self.assertEqual(res.json()["name"], "Nuovo Nome")

    def test_rename_trims_whitespace(self):
        res = self._as(self.owner).patch(self._url(), {"name": "  Spaziosi  "}, format="json")
        self.assertEqual(res.status_code, 200)
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, "Spaziosi")

    def test_blank_name_is_rejected(self):
        res = self._as(self.owner).patch(self._url(), {"name": "   "}, format="json")
        self.assertEqual(res.status_code, 400)
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, "Vecchio Nome")

    def test_duplicate_name_is_a_400_not_a_500(self):
        """unique_together (league, name) would otherwise surface as an
        IntegrityError — a server error for something the user can fix."""
        res = self._as(self.owner).patch(self._url(), {"name": "Rivali FC"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("name", res.json())
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, "Vecchio Nome")

    def test_duplicate_name_is_caught_case_insensitively(self):
        """The database would accept "rivali fc" next to "Rivali FC"; two teams
        that differ only in case are indistinguishable in a standings table."""
        res = self._as(self.owner).patch(self._url(), {"name": "rivali fc"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_keeping_own_name_is_not_a_clash(self):
        res = self._as(self.owner).patch(self._url(), {"name": "Vecchio Nome"}, format="json")
        self.assertEqual(res.status_code, 200)

    # --- crest ------------------------------------------------------------

    def test_set_and_clear_crest(self):
        descriptor = '{"shape":"shield","pattern":"stripes","primary":"1e3a8a"}'
        res = self._as(self.owner).patch(self._url(), {"crest": descriptor}, format="json")
        self.assertEqual(res.status_code, 200)
        self.team.refresh_from_db()
        self.assertEqual(self.team.crest, descriptor)

        # Blank is meaningful: it means "back to the crest drawn from the name".
        res = self._as(self.owner).patch(self._url(), {"crest": ""}, format="json")
        self.assertEqual(res.status_code, 200)
        self.team.refresh_from_db()
        self.assertEqual(self.team.crest, "")

    def test_crest_is_opaque_to_the_server(self):
        """The SPA owns the schema; the server stores and echoes it back. This is
        what lets new crest options ship without a migration."""
        res = self._as(self.owner).patch(self._url(), {"crest": "non-json-affatto"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.team.refresh_from_db()
        self.assertEqual(self.team.crest, "non-json-affatto")

    def test_saving_a_crest_does_not_touch_the_name(self):
        self._as(self.owner).patch(self._url(), {"crest": "{}"}, format="json")
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, "Vecchio Nome")

    # --- who may do it ----------------------------------------------------

    def test_a_stranger_gets_404(self):
        res = self._as(self.stranger).patch(self._url(), {"name": "Mia"}, format="json")
        self.assertEqual(res.status_code, 404)
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, "Vecchio Nome")

    def test_a_member_edits_only_his_own_team(self):
        """There is no team id in the request: the endpoint resolves it from the
        caller's membership, so an admin cannot rename someone else's team here."""
        res = self._as(self.other).patch(self._url(), {"name": "Rinominata"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.other_team.refresh_from_db()
        self.team.refresh_from_db()
        self.assertEqual(self.other_team.name, "Rinominata")
        self.assertEqual(self.team.name, "Vecchio Nome")

    def test_anonymous_is_rejected(self):
        res = APIClient().patch(self._url(), {"name": "Mia"}, format="json")
        self.assertIn(res.status_code, (401, 403))

    def test_member_without_a_team_gets_404(self):
        loner = User.objects.create_user("senzasquadra", password="x")
        LeagueMembership.objects.create(
            league=self.league, user=loner, role=LeagueMembership.ROLE_MANAGER)
        res = self._as(loner).patch(self._url(), {"name": "Fantasma"}, format="json")
        self.assertEqual(res.status_code, 404)

    # --- the crest travels with the payloads the UI reads -----------------

    def test_league_list_carries_the_crest(self):
        self.team.crest = '{"shape":"circle"}'
        self.team.save(update_fields=["crest"])
        res = self._as(self.owner).get("/api/v1/leagues")
        self.assertEqual(res.status_code, 200)
        row = next(r for r in res.json() if r["league_id"] == self.league.id)
        self.assertEqual(row["team_crest"], '{"shape":"circle"}')

    def test_standings_carry_the_crest(self):
        """The standings rows are built by a block that DUPLICATES
        _compute_standings(). The crest was added to one and not the other, and
        nothing failed — the column simply came back empty. This is the test that
        would have caught it."""
        comp = FantasyCompetition.objects.create(league=self.league, name="Campionato")
        self.team.crest = '{"shape":"shield"}'
        self.team.save(update_fields=["crest"])
        FantasyFixture.objects.create(
            competition=comp, home_team=self.team, away_team=self.other_team,
            round_no=1, leg_no=1, status=FantasyFixture.STATUS_FINISHED,
            home_total=2, away_total=1)

        res = self._as(self.owner).get(f"/api/v1/leagues/{self.league.id}/standings")
        self.assertEqual(res.status_code, 200)
        by_name = {r["team"]: r for r in res.json()["standings"]}
        self.assertEqual(by_name["Vecchio Nome"]["crest"], '{"shape":"shield"}')
        self.assertEqual(by_name["Rivali FC"]["crest"], "")

    def test_fixtures_carry_the_crest(self):
        comp = FantasyCompetition.objects.create(league=self.league, name="Campionato")
        self.other_team.crest = '{"shape":"circle"}'
        self.other_team.save(update_fields=["crest"])
        FantasyFixture.objects.create(
            competition=comp, home_team=self.team, away_team=self.other_team,
            round_no=1, leg_no=1, status=FantasyFixture.STATUS_SCHEDULED)

        res = self._as(self.owner).get(f"/api/v1/leagues/{self.league.id}/fixtures")
        self.assertEqual(res.status_code, 200)
        fixture = res.json()[0]
        self.assertEqual(fixture["away_team"]["crest"], '{"shape":"circle"}')
        self.assertEqual(fixture["home_team"]["crest"], "")

    def test_league_detail_carries_the_crest_of_every_team(self):
        self.other_team.crest = '{"shape":"pennant"}'
        self.other_team.save(update_fields=["crest"])
        res = self._as(self.owner).get(f"/api/v1/leagues/{self.league.id}")
        self.assertEqual(res.status_code, 200)
        crests = {t["name"]: t["crest"] for t in res.json()["teams"]}
        self.assertEqual(crests["Rivali FC"], '{"shape":"pennant"}')
        self.assertEqual(crests["Vecchio Nome"], "")
