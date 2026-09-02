"""Repair market (offer-based, classic): recovery math, offer legality with credit
reservation, rebids resetting the 24h clock, deadline promotion, and admin apply.

Economy under test: budget 1000, roster 3-8-8-6. An offer on a free agent pledges a
same-role release; the ceiling is (remaining - reserved_net) + recovery(release),
where reserved_net sums max(0, amount - recovery) over the manager's live offers.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from realdata.models import (
    Competition, CompetitionSeason, Match, Player, PlayerTeamStint, Season, Team,
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

    def test_a_cheap_offer_with_a_big_recovery_does_not_fund_the_others(self):
        # Il recupero dello svincolo vale SOLO nell'offerta che lo promette: se
        # quella viene superata il giocatore resta in rosa e i crediti non arrivano.
        # Mario: 10 residui. Offre 1 per FA1 svincolando D1 pagato 50 (recupero
        # 50% = 25): netto -24. Prima quel -24 allargava i disponibili a 34, e
        # un'altra offerta poteva spenderli; ora restano 10.
        d1 = self._player("D1", "DIF", fieldable=False)
        d2 = self._player("D2", "DIF", fieldable=False)
        self._own(self.t2, d1, 50)
        self._own(self.t2, d2, 5)
        park = self._player("Park", "ATT", fieldable=False)
        self._own(self.t2, park, 935)  # 1000 - 50 - 5 - 935 = 10 remaining
        fa1 = self._player("FA1", "DIF")
        fa2 = self._player("FA2", "DIF")
        s = self._session(MarketSession.RECOVERY_FRAC50)

        # La prima offerta da sola puo' salire fino a 10 + 25 = 35.
        self.assertEqual(me.check_offer(s, self.t2, fa1.id, d1.id, 35).max_amount, 35)
        me.place_offer(s, self.t2, fa1.id, d1.id, 1, actor=self.u2)

        st = me.market_states(s.league, s)[self.t2.id]
        self.assertEqual(st.reserved_net, 0)
        self.assertEqual(st.available(), 10)
        # Seconda offerta: 10 disponibili + recupero(D2) = ceil(2.5) = 3 -> tetto 13.
        chk = me.check_offer(s, self.t2, fa2.id, d2.id, 14)
        self.assertFalse(chk.ok)
        self.assertEqual(chk.max_amount, 13)
        self.assertTrue(me.check_offer(s, self.t2, fa2.id, d2.id, 13).ok)

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

    def test_the_leading_row_names_the_promised_release(self):
        """Un'offerta e' uno scambio pari ruolo: la lista deve dire anche chi
        esce, non solo chi entra e a quanto. Vale per chiunque guardi — qui un
        rivale, che e' proprio chi deve decidere se rilanciare."""
        d2 = self._player("MarioDef", "DIF", fieldable=False)
        self._own(self.t2, d2, 40)
        fa = self._player("FreeDef", "DIF")
        self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/market/sessions/create",
            {"credit_recovery_mode": "frac50"}, format="json")
        r = self._as(self.u2).post(
            f"/api/v1/leagues/{self.league.id}/market/offers",
            {"target_player_id": fa.id, "release_player_id": d2.id, "amount": 30},
            format="json")
        self.assertEqual(r.status_code, 201, r.content)

        body = self._as(self.u3).get(
            f"/api/v1/leagues/{self.league.id}/market/active").json()
        lead = next(f for f in body["free_agents"] if f["player_id"] == fa.id)["leading"]
        self.assertEqual(lead["release_player_id"], d2.id)
        self.assertEqual(lead["release_name"], "MarioDef")

    def test_a_won_offer_still_says_who_won_it_while_it_waits(self):
        """Fra la vittoria e la validazione l'offerta non deve sparire: era
        pubblica un istante prima (stava in testa) e torna pubblica appena
        l'admin decide. Qui la guarda un rivale, che e' chi ci rimane male."""
        d2 = self._player("MarioDef", "DIF", fieldable=False)
        self._own(self.t2, d2, 40)
        fa = self._player("FreeDef", "DIF")
        self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/market/sessions/create",
            {"credit_recovery_mode": "frac50"}, format="json")
        r = self._as(self.u2).post(
            f"/api/v1/leagues/{self.league.id}/market/offers",
            {"target_player_id": fa.id, "release_player_id": d2.id, "amount": 30},
            format="json")
        MarketOffer.objects.filter(id=r.json()["offer_id"]).update(
            deadline_at=timezone.now() - timedelta(minutes=1))

        # La lettura stessa promuove l'offerta a `accepted`: da qui in poi il
        # giocatore e' bloccato e la decisione e' dell'admin.
        body = self._as(self.u3).get(
            f"/api/v1/leagues/{self.league.id}/market/active").json()
        row = next(f for f in body["free_agents"] if f["player_id"] == fa.id)
        self.assertTrue(row["locked"])
        self.assertIsNone(row["leading"])
        self.assertEqual(row["pending"]["team_name"], "MarioFC")
        self.assertEqual(row["pending"]["amount"], 30)
        self.assertEqual(row["pending"]["release_name"], "MarioDef")
        self.assertFalse(row["pending"]["mine"])
        # E per chi l'ha vinta e' "tua".
        mine = next(f for f in self._as(self.u2).get(
            f"/api/v1/leagues/{self.league.id}/market/active").json()["free_agents"]
            if f["player_id"] == fa.id)
        self.assertTrue(mine["pending"]["mine"])

    def test_one_live_session_per_league(self):
        self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/market/sessions/create",
            {"credit_recovery_mode": "fixed"}, format="json")
        r = self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/market/sessions/create",
            {"credit_recovery_mode": "fixed"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("gia' una sessione", r.json()["detail"])


class DiscardRebidTests(MarketBase):
    """Annullare (o rifiutare) un'offerta che era un RILANCIO.

    Sotto c'e' un'offerta superata che il codice non rimette in piedi da sola. La
    decisione non e' del server: l'admin la vede raccontata e sceglie. Qui si
    verifica che il racconto sia vero e che la scelta abbia l'effetto promesso.
    """

    def setUp(self):
        super().setUp()
        # Mario stretto ai vfooties: 1000 - 40 - 4 - 946 = 10 residui.
        self.d2 = self._player("MarioDef", "DIF", fieldable=False)
        self.d2b = self._player("MarioDefB", "DIF", fieldable=False)
        self.filler = self._player("MarioFiller", "ATT", fieldable=False)
        self._own(self.t2, self.d2, 40)
        self._own(self.t2, self.d2b, 4)
        self._own(self.t2, self.filler, 946)
        # Luigi comodo.
        self.d3 = self._player("LuigiDef", "DIF", fieldable=False)
        self._own(self.t3, self.d3, 5)

        self.fa = self._player("FreeDef", "DIF")
        self.fa2 = self._player("FreeDefB", "DIF")
        self.s = self._session(MarketSession.RECOVERY_FRAC50)

    def _chain(self, first_ago=timedelta(hours=2), rebid_ago=timedelta(hours=1)):
        """Mario offre 30, Luigi rilancia a 31. Torna (offerta di Mario, di Luigi)."""
        now = timezone.now()
        a = me.place_offer(self.s, self.t2, self.fa.id, self.d2.id, 30,
                           actor=self.u2, now=now - first_ago)
        b = me.place_offer(self.s, self.t3, self.fa.id, self.d3.id, 31,
                           actor=self.u3, now=now - rebid_ago)
        a.refresh_from_db()
        return a, b

    def _preview(self, offer_id, action="cancel"):
        r = self._as(self.admin).get(
            f"/api/v1/leagues/{self.league.id}/market/offers/{offer_id}/{action}")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def _discard(self, offer_id, action="cancel", **body):
        return self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/market/offers/{offer_id}/{action}",
            body, format="json")

    # --- chi c'e' sotto -----------------------------------------------------

    def test_previous_is_the_one_just_below(self):
        """Catena A -> B -> C: togliendo C si guarda B, mai A."""
        now = timezone.now()
        a = me.place_offer(self.s, self.t2, self.fa.id, self.d2.id, 10,
                           actor=self.u2, now=now - timedelta(hours=3))
        b = me.place_offer(self.s, self.t3, self.fa.id, self.d3.id, 20,
                           actor=self.u3, now=now - timedelta(hours=2))
        c = me.place_offer(self.s, self.t_admin, self.fa.id,
                           self._own(self.t_admin,
                                     self._player("AdminDef", "DIF", fieldable=False),
                                     5).player_id,
                           30, actor=self.admin, now=now - timedelta(hours=1))
        self.assertEqual(me.previous_offer_for(c).id, b.id)
        self.assertEqual(me.previous_offer_for(b).id, a.id)

    def test_lone_offer_is_not_a_rebid(self):
        offer = me.place_offer(self.s, self.t2, self.fa.id, self.d2.id, 30, actor=self.u2)
        pv = self._preview(offer.id)
        self.assertFalse(pv["is_rebid"])
        self.assertIsNone(pv["previous"])
        # Nessuna decisione da prendere: passa liscia com'e' sempre stato.
        r = self._discard(offer.id)
        self.assertEqual(r.status_code, 200, r.content)
        offer.refresh_from_db()
        self.assertEqual(offer.status, MarketOffer.STATUS_CANCELLED)

    # --- il racconto all'admin ---------------------------------------------

    def test_preview_describes_a_live_previous_offer(self):
        a, b = self._chain()
        pv = self._preview(b.id)
        self.assertTrue(pv["is_rebid"])
        prev = pv["previous"]
        self.assertEqual(prev["offer_id"], a.id)
        self.assertEqual(prev["team_name"], "MarioFC")
        self.assertEqual(prev["amount"], 30)
        self.assertEqual(prev["release_name"], "MarioDef")
        self.assertTrue(prev["restorable"])
        self.assertFalse(prev["expired"])
        self.assertFalse(prev["would_queue"])

    def test_preview_flags_an_expired_previous_offer(self):
        """Scaduta mentre il rilancio la teneva coperta: ripristinarla vuol dire
        mandarla dritta in coda di validazione."""
        a, b = self._chain(first_ago=timedelta(hours=30), rebid_ago=timedelta(hours=7))
        prev = self._preview(b.id)["previous"]
        self.assertTrue(prev["expired"])
        self.assertTrue(prev["would_queue"])
        self.assertTrue(prev["restorable"])

    def test_preview_flags_credits_spent_elsewhere(self):
        a, b = self._chain()
        # Mario impegna altrove quel che gli restava: 10 disponibili + 2 di
        # recupero = 12 al massimo, e il netto prenotato lo lascia a secco.
        me.place_offer(self.s, self.t2, self.fa2.id, self.d2b.id, 12, actor=self.u2)
        prev = self._preview(b.id)["previous"]
        self.assertFalse(prev["restorable"])
        self.assertIn("vfooties", prev["blocker"])

    def test_preview_flags_a_released_pledge(self):
        a, b = self._chain()
        # Il giocatore che Mario prometteva in svincolo ha gia' lasciato la rosa.
        FantasyRosterSlot.objects.filter(team=self.t2, player=self.d2).update(
            released_at=timezone.now())
        prev = self._preview(b.id)["previous"]
        self.assertFalse(prev["restorable"])
        self.assertIn("svincolo", prev["blocker"])

    # --- la decisione -------------------------------------------------------

    def test_discarding_a_rebid_without_a_decision_changes_nothing(self):
        a, b = self._chain()
        r = self._discard(b.id)
        self.assertEqual(r.status_code, 409, r.content)
        self.assertTrue(r.json()["requires_decision"])
        self.assertEqual(r.json()["previous"]["offer_id"], a.id)
        b.refresh_from_db()
        self.assertEqual(b.status, MarketOffer.STATUS_LEADING)

    def test_cancel_without_restore_leaves_the_player_free(self):
        """La scelta di non fare niente resta possibile: e' lo stato attuale."""
        a, b = self._chain()
        r = self._discard(b.id, restore_previous=False)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIsNone(r.json()["restored"])
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(b.status, MarketOffer.STATUS_CANCELLED)
        self.assertEqual(a.status, MarketOffer.STATUS_OUTBID)
        self.assertIsNone(me.leading_offer_for(self.s, self.fa.id))

    def test_restore_puts_the_previous_offer_back_on_its_own_clock(self):
        a, b = self._chain()
        deadline = a.deadline_at
        r = self._discard(b.id, restore_previous=True)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["restored"]["offer_id"], a.id)
        a.refresh_from_db()
        self.assertEqual(a.status, MarketOffer.STATUS_LEADING)
        self.assertIsNone(a.resolved_at)
        # L'orologio NON riparte: il tempo consumato l'ha consumato davvero.
        self.assertEqual(a.deadline_at, deadline)
        self.assertEqual(me.leading_offer_for(self.s, self.fa.id).id, a.id)

    def test_restoring_an_expired_offer_queues_it_for_validation(self):
        a, b = self._chain(first_ago=timedelta(hours=30), rebid_ago=timedelta(hours=7))
        self._discard(b.id, restore_previous=True)
        a.refresh_from_db()
        self.assertEqual(a.status, MarketOffer.STATUS_ACCEPTED)
        queue = self._as(self.admin).get(
            f"/api/v1/leagues/{self.league.id}/market/active").json()["admin_queue"]
        self.assertEqual([q["offer_id"] for q in queue], [a.id])

    def test_impossible_restore_leaves_everything_untouched(self):
        a, b = self._chain()
        me.place_offer(self.s, self.t2, self.fa2.id, self.d2b.id, 12, actor=self.u2)
        r = self._discard(b.id, restore_previous=True)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("non e' piu' ripristinabile", r.json()["detail"])
        # O tutt'e due le cose, o nessuna: il rilancio e' ancora in testa.
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(b.status, MarketOffer.STATUS_LEADING)
        self.assertEqual(a.status, MarketOffer.STATUS_OUTBID)

    def test_reject_from_the_queue_takes_the_same_road(self):
        """Rifiutare un'offerta vinta lascia sotto lo stesso vuoto di un
        annullamento, e si decide allo stesso modo."""
        a, b = self._chain(first_ago=timedelta(hours=30), rebid_ago=timedelta(hours=26))
        me.promote_expired(self.s)
        b.refresh_from_db()
        self.assertEqual(b.status, MarketOffer.STATUS_ACCEPTED)

        self.assertEqual(self._discard(b.id, action="reject").status_code, 409)
        r = self._discard(b.id, action="reject", restore_previous=True)
        self.assertEqual(r.status_code, 200, r.content)
        b.refresh_from_db()
        a.refresh_from_db()
        self.assertEqual(b.status, MarketOffer.STATUS_REJECTED)
        self.assertEqual(a.status, MarketOffer.STATUS_ACCEPTED)

    def test_restore_into_a_closed_session_queues_instead_of_leading(self):
        """A sessione chiusa non esiste piu' un "in testa": la chiusura fa da
        scadenza per tutte, e l'offerta ripristinata va decisa dall'admin."""
        a, b = self._chain()
        me.close_session(self.s, actor=self.admin)
        b.refresh_from_db()
        self._discard(b.id, restore_previous=True)
        a.refresh_from_db()
        self.assertEqual(a.status, MarketOffer.STATUS_ACCEPTED)


class MatchdayFreezeTests(MarketBase):
    """R3 NON C'E' PIU': a giornata in corso si valida.

    Diceva «mentre il campionato e' in campo non cambia nessuna rosa», ed era la
    stampella di R2. Il prezzo lo pagava l'allenatore: con un acquisto in coda
    restava per giorni con i crediti prenotati e il giocatore da svincolare
    impegnato, senza poter offrire per chi si liberava nel frattempo — e senza
    poter mettere in svincolo l'acquisto stesso, che in rosa non c'era ancora.

    A proteggere le formazioni gia' schierate ora c'e' R4 (la rosa di una
    giornata e' quella del suo primo calcio d'inizio), che e' piu' preciso: non
    «la rosa non cambia», ma «la rosa di QUESTA giornata non cambia».
    """

    def _kickoff_now(self):
        """Una partita della stagione di riferimento appena cominciata."""
        Match.objects.create(
            competition_season=self.cs, matchday=5,
            home_team=self.team_season, away_team=self.team_season,
            kickoff=timezone.now() - timedelta(minutes=20), kickoff_provisional=False,
            status=Match.STATUS_LIVE, data_ready=False,
            external_source="sofascore", external_id="live1")

    def _queued_offer(self):
        d2 = self._player("MarioDef", "DIF", fieldable=False)
        self._own(self.t2, d2, 40)
        fa = self._player("FreeDef", "DIF")
        s = self._session(MarketSession.RECOVERY_FRAC50)
        offer = me.place_offer(s, self.t2, fa.id, d2.id, 30, actor=self.u2)
        me.promote_expired(s, now=offer.deadline_at + timedelta(seconds=1))
        offer.refresh_from_db()
        return offer, fa

    def test_applying_goes_through_while_the_round_is_on_the_pitch(self):
        """IL CASO DELL'UTENTE: l'acquisto in coda si valida anche col campionato
        in campo, e da li' e' in rosa — cioe' offribile in svincolo per il
        giocatore che si e' liberato nel frattempo."""
        self._kickoff_now()
        offer, fa = self._queued_offer()
        me.apply_offer(offer, actor=self.admin)
        offer.refresh_from_db()
        self.assertEqual(offer.status, MarketOffer.STATUS_SETTLED)
        self.assertTrue(FantasyRosterSlot.objects.filter(
            team=self.t2, player=fa, released_at__isnull=True).exists())

    def test_the_queue_still_says_a_round_is_being_played(self):
        """Il pannello non lo usa piu' per spegnere il bottone, ma l'admin deve
        sapere che sta validando a giornata in corso: cambia cosa succede alle
        formazioni (niente, fino al turno dopo), e va detto."""
        self._kickoff_now()
        offer, _ = self._queued_offer()
        body = self._as(self.admin).get(
            f"/api/v1/leagues/{self.league.id}/market/active").json()
        self.assertTrue(body["matchday_in_progress"])
        self.assertEqual(body["playing_matchday"], 5)
        self.assertEqual(len(body["admin_queue"]), 1)
        r = self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/market/offers/{offer.id}/accept",
            format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "settled")

    def test_between_rounds_nothing_is_frozen(self):
        offer, fa = self._queued_offer()
        body = self._as(self.admin).get(
            f"/api/v1/leagues/{self.league.id}/market/active").json()
        self.assertFalse(body["matchday_in_progress"])
        self.assertIsNone(body["playing_matchday"])
        r = self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/market/offers/{offer.id}/accept",
            format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(FantasyRosterSlot.objects.filter(
            team=self.t2, player=fa, released_at__isnull=True).exists())

    def test_rejecting_is_not_frozen(self):
        """Rifiutare non muove nessuna rosa: la giornata non c'entra, ed e' la
        sola cosa che l'admin puo' ancora fare mentre si gioca."""
        self._kickoff_now()
        offer, _ = self._queued_offer()
        r = self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/market/offers/{offer.id}/reject",
            format="json")
        self.assertEqual(r.status_code, 200, r.content)
        offer.refresh_from_db()
        self.assertEqual(offer.status, MarketOffer.STATUS_REJECTED)
