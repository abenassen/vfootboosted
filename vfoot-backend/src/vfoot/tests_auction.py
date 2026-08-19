"""Auction room: legality engine + REST endpoints (create/nominate/bid/close/
assign/undo).

The economy under test is the classic one: budget = 1000 by default, roster
3-8-8-6, every player >= 1 credit, and a bid is legal only if the team keeps at
least 1 credit reservable for each of its still-unfilled slots.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from realdata.models import (
    Competition, CompetitionSeason, Player, Season, Team, TeamSeason,
)
from vfoot.models import (
    AuctionBid, AuctionEvent, AuctionNomination, AuctionSession,
    FantasyLeague, FantasyRosterSlot, FantasyTeam, LeagueMembership, LeaguePlayerRole,
)
from vfoot.services.auction_engine import check_purchase, team_budgets


class AuctionBase(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2025-2026"),
            name="Serie A 2025-2026")
        self.ts = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Inter"))

        self.admin = User.objects.create_user("admin", password="x")
        self.u2 = User.objects.create_user("mario", password="x")
        self.u3 = User.objects.create_user("luigi", password="x")

        self.league = FantasyLeague.objects.create(
            name="Lega", owner=self.admin, mode="classic", reference_season=self.cs,
            initial_budget=1000, slots_gk=3, slots_def=8, slots_mid=8, slots_fwd=6)

        self.m_admin = LeagueMembership.objects.create(
            league=self.league, user=self.admin, role=LeagueMembership.ROLE_ADMIN)
        self.m2 = LeagueMembership.objects.create(
            league=self.league, user=self.u2, role=LeagueMembership.ROLE_MANAGER)
        self.m3 = LeagueMembership.objects.create(
            league=self.league, user=self.u3, role=LeagueMembership.ROLE_MANAGER)

        self.t_admin = FantasyTeam.objects.create(league=self.league, manager=self.m_admin, name="AdminFC")
        self.t2 = FantasyTeam.objects.create(league=self.league, manager=self.m2, name="MarioFC")
        self.t3 = FantasyTeam.objects.create(league=self.league, manager=self.m3, name="LuigiFC")

        self.client = APIClient()

    def _player(self, name, role):
        p = Player.objects.create(full_name=name, short_name=name)
        LeaguePlayerRole.objects.create(league=self.league, player=p, role=role)
        return p

    def _as(self, user):
        self.client.force_authenticate(user=user)
        return self.client


class LegalityEngineTests(AuctionBase):
    def test_max_bid_reserves_one_credit_per_remaining_slot(self):
        # Fresh team: 25 empty slots, 1000 credits. Biggest single bid must leave
        # 24 credits (1 per other slot) -> 1000 - 24 = 976.
        b = team_budgets(self.league)[self.t2.id]
        self.assertEqual(b.remaining, 1000)
        self.assertEqual(b.slots_remaining_total, 25)
        self.assertEqual(b.max_bid_for_role("ATT"), 976)

    def test_bid_over_max_is_rejected(self):
        p = self._player("Bomber", "ATT")
        res = check_purchase(self.league, self.t2.id, "ATT", 977)
        self.assertFalse(res.ok)
        self.assertEqual(res.max_bid, 976)
        self.assertTrue(check_purchase(self.league, self.t2.id, "ATT", 976).ok)
        self.assertGreaterEqual(p.id, 1)

    def test_slot_full_blocks_role(self):
        # Fill all 3 GK slots, then a 4th GK bid is illegal regardless of budget.
        for i in range(3):
            gk = self._player(f"Portiere{i}", "POR")
            FantasyRosterSlot.objects.create(team=self.t2, player=gk, purchase_price=1)
        res = check_purchase(self.league, self.t2.id, "POR", 5)
        self.assertFalse(res.ok)
        self.assertIn("Nessuno slot", res.reason)

    def test_min_one_credit(self):
        self.assertFalse(check_purchase(self.league, self.t2.id, "ATT", 0).ok)

    def test_spent_reduces_remaining_and_max(self):
        p = self._player("Costoso", "ATT")
        FantasyRosterSlot.objects.create(team=self.t2, player=p, purchase_price=500)
        b = team_budgets(self.league)[self.t2.id]
        self.assertEqual(b.remaining, 500)
        self.assertEqual(b.slots_remaining_total, 24)
        # 500 - (24 - 1) = 477
        self.assertEqual(b.max_bid_for_role("ATT"), 477)
        self.assertEqual(b.slots["ATT"]["filled"], 1)


class AuctionFlowTests(AuctionBase):
    def _create_auction(self, players):
        res = self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/auctions",
            {"player_ids": [p.id for p in players]}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        return res.json()["auction_id"]

    def test_only_classic_leagues(self):
        self.league.mode = "aura"
        self.league.save()
        p = self._player("X", "ATT")
        res = self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/auctions", {"player_ids": [p.id]}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_create_defaults_pool_to_listone(self):
        self._player("A", "ATT")
        self._player("B", "DIF")
        res = self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/auctions", {}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["players"], 2)

    def test_second_active_auction_returns_existing(self):
        p = self._player("A", "ATT")
        aid = self._create_auction([p])
        res = self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/auctions", {"player_ids": [p.id]}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["auction_id"], aid)

    def test_manual_nominate_then_bid_then_close(self):
        atk = self._player("Lautaro", "ATT")
        aid = self._create_auction([atk])
        # nominate manual
        res = self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/nominate",
            {"mode": "manual", "player_id": atk.id}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        nom_id = res.json()["nomination_id"]

        # manager bids 10
        res = self._as(self.u2).post(f"/api/v1/nominations/{nom_id}/bid", {"amount": 10}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        # other manager must exceed
        res = self._as(self.u3).post(f"/api/v1/nominations/{nom_id}/bid", {"amount": 10}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self._as(self.u3).post(f"/api/v1/nominations/{nom_id}/bid", {"amount": 11}, format="json")
        self.assertEqual(res.status_code, 201)

        # admin closes -> luigi wins at 11
        res = self._as(self.admin).post(f"/api/v1/nominations/{nom_id}/close", format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["winner_team_id"], self.t3.id)
        slot = FantasyRosterSlot.objects.get(team=self.t3, player=atk)
        self.assertEqual(slot.purchase_price, 11)
        self.assertEqual(team_budgets(self.league)[self.t3.id].remaining, 989)

    def test_bid_rejected_when_illegal(self):
        atk = self._player("Costoso", "ATT")
        aid = self._create_auction([atk])
        res = self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/nominate", {"mode": "manual", "player_id": atk.id}, format="json")
        nom_id = res.json()["nomination_id"]
        # 977 exceeds the 976 max on an empty roster
        res = self._as(self.u2).post(f"/api/v1/nominations/{nom_id}/bid", {"amount": 977}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["max_bid"], 976)

    def test_random_role_only_draws_that_role(self):
        gk = self._player("Portiere", "POR")
        atk = self._player("Attaccante", "ATT")
        aid = self._create_auction([gk, atk])
        res = self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/nominate",
            {"mode": "random_role", "role": "POR", "random_seed": 1}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["player_id"], gk.id)

    def test_nominate_excludes_already_assigned(self):
        a = self._player("A", "ATT")
        b = self._player("B", "ATT")
        aid = self._create_auction([a, b])
        # assign A directly
        self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/assign",
            {"player_id": a.id, "team_id": self.t2.id, "price": 5}, format="json")
        # random must now only ever return B
        for _ in range(5):
            res = self._as(self.admin).post(
                f"/api/v1/auctions/{aid}/nominate", {"mode": "random"}, format="json")
            self.assertEqual(res.json()["player_id"], b.id)
            # cancel so we can nominate again
            self._as(self.admin).post(
                f"/api/v1/nominations/{res.json()['nomination_id']}/cancel", format="json")

    def test_direct_assign_shortcut(self):
        atk = self._player("Verbale", "ATT")
        aid = self._create_auction([atk])
        res = self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/assign",
            {"player_id": atk.id, "team_id": self.t2.id, "price": 30}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertTrue(FantasyRosterSlot.objects.filter(team=self.t2, player=atk, purchase_price=30).exists())
        self.assertEqual(team_budgets(self.league)[self.t2.id].remaining, 970)

    def test_assign_rejected_when_illegal(self):
        atk = self._player("Troppo", "ATT")
        aid = self._create_auction([atk])
        res = self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/assign",
            {"player_id": atk.id, "team_id": self.t2.id, "price": 1000}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_admin_bids_on_behalf(self):
        atk = self._player("X", "ATT")
        aid = self._create_auction([atk])
        res = self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/nominate", {"mode": "manual", "player_id": atk.id}, format="json")
        nom_id = res.json()["nomination_id"]
        res = self._as(self.admin).post(
            f"/api/v1/nominations/{nom_id}/bid", {"amount": 7, "team_id": self.t2.id}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self._as(self.admin).post(f"/api/v1/nominations/{nom_id}/close", format="json")
        self.assertTrue(FantasyRosterSlot.objects.filter(team=self.t2, player=atk).exists())

    def test_close_without_bids_refused(self):
        atk = self._player("X", "ATT")
        aid = self._create_auction([atk])
        res = self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/nominate", {"mode": "manual", "player_id": atk.id}, format="json")
        nom_id = res.json()["nomination_id"]
        res = self._as(self.admin).post(f"/api/v1/nominations/{nom_id}/close", format="json")
        self.assertEqual(res.status_code, 400)


class AuctionUndoTests(AuctionBase):
    def _create_auction(self, players):
        res = self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/auctions",
            {"player_ids": [p.id for p in players]}, format="json")
        return res.json()["auction_id"]

    def test_cancel_nomination_returns_player_to_pool(self):
        atk = self._player("X", "ATT")
        aid = self._create_auction([atk])
        res = self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/nominate", {"mode": "manual", "player_id": atk.id}, format="json")
        nom_id = res.json()["nomination_id"]
        res = self._as(self.admin).post(f"/api/v1/nominations/{nom_id}/cancel", format="json")
        self.assertEqual(res.status_code, 200, res.content)
        # can nominate the same player again
        res = self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/nominate", {"mode": "manual", "player_id": atk.id}, format="json")
        self.assertEqual(res.status_code, 201)

    def test_unsold_leaves_the_draw_but_stays_callable(self):
        """Scartato non è annullato: la differenza sta tutta nel sorteggio."""
        a = self._player("Scartato", "ATT")
        b = self._player("Altro", "ATT")
        aid = self._create_auction([a, b])
        nom_id = self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/nominate", {"mode": "manual", "player_id": a.id},
            format="json").json()["nomination_id"]
        res = self._as(self.admin).post(f"/api/v1/nominations/{nom_id}/unsold", format="json")
        self.assertEqual(res.status_code, 200, res.content)

        # Il sorteggio non lo ripesca più: resta solo l'altro.
        for _ in range(5):
            drawn = self._as(self.admin).post(
                f"/api/v1/auctions/{aid}/nominate", {"mode": "random"}, format="json")
            self.assertEqual(drawn.json()["player_id"], b.id)
            self._as(self.admin).post(
                f"/api/v1/nominations/{drawn.json()['nomination_id']}/cancel", format="json")

        # Ma chiamato per nome torna sul banco, che è come si recupera.
        again = self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/nominate", {"mode": "manual", "player_id": a.id}, format="json")
        self.assertEqual(again.status_code, 201, again.content)

    def test_undo_of_unsold_puts_him_back_in_the_draw(self):
        a = self._player("Pentito", "ATT")
        aid = self._create_auction([a])
        nom_id = self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/nominate", {"mode": "manual", "player_id": a.id},
            format="json").json()["nomination_id"]
        self._as(self.admin).post(f"/api/v1/nominations/{nom_id}/unsold", format="json")
        res = self._as(self.admin).post(f"/api/v1/auctions/{aid}/undo-last", format="json")
        self.assertEqual(res.json()["undone"], "unsold")
        # Ritirato lo scarto, il sorteggio lo rivede.
        drawn = self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/nominate", {"mode": "random"}, format="json")
        self.assertEqual(drawn.json()["player_id"], a.id)

    def test_void_bid(self):
        atk = self._player("X", "ATT")
        aid = self._create_auction([atk])
        nom_id = self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/nominate", {"mode": "manual", "player_id": atk.id},
            format="json").json()["nomination_id"]
        bid_id = self._as(self.u2).post(
            f"/api/v1/nominations/{nom_id}/bid", {"amount": 10}, format="json").json()["bid_id"]
        res = self._as(self.admin).post(f"/api/v1/bids/{bid_id}/void", format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(AuctionBid.objects.get(id=bid_id).is_void)
        # top bid gone -> next min is 1 again
        state = self._as(self.u2).get(f"/api/v1/auctions/{aid}").json()
        self.assertEqual(state["open_nomination"]["min_next_bid"], 1)

    def test_only_one_open_nomination_per_session(self):
        """Il database rifiuta la seconda chiamata aperta, non solo la vista.

        Il controllo nella vista legge e poi scrive dentro la transazione: con un
        banditore solo basta, con due amministratori che premono «Chiama» nello
        stesso istante no — su Postgres in READ COMMITTED nessuna delle due
        transazioni vede l'inserimento dell'altra prima della commit.
        """
        a = self._player("Uno", "ATT")
        b = self._player("Due", "ATT")
        aid = self._create_auction([a, b])
        self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/nominate", {"mode": "manual", "player_id": a.id}, format="json")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AuctionNomination.objects.create(
                    session_id=aid, player=b, nominator=self.m_admin,
                    call_mode=AuctionNomination.CALL_MANUAL)
        # Chiuse, annullate e invendute possono essere quante sono: vincola `open`.
        AuctionNomination.objects.create(
            session_id=aid, player=b, nominator=self.m_admin,
            call_mode=AuctionNomination.CALL_MANUAL, status=AuctionNomination.STATUS_CANCELLED)

    def test_revert_assignment_refunds_and_reopens(self):
        atk = self._player("X", "ATT")
        aid = self._create_auction([atk])
        self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/assign",
            {"player_id": atk.id, "team_id": self.t2.id, "price": 40}, format="json")
        nom = AuctionNomination.objects.get(session_id=aid, player=atk)
        self.assertEqual(team_budgets(self.league)[self.t2.id].remaining, 960)
        res = self._as(self.admin).post(f"/api/v1/nominations/{nom.id}/revert", format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertFalse(FantasyRosterSlot.objects.filter(team=self.t2, player=atk).exists())
        self.assertEqual(team_budgets(self.league)[self.t2.id].remaining, 1000)
        self.assertEqual(AuctionNomination.objects.get(id=nom.id).status, AuctionNomination.STATUS_OPEN)

    def test_undo_last_dispatches_by_event(self):
        atk = self._player("X", "ATT")
        aid = self._create_auction([atk])
        nom_id = self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/nominate", {"mode": "manual", "player_id": atk.id},
            format="json").json()["nomination_id"]
        self._as(self.u2).post(f"/api/v1/nominations/{nom_id}/bid", {"amount": 10}, format="json")
        # last action was a bid -> undo voids it
        res = self._as(self.admin).post(f"/api/v1/auctions/{aid}/undo-last", format="json")
        self.assertEqual(res.json()["undone"], "bid")
        # next undo targets the nomination
        res = self._as(self.admin).post(f"/api/v1/auctions/{aid}/undo-last", format="json")
        self.assertEqual(res.json()["undone"], "nomination")

    def test_settings_locked_after_auction_start(self):
        atk = self._player("X", "ATT")
        self._create_auction([atk])
        res = self._as(self.admin).patch(
            f"/api/v1/leagues/{self.league.id}/settings", {"initial_budget": 500}, format="json")
        self.assertEqual(res.status_code, 400)


class AuctionRostersTests(AuctionBase):
    """Le rose in sala d'asta: chi ha comprato chi, e quando vale rileggerle.

    Stanno su un endpoint loro perche' lo stato lo rileggono tutti i dispositivi a
    ogni rilancio; ``rosters_rev`` e' il segnale che dice al client quando le rose
    sono davvero cambiate.
    """

    def _create_auction(self, players):
        return self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/auctions",
            {"player_ids": [p.id for p in players]}, format="json").json()["auction_id"]

    def _roster(self, payload, team_id):
        row = next((t for t in payload["teams"] if t["team_id"] == team_id), None)
        return row["roster"] if row else []

    def _assign(self, aid, player, team, price):
        res = self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/assign",
            {"player_id": player.id, "team_id": team.id, "price": price}, format="json")
        self.assertEqual(res.status_code, 201, res.content)

    def test_rosters_list_who_bought_whom(self):
        gk = self._player("Portiere", "POR")
        atk = self._player("Bomber", "ATT")
        aid = self._create_auction([gk, atk])
        self._assign(aid, atk, self.t2, 40)
        self._assign(aid, gk, self.t2, 12)

        res = self._as(self.u2).get(f"/api/v1/auctions/{aid}/rosters")
        self.assertEqual(res.status_code, 200, res.content)
        payload = res.json()
        # Per reparto nell'ordine del listone, e dentro il reparto dal piu' caro.
        self.assertEqual(
            [(e["name"], e["role"], e["price"]) for e in self._roster(payload, self.t2.id)],
            [("Portiere", "POR", 12), ("Bomber", "ATT", 40)])
        self.assertEqual(self._roster(payload, self.t3.id), [])
        self.assertEqual(payload["last_purchase"], {"team_id": self.t2.id, "player_id": gk.id})

    def test_rosters_are_not_in_the_state(self):
        """Lo stato resta leggero: e' la lettura che si moltiplica per rilancio."""
        atk = self._player("Bomber", "ATT")
        aid = self._create_auction([atk])
        self._assign(aid, atk, self.t2, 40)
        state = self._as(self.u2).get(f"/api/v1/auctions/{aid}").json()
        self.assertNotIn("roster", state["team_budgets"][0])
        self.assertEqual(state["my_team_id"], self.t2.id)
        self.assertEqual(
            state["rosters_rev"],
            self._as(self.u2).get(f"/api/v1/auctions/{aid}/rosters").json()["rev"])

    def test_state_says_which_team_is_the_viewers(self):
        atk = self._player("Bomber", "ATT")
        aid = self._create_auction([atk])
        self.assertEqual(self._as(self.u2).get(f"/api/v1/auctions/{aid}").json()["my_team_id"], self.t2.id)
        self.assertEqual(self._as(self.u3).get(f"/api/v1/auctions/{aid}").json()["my_team_id"], self.t3.id)

    def test_rev_moves_on_purchases_but_not_on_bids(self):
        a = self._player("Uno", "ATT")
        b = self._player("Due", "ATT")
        aid = self._create_auction([a, b])
        rev0 = self._as(self.u2).get(f"/api/v1/auctions/{aid}").json()["rosters_rev"]

        nom_id = self._as(self.admin).post(
            f"/api/v1/auctions/{aid}/nominate", {"mode": "manual", "player_id": a.id},
            format="json").json()["nomination_id"]
        self._as(self.u2).post(f"/api/v1/nominations/{nom_id}/bid", {"amount": 10}, format="json")
        # Un rilancio non sposta nessun giocatore: le rose non si rileggono.
        self.assertEqual(self._as(self.u2).get(f"/api/v1/auctions/{aid}").json()["rosters_rev"], rev0)

        self._as(self.admin).post(f"/api/v1/nominations/{nom_id}/close", format="json")
        rev1 = self._as(self.u2).get(f"/api/v1/auctions/{aid}").json()["rosters_rev"]
        self.assertNotEqual(rev1, rev0)

        # Revoca e riacquisto ALLO STESSO PREZZO su un altro giocatore: ogni cifra
        # di budget torna identica, ma la rosa e' un'altra e l'impronta deve dirlo.
        nom = AuctionNomination.objects.get(session_id=aid, player=a)
        self._as(self.admin).post(f"/api/v1/nominations/{nom.id}/revert", format="json")
        self._assign(aid, b, self.t2, 10)
        state = self._as(self.u2).get(f"/api/v1/auctions/{aid}").json()
        self.assertEqual(team_budgets(self.league)[self.t2.id].remaining, 990)
        self.assertNotIn(state["rosters_rev"], (rev0, rev1))

    def test_reverted_purchase_leaves_the_roster(self):
        atk = self._player("Bomber", "ATT")
        aid = self._create_auction([atk])
        self._assign(aid, atk, self.t2, 40)
        nom = AuctionNomination.objects.get(session_id=aid, player=atk)
        self._as(self.admin).post(f"/api/v1/nominations/{nom.id}/revert", format="json")
        payload = self._as(self.u2).get(f"/api/v1/auctions/{aid}/rosters").json()
        self.assertEqual(self._roster(payload, self.t2.id), [])
        self.assertIsNone(payload["last_purchase"])

    def test_rosters_refused_to_outsiders(self):
        atk = self._player("Bomber", "ATT")
        aid = self._create_auction([atk])
        stranger = User.objects.create_user("estraneo", password="x")
        self.assertEqual(self._as(stranger).get(f"/api/v1/auctions/{aid}/rosters").status_code, 404)
