"""Tests for the league decision queue and the market gate."""
from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from datetime import date, timedelta
from unittest.mock import patch

from realdata.models import (
    Competition, CompetitionSeason, Player, PlayerMarketValue, PlayerTeamStint,
    Season, Team, TeamSeason,
)
from vfoot.models import (
    FantasyLeague, LeagueDecision, LeagueMembership, LeaguePlayerRole,
    CurrentPlayerRole,
)
from vfoot.services import push_channel
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

    def _player(self, name, *, method, tm_position="left winger", role="CEN",
                value_eur=10_000_000):
        p = Player.objects.create(full_name=name, short_name=name)
        PlayerTeamStint.objects.create(player=p, team_season=self.ts,
                                       tm_position=tm_position)
        CurrentPlayerRole.objects.create(
            player=p, method=method,
            tm_position=tm_position, role_data=role, role_mitigated=role)
        # A market value at/above the relevance floor by default, so a test player
        # reaches the decision queue; pass a low value_eur to exercise the gate.
        if value_eur is not None:
            PlayerMarketValue.objects.create(
                player=p, provider="transfermarkt", value_eur=value_eur,
                as_of=date(2026, 7, 1))
        return p

    def test_only_unmeasurable_ambiguous_players_become_decisions(self):
        self._player("Misurato", method=CurrentPlayerRole.METHOD_CATEGORY)
        self._player("Centrale", method=CurrentPlayerRole.METHOD_TM,
                     tm_position="centre-back", role="DIF")
        newcomer = self._player("Esordiente", method=CurrentPlayerRole.METHOD_DEFAULT)

        self.assertEqual(open_role_decisions(self.league), 1)
        d = LeagueDecision.objects.get(league=self.league)
        self.assertEqual(d.player_id, newcomer.id)
        self.assertTrue(d.blocks_market)
        self.assertEqual(d.proposed, "CEN")
        self.assertIn("Nessun dato", d.rationale)

    def test_only_relevant_players_reach_the_queue(self):
        # Same ambiguous, unmeasurable position; only market value differs.
        big = self._player("Titolare costoso", method=CurrentPlayerRole.METHOD_DEFAULT,
                           value_eur=8_000_000)
        self._player("Riserva economica", method=CurrentPlayerRole.METHOD_DEFAULT,
                     value_eur=500_000)
        self.assertEqual(open_role_decisions(self.league), 1)
        d = LeagueDecision.objects.get(league=self.league)
        self.assertEqual(d.player_id, big.id)  # the cheap one auto-took his proposal

    def test_a_sofascore_resolved_player_still_needs_no_decision_when_cheap(self):
        self._player("Ala economica", method=CurrentPlayerRole.METHOD_SOFA,
                     role="ATT", value_eur=1_000_000)
        self.assertEqual(open_role_decisions(self.league), 0)

    def test_reseeding_does_not_duplicate_or_reopen(self):
        self._player("Esordiente", method=CurrentPlayerRole.METHOD_DEFAULT)
        self.assertEqual(open_role_decisions(self.league), 1)
        self.assertEqual(open_role_decisions(self.league), 0)
        resolve(LeagueDecision.objects.get(league=self.league), "ATT", user=self.admin)
        # a question already answered must not come back
        self.assertEqual(open_role_decisions(self.league), 0)
        self.assertEqual(LeagueDecision.objects.filter(league=self.league).count(), 1)

    def test_only_the_undecided_player_is_in_limbo(self):
        """Per PLAYER, not per league: a single January signing must not stop
        everyone else in the league from trading."""
        ok = self._player("Deciso", method=CurrentPlayerRole.METHOD_TM,
                          tm_position="centre-back", role="DIF")
        pending = self._player("Esordiente", method=CurrentPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)

        self.assertEqual(undecided_player_ids(self.league), {pending.id})
        self.assertEqual(unavailable_players(self.league, [ok.id]), [])
        self.assertEqual(len(unavailable_players(self.league, [ok.id, pending.id])), 1)
        self.assertIsNotNone(market_blocked_reason(self.league))   # avviso, non blocco

        resolve(LeagueDecision.objects.get(league=self.league, player=pending),
                "ATT", user=self.admin)
        self.assertEqual(undecided_player_ids(self.league), set())

    def test_resolving_writes_the_frozen_league_role_as_an_admin_choice(self):
        p = self._player("Esordiente", method=CurrentPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)
        resolve(LeagueDecision.objects.get(league=self.league), "ATT", user=self.admin)
        row = LeaguePlayerRole.objects.get(league=self.league, player=p)
        self.assertEqual(row.role, "ATT")
        self.assertEqual(row.source, LeaguePlayerRole.SOURCE_ADMIN)

    def test_an_outcome_outside_the_offered_options_is_refused(self):
        self._player("Esordiente", method=CurrentPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)
        d = LeagueDecision.objects.get(league=self.league)
        with self.assertRaises(ValueError):
            resolve(d, "POR", user=self.admin)   # keepers are not on offer
        with self.assertRaises(ValueError):
            resolve(d, "", user=self.admin)

    def test_bulk_accept_skips_decisions_under_consultation(self):
        """Otherwise a bulk sign-off would quietly overrule a consultation the
        admin himself opened and members are still answering."""
        self._player("Uno", method=CurrentPlayerRole.METHOD_DEFAULT)
        self._player("Due", method=CurrentPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)
        d = LeagueDecision.objects.filter(league=self.league).first()
        d.consultation_open = True
        d.save(update_fields=["consultation_open"])

        self.assertEqual(accept_all_proposals(self.league, user=self.admin), 1)
        d.refresh_from_db()
        self.assertEqual(d.status, LeagueDecision.STATUS_OPEN)
        self.assertIsNotNone(market_blocked_reason(self.league))

    def test_members_only_see_and_are_notified_of_consultations(self):
        self._player("Uno", method=CurrentPlayerRole.METHOD_DEFAULT)
        self._player("Due", method=CurrentPlayerRole.METHOD_DEFAULT)
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
        self._player("Uno", method=CurrentPlayerRole.METHOD_DEFAULT)
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
        self._player("Uno", method=CurrentPlayerRole.METHOD_DEFAULT)
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

    def test_a_pending_player_does_not_freeze_the_others(self):
        """The league keeps working around him; only he waits.

        Written against the league-wide switch that used to sit here: with the
        gate per player, a roster still fills up while one name is in limbo."""
        from vfoot.models import FantasyTeam
        from vfoot.services.listone import snapshot_league_listone
        ok = self._player("Deciso", method=CurrentPlayerRole.METHOD_TM,
                          tm_position="centre-back", role="DIF")
        self._player("Esordiente", method=CurrentPlayerRole.METHOD_DEFAULT)
        # Il listone, non solo la coda delle decisioni: comprare passa ora dalla
        # legalita' d'asta, che il ruolo congelato lo pretende — e senza sarebbe
        # possibile mettere in rosa qualcuno che nella lega non esiste ancora.
        snapshot_league_listone(self.league)
        team = FantasyTeam.objects.create(
            league=self.league,
            manager=LeagueMembership.objects.get(league=self.league, user=self.admin),
            name="Squadra")

        self.client.force_authenticate(user=self.admin)
        r = self.client.post(
            f"/api/v1/leagues/{self.league.id}/teams/{team.id}/roster/add",
            {"player_id": ok.id, "purchase_price": 10}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_an_auction_refuses_the_undecided_and_names_them(self):
        ok = self._player("Deciso", method=CurrentPlayerRole.METHOD_TM,
                          tm_position="centre-back", role="DIF")
        pending = self._player("Esordiente", method=CurrentPlayerRole.METHOD_DEFAULT)
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
        self._player("Uno", method=CurrentPlayerRole.METHOD_DEFAULT)
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
        self._player("Uno", method=CurrentPlayerRole.METHOD_DEFAULT)
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
        """Through the snapshot itself, which is what the Transfermarkt import runs
        for every classic league on the season right after it has written the new
        stints — the arrival and the question it raises are the same event."""
        self._player("Titolare", method=CurrentPlayerRole.METHOD_TM,
                     tm_position="centre-back", role="DIF")
        self.snapshot(self.league)
        self.assertIsNone(market_blocked_reason(self.league))

        # ...the January window opens and an unclassifiable winger arrives.
        self._player("Arrivato a gennaio", method=CurrentPlayerRole.METHOD_DEFAULT)

        summary = self.snapshot(self.league)
        self.assertEqual(summary["decisions_opened"], 1)
        self.assertIsNotNone(market_blocked_reason(self.league))

    def test_a_late_arrival_cannot_be_added_to_a_roster_undecided(self):
        """The gate that actually matters: there is no other one left.

        (The catch-up itself is tested above, on the snapshot the Transfermarkt
        import runs — it used to be triggered by opening the market, an
        interruttore che non esiste piu'.)"""
        self.snapshot(self.league)
        p = self._player("Arrivato tardi", method=CurrentPlayerRole.METHOD_DEFAULT)
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
        CurrentPlayerRole later stopped being measurable, acquired an open
        decision while his frozen role sat there intact."""
        p = self._player("Misurato", method=CurrentPlayerRole.METHOD_CATEGORY)
        self.snapshot(self.league)
        self.assertEqual(LeagueDecision.objects.filter(league=self.league).count(), 0)
        frozen = LeaguePlayerRole.objects.get(league=self.league, player=p).role

        # the season roles are recomputed and he is no longer measurable
        CurrentPlayerRole.objects.filter(player=p).update(
            method=CurrentPlayerRole.METHOD_DEFAULT, category="", confidence=0.0)
        self.snapshot(self.league)

        self.assertEqual(LeagueDecision.objects.filter(league=self.league).count(), 0)
        self.assertEqual(undecided_player_ids(self.league), set())
        self.assertEqual(
            LeaguePlayerRole.objects.get(league=self.league, player=p).role, frozen)

    def test_refreshing_never_disturbs_a_role_already_settled(self):
        p = self._player("Deciso", method=CurrentPlayerRole.METHOD_DEFAULT)
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

    He has no CurrentPlayerRole at all, so the criterion has never looked at him.
    Before this he was seeded straight from Player.classic_role_seed — the raw
    provider map, under which every winger is a midfielder — silently bypassing
    both the criterion and the limbo.
    """

    def _stint_only(self, name, tm_position="left winger", classic_role_seed="CEN",
                    value_eur=10_000_000):
        from realdata.models import Player, PlayerTeamStint
        p = Player.objects.create(full_name=name, short_name=name,
                                  classic_role_seed=classic_role_seed)
        PlayerTeamStint.objects.create(player=p, team_season=self.ts,
                                       tm_position=tm_position)
        if value_eur is not None:  # relevant enough to reach the queue by default
            PlayerMarketValue.objects.create(
                player=p, provider="transfermarkt", value_eur=value_eur,
                as_of=date(2026, 7, 1))
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
                             classic_role_seed="DIF")
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
        p = self._player("Difensore", method=CurrentPlayerRole.METHOD_CATEGORY,
                         tm_position="centre-back", role="DIF")
        snapshot_league_listone(self.league)
        self.assertEqual(
            LeaguePlayerRole.objects.get(league=self.league, player=p).role, "DIF")

        # 2. he leaves for abroad; meanwhile Transfermarkt reclassifies him ATT
        self._set_end(p, True)
        CurrentPlayerRole.objects.filter(player=p).update(
            role_data="ATT", role_mitigated="ATT")
        Player.objects.filter(id=p.id).update(classic_role_seed="ATT")
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
        p = self._player("Ambivalente", method=CurrentPlayerRole.METHOD_CATEGORY,
                         tm_position="centre-back", role="DIF")
        snapshot_league_listone(self.league)
        # TM flips him to an attacker; a later poll must NOT move the frozen role
        CurrentPlayerRole.objects.filter(player=p).update(
            role_data="ATT", role_mitigated="ATT")
        Player.objects.filter(id=p.id).update(classic_role_seed="ATT")
        snapshot_league_listone(self.league)
        self.assertEqual(
            LeaguePlayerRole.objects.get(league=self.league, player=p).role, "DIF")


class QueueCriterionTests(TestCase):
    """WHO reaches the admin queue. Every branch here is a measured claim, and the
    measurements are in the docstring of ``role_inference.needs_decision``."""

    def _role(self, **kw):
        from realdata.models import Player
        from vfoot.models import CurrentPlayerRole
        p = Player.objects.create(full_name=kw.pop("name", "X"))
        return CurrentPlayerRole.objects.create(player=p, **kw), p

    def test_a_certain_tm_position_ends_the_question_however_torn_the_measurement(self):
        """Nico Paz: TM says attacking midfield, our clustering says ATT at a margin
        of 0.24. TM matched the listone 351/352 across EVERY margin band, so this is
        not a doubt — it is our own wobble under an answer that is right."""
        from vfoot.services.role_inference import PlayerRoleResult
        r = PlayerRoleResult(player_id=1, category="ala offensiva", confidence=0.5,
                             role_data="ATT", role_mitigated="CEN", method="category",
                             tm_position="attacking midfield", role_margin=0.05)
        self.assertFalse(r.needs_decision)

    def test_an_ambiguous_position_with_a_torn_measurement_does_need_one(self):
        """Berardi: TM says right winger (54% pure in the listone), so nobody
        overrules the clustering — and the clustering split him CEN 56% / ATT 35%."""
        from vfoot.services.role_inference import PlayerRoleResult
        r = PlayerRoleResult(player_id=1, category="centrocampista offensivo",
                             confidence=0.34, role_data="CEN", role_mitigated="CEN",
                             method="category", tm_position="right winger",
                             role_margin=0.21)
        self.assertTrue(r.needs_decision)

    def test_an_ambiguous_position_resolved_only_by_the_lineup_needs_one(self):
        """The SofaScore position is F/M/D: for a winger it always reads ATT, and
        against the listone that is right 8 times out of 15."""
        from vfoot.services.role_inference import PlayerRoleResult
        r = PlayerRoleResult(player_id=1, category="", confidence=0.0,
                             role_data="ATT", role_mitigated="ATT", method="sofa",
                             tm_position="right winger", role_margin=1.0)
        self.assertTrue(r.needs_decision)

    def test_a_confident_measurement_under_an_ambiguous_position_does_not(self):
        from vfoot.services.role_inference import PlayerRoleResult
        r = PlayerRoleResult(player_id=1, category="ala offensiva", confidence=0.8,
                             role_data="ATT", role_mitigated="ATT", method="category",
                             tm_position="left winger", role_margin=0.9)
        self.assertFalse(r.needs_decision)

    def test_a_settled_margin_on_a_border_player_still_needs_one(self):
        """Esposito: the runs agreed (margin 0.44) and he is still on the CEN/ATT
        line (boundary 0.82). This is the case the margin alone cannot see, since
        it is read off the co-association average that erased the border."""
        from vfoot.services.role_inference import PlayerRoleResult
        r = PlayerRoleResult(player_id=1, category="centrocampista offensivo",
                             confidence=0.34, role_data="CEN", role_mitigated="CEN",
                             method="category", tm_position="second striker",
                             role_margin=0.44, role_boundary=0.82)
        self.assertTrue(r.needs_decision)

    def test_a_player_far_from_every_other_role_does_not(self):
        """Zaniolo: ambiguous position, but 0.79 from the nearest category of
        another role and a margin of 0.67. Nothing to arbitrate — where we differ
        from the listone on him it is a convention, not a doubt, and conventions
        are not the queue's business."""
        from vfoot.services.role_inference import PlayerRoleResult
        r = PlayerRoleResult(player_id=1, category="ala offensiva", confidence=0.76,
                             role_data="ATT", role_mitigated="ATT", method="category",
                             tm_position="second striker",
                             role_margin=0.67, role_boundary=0.79)
        self.assertFalse(r.needs_decision)

    def test_a_certain_tm_position_ends_the_question_however_close_the_border(self):
        """The boundary is subject to the same gate as the margin: an unambiguous
        TM position answers first, and being on a border under it says our
        clustering wobbled, not that TM is wrong."""
        from vfoot.services.role_inference import PlayerRoleResult
        r = PlayerRoleResult(player_id=1, category="centrocampista offensivo",
                             confidence=0.3, role_data="CEN", role_mitigated="ATT",
                             method="category", tm_position="centre-forward",
                             role_margin=0.9, role_boundary=0.99)
        self.assertFalse(r.needs_decision)


class LimboSurvivesRepollTests(DecisionQueueTests):
    """A player waiting on a decision must still be waiting after the next poll.

    The listone snapshot runs on every Transfermarkt scrape and every market
    opening. ``players_needing_decision`` deliberately skips anyone with an open
    decision (it must not ask twice) — so without an explicit exclusion the second
    run saw a roster player with no frozen role, no pending question as far as it
    could tell, and seeded him from the raw map: the question was answered by the
    poll rather than by the admin, and the offer market — which gates on exactly
    "has a frozen role" — put him back on the shelf.
    """

    def _snapshot(self):
        from vfoot.services.listone import snapshot_league_listone
        return snapshot_league_listone(self.league)

    def test_a_second_poll_does_not_seed_a_player_still_in_limbo(self):
        p = self._player("In dubbio", method=CurrentPlayerRole.METHOD_DEFAULT)
        first = self._snapshot()
        self.assertEqual(first["decisions_opened"], 1)

        second = self._snapshot()          # the nightly TM scrape
        self.assertEqual(second["awaiting_decision"], 1)
        self.assertFalse(
            LeaguePlayerRole.objects.filter(league=self.league, player=p).exists())
        self.assertEqual(undecided_player_ids(self.league), {p.id})

    def test_the_limbo_ends_only_when_the_admin_answers(self):
        p = self._player("In dubbio", method=CurrentPlayerRole.METHOD_DEFAULT)
        self._snapshot()
        resolve(LeagueDecision.objects.get(league=self.league, player=p), "ATT",
                user=self.admin)
        self._snapshot()

        row = LeaguePlayerRole.objects.get(league=self.league, player=p)
        self.assertEqual((row.role, row.source), ("ATT", LeaguePlayerRole.SOURCE_ADMIN))
        self.assertEqual(undecided_player_ids(self.league), set())

    def test_an_undecided_player_is_not_offerable_as_a_free_agent(self):
        from vfoot.services.market_engine import free_agent_ids
        p = self._player("In dubbio", method=CurrentPlayerRole.METHOD_DEFAULT)
        self._snapshot()
        # Even with a stray frozen row (a listone seeded before the gate existed),
        # an open question keeps him off the market.
        LeaguePlayerRole.objects.create(league=self.league, player=p, role="CEN",
                                        source=LeaguePlayerRole.SOURCE_SEED)
        self.assertNotIn(p.id, free_agent_ids(self.league))


class DecisionRationaleTests(DecisionQueueTests):
    """Every case in the queue says why it is there. The two the criterion added
    last — the lineup-only role and the coin-flip clustering — used to arrive with
    an empty explanation, which is the one thing an admin cannot act on."""

    def test_a_lineup_only_role_says_the_measure_is_missing(self):
        self._player("Solo distinta", method=CurrentPlayerRole.METHOD_SOFA)
        open_role_decisions(self.league)
        d = LeagueDecision.objects.get(league=self.league)
        self.assertIn("distinta", d.rationale)

    def test_a_torn_measure_reports_its_margin(self):
        p = self._player("In bilico", method=CurrentPlayerRole.METHOD_CATEGORY)
        CurrentPlayerRole.objects.filter(player=p).update(
            role_margin=0.12, category="ala offensiva")
        open_role_decisions(self.league)
        d = LeagueDecision.objects.get(league=self.league)
        self.assertIn("12%", d.rationale)

    def test_a_border_player_is_not_described_as_a_torn_measure(self):
        """The margin that got him here is 0.44 — ABOVE the threshold. Reporting it
        as "stacca di appena 44%, sotto la soglia" quotes a number against a
        threshold it does not cross, and the admin is left reading a sentence that
        contradicts itself."""
        p = self._player("Sul confine", method=CurrentPlayerRole.METHOD_CATEGORY)
        CurrentPlayerRole.objects.filter(player=p).update(
            role_margin=0.44, role_boundary=0.82,
            category="centrocampista offensivo")
        open_role_decisions(self.league)
        d = LeagueDecision.objects.get(league=self.league)
        self.assertIn("confine", d.rationale)
        self.assertIn("82%", d.rationale)
        self.assertNotIn("44%", d.rationale)
        self.assertIn("centrocampista offensivo", d.rationale)

    def test_no_case_reaches_the_admin_without_an_explanation(self):
        self._player("Distinta", method=CurrentPlayerRole.METHOD_SOFA)
        self._player("Default", method=CurrentPlayerRole.METHOD_DEFAULT)
        self._player("Ignoto", method=CurrentPlayerRole.METHOD_UNKNOWN)
        torn = self._player("Bilico", method=CurrentPlayerRole.METHOD_CATEGORY)
        CurrentPlayerRole.objects.filter(player=torn).update(role_margin=0.1)
        open_role_decisions(self.league)
        self.assertEqual(LeagueDecision.objects.filter(league=self.league).count(), 4)
        for d in LeagueDecision.objects.filter(league=self.league):
            self.assertTrue(d.rationale, f"{d.title} arriva senza motivazione")


class LeagueCreationTests(DecisionQueueTests):
    """The queue must exist from the first minute of a classic league.

    Building the listone only when the market opened meant a freshly created
    league answered "nessuna decisione in sospeso" while a dozen questions were
    in fact waiting to be asked — and the admin met them on auction day.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _create(self, mode):
        return self.client.post("/api/v1/leagues", {
            "name": f"Nuova {mode}", "team_name": "Squadra", "mode": mode,
            "reference_season_id": self.cs.id}, format="json")

    def test_creating_a_classic_league_raises_its_questions_at_once(self):
        self._player("Da decidere", method=CurrentPlayerRole.METHOD_DEFAULT)
        self._player("Centrale", method=CurrentPlayerRole.METHOD_TM,
                     tm_position="centre-back", role="DIF")
        r = self._create("classic")

        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["decisions_opened"], 1)
        new = FantasyLeague.objects.get(id=r.json()["league_id"])
        self.assertEqual(len(undecided_player_ids(new)), 1)   # in limbo from day one
        self.assertEqual(
            LeagueDecision.objects.filter(league=new, status="open").count(), 1)
        # ...and the unambiguous one was frozen without asking anybody.
        self.assertEqual(LeaguePlayerRole.objects.filter(league=new).count(), 1)

    def test_an_aura_league_gets_no_listone_and_no_questions(self):
        self._player("Da decidere", method=CurrentPlayerRole.METHOD_DEFAULT)
        r = self._create("aura")

        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["decisions_opened"], 0)
        new = FantasyLeague.objects.get(id=r.json()["league_id"])
        self.assertFalse(LeaguePlayerRole.objects.filter(league=new).exists())
        self.assertFalse(LeagueDecision.objects.filter(league=new).exists())

    def test_an_aura_league_is_never_given_a_listone(self):
        """The listone is a classic-mode object; seeding one into an aura league
        would fill it with per-role rows nothing there reads. Every entry point to
        the snapshot is gated on the mode, so the league simply never gets one."""
        r = self._create("aura")
        aura = FantasyLeague.objects.get(id=r.json()["league_id"])
        LeagueMembership.objects.filter(league=aura, user=self.admin).update(role="admin")

        listed = self.client.get(f"/api/v1/leagues/{aura.id}/decisions").json()
        self.assertFalse(listed["has_listone"])
        self.assertFalse(LeaguePlayerRole.objects.filter(league=aura).exists())


class ConsultationEmailTests(DecisionQueueTests):
    """Being asked, and being told how it ended.

    The badge only reaches someone who opens the app; a consultation nobody sees
    is a survey with no respondents. Two messages, and only two: the question
    addressed to you, and its answer.

    ``captureOnCommitCallbacks`` everywhere on purpose — the sends are queued for
    after the commit, and a test that did not run them would pass while the real
    thing never left the building.
    """

    def setUp(self):
        super().setUp()
        from django.core import mail
        self.mail = mail
        self.mail.outbox = []
        for u in (self.admin, self.member):
            u.email = f"{u.username}@example.com"
            u.save(update_fields=["email"])

    def _one_decision(self):
        self._player("Da decidere", method=CurrentPlayerRole.METHOD_DEFAULT)
        open_role_decisions(self.league)
        return LeagueDecision.objects.get(league=self.league)

    def _consult(self, decision, is_open=True, user=None):
        from vfoot.services.league_decisions import set_consultation
        with self.captureOnCommitCallbacks(execute=True):
            set_consultation(decision, is_open, user=user or self.admin)

    def _resolve(self, decision, option, user=None):
        with self.captureOnCommitCallbacks(execute=True):
            resolve(decision, option, user=user or self.admin)

    def test_opening_a_consultation_asks_the_members_by_email(self):
        d = self._one_decision()
        self._consult(d)

        self.assertEqual(len(self.mail.outbox), 1)          # not the admin himself
        msg = self.mail.outbox[0]
        self.assertEqual(msg.to, [self.member.email])
        self.assertIn("parere", msg.subject)
        self.assertIn(d.question, msg.body)
        self.assertIn("/decisioni", msg.body)

    def test_closing_a_consultation_mails_nobody(self):
        d = self._one_decision()
        self._consult(d)
        self.mail.outbox = []
        self._consult(d, False)
        self.assertEqual(self.mail.outbox, [])

    def test_reopening_an_already_open_consultation_does_not_ask_twice(self):
        d = self._one_decision()
        self._consult(d)
        self.mail.outbox = []
        self._consult(d)
        self.assertEqual(self.mail.outbox, [])

    def test_the_outcome_goes_back_to_whoever_was_asked(self):
        d = self._one_decision()
        self._consult(d)
        cast_vote(d, self.member, "ATT")
        self.mail.outbox = []

        self._resolve(d, "CEN")
        self.assertEqual(len(self.mail.outbox), 1)
        msg = self.mail.outbox[0]
        self.assertEqual(msg.to, [self.member.email])
        self.assertIn("Centrocampista", msg.body)   # the outcome, in words
        self.assertIn("Attaccante: 1", msg.body)    # and what the league thought

    def test_a_routine_sign_off_mails_nobody(self):
        """No consultation, no mail: the admin's own backlog is not news."""
        self._resolve(self._one_decision(), "CEN")
        self.assertEqual(self.mail.outbox, [])

    def test_a_member_without_an_address_is_simply_skipped(self):
        d = self._one_decision()
        User.objects.filter(id=self.member.id).update(email="")
        self._consult(d)
        self.assertEqual(self.mail.outbox, [])

    def test_a_broken_relay_does_not_break_the_admin_s_action(self):
        """The mail is a courtesy; the decision is the point."""
        from unittest.mock import patch
        d = self._one_decision()
        with patch("vfoot.services.league_notifications.get_connection",
                   side_effect=OSError("relay down")):
            self._consult(d)
        d.refresh_from_db()
        self.assertTrue(d.consultation_open)

    def test_the_switch_silences_everything(self):
        d = self._one_decision()
        with self.settings(VFOOT_NOTIFY_EMAILS=False):
            self._consult(d)
            self._resolve(d, "CEN")
        self.assertEqual(self.mail.outbox, [])


class NewDecisionNotificationTests(LateArrivalTests):
    """The admin is told the queue has grown — but only when nobody was watching.

    The market stays blocked for a player in limbo, so a question raised at six in
    the morning by the Transfermarkt import is work that will sit untouched until
    someone happens to open the page. That is the one case worth a push.
    """

    def test_the_unattended_import_path_notifies_the_admin(self):
        self.snapshot(self.league)
        self._player("Arrivato a gennaio", method=CurrentPlayerRole.METHOD_DEFAULT)

        with patch.object(push_channel, "send_to_user", return_value=1) as send:
            summary = self.snapshot(self.league, notify=True)

        self.assertEqual(summary["decisions_opened"], 1)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.args[0], self.admin)
        # One tag per league: a second import before he has answered replaces the
        # notification rather than stacking another copy of it.
        self.assertEqual(send.call_args.kwargs["tag"], f"decisions-{self.league.id}")
        self.assertEqual(send.call_args.kwargs["url"], "/decisioni")

    def test_a_snapshot_the_admin_is_watching_stays_silent(self):
        """League creation, opening the market: the questions are already on the
        screen he is looking at, and a notification about that is noise."""
        self.snapshot(self.league)
        self._player("Arrivato a gennaio", method=CurrentPlayerRole.METHOD_DEFAULT)

        with patch.object(push_channel, "send_to_user") as send:
            summary = self.snapshot(self.league)          # notify defaults to False

        self.assertEqual(summary["decisions_opened"], 1)
        send.assert_not_called()

    def test_an_import_that_raises_nothing_notifies_nobody(self):
        self.snapshot(self.league)
        with patch.object(push_channel, "send_to_user") as send:
            summary = self.snapshot(self.league, notify=True)
        self.assertEqual(summary["decisions_opened"], 0)
        send.assert_not_called()


class RealSigningFeedTests(DecisionQueueTests):
    """"Who is new to MY listone", on the league's home feed — the coups only.

    Deliberately NOT derived from the roster stint. A stint records when we first
    SAW a player in a squad: the season's first import opens one for all 660 of
    them on the same day and never fills transfer_kind, so it cannot tell a January
    arrival from the opening squad load. The league's own listone can — it is
    seeded in one burst, and a role row created well after that burst belongs to
    someone who was not there before.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.opened = timezone.now() - timedelta(days=90)

    def _in_listone(self, name, value_eur, *, created_at, source=None):
        p = Player.objects.create(full_name=name, short_name=name)
        PlayerMarketValue.objects.create(player=p, provider="transfermarkt",
                                         value_eur=value_eur,
                                         as_of=date(2026, 7, 1))
        row = LeaguePlayerRole.objects.create(
            league=self.league, player=p, role="ATT",
            source=source or LeaguePlayerRole.SOURCE_SEED)
        # created_at has a default rather than auto_now_add, but the row is already
        # written: set it explicitly so the test controls the timeline.
        LeaguePlayerRole.objects.filter(pk=row.pk).update(created_at=created_at)
        return p

    def _opening_squad(self, at=None, n=25):
        """A burst that draws the listone: nobody in it is news, whenever it lands."""
        when = at or self.opened
        for i in range(n):
            self._in_listone(f"Titolare {when:%m%d}-{i}", 40_000_000, created_at=when)

    def _feed(self):
        return [i for i in self.client.get(
            f"/api/v1/leagues/{self.league.id}/activity?limit=50").json()
            if i["kind"] == "mercato_reale"]

    def test_the_opening_squad_is_not_a_transfer_ticker(self):
        """The bug this shape exists to avoid: 660 players seeded on day one, all
        reported as signings, burying every other thing the league did."""
        self._opening_squad()
        self.assertEqual(self._feed(), [])

    def test_a_later_arrival_is_news(self):
        self._opening_squad()
        self._in_listone("Colpo di gennaio", 25_000_000,
                         created_at=timezone.now() - timedelta(days=2))
        feed = self._feed()
        self.assertEqual(len(feed), 1)
        self.assertIn("Colpo di gennaio", feed[0]["text"])
        self.assertEqual(feed[0]["detail"], "25 M€")

    def test_a_cheap_later_arrival_is_not(self):
        self._opening_squad()
        self._in_listone("Riserva", 800_000,
                         created_at=timezone.now() - timedelta(days=2))
        self.assertEqual(self._feed(), [])

    def test_the_floor_is_higher_than_the_one_that_raises_a_decision(self):
        """€5M is 'worth deciding a role for'; it is not 'worth telling the league
        about'. A player between the two reaches the admin's queue and stays off
        everyone's home page."""
        self._opening_squad()
        self._in_listone("Fra le due soglie", 7_000_000,
                         created_at=timezone.now() - timedelta(days=2))
        self.assertEqual(self._feed(), [])

    def test_an_admin_answer_is_not_reported_as_a_signing(self):
        """Resolving a decision writes a role row too; it is the decision, and the
        feed already carries those under their own kind."""
        self._opening_squad()
        self._in_listone("Deciso dall'admin", 30_000_000,
                         created_at=timezone.now() - timedelta(days=2),
                         source=LeaguePlayerRole.SOURCE_ADMIN)
        self.assertEqual(self._feed(), [])

    def test_a_null_market_value_does_not_crash_the_feed(self):
        """Real data has them, and latest_market_values KEYS such a player with a
        None rather than leaving him out — so a `.get(pid, 0)` default never fires
        and the comparison blows up. Found by opening the page, not by a test."""
        self._opening_squad()
        self._in_listone("Senza quotazione", None,
                         created_at=timezone.now() - timedelta(days=2))
        self._in_listone("Colpo", 25_000_000,
                         created_at=timezone.now() - timedelta(days=2))
        feed = self._feed()
        self.assertEqual(len(feed), 1)
        self.assertIn("Colpo", feed[0]["text"])

    def test_a_second_seeding_burst_is_not_a_wave_of_signings(self):
        """A listone can be drawn more than once — a reference season set later, a
        --reset, a demo re-seed. Keying on "the FIRST burst" reported every row of
        the second one as a transfer; a real dev league seeded in two runs (250 rows,
        then 287 six days later) filled its whole home page that way."""
        self._opening_squad()
        self._opening_squad(at=timezone.now() - timedelta(days=30))
        self.assertEqual(self._feed(), [])

    def test_a_handful_arriving_together_is_still_news(self):
        """The rule is about the SHAPE of a seeding, not about arriving on the same
        day: a poll that finds three signings at once must still report them."""
        self._opening_squad()
        when = timezone.now() - timedelta(days=2)
        for i in range(3):
            self._in_listone(f"Colpo {i}", 25_000_000, created_at=when)
        self.assertEqual(len(self._feed()), 3)

    def test_a_signing_says_which_club_he_joined(self):
        """"Entra nel listone / 15 M€" non diceva DOVE. La squadra sta nel
        dettaglio, non nel testo: il testo il frontend lo tronca a una riga."""
        self._opening_squad()
        p = self._in_listone("Colpo", 25_000_000,
                             created_at=timezone.now() - timedelta(days=2))
        PlayerTeamStint.objects.create(player=p, team_season=self.ts,
                                       start_date=date(2026, 8, 14))
        feed = self._feed()
        self.assertEqual(len(feed), 1)
        self.assertEqual(feed[0]["detail"], "25 M€ · Torino")

    def test_without_a_stint_the_signing_keeps_its_line(self):
        """Letto dal listone ma da nessuna rosa: si perde la circostanza, non la
        notizia."""
        self._opening_squad()
        self._in_listone("Colpo", 25_000_000,
                         created_at=timezone.now() - timedelta(days=2))
        self.assertEqual(self._feed()[0]["detail"], "25 M€")


class RealTransferFeedTests(DecisionQueueTests):
    """Chi CAMBIA MAGLIA dentro la Serie A, che prima non compariva a nessuna cifra.

    Il 14/08/2026 Pellegrino, Kristensen e Piccoli si sono mossi fra due squadre di
    Serie A e la home non ha detto niente: erano gia' nel listone, quindi nessun
    ``LeaguePlayerRole`` nuovo e ``_real_signings`` non poteva vederli. Intanto la
    stessa home annunciava riempi-rose da 0,1 M€ che entravano.

    Qui i tesseramenti si possono leggere — trappola dei 660 compresa — perche' la
    prova non e' una data ma una FORMA: aperto qui, chiuso altrove.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.altra = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Parma"))

    def _listone(self, name, value_eur=25_000_000):
        p = Player.objects.create(full_name=name, short_name=name)
        if value_eur is not None:
            PlayerMarketValue.objects.create(player=p, provider="transfermarkt",
                                             value_eur=value_eur,
                                             as_of=date(2026, 7, 1))
        LeaguePlayerRole.objects.create(league=self.league, player=p, role="ATT",
                                        source=LeaguePlayerRole.SOURCE_SEED)
        return p

    def _transfer(self, p, *, da, a, quando=date(2026, 8, 14)):
        PlayerTeamStint.objects.create(player=p, team_season=da,
                                       start_date=date(2026, 7, 1),
                                       end_date=quando)
        PlayerTeamStint.objects.create(player=p, team_season=a, start_date=quando)

    def _feed(self):
        return [i for i in self.client.get(
            f"/api/v1/leagues/{self.league.id}/activity?limit=50").json()
            if i["kind"] == "trasferimento_reale"]

    def test_un_trasferimento_e_notizia_e_dice_le_due_squadre(self):
        self._transfer(self._listone("Piccoli"), da=self.altra, a=self.ts)
        feed = self._feed()
        self.assertEqual(len(feed), 1)
        self.assertEqual(feed[0]["text"], "Piccoli → Torino")
        self.assertEqual(feed[0]["detail"], "ex Parma · 25 M€")

    def test_la_provenienza_non_prende_l_articolo(self):
        """Visto sui dati veri: "dal Fiorentina", "dal Udinese". L'articolo si
        accorda col nome del club e una tabella di generi si rompe al primo
        neopromosso; "ex" vale per tutte."""
        viola = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Fiorentina"))
        self._transfer(self._listone("Piccoli"), da=viola, a=self.ts)
        detail = self._feed()[0]["detail"]
        self.assertTrue(detail.startswith("ex Fiorentina"), detail)
        self.assertNotIn("dal ", detail)

    def test_il_caricamento_iniziale_non_e_una_valanga_di_trasferimenti(self):
        """La trappola che ha gia' morso una volta dall'altra parte: il primo
        import di stagione apre 660 tesseramenti nello stesso giorno. Nessuno di
        loro ha un tesseramento CHIUSO alle spalle, ed e' quello a salvarci —
        non la data, di cui non ci si potrebbe fidare."""
        for i in range(30):
            PlayerTeamStint.objects.create(
                player=self._listone(f"Titolare {i}"), team_season=self.ts,
                start_date=date(2026, 8, 14))
        self.assertEqual(self._feed(), [])

    def test_chi_resta_dove_era_non_e_notizia(self):
        """Un tesseramento riaperto nella STESSA squadra (rinnovo, rientro da
        prestito) non e' un cambio di maglia."""
        p = self._listone("Fedele")
        self._transfer(p, da=self.ts, a=self.ts)
        self.assertEqual(self._feed(), [])

    def test_la_soglia_e_piu_bassa_di_quella_degli_ingressi(self):
        """Chi si trasferisce e' gia' nel listone e puo' essere in una rosa di
        questa lega: 7 M€ non basta per annunciare un ingresso, basta per dire a
        chi ce l'ha che ha cambiato squadra."""
        self._transfer(self._listone("Fra le due soglie", 7_000_000),
                       da=self.altra, a=self.ts)
        self.assertEqual(len(self._feed()), 1)

    def test_sotto_la_soglia_di_rilevanza_resta_fuori(self):
        self._transfer(self._listone("Riserva", 800_000),
                       da=self.altra, a=self.ts)
        self.assertEqual(self._feed(), [])

    def test_chi_non_e_nel_listone_di_questa_lega_non_e_notizia_di_questa_lega(self):
        p = Player.objects.create(full_name="Estraneo", short_name="Estraneo")
        PlayerMarketValue.objects.create(player=p, provider="transfermarkt",
                                         value_eur=50_000_000,
                                         as_of=date(2026, 7, 1))
        self._transfer(p, da=self.altra, a=self.ts)
        self.assertEqual(self._feed(), [])

    def test_senza_quotazione_non_fa_saltare_il_feed(self):
        """latest_market_values CHIAVA un giocatore senza quotazione con None: e'
        il difetto che aveva gia' rotto la pagina dall'altra parte."""
        self._transfer(self._listone("Senza quotazione", None),
                       da=self.altra, a=self.ts)
        self.assertEqual(self._feed(), [])

    def test_con_due_squadre_alle_spalle_viene_dall_ultima(self):
        p = self._listone("Girovago")
        terza = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Genoa"))
        PlayerTeamStint.objects.create(player=p, team_season=terza,
                                       start_date=date(2026, 7, 1),
                                       end_date=date(2026, 7, 20))
        self._transfer(p, da=self.altra, a=self.ts)
        self.assertEqual(self._feed()[0]["detail"], "ex Parma · 25 M€")
