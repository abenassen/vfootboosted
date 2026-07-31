"""Cosa succede alle offerte quando la sessione ha una scadenza programmata.

Sonda del comportamento ATTUALE (nessuna modifica al codice): chiusura via
``market_tick``, offerte in vari stati, e cosa resta all'admin da validare.
"""
from __future__ import annotations

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.utils import timezone

from vfoot.models import FantasyRosterSlot, MarketOffer, MarketSession
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
    def test_alla_scadenza_le_offerte_in_corso_passano_in_validazione(self):
        """La chiusura fa da scadenza per tutte: chi e' in testa passa in coda
        anche se il suo timer di 24h non e' compiuto. E' cio' che rende
        conveniente offrire all'ultimo momento."""
        self._setup(closes_in=timedelta(hours=-1))
        print("\n[2] scadenza sessione gia' passata ->", self._tick())
        for k, v in self._statuses().items():
            print(f"      {k:36} {v}")
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, MarketSession.STATUS_CLOSED)
        self.assertEqual(self.giovane.status, MarketOffer.STATUS_ACCEPTED)
        self.assertEqual(self.scaduta.status, MarketOffer.STATUS_ACCEPTED)
        self.assertEqual(self.accettata.status, MarketOffer.STATUS_ACCEPTED)
        # Nessuna e' andata persa: la coda dell'admin le ha tutte e tre.
        self.assertEqual(MarketOffer.objects.filter(
            session=self.session, status=MarketOffer.STATUS_CANCELLED).count(), 0)

    def test_offerta_dell_ultimo_minuto_arriva_in_coda(self):
        """Lo scenario del cecchino: rilancio pochi minuti prima della chiusura,
        nessuno fa in tempo a rispondere, il giocatore va all'admin per la
        validazione con la mia offerta sopra."""
        self._setup(closes_in=timedelta(minutes=1))
        now = timezone.now()
        # Il suo primo attaccante e' gia' impegnato sull'altra offerta.
        secondo = self._player("Riserva t3", "ATT")
        self._own(self.t3, secondo, 100)
        cecchino = me.place_offer(
            self.session, self.t3, self.free[0].id, secondo.id, 20,
            now=now - timedelta(seconds=30))
        self.giovane.refresh_from_db()
        self.assertEqual(self.giovane.status, MarketOffer.STATUS_OUTBID)

        self.session.closes_at = now - timedelta(seconds=1)
        self.session.save(update_fields=["closes_at"])
        print("\n[5] rilancio sul filo della chiusura ->", self._tick())
        cecchino.refresh_from_db()
        self.giovane.refresh_from_db()
        print(f"      offerta del cecchino (30s di vita, 20 cr)   {cecchino.status}")
        print(f"      offerta superata (10 cr)                    {self.giovane.status}")
        self.assertEqual(cecchino.status, MarketOffer.STATUS_ACCEPTED)
        self.assertEqual(self.giovane.status, MarketOffer.STATUS_OUTBID)

    def test_anche_la_chiusura_a_mano_manda_in_coda(self):
        """Stessa regola quando l'admin chiude dal pannello: due esiti diversi
        per lo stesso bottone sarebbero solo una trappola."""
        self._setup(closes_in=None)
        c = self._as(self.admin)
        r = c.post(f"/api/v1/leagues/{self.league.id}/market/sessions/{self.session.id}/close")
        self.assertEqual(r.status_code, 200)
        print("\n[6] chiusura a mano dall'admin:")
        for k, v in self._statuses().items():
            print(f"      {k:36} {v}")
        self.assertEqual(self.giovane.status, MarketOffer.STATUS_ACCEPTED)

    def test_la_coda_resta_validabile_a_sessione_chiusa(self):
        """Accettare applica lo scambio anche dopo la chiusura: altrimenti la
        promozione sarebbe un vicolo cieco."""
        self._setup(closes_in=timedelta(hours=-1))
        self._tick()
        self.giovane.refresh_from_db()
        c = self._as(self.admin)
        r = c.post(f"/api/v1/leagues/{self.league.id}/market/offers/{self.giovane.id}/accept")
        self.giovane.refresh_from_db()
        print(f"\n[7] validazione a sessione chiusa: HTTP {r.status_code} -> {self.giovane.status}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.giovane.status, MarketOffer.STATUS_SETTLED)
        self.assertTrue(FantasyRosterSlot.objects.filter(
            team=self.t2, player_id=self.free[0].id, released_at__isnull=True).exists())
        self.assertFalse(FantasyRosterSlot.objects.filter(
            team=self.t2, player_id=self.mine[0].id, released_at__isnull=True).exists())

    # -- 3. la scadenza vale anche senza cron --------------------------------
    def test_aprire_la_pagina_dopo_la_scadenza_chiude_la_sessione(self):
        """Il server se ne accorge da solo: chi apre il mercato dopo la scadenza
        lo trova chiuso, senza che nessun cron sia passato."""
        self._setup(closes_in=timedelta(hours=-1))
        c = self._as(self.u2)
        r = c.get(f"/api/v1/leagues/{self.league.id}/market/active")
        print("\n[3] scadenza passata, solo apertura pagina (nessun tick):")
        print(f"      sessione: {r.json()['session']['status']}")
        for k, v in self._statuses().items():
            print(f"      {k:36} {v}")
        self.assertEqual(r.json()["session"]["status"], MarketSession.STATUS_CLOSED)
        self.assertEqual(self.giovane.status, MarketOffer.STATUS_ACCEPTED)

    def test_dopo_la_scadenza_non_si_offre_piu(self):
        """Il buco che conta: senza chiusura, un'offerta piazzata dopo la
        scadenza veniva accettata come se il mercato fosse ancora aperto."""
        self._setup(closes_in=timedelta(hours=-1))
        tardivo = self._player("Tardivo", "ATT")
        libero = self._player("Riserva t2", "ATT")  # mine[0] e' gia' impegnato
        self._own(self.t2, libero, 100)
        c = self._as(self.u2)
        r = c.post(f"/api/v1/leagues/{self.league.id}/market/offers", {
            "target_player_id": tardivo.id,
            "release_player_id": libero.id,
            "amount": 5,
        }, format="json")
        print(f"\n[8] offerta dopo la scadenza: HTTP {r.status_code} — {r.json().get('detail')}")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(MarketOffer.objects.filter(target_player=tardivo).exists())
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, MarketSession.STATUS_CLOSED)

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
        self.assertEqual(self.giovane.status, MarketOffer.STATUS_ACCEPTED)
