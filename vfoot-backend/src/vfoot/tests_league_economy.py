"""Le due cose che l'admin fa all'economia dal di fuori: dare crediti, e
registrare uno scambio fra due allenatori.

Il punto dello scambio non e' che le rose cambino — quello lo fanno gia' vendita
e acquisto separati — ma che il PREZZO viaggi col giocatore: comprato a 50, arriva
a 50, e quel 50 e' la cifra su cui si calcolera' il recupero il giorno che verra'
svincolato. Qui sotto si controlla proprio quello, oltre ai conti.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase

from vfoot.models import (
    BudgetGrant,
    FantasyLeague,
    FantasyRosterSlot,
    FantasyTeam,
    LeagueMembership,
    MarketSession,
    PlayerTrade,
    SavedLineupSnapshot,
)
from vfoot.services import league_economy as econ
from vfoot.services import market_engine as me
from vfoot.services.auction_engine import team_budgets
from vfoot.tests_market import MarketBase


class GrantTests(MarketBase):
    def _remaining(self, team):
        return team_budgets(self.league)[team.id].remaining

    def test_a_tutti_arrivano_a_tutti(self):
        econ.grant_credits(self.league, list(self.league.teams.all()), 50,
                           "Prima del mercato", actor=self.admin)
        for t in self.league.teams.all():
            self.assertEqual(self._remaining(t), 1000 + 50)
        # Un gesto solo: dieci righe con lo stesso batch, non dieci concessioni.
        self.assertEqual(BudgetGrant.objects.values("batch").distinct().count(), 1)

    def test_a_una_squadra_sola(self):
        econ.grant_credits(self.league, [self.t2], 30, actor=self.admin)
        self.assertEqual(self._remaining(self.t2), 1030)
        self.assertEqual(self._remaining(self.t3), 1000)

    def test_i_crediti_dati_si_possono_spendere(self):
        """Non e' un numero decorativo: alza davvero il tetto di un'offerta."""
        mio = self._player("Mio", "ATT", fieldable=False)
        self._own(self.t2, mio, 1000)          # ha speso tutto
        libero = self._player("Libero", "ATT")
        s = self._session(MarketSession.RECOVERY_FIXED, fixed=1)
        self.assertFalse(me.check_offer(s, self.t2, libero.id, mio.id, 20).ok)

        econ.grant_credits(self.league, [self.t2], 50, actor=self.admin)
        self.assertTrue(me.check_offer(s, self.t2, libero.id, mio.id, 20).ok)

    def test_togliere_si_puo_ma_non_sotto_zero(self):
        econ.grant_credits(self.league, [self.t2], -100, actor=self.admin)
        self.assertEqual(self._remaining(self.t2), 900)
        with self.assertRaises(econ.EconomyError) as cm:
            econ.grant_credits(self.league, [self.t2], -1000, actor=self.admin)
        self.assertIn("sotto zero", str(cm.exception))
        self.assertEqual(self._remaining(self.t2), 900)

    def test_annullare_una_concessione(self):
        grants = econ.grant_credits(self.league, [self.t2], 40, actor=self.admin)
        econ.revoke_batch(self.league, grants[0].batch)
        self.assertEqual(self._remaining(self.t2), 1000)
        self.assertEqual(BudgetGrant.objects.count(), 0)

    def test_non_si_annulla_cio_che_e_gia_stato_speso(self):
        grants = econ.grant_credits(self.league, [self.t2], 40, actor=self.admin)
        caro = self._player("Caro", "ATT", fieldable=False)
        self._own(self.t2, caro, 1030)     # 1000 + 40 - 1030 = 10 residui
        with self.assertRaises(econ.EconomyError):
            econ.revoke_batch(self.league, grants[0].batch)
        self.assertEqual(BudgetGrant.objects.count(), 1)

    def test_in_bacheca_una_riga_sola(self):
        econ.grant_credits(self.league, list(self.league.teams.all()), 50,
                           "Dote di riparazione", actor=self.admin)
        body = self._as(self.u2).get(
            f"/api/v1/leagues/{self.league.id}/activity?limit=20").json()
        righe = [i for i in body if i["kind"] == "concessione"]
        self.assertEqual(len(righe), 1, righe)
        self.assertIn("a tutti", righe[0]["text"])
        self.assertEqual(righe[0]["detail"], "Dote di riparazione")

    def test_l_api_da_a_tutti_quando_non_dici_a_chi(self):
        r = self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/budget/grants",
            {"amount": 25, "reason": "Bonus"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["teams"], self.league.teams.count())

    def test_solo_l_admin_puo_darli(self):
        r = self._as(self.u2).post(
            f"/api/v1/leagues/{self.league.id}/budget/grants",
            {"amount": 25}, format="json")
        self.assertEqual(r.status_code, 404)   # gli endpoint admin sono nascosti
        self.assertEqual(BudgetGrant.objects.count(), 0)


class TradeTests(MarketBase):
    def setUp(self):
        super().setUp()
        # Due centrocampisti a prezzi diversi: la differenza e' quello che si vede.
        self.yildiz = self._player("Yildiz", "CEN")
        self.pellegrini = self._player("Pellegrini", "CEN")
        self._own(self.t2, self.yildiz, 50)
        self._own(self.t3, self.pellegrini, 20)

    def _remaining(self, team):
        return team_budgets(self.league)[team.id].remaining

    def _open_slot(self, team, player):
        return FantasyRosterSlot.objects.get(
            team=team, player=player, released_at__isnull=True)

    def test_il_prezzo_viaggia_col_giocatore(self):
        econ.apply_trade(self.league, self.t2, self.t3,
                         [self.yildiz.id], [self.pellegrini.id], actor=self.admin)
        self.assertEqual(self._open_slot(self.t3, self.yildiz).purchase_price, 50)
        self.assertEqual(self._open_slot(self.t2, self.pellegrini).purchase_price, 20)

    def test_il_contratto_di_partenza_si_chiude_senza_buco(self):
        """Chiuso a incasso pieno: la cessione non brucia niente, quel che il
        giocatore costava se lo porta dietro."""
        econ.apply_trade(self.league, self.t2, self.t3,
                         [self.yildiz.id], [self.pellegrini.id], actor=self.admin)
        vecchio = FantasyRosterSlot.objects.get(
            team=self.t2, player=self.yildiz, released_at__isnull=False)
        self.assertEqual(vecchio.sale_price, 50)
        # 1000 - 50 (Yildiz) diventa 1000 - 20 (Pellegrini): +30 in cassa.
        self.assertEqual(self._remaining(self.t2), 1000 - 20)
        self.assertEqual(self._remaining(self.t3), 1000 - 50)

    def test_il_recupero_futuro_e_quello_del_prezzo_ereditato(self):
        """La ragione per cui il prezzo viaggia: svincolandolo dopo, chi lo ha
        ricevuto recupera meta' di 50, non meta' di quello che avrebbe pagato lui."""
        econ.apply_trade(self.league, self.t2, self.t3,
                         [self.yildiz.id], [self.pellegrini.id], actor=self.admin)
        s = self._session(MarketSession.RECOVERY_FRAC50)
        slot = self._open_slot(self.t3, self.yildiz)
        self.assertEqual(me.recovery_for(s, slot.purchase_price), 25)

    def test_la_contropartita_sposta_i_crediti(self):
        econ.apply_trade(self.league, self.t2, self.t3,
                         [self.yildiz.id], [self.pellegrini.id],
                         cash_amount=10, cash_from="b", actor=self.admin)
        # t3 paga 10 a t2, sopra la differenza di prezzo.
        self.assertEqual(self._remaining(self.t2), 1000 - 20 + 10)
        self.assertEqual(self._remaining(self.t3), 1000 - 50 - 10)
        self.assertEqual(BudgetGrant.objects.filter(trade__isnull=False).count(), 2)

    def test_la_contropartita_non_porta_sotto_zero(self):
        speso = self._player("Speso", "ATT", fieldable=False)
        self._own(self.t3, speso, 970)          # a t3 restano 10
        with self.assertRaises(econ.EconomyError) as cm:
            econ.apply_trade(self.league, self.t2, self.t3,
                             [self.yildiz.id], [self.pellegrini.id],
                             cash_amount=100, cash_from="b", actor=self.admin)
        self.assertIn("crediti", str(cm.exception))
        self.assertFalse(PlayerTrade.objects.exists())

    def test_in_classic_i_ruoli_devono_combaciare(self):
        att = self._player("Attaccante", "ATT")
        self._own(self.t3, att, 30)
        check = econ.check_trade(self.league, self.t2, self.t3,
                                 [self.yildiz.id], [att.id])
        self.assertFalse(check.ok)
        self.assertIn("pari ruolo", check.reason)

    def test_in_classic_niente_due_per_uno(self):
        altro = self._player("Altro CEN", "CEN")
        self._own(self.t2, altro, 10)
        check = econ.check_trade(self.league, self.t2, self.t3,
                                 [self.yildiz.id, altro.id], [self.pellegrini.id])
        self.assertFalse(check.ok)
        self.assertIn("CEN", check.reason)

    def test_due_coppie_insieme_si_possono(self):
        mio2 = self._player("Mio DIF", "DIF")
        suo2 = self._player("Suo DIF", "DIF")
        self._own(self.t2, mio2, 5)
        self._own(self.t3, suo2, 7)
        trade = econ.apply_trade(
            self.league, self.t2, self.t3,
            [self.yildiz.id, mio2.id], [self.pellegrini.id, suo2.id], actor=self.admin)
        self.assertIsNotNone(trade.id)
        self.assertEqual(self._open_slot(self.t3, mio2).purchase_price, 5)
        self.assertEqual(self._open_slot(self.t2, suo2).purchase_price, 7)

    def test_un_giocatore_che_non_e_suo(self):
        check = econ.check_trade(self.league, self.t2, self.t3,
                                 [self.pellegrini.id], [self.yildiz.id])
        self.assertFalse(check.ok)
        self.assertIn("non e' nella rosa", check.reason)

    def test_non_si_scambia_chi_e_promesso_a_un_offerta(self):
        """I crediti di quell'offerta sono bloccati contando su di lui: portarlo
        via lascerebbe una trattativa che non puo' piu' concludersi."""
        libero = self._player("Svincolato", "CEN")
        s = self._session()
        me.place_offer(s, self.t2, libero.id, self.yildiz.id, 5, actor=self.u2)
        check = econ.check_trade(self.league, self.t2, self.t3,
                                 [self.yildiz.id], [self.pellegrini.id])
        self.assertFalse(check.ok)
        self.assertIn("offerta di mercato aperta", check.reason)

    def test_lo_scambio_ripara_la_formazione_gia_consegnata(self):
        """R2 dalle due parti: chi entra prende il posto esatto di chi esce."""
        snap = SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), lineup_id=f"team{self.t2.id}",
            matchday_id="1", gk_player_id=None,
            # Gli id nelle formazioni sono stringhe, come li scrive la pagina.
            starter_player_ids=[str(self.yildiz.id)], bench_player_ids=[],
        )
        econ.apply_trade(self.league, self.t2, self.t3,
                         [self.yildiz.id], [self.pellegrini.id], actor=self.admin)
        snap.refresh_from_db()
        self.assertEqual(snap.starter_player_ids, [str(self.pellegrini.id)])

    def test_in_bacheca_e_uno_scambio_non_due_acquisti(self):
        econ.apply_trade(self.league, self.t2, self.t3,
                         [self.yildiz.id], [self.pellegrini.id],
                         cash_amount=10, cash_from="b", actor=self.admin)
        body = self._as(self.u2).get(
            f"/api/v1/leagues/{self.league.id}/activity?limit=30").json()
        scambi = [i for i in body if i["kind"] == "scambio"]
        self.assertEqual(len(scambi), 1, scambi)
        self.assertIn("Yildiz", scambi[0]["detail"])
        self.assertIn("Pellegrini", scambi[0]["detail"])
        # I due contratti nuovi non ricompaiono come acquisti...
        acquisti = [i for i in body if i["kind"] == "acquisto"
                    and ("Yildiz" in i["text"] or "Pellegrini" in i["text"])]
        self.assertEqual(acquisti, [])
        # ...e nemmeno la contropartita come un regalo dell'admin.
        self.assertEqual([i for i in body if i["kind"] == "concessione"], [])

    def test_via_api(self):
        r = self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/trades",
            {"team_a": self.t2.id, "team_b": self.t3.id,
             "players_a": [self.yildiz.id], "players_b": [self.pellegrini.id],
             "cash_amount": 10, "cash_from": "b", "note": "Accordo di gennaio"},
            format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["remaining_a"], 1000 - 20 + 10)
        self.assertEqual(PlayerTrade.objects.get().note, "Accordo di gennaio")

    def test_l_anteprima_non_scrive_niente(self):
        r = self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/trades/check",
            {"team_a": self.t2.id, "team_b": self.t3.id,
             "players_a": [self.yildiz.id], "players_b": [self.pellegrini.id]},
            format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["remaining_a"], 1000 - 20)
        self.assertFalse(PlayerTrade.objects.exists())

    def test_un_manager_non_puo_registrarlo(self):
        r = self._as(self.u2).post(
            f"/api/v1/leagues/{self.league.id}/trades",
            {"team_a": self.t2.id, "team_b": self.t3.id,
             "players_a": [self.yildiz.id], "players_b": [self.pellegrini.id]},
            format="json")
        self.assertEqual(r.status_code, 404)
        self.assertFalse(PlayerTrade.objects.exists())


class AuraTradeTests(TestCase):
    """In aura i ruoli non esistono: il vincolo non ha ragione d'essere."""

    def setUp(self):
        from realdata.models import Player

        self.admin = User.objects.create_user("aura_admin", password="x")
        self.league = FantasyLeague.objects.create(
            name="Lega Aura", owner=self.admin, mode="aura")
        m = LeagueMembership.objects.create(
            league=self.league, user=self.admin, role=LeagueMembership.ROLE_ADMIN)
        u2 = User.objects.create_user("aura_mgr", password="x")
        m2 = LeagueMembership.objects.create(
            league=self.league, user=u2, role=LeagueMembership.ROLE_MANAGER)
        self.t1 = FantasyTeam.objects.create(league=self.league, manager=m, name="A")
        self.t2 = FantasyTeam.objects.create(league=self.league, manager=m2, name="B")
        self.p1 = Player.objects.create(full_name="Uno", short_name="Uno")
        self.p2 = Player.objects.create(full_name="Due", short_name="Due")
        self.p3 = Player.objects.create(full_name="Tre", short_name="Tre")
        FantasyRosterSlot.objects.create(team=self.t1, player=self.p1, purchase_price=9)
        FantasyRosterSlot.objects.create(team=self.t2, player=self.p2, purchase_price=4)
        FantasyRosterSlot.objects.create(team=self.t2, player=self.p3, purchase_price=3)

    def test_liste_di_lunghezza_diversa(self):
        trade = econ.apply_trade(self.league, self.t1, self.t2,
                                 [self.p1.id], [self.p2.id, self.p3.id],
                                 actor=self.admin)
        self.assertIsNotNone(trade.id)
        self.assertEqual(
            FantasyRosterSlot.objects.filter(team=self.t1, released_at__isnull=True)
            .count(), 2)
        self.assertEqual(
            FantasyRosterSlot.objects.filter(team=self.t2, released_at__isnull=True)
            .count(), 1)

    def test_niente_crediti_in_aura(self):
        check = econ.check_trade(self.league, self.t1, self.t2,
                                 [self.p1.id], [self.p2.id], cash_amount=5)
        self.assertFalse(check.ok)
        self.assertIn("aura", check.reason)
