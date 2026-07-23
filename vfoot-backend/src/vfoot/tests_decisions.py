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
    open_role_decisions, resolve, unavailable_players, undecided_player_ids,
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

    def test_only_the_undecided_player_is_in_limbo(self):
        """Per PLAYER, not per league: a single January signing must not stop
        everyone else in the league from trading."""
        ok = self._player("Deciso", method=SeasonPlayerRole.METHOD_TM,
                          tm_position="centre-back", role="DIF")
        pending = self._player("Esordiente", method=SeasonPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)

        self.assertEqual(undecided_player_ids(self.league), {pending.id})
        self.assertEqual(unavailable_players(self.league, [ok.id]), [])
        self.assertEqual(len(unavailable_players(self.league, [ok.id, pending.id])), 1)
        self.assertIsNotNone(market_blocked_reason(self.league))   # avviso, non blocco

        resolve(LeagueDecision.objects.get(league=self.league, player=pending),
                "ATT", user=self.admin)
        self.assertEqual(undecided_player_ids(self.league), set())

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

    def test_the_market_opens_even_with_a_player_still_pending(self):
        """The league keeps working around him; only he waits."""
        self._player("Esordiente", method=SeasonPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)
        self.client.force_authenticate(user=self.admin)
        r = self.client.patch(f"/api/v1/leagues/{self.league.id}/market",
                              {"is_open": True}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_an_auction_refuses_the_undecided_and_names_them(self):
        ok = self._player("Deciso", method=SeasonPlayerRole.METHOD_TM,
                          tm_position="centre-back", role="DIF")
        pending = self._player("Esordiente", method=SeasonPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)
        self.client.force_authenticate(user=self.admin)

        r = self.client.post(f"/api/v1/leagues/{self.league.id}/auctions",
                             {"player_ids": [ok.id, pending.id]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "pending_decisions")
        # says WHICH one: a gate that only says "no" cannot be acted on
        self.assertEqual([p["player_id"] for p in r.json()["players"]], [pending.id])
        self.assertIn("Esordiente", r.json()["detail"])

        r = self.client.post(f"/api/v1/leagues/{self.league.id}/auctions",
                             {"player_ids": [ok.id]}, format="json")
        self.assertNotEqual(r.status_code, 400)

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


class LateArrivalTests(DecisionQueueTests):
    """Roles are frozen; the roster is not.

    A player signed after the listone was drawn — a January arrival, or anyone
    bought once the auction is over — had no frozen role at all, so the pagella
    silently fell back to the global seed for him and no decision was ever
    raised. He walked straight past the gate the rest of the flow depends on.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        from vfoot.services.listone import snapshot_league_listone
        self.snapshot = snapshot_league_listone

    def test_a_late_arrival_is_seeded_and_can_block_the_market(self):
        self._player("Titolare", method=SeasonPlayerRole.METHOD_TM,
                     tm_position="centre-back", role="DIF")
        self.snapshot(self.league)
        self.assertIsNone(market_blocked_reason(self.league))

        # ...the January window opens and an unclassifiable winger arrives.
        self._player("Arrivato a gennaio", method=SeasonPlayerRole.METHOD_DEFAULT)

        self.client.force_authenticate(user=self.admin)
        r = self.client.post(f"/api/v1/leagues/{self.league.id}/decisions/refresh",
                             format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["opened"], 1)
        self.assertIsNotNone(r.json()["blocked_reason"])

    def test_opening_the_market_catches_up_with_the_roster_by_itself(self):
        """Opening the market seeds whoever has arrived since — and opens for
        them, not against them: the market opens, only the newcomer waits."""
        self.snapshot(self.league)
        late = self._player("Arrivato tardi", method=SeasonPlayerRole.METHOD_DEFAULT)
        self.league.market_open = False
        self.league.save(update_fields=["market_open"])

        self.client.force_authenticate(user=self.admin)
        r = self.client.patch(f"/api/v1/leagues/{self.league.id}/market",
                              {"is_open": True}, format="json")
        self.assertEqual(r.status_code, 200)
        self.league.refresh_from_db()
        self.assertTrue(self.league.market_open)
        self.assertEqual(undecided_player_ids(self.league), {late.id})

    def test_a_late_arrival_cannot_be_added_to_a_roster_undecided(self):
        """The gate that actually matters, since the market is open by default."""
        self.snapshot(self.league)
        p = self._player("Arrivato tardi", method=SeasonPlayerRole.METHOD_DEFAULT)
        self.snapshot(self.league)
        from vfoot.models import FantasyTeam
        team = FantasyTeam.objects.create(
            league=self.league,
            manager=LeagueMembership.objects.get(league=self.league, user=self.admin),
            name="Squadra")
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(
            f"/api/v1/leagues/{self.league.id}/teams/{team.id}/roster/add",
            {"player_id": p.id, "price": 10}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json().get("code"), "pending_decisions")

    def test_a_frozen_role_is_never_reopened_by_a_recompute(self):
        """A player on a roster was bought, so he had a role when he was paid
        for. A recomputation of the season roles must not be able to drag him
        back into limbo and leave a squad holding someone unusable.

        Reproduced before the fix: a player seeded automatically as ATT, whose
        SeasonPlayerRole later stopped being measurable, acquired an open
        decision while his frozen role sat there intact."""
        p = self._player("Misurato", method=SeasonPlayerRole.METHOD_CATEGORY)
        self.snapshot(self.league)
        self.assertEqual(LeagueDecision.objects.filter(league=self.league).count(), 0)
        frozen = LeaguePlayerRole.objects.get(league=self.league, player=p).role

        # the season roles are recomputed and he is no longer measurable
        SeasonPlayerRole.objects.filter(player=p).update(
            method=SeasonPlayerRole.METHOD_DEFAULT, category="", confidence=0.0)
        self.snapshot(self.league)

        self.assertEqual(LeagueDecision.objects.filter(league=self.league).count(), 0)
        self.assertEqual(undecided_player_ids(self.league), set())
        self.assertEqual(
            LeaguePlayerRole.objects.get(league=self.league, player=p).role, frozen)

    def test_refreshing_never_disturbs_a_role_already_settled(self):
        p = self._player("Deciso", method=SeasonPlayerRole.METHOD_DEFAULT)
        self.snapshot(self.league)
        resolve(LeagueDecision.objects.get(league=self.league, player=p), "ATT",
                user=self.admin)

        self.snapshot(self.league)
        self.assertEqual(LeagueDecision.objects.filter(league=self.league).count(), 1)
        row = LeaguePlayerRole.objects.get(league=self.league, player=p)
        self.assertEqual(row.role, "ATT")
        self.assertEqual(row.source, LeaguePlayerRole.SOURCE_ADMIN)


class UnseenArrivalTests(DecisionQueueTests):
    """A player who signs between two runs of the role inference.

    He has no SeasonPlayerRole at all, so the criterion has never looked at him.
    Before this he was seeded straight from Player.classic_role — the raw
    provider map, under which every winger is a midfielder — silently bypassing
    both the criterion and the limbo.
    """

    def _stint_only(self, name, tm_position="left winger", classic_role="CEN"):
        from realdata.models import Player, PlayerTeamStint
        p = Player.objects.create(full_name=name, short_name=name,
                                  classic_role=classic_role)
        PlayerTeamStint.objects.create(player=p, team_season=self.ts,
                                       tm_position=tm_position)
        return p

    def test_an_ambiguous_arrival_goes_to_limbo_not_to_the_raw_provider_map(self):
        from vfoot.services.listone import snapshot_league_listone
        p = self._stint_only("Ala Nuova")
        summary = snapshot_league_listone(self.league)

        self.assertEqual(summary["awaiting_decision"], 1)
        self.assertEqual(summary["decisions_opened"], 1)
        self.assertFalse(LeaguePlayerRole.objects.filter(league=self.league,
                                                         player=p).exists())
        self.assertEqual(undecided_player_ids(self.league), {p.id})
        d = LeagueDecision.objects.get(league=self.league, player=p)
        self.assertIn("Arrivato dopo l'ultimo calcolo", d.rationale)
        self.assertTrue(d.proposed)   # a proposal to accept, not a blank form

    def test_an_unambiguous_arrival_is_seeded_without_bothering_anyone(self):
        from vfoot.services.listone import snapshot_league_listone
        p = self._stint_only("Centrale Nuovo", tm_position="centre-back",
                             classic_role="DIF")
        summary = snapshot_league_listone(self.league)

        self.assertEqual(summary["decisions_opened"], 0)
        self.assertEqual(
            LeaguePlayerRole.objects.get(league=self.league, player=p).role, "DIF")
        self.assertEqual(undecided_player_ids(self.league), set())


class DepartureReturnTests(DecisionQueueTests):
    """A player leaves Serie A (stint closed) and returns in January. The role
    frozen at his FIRST assignment must survive the disappearance AND must not
    drift to whatever Transfermarkt reclassified him as while he was gone. Encodes
    the user's rules: an already-settled per-league role never changes; the listone
    membership may come and go, the frozen role does not.
    """

    def _set_end(self, player, end):
        from datetime import date
        PlayerTeamStint.objects.filter(player=player, team_season=self.ts).update(
            end_date=(date(2026, 8, 31) if end else None))

    def test_departed_and_returning_player_keeps_the_original_frozen_role(self):
        from vfoot.services.listone import snapshot_league_listone
        # 1. present when the listone opens, unambiguous -> frozen as DIF
        p = self._player("Difensore", method=SeasonPlayerRole.METHOD_CATEGORY,
                         tm_position="centre-back", role="DIF")
        snapshot_league_listone(self.league)
        self.assertEqual(
            LeaguePlayerRole.objects.get(league=self.league, player=p).role, "DIF")

        # 2. he leaves for abroad; meanwhile Transfermarkt reclassifies him ATT
        self._set_end(p, True)
        SeasonPlayerRole.objects.filter(player=p).update(
            role_data="ATT", role_mitigated="ATT")
        Player.objects.filter(id=p.id).update(classic_role="ATT")
        snapshot_league_listone(self.league)          # a poll while he is gone
        # his frozen row is kept as history, untouched — not deleted, not changed
        self.assertEqual(
            LeaguePlayerRole.objects.get(league=self.league, player=p).role, "DIF")

        # 3. he returns in January -> STILL the original frozen DIF, not the new ATT
        self._set_end(p, False)
        snapshot_league_listone(self.league)
        rows = LeaguePlayerRole.objects.filter(league=self.league, player=p)
        self.assertEqual(rows.count(), 1)             # no duplicate row on return
        self.assertEqual(rows.first().role, "DIF")    # consolidated from the start

    def test_a_tm_role_change_does_not_touch_a_league_where_he_is_present(self):
        """Rule 4: TM changing a player's role must not disturb leagues that already
        froze him; only leagues formed afterwards see the new role."""
        from vfoot.services.listone import snapshot_league_listone
        p = self._player("Ambivalente", method=SeasonPlayerRole.METHOD_CATEGORY,
                         tm_position="centre-back", role="DIF")
        snapshot_league_listone(self.league)
        # TM flips him to an attacker; a later poll must NOT move the frozen role
        SeasonPlayerRole.objects.filter(player=p).update(
            role_data="ATT", role_mitigated="ATT")
        Player.objects.filter(id=p.id).update(classic_role="ATT")
        snapshot_league_listone(self.league)
        self.assertEqual(
            LeaguePlayerRole.objects.get(league=self.league, player=p).role, "DIF")
