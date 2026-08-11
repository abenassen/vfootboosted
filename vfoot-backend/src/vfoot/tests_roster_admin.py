"""Le tre operazioni dell'admin su una rosa, e i conti che ne restano.

Acquisto, vendita, annullamento: tre gesti diversi, non tre modi di dire lo
stesso. Quello che li tiene insieme e' il portafoglio, che non e' un saldo
memorizzato da nessuna parte — si rilegge ogni volta dai contratti:

    residuo = budget iniziale
            - quanto pesano i contratti aperti
            - quanto hanno bruciato quelli chiusi (pagato - incassato)

Il secondo termine e' la ragione di questo file. Finche' non c'era, chiudere un
contratto restituiva ogni credito pagato qualunque cifra fosse stata pattuita:
il tetto veniva applicato al momento dell'offerta e disfatto un attimo dopo.
"""
from __future__ import annotations

from vfoot.models import FantasyRosterSlot, MarketSession
from vfoot.services import market_engine as me
from vfoot.services.auction_engine import team_budgets
from vfoot.tests_market import MarketBase


class AdminRosterOpsTests(MarketBase):
    def _remaining(self, team):
        return team_budgets(self.league)[team.id].remaining

    def _url(self, team, action):
        return f"/api/v1/leagues/{self.league.id}/teams/{team.id}/roster/{action}"

    # --- vendita ---------------------------------------------------------

    def test_selling_leaves_the_hole_the_admin_decided(self):
        """Comprato a 100, ceduto per 30: mancano 70 alla cassa, per sempre."""
        p = self._player("Ceduto", "DIF")
        self._own(self.t2, p, 100)
        self.assertEqual(self._remaining(self.t2), 900)

        r = self._as(self.admin).post(self._url(self.t2, "sell"),
                                      {"player_id": p.id, "sale_price": 30}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._remaining(self.t2), 930)

    def test_selling_without_a_price_gives_everything_back(self):
        """Il comportamento storico del vecchio Remove, ora dichiarato: senza una
        cifra l'incasso e' il prezzo pagato, e la cassa torna com'era."""
        p = self._player("Ceduto", "DIF")
        self._own(self.t2, p, 100)

        r = self._as(self.admin).post(self._url(self.t2, "sell"),
                                      {"player_id": p.id}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["sale_price"], 100)
        self.assertEqual(self._remaining(self.t2), 1000)

    def test_selling_above_the_purchase_price_is_a_gain(self):
        """L'admin trascrive un accordo preso fuori dall'app: se l'ha rivenduto a
        piu' di quanto l'aveva pagato, la squadra ci guadagna."""
        p = self._player("Rivenduto", "DIF")
        self._own(self.t2, p, 10)

        self._as(self.admin).post(self._url(self.t2, "sell"),
                                  {"player_id": p.id, "sale_price": 40}, format="json")
        self.assertEqual(self._remaining(self.t2), 1030)

    def test_a_sold_player_frees_his_slot_and_can_be_bought_again(self):
        p = self._player("Girovago", "DIF")
        self._own(self.t2, p, 10)
        self._as(self.admin).post(self._url(self.t2, "sell"),
                                  {"player_id": p.id, "sale_price": 1}, format="json")

        r = self._as(self.admin).post(self._url(self.t3, "add"),
                                      {"player_id": p.id, "purchase_price": 5}, format="json")
        self.assertEqual(r.status_code, 201)
        # e i due conti restano separati: chi ha venduto porta il suo buco
        self.assertEqual(self._remaining(self.t2), 991)
        self.assertEqual(self._remaining(self.t3), 995)

    # --- annullamento ----------------------------------------------------

    def test_voiding_erases_the_contract(self):
        """Non e' una cessione a incasso pieno: la riga sparisce, quindi non
        resta nello storico un acquisto seguito da una cessione mai avvenuta."""
        p = self._player("Errore", "DIF")
        slot = self._own(self.t2, p, 100)

        r = self._as(self.admin).post(self._url(self.t2, "void"),
                                      {"player_id": p.id}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(FantasyRosterSlot.objects.filter(id=slot.id).exists())
        self.assertEqual(self._remaining(self.t2), 1000)

    def test_voiding_a_closed_contract_needs_its_slot_id(self):
        """Di contratti chiusi sullo stesso giocatore ce ne puo' essere piu' d'uno:
        per nome non si saprebbe quale. Annullarne uno cancella anche il suo buco."""
        p = self._player("Ceduto", "DIF")
        slot = self._own(self.t2, p, 100)
        self._as(self.admin).post(self._url(self.t2, "sell"),
                                  {"player_id": p.id, "sale_price": 30}, format="json")
        self.assertEqual(self._remaining(self.t2), 930)

        r = self._as(self.admin).post(self._url(self.t2, "void"),
                                      {"slot_id": slot.id}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._remaining(self.t2), 1000)

    def test_voiding_needs_to_be_told_what(self):
        r = self._as(self.admin).post(self._url(self.t2, "void"), {}, format="json")
        self.assertEqual(r.status_code, 400)

    # --- acquisto --------------------------------------------------------

    def test_buying_refuses_a_role_that_is_already_full(self):
        """Prima passava: il nono difensore entrava in rosa e la squadra
        risultava illegale solo piu' tardi, in campo."""
        for i in range(self.league.slots_def):
            self._own(self.t2, self._player(f"Dif {i}", "DIF"), 1)
        extra = self._player("Nono", "DIF")

        r = self._as(self.admin).post(self._url(self.t2, "add"),
                                      {"player_id": extra.id, "purchase_price": 1}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "illegal_purchase")
        self.assertIn("DIF", r.json()["detail"])

    def test_buying_refuses_a_price_that_would_bankrupt_the_rest(self):
        """Il tetto e' 'lascia almeno 1 per ogni casella ancora vuota': con 25
        slot e 1000 crediti, il primo acquisto non puo' superare 976."""
        p = self._player("Fenomeno", "ATT")
        r = self._as(self.admin).post(self._url(self.t2, "add"),
                                      {"player_id": p.id, "purchase_price": 977}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["max_price"], 976)

        r = self._as(self.admin).post(self._url(self.t2, "add"),
                                      {"player_id": p.id, "purchase_price": 976}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_force_is_there_for_a_roster_that_comes_from_elsewhere(self):
        """Ricostruire una rosa gia' giocata su un'altra app: i conti non tornano
        con questa lega, e va bene — ma bisogna chiederlo per nome."""
        p = self._player("Fenomeno", "ATT")
        r = self._as(self.admin).post(
            self._url(self.t2, "add"),
            {"player_id": p.id, "purchase_price": 999, "force": True}, format="json")
        self.assertEqual(r.status_code, 201)

    # --- la rosa che il pannello legge -----------------------------------

    def test_the_roster_carries_role_and_wallet(self):
        self._own(self.t2, self._player("Portiere", "POR"), 20)
        r = self._as(self.admin).get(
            f"/api/v1/leagues/{self.league.id}/teams/{self.t2.id}/roster")
        body = r.json()
        self.assertEqual(body["players"][0]["role"], "POR")
        self.assertEqual(body["budget"]["remaining"], 980)
        self.assertEqual(body["budget"]["slots"]["POR"], {"quota": 3, "filled": 1, "remaining": 2})

    # --- la regressione che ha fatto nascere sale_price ------------------

    def test_a_settled_offer_no_longer_prints_credits(self):
        """Comprato a 100, svincolato col recupero pattuito di 1, acquisto da 5:
        la squadra deve USCIRNE con 4 crediti in meno. Prima ne guadagnava 95 —
        il tetto veniva applicato all'offerta e sciolto alla validazione."""
        session = self._session(mode=MarketSession.RECOVERY_FIXED, fixed=1)
        out = self._player("Uscente", "DIF")
        into = self._player("Entrante", "DIF")
        self._own(self.t2, out, 100)
        before = self._remaining(self.t2)

        offer = me.place_offer(session, self.t2, into.id, out.id, 5, actor=self.u2)
        me.apply_offer(offer, actor=self.admin)

        self.assertEqual(self._remaining(self.t2) - before, -4)
