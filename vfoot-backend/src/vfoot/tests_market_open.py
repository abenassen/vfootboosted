"""Apertura programmata: una sessione annunciata prima della sua ora.

L'admin fissa il momento in cui il mercato comincera', cosi' puo' dirlo alla
lega in anticipo. Fino a quell'ora la sessione si vede e si guarda chi e'
libero, ma non si offre; all'ora fissata si apre da sola, con o senza cron.
"""
from __future__ import annotations

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.utils import timezone

from vfoot.models import LeaguePlayerRole, MarketOffer, MarketSession
from vfoot.services import market_engine as me
from vfoot.tests_market import MarketBase


class ScheduledOpenTests(MarketBase):
    def _setup(self, opens_in: timedelta):
        self.session = self._session(opens_in=opens_in)
        self.libero = self._player("Libero", "ATT")
        self.mio = self._player("Mio", "ATT")
        self._own(self.t2, self.mio, 100)

    def _offer(self):
        return self._as(self.u2).post(
            f"/api/v1/leagues/{self.league.id}/market/offers",
            {"target_player_id": self.libero.id,
             "release_player_id": self.mio.id, "amount": 10},
            format="json")

    # -- prima dell'ora ------------------------------------------------------
    def test_prima_dell_ora_non_si_offre(self):
        self._setup(opens_in=timedelta(hours=3))
        r = self._offer()
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("non e' ancora aperto", r.json()["detail"])
        self.assertFalse(MarketOffer.objects.exists())

    def test_prima_dell_ora_si_guarda_chi_e_libero(self):
        """La sessione c'e' e si vede: e' tutto il punto di annunciarla prima.
        Chi apre la pagina trova l'ora di apertura e gli svincolati da studiare."""
        self._setup(opens_in=timedelta(hours=3))
        body = self._as(self.u2).get(
            f"/api/v1/leagues/{self.league.id}/market/active").json()
        self.assertEqual(body["session"]["status"], MarketSession.STATUS_OPEN)
        self.assertIsNone(body["session"]["opened_at"])   # annunciata, non aperta
        self.assertIsNotNone(body["session"]["opens_at"])
        self.assertIn(self.libero.id, [f["player_id"] for f in body["free_agents"]])

    def test_una_sola_sessione_viva_anche_se_programmata(self):
        """Programmarne una tiene il posto: non se ne apre un'altra sopra."""
        self._setup(opens_in=timedelta(hours=3))
        r = self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/market/sessions/create",
            {"credit_recovery_mode": "fixed"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("gia' una sessione", r.json()["detail"])

    # -- l'ora scatta --------------------------------------------------------
    def test_all_ora_si_apre_da_sola(self):
        """Nessun cron: la prima richiesta che arriva dopo l'ora la apre."""
        self._setup(opens_in=timedelta(hours=-1))   # l'ora e' appena passata
        r = self._offer()
        self.assertEqual(r.status_code, 201, r.content)
        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.opened_at)

    def test_l_apertura_aggiorna_il_listone(self):
        """Fra l'annuncio e l'apertura le squadre vere possono aver firmato
        qualcuno: chi e' arrivato dopo l'annuncio dev'essere offribile."""
        self._setup(opens_in=timedelta(hours=-1))
        nuovo = self._player_without_role("Nuovo Acquisto", "ATT")
        self.assertNotIn(nuovo.id, me.free_agent_ids(self.league))

        me.sync_session(self.session)

        self.assertTrue(LeaguePlayerRole.objects.filter(
            league=self.league, player=nuovo).exists())
        self.assertIn(nuovo.id, me.free_agent_ids(self.league))

    def test_l_apertura_avviene_una_volta_sola(self):
        self._setup(opens_in=timedelta(hours=-1))
        me.sync_session(self.session)
        self.session.refresh_from_db()
        first = self.session.opened_at
        me.sync_session(self.session)
        self.session.refresh_from_db()
        self.assertEqual(self.session.opened_at, first)
        self.assertEqual(self.session.events.filter(
            event_type="session_opened").count(), 1)

    def test_il_tick_apre_la_sessione(self):
        self._setup(opens_in=timedelta(hours=-1))
        out = StringIO()
        call_command("market_tick", "--dry-run", stdout=out)
        self.assertIn(f"would open session {self.session.id}", out.getvalue())
        self.session.refresh_from_db()
        self.assertIsNone(self.session.opened_at)       # dry-run non scrive

        out = StringIO()
        call_command("market_tick", stdout=out)
        self.assertIn("opened=1", out.getvalue())
        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.opened_at)

    def test_il_tick_lascia_stare_quella_ancora_da_venire(self):
        self._setup(opens_in=timedelta(hours=3))
        out = StringIO()
        call_command("market_tick", stdout=out)
        self.assertIn("opened=0", out.getvalue())
        self.session.refresh_from_db()
        self.assertIsNone(self.session.opened_at)


class CreateScheduledSessionTests(MarketBase):
    def _create(self, **extra):
        payload = {"credit_recovery_mode": "fixed"}
        payload.update(extra)
        return self._as(self.admin).post(
            f"/api/v1/leagues/{self.league.id}/market/sessions/create",
            payload, format="json")

    def test_apertura_futura_resta_programmata(self):
        at = timezone.now() + timedelta(days=2)
        r = self._create(opens_at=at.isoformat())
        self.assertEqual(r.status_code, 201, r.content)
        s = MarketSession.objects.get(id=r.json()["session_id"])
        self.assertIsNone(s.opened_at)
        self.assertTrue(s.is_pending())

    def test_senza_apertura_si_apre_subito(self):
        r = self._create()
        self.assertEqual(r.status_code, 201, r.content)
        s = MarketSession.objects.get(id=r.json()["session_id"])
        self.assertIsNotNone(s.opened_at)
        self.assertFalse(s.is_pending())

    def test_apertura_gia_passata_vale_adesso(self):
        """Un'ora gia' suonata non fa aspettare nessuno."""
        r = self._create(opens_at=(timezone.now() - timedelta(hours=5)).isoformat())
        s = MarketSession.objects.get(id=r.json()["session_id"])
        self.assertIsNotNone(s.opened_at)
        self.assertFalse(s.is_pending())

    def test_la_chiusura_deve_venire_dopo_l_apertura(self):
        at = timezone.now() + timedelta(days=2)
        r = self._create(opens_at=at.isoformat(),
                         closes_at=(at - timedelta(hours=1)).isoformat())
        self.assertEqual(r.status_code, 400)
        self.assertIn("closes_at", r.json())
        self.assertFalse(MarketSession.objects.exists())

    def test_la_chiusura_non_puo_essere_gia_passata(self):
        """Il buco simmetrico: una sessione nata gia' scaduta, che la prima
        richiesta chiudeva senza che nessuno avesse potuto offrire."""
        r = self._create(closes_at=(timezone.now() - timedelta(hours=1)).isoformat())
        self.assertEqual(r.status_code, 400)
        self.assertFalse(MarketSession.objects.exists())
