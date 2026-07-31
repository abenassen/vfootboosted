"""Cosa succede alle offerte quando la sessione ha una scadenza programmata.

Sonda del comportamento ATTUALE (nessuna modifica al codice): chiusura via
``market_tick``, offerte in vari stati, e cosa resta all'admin da validare.
"""
from __future__ import annotations

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.utils import timezone

from vfoot.models import MarketOffer, MarketSession
from vfoot.services import market_engine as me
from vfoot.tests_market import MarketBase


class ScheduledCloseTests(MarketBase):
    def _setup(self, closes_in: timedelta | None):
        """Sessione con scadenza + tre offerte: una giovane, una gia' oltre le
        24h ma non ancora promossa, e una gia' accettata."""
        now = timezone.now()
        self.session = self._session()
        if closes_in is not None:
            self.session.closes_at = now + closes_in
            self.session.save(update_fields=["closes_at"])

        # Ogni squadra ha un attaccante da svincolare; tre svincolati in palio.
        self.free = [self._player(f"Libero {i}", "ATT") for i in range(3)]
        self.mine = [self._player(f"Mio {i}", "ATT") for i in range(3)]
        for team, p in zip((self.t2, self.t3, self.t_admin), self.mine):
            self._own(team, p, 100)

        # 1) offerta fresca: il suo timer di 24h scade fra un pezzo
        self.giovane = me.place_offer(
            self.session, self.t2, self.free[0].id, self.mine[0].id, 10,
            now=now - timedelta(hours=1))
        # 2) offerta il cui timer di 24h e' gia' passato ma nessuno l'ha promossa
        self.scaduta = me.place_offer(
            self.session, self.t3, self.free[1].id, self.mine[1].id, 10,
            now=now - timedelta(hours=25))
        # 3) offerta gia' promossa, in coda di validazione
        self.accettata = me.place_offer(
            self.session, self.t_admin, self.free[2].id, self.mine[2].id, 10,
            now=now - timedelta(hours=30))
        me.promote_expired(self.session, now=now - timedelta(hours=2))
        self.accettata.refresh_from_db()
        assert self.accettata.status == MarketOffer.STATUS_ACCEPTED
        # la #2 non deve essere stata promossa da quel giro: e' piu' giovane
        self.scaduta.refresh_from_db()
        assert self.scaduta.status == MarketOffer.STATUS_LEADING, self.scaduta.status

    def _tick(self):
        out = StringIO()
        call_command("market_tick", stdout=out)
        return out.getvalue().strip()

    def _statuses(self):
        for o in (self.giovane, self.scaduta, self.accettata):
            o.refresh_from_db()
        return {
            "giovane (timer 23h da correre)": self.giovane.status,
            "scaduta (timer 24h gia' passato)": self.scaduta.status,
            "accettata (gia' in coda)": self.accettata.status,
        }

    # -- 1. la scadenza non e' ancora arrivata --------------------------------
    def test_prima_della_scadenza_promuove_solo_i_timer_scaduti(self):
        self._setup(closes_in=timedelta(hours=5))
        print("\n[1] scadenza sessione fra 5h ->", self._tick())
        for k, v in self._statuses().items():
            print(f"      {k:36} {v}")
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, MarketSession.STATUS_OPEN)
        self.assertEqual(self.giovane.status, MarketOffer.STATUS_LEADING)
        self.assertEqual(self.scaduta.status, MarketOffer.STATUS_ACCEPTED)

    # -- 2. la scadenza e' passata --------------------------------------------
    def test_alla_scadenza_le_offerte_in_corso_finiscono_annullate(self):
        self._setup(closes_in=timedelta(hours=-1))
        print("\n[2] scadenza sessione gia' passata ->", self._tick())
        for k, v in self._statuses().items():
            print(f"      {k:36} {v}")
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, MarketSession.STATUS_CLOSED)
        # Un'offerta che non ha compiuto le sue 24h NON viene accettata dalla
        # chiusura: viene annullata. Chi le 24h le aveva compiute passa in coda.
        self.assertEqual(self.giovane.status, MarketOffer.STATUS_CANCELLED)
        self.assertEqual(self.scaduta.status, MarketOffer.STATUS_ACCEPTED)
        self.assertEqual(self.accettata.status, MarketOffer.STATUS_ACCEPTED)

    # -- 3. senza il cron, la scadenza non fa nulla da sola -------------------
    def test_senza_tick_la_sessione_resta_aperta_oltre_la_scadenza(self):
        self._setup(closes_in=timedelta(hours=-1))
        c = self._as(self.u2)
        r = c.get(f"/api/v1/leagues/{self.league.id}/market/active")
        print("\n[3] scadenza passata, solo apertura pagina (nessun tick):")
        print(f"      sessione: {r.json()['session']['status']}")
        for k, v in self._statuses().items():
            print(f"      {k:36} {v}")
        self.assertEqual(r.json()["session"]["status"], MarketSession.STATUS_OPEN)
        self.assertEqual(self.giovane.status, MarketOffer.STATUS_LEADING)

    # -- 4. offerta che scade nella stessa finestra della sessione ------------
    def test_timer_scaduto_prima_della_chiusura_viene_promosso(self):
        """Il caso di confine: fra due tick scadono sia il timer dell'offerta sia
        la sessione. L'offerta aveva compiuto le sue 24h, quindi la promozione
        deve precedere la chiusura — altrimenti l'esito dipenderebbe da quando
        e' passato il cron."""
        self._setup(closes_in=timedelta(hours=-1))
        print("\n[4] timer offerta e sessione scaduti entrambi ->", self._tick())
        for k, v in self._statuses().items():
            print(f"      {k:36} {v}")
        self.assertEqual(self.scaduta.status, MarketOffer.STATUS_ACCEPTED)
        self.assertEqual(self.giovane.status, MarketOffer.STATUS_CANCELLED)
