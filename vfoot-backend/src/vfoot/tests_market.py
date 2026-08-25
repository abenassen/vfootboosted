"""Repair market (offer-based, classic): recovery math, offer legality with credit
reservation, rebids resetting the 24h clock, deadline promotion, and admin apply.

Economy under test: budget 1000, roster 3-8-8-6. An offer on a free agent pledges a
same-role release; the ceiling is (remaining - reserved_net) + recovery(release).
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from realdata.models import (
    Competition, CompetitionSeason, Player, PlayerTeamStint, Season, Team,
    TeamSeason,
)
from vfoot.models import (
    FantasyLeague, FantasyRosterSlot, FantasyTeam, LeagueMembership,
    LeaguePlayerRole, MarketOffer, MarketSession,
)
from vfoot.services import market_engine as me


class MarketBase(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2025-2026"),
            name="Serie A 2025-2026")
        self.team_season = TeamSeason.objects.create(
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

    def _player(self, name, role, *, fieldable=True):
        p = Player.objects.create(full_name=name, short_name=name)
        LeaguePlayerRole.objects.create(league=self.league, player=p, role=role)
        if fieldable:
            # An OPEN stint in the reference season -> counts as a free agent pool member.
            PlayerTeamStint.objects.create(
                player=p, team_season=self.team_season, end_date=None)
        return p

    def _player_without_role(self, name, role):
        """Un giocatore arrivato DOPO l'ultimo giro del listone: gioca nella
        stagione di riferimento e ha il suo ruolo di provenienza, ma nessuna riga
        congelata nella lega — quindi non e' ancora offribile."""
        p = Player.objects.create(full_name=name, short_name=name,
                                  classic_role_seed=role)
        PlayerTeamStint.objects.create(
            player=p, team_season=self.team_season, end_date=None)
        return p

    def _own(self, team, player, price):
        return FantasyRosterSlot.objects.create(team=team, player=player, purchase_price=price)

    def _session(self, mode=MarketSession.RECOVERY_FRAC50, fixed=1, opens_in=None):
        """Sessione viva. Di norma gia' aperta (``opened_at`` valorizzato): senza,
        la prima richiesta la prenderebbe per un'apertura programmata appena
        scattata e rifarebbe il giro del listone. ``opens_in`` la programma nel
        futuro, com'e' quando l'admin la annuncia in anticipo."""
        now = timezone.now()
        opens_at = now + opens_in if opens_in is not None else now
        return MarketSession.objects.create(
            league=self.league, status=MarketSession.STATUS_OPEN,
            credit_recovery_mode=mode, fixed_recovery_amount=fixed,
            opens_at=opens_at, opened_at=None if opens_in is not None else now,
            created_by=self.admin)

    def _as(self, user):
        self.client.force_authenticate(user=user)
        return self.client


class RecoveryMathTests(TestCase):
    """Pure recovery arithmetic — unsaved session instances (the live-session
    uniqueness constraint forbids several open sessions per league)."""

    def _s(self, mode, fixed=1):
        return MarketSession(credit_recovery_mode=mode, fixed_recovery_amount=fixed)

    def test_fixed_recovery(self):
        self.assertEqual(me.recovery_for(self._s(MarketSession.RECOVERY_FIXED, 3), 135), 3)

    def test_fraction_rounds_up(self):
        self.assertEqual(me.recovery_for(self._s(MarketSession.RECOVERY_FRAC50), 135), 68)  # ceil(67.5)
        self.assertEqual(me.recovery_for(self._s(MarketSession.RECOVERY_FRAC30), 135), 41)  # ceil(40.5)
        self.assertEqual(me.recovery_for(self._s(MarketSession.RECOVERY_FRAC75), 10), 8)    # ceil(7.5)


class OfferLegalityTests(MarketBase):
    def test_worked_example_ceiling(self):
        # Mario owns Lautaro (135), so 1000-135 = 865 remaining. To match the doc's
        # example we squeeze his cash to 26 by parking the rest on a filler.
        lautaro = self._player("Lautaro", "ATT", fieldable=False)
        self._own(self.t2, lautaro, 135)
        filler = self._player("Filler", "ATT", fieldable=False)
        self._own(self.t2, filler, 1000 - 135 - 26)  # spend down to 26 remaining
        vlahovic = self._player("Vlahovic", "ATT")

        s = self._session(MarketSession.RECOVERY_FRAC50)
        chk = me.check_offer(s, self.t2, vlahovic.id, lautaro.id, 94)
        self.assertTrue(chk.ok, chk.reason)
        self.assertEqual(chk.max_amount, 94)   # 26 + ceil(135/2)=68
        self.assertFalse(me.check_offer(s, self.t2, vlahovic.id, lautaro.id, 95).ok)

    def test_role_must_match(self):
        defender = self._player("Bastoni", "DIF", fieldable=False)
        self._own(self.t2, defender, 50)
        striker = self._player("Osimhen", "ATT")
        s = self._session()
        chk = me.check_offer(s, self.t2, striker.id, defender.id, 5)
        self.assertFalse(chk.ok)
        self.assertIn("Ruolo diverso", chk.reason)

    def test_release_must_be_on_roster(self):
        someone = self._player("NotMine", "ATT", fieldable=False)  # not owned by t2
        target = self._player("Target", "ATT")
        s = self._session()
        chk = me.check_offer(s, self.t2, target.id, someone.id, 5)
        self.assertFalse(chk.ok)
        self.assertIn("non e' nella tua rosa", chk.reason)

    def test_target_must_be_free_agent(self):
        mine = self._player("Mine", "ATT", fieldable=False)
        self._own(self.t2, mine, 10)
        # Target owned by another team -> not a free agent.
        rostered = self._player("Owned", "ATT", fieldable=False)
        self._own(self.t3, rostered, 20)
        s = self._session()
        chk = me.check_offer(s, self.t2, rostered.id, mine.id, 5)
        self.assertFalse(chk.ok)
        self.assertIn("svincolato", chk.reason)


class ReservationTests(MarketBase):
    def test_two_open_offers_reserve_net_credits(self):
        # Mario: 1000 - 990 spent = 10 remaining, releasing two DIFs each bought at 5
        # (recovery fixed 1). First offer of 10 (net 9) leaves available = 1 for the
        # second, whose ceiling is 1 + 1 = 2.
        d1 = self._player("D1", "DIF", fieldable=False)
        d2 = self._player("D2", "DIF", fieldable=False)
        self._own(self.t2, d1, 5)
        self._own(self.t2, d2, 5)
        park = self._player("Park", "ATT", fieldable=False)
        self._own(self.t2, park, 980)  # spend to 10 remaining
        fa1 = self._player("FA1", "DIF")
        fa2 = self._player("FA2", "DIF")
        s = self._session(MarketSession.RECOVERY_FIXED, fixed=1)

        me.place_offer(s, self.t2, fa1.id, d1.id, 10, actor=self.u2)
        # remaining 10, reserved_net = 10-1 = 9, available = 1 -> ceiling 1+1 = 2.
        chk = me.check_offer(s, self.t2, fa2.id, d2.id, 3)
        self.assertFalse(chk.ok)
        self.assertEqual(chk.max_amount, 2)
        self.assertTrue(me.check_offer(s, self.t2, fa2.id, d2.id, 2).ok)

    def test_cannot_pledge_same_release_twice(self):
        d1 = self._player("D1", "DIF", fieldable=False)
        self._own(self.t2, d1, 5)
        fa1 = self._player("FA1", "DIF")
        fa2 = self._player("FA2", "DIF")
        s = self._session()
        me.place_offer(s, self.t2, fa1.id, d1.id, 3, actor=self.u2)
        chk = me.check_offer(s, self.t2, fa2.id, d1.id, 3)
        self.assertFalse(chk.ok)
        self.assertIn("svincolo su un'altra offerta", chk.reason)


class RebidTests(MarketBase):
    def test_rebid_demotes_and_resets_clock(self):
        d2 = self._player("MarioDef", "DIF", fieldable=False)
        d3 = self._player("LuigiDef", "DIF", fieldable=False)
        self._own(self.t2, d2, 5)
        self._own(self.t3, d3, 5)
        fa = self._player("FreeDef", "DIF")
        s = self._session()

        o1 = me.place_offer(s, self.t2, fa.id, d2.id, 5, actor=self.u2)
        old_deadline = o1.deadline_at
        # Luigi rebids higher; Mario's offer becomes outbid, a fresh leader appears.
        later = timezone.now() + timedelta(hours=1)
        o2 = me.place_offer(s, self.t3, fa.id, d3.id, 8, actor=self.u3, now=later)
        o1.refresh_from_db()
        self.assertEqual(o1.status, MarketOffer.STATUS_OUTBID)
        self.assertEqual(o2.status, MarketOffer.STATUS_LEADING)
        self.assertGreater(o2.deadline_at, old_deadline)

    def test_rebid_must_exceed_leader(self):
        d2 = self._player("MarioDef", "DIF", fieldable=False)
        d3 = self._player("LuigiDef", "DIF", fieldable=False)
        self._own(self.t2, d2, 5)
        self._own(self.t3, d3, 5)
        fa = self._player("FreeDef", "DIF")
        s = self._session()
        me.place_offer(s, self.t2, fa.id, d2.id, 5, actor=self.u2)
        chk = me.check_offer(s, self.t3, fa.id, d3.id, 5)  # equal, not higher
        self.assertFalse(chk.ok)
        self.assertIn("rilancio", chk.reason)


class PromotionAndApplyTests(MarketBase):
    def test_promotion_only_after_deadline(self):
        d2 = self._player("MarioDef", "DIF", fieldable=False)
        self._own(self.t2, d2, 5)
        fa = self._player("FreeDef", "DIF")
        s = self._session()
        offer = me.place_offer(s, self.t2, fa.id, d2.id, 5, actor=self.u2)

        self.assertEqual(me.promote_expired(s), [])   # not due yet
        after = offer.deadline_at + timedelta(seconds=1)
        promoted = me.promote_expired(s, now=after)
        self.assertEqual([o.id for o in promoted], [offer.id])
        offer.refresh_from_db()
        self.assertEqual(offer.status, MarketOffer.STATUS_ACCEPTED)

    def test_apply_swaps_roster_and_price(self):
        d2 = self._player("MarioDef", "DIF", fieldable=False)
        self._own(self.t2, d2, 40)
        fa = self._player("FreeDef", "DIF")
        s = self._session(MarketSession.RECOVERY_FRAC50)
        offer = me.place_offer(s, self.t2, fa.id, d2.id, 30, actor=self.u2)
        me.promote_expired(s, now=offer.deadline_at + timedelta(seconds=1))
        offer.refresh_from_db()

        me.apply_offer(offer, actor=self.admin)
        offer.refresh_from_db()
        self.assertEqual(offer.status, MarketOffer.STATUS_SETTLED)
        # Released player is gone from the active roster; target is in at price 30.
        self.assertFalse(FantasyRosterSlot.objects.filter(
            team=self.t2, player=d2, released_at__isnull=True).exists())
        acq = FantasyRosterSlot.objects.get(
            team=self.t2, player=fa, released_at__isnull=True)
        self.assertEqual(acq.purchase_price, 30)

    def test_suspended_session_does_not_promote(self):
        d2 = self._player("MarioDef", "DIF", fieldable=False)
        self._own(self.t2, d2, 5)
        fa = self._player("FreeDef", "DIF")
        s = self._session()
        offer = me.place_offer(s, self.t2, fa.id, d2.id, 5, actor=self.u2)
        s.status = MarketSession.STATUS_SUSPENDED
        s.save(update_fields=["status"])
        self.assertEqual(me.promote_expired(s, now=offer.deadline_at + timedelta(hours=2)), [])


class MarketApiTests(MarketBase):
    def test_full_flow_over_api(self):
        d2 = self._player("MarioDef", "DIF", fieldable=False)
        self._own(self.t2, d2, 40)
        fa = self._player("FreeDef", "DIF")

        # Admin opens a session.
        r = self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/market/sessions/create",
            {"credit_recovery_mode": "frac50"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        sid = r.json()["session_id"]

        # Mario offers.
        r = self._as(self.u2).post(
            f"/api/v1/leagues/{self.league.id}/market/offers",
            {"target_player_id": fa.id, "release_player_id": d2.id, "amount": 30},
            format="json")
        self.assertEqual(r.status_code, 201, r.content)
        offer_id = r.json()["offer_id"]

        # Active state shows my offer and my budget.
        r = self._as(self.u2).get(f"/api/v1/leagues/{self.league.id}/market/active")
        body = r.json()
        self.assertEqual(len(body["my_offers"]), 1)
        # net reservation = amount - recovery; recovery = ceil(40*50%) = 20.
        self.assertEqual(body["my_budget"]["reserved"], 30 - 20)

        # A non-admin cannot accept (the codebase hides admin endpoints behind 404).
        r = self._as(self.u2).post(
            f"/api/v1/leagues/{self.league.id}/market/offers/{offer_id}/accept", format="json")
        self.assertEqual(r.status_code, 404)

        # Force the deadline past, then admin accepts -> roster swapped.
        MarketOffer.objects.filter(id=offer_id).update(
            deadline_at=timezone.now() - timedelta(minutes=1))
        MarketSession.objects.get(id=sid)  # sanity
        r = self._as(self.admin).get(f"/api/v1/leagues/{self.league.id}/market/active")
        self.assertEqual(len(r.json()["admin_queue"]), 1)   # promoted lazily on read

        r = self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/market/offers/{offer_id}/accept", format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(FantasyRosterSlot.objects.filter(
            team=self.t2, player=fa, released_at__isnull=True).exists())

    def test_one_live_session_per_league(self):
        self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/market/sessions/create",
            {"credit_recovery_mode": "fixed"}, format="json")
        r = self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/market/sessions/create",
            {"credit_recovery_mode": "fixed"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("gia' una sessione", r.json()["detail"])
