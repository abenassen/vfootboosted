"""Il guasto del 13/08/2026, e le due cose che lo rendevano invisibile.

Alle 06:04 il polling Transfermarkt importava 632 giocatori. Alle 18:01 leggeva
zero club, e cosi' ogni giro dopo. Non era il codice: TM era passata dietro
CloudFront con AWS WAF, che sfida l'IP datacenter del Linode con un ``202`` a
corpo vuoto. Dal PC di casa la stessa pagina rispondeva 200 e 206 KB.

Due difetti si sommavano, e i test qui li fissano separatamente.

**Il 202 si travestiva da pagina.** E' un 2xx: ``raise_for_status`` non scatta,
non c'e' ritentativo, il corpo vuoto si parsa in zero club. Un blocco arrivava
fino in fondo mascherato da campionato senza squadre. (Che il listone non si sia
corrotto lo si deve alla guardia ``scraped == 0`` a valle, non a questo strato.)

**Il pool era uno solo, e sceglieva con la sonda sbagliata.** Sondando 26 uscite
Surfshark su entrambi i siti nello stesso tunnel, il 14/08/2026: 3 IP su 8
rifiutati da SofaScore servivano TM benissimo, e 2 accettati da SofaScore non
apravano nemmeno la connessione verso TM. Un pool condiviso sbaglia in entrambe
le direzioni; la seconda e' quella che fa fallire il giro.

Il lock e' il terzo pezzo, e non e' contesa sui dati: e' un namespace solo.
"""
from __future__ import annotations

import json
import multiprocessing
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import httpx
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from io import StringIO

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "egress"))
import sofascore_egress as E  # noqa: E402

from realdata.management.commands import poll_transfermarkt as poll_tm  # noqa: E402
from realdata.models import (  # noqa: E402
    Competition, CompetitionSeason, JobRun, Season, Team, TeamSeason,
)
from realdata.services import egress_client  # noqa: E402
from realdata.services.scrape_transfermarkt_squads import (  # noqa: E402
    TM, TransfermarktBlocked,
)


def _response(status: int, body: str = "", headers: dict | None = None):
    return httpx.Response(status, text=body, headers=headers or {},
                          request=httpx.Request("GET", "https://tm.invalid/x"))


class IlChallengeNonEUnaPagina(SimpleTestCase):
    """Il 202 del WAF deve fermarsi qui, non diventare 'zero club'."""

    def _tm(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return TM(Path(tmp.name), min_delay=0, jitter=0, attempts=3,
                  logger=lambda *_: None)

    def test_il_202_del_waf_risale_invece_di_sembrare_vuoto(self):
        """Il caso esatto del 13/08: 202, corpo vuoto, header del WAF."""
        tm = self._tm()
        tm._client = mock.Mock()
        tm._client.get.return_value = _response(
            202, "", {"x-amzn-waf-action": "challenge"})
        with self.assertRaises(TransfermarktBlocked):
            tm._get_html("https://tm.invalid/x")

    def test_un_blocco_non_si_ritenta(self):
        """Un verdetto di reputazione non lo ripara il tempo: si ruota uscita.

        Ritentarlo tre volte sullo stesso IP costa solo tre richieste in piu' da
        un indirizzo che il sito ha gia' deciso di non servire."""
        tm = self._tm()
        tm._client = mock.Mock()
        tm._client.get.return_value = _response(
            202, "", {"x-amzn-waf-action": "challenge"})
        with self.assertRaises(TransfermarktBlocked):
            tm._get_html("https://tm.invalid/x")
        self.assertEqual(tm._client.get.call_count, 1)

    def test_anche_il_403_e_un_blocco(self):
        tm = self._tm()
        tm._client = mock.Mock()
        tm._client.get.return_value = _response(403, "nope")
        with self.assertRaises(TransfermarktBlocked):
            tm._get_html("https://tm.invalid/x")

    def test_una_pagina_vera_passa_ancora(self):
        tm = self._tm()
        tm._client = mock.Mock()
        tm._client.get.return_value = _response(200, "<html>ok</html>")
        self.assertEqual(tm._get_html("https://tm.invalid/x"), "<html>ok</html>")

    def test_un_500_resta_un_guasto_passeggero_e_si_ritenta(self):
        """Il confine da non spostare: il WAF non e' un 5xx, e un 5xx non e' il WAF."""
        tm = self._tm()
        tm._client = mock.Mock()
        tm._client.get.side_effect = [_response(500), _response(200, "ok")]
        with mock.patch.object(time, "sleep"):
            self.assertEqual(tm._get_html("https://tm.invalid/x"), "ok")
        self.assertEqual(tm._client.get.call_count, 2)


class DuePoolDistinti(SimpleTestCase):
    """La selezione e' per bersaglio, non condivisa."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        for attr, name in (("POOL_FILE", "sofa_pool.json"),
                           ("TM_POOL_FILE", "tm_pool.json"),
                           ("LOCK_FILE", "egress.lock")):
            p = mock.patch.object(E, attr, self.dir / name)
            p.start(); self.addCleanup(p.stop)

    def test_i_due_pool_sono_file_diversi(self):
        sofa, tm = E.target(E.SOFASCORE), E.target(E.TRANSFERMARKT)
        self.assertNotEqual(sofa.pool_file, tm.pool_file)
        E.save_pool(sofa, [{"endpoint_ip": "1.1.1.1", "last_ok": E._now()}])
        self.assertEqual(E.load_pool(tm), [])

    def test_ogni_bersaglio_usa_la_propria_sonda(self):
        self.assertNotEqual(E.target(E.SOFASCORE).probe,
                            E.target(E.TRANSFERMARKT).probe)

    def test_un_ip_bruciato_su_sofascore_resta_candidato_per_tm(self):
        """I 3 su 8 della misura: e' la capacita' che il pool condiviso buttava.

        ``candidate_ips`` salta i noti DI QUEL BERSAGLIO. Passargli l'unione
        rimetterebbe insieme le due reputazioni."""
        bruciato = "185.108.105.108"
        E.save_pool(E.target(E.SOFASCORE),
                    [{"endpoint_ip": bruciato, "last_ok": None, "fail_count": 3}])
        catalogo = [{"connectionName": "mk-skp.prod.surfshark.com",
                     "pubKey": "k", "countryCode": "mk", "load": 5}]
        with mock.patch.object(E, "_catalog", return_value=catalogo), \
             mock.patch.object(E, "_resolve_ips", return_value=[bruciato]):
            noti_tm = {s["endpoint_ip"] for s in E.load_pool(E.target(E.TRANSFERMARKT))}
            cands = E.candidate_ips(known=noti_tm, preferred_cc=E.TM_PREFERRED_CC)
        self.assertEqual([ip for ip, _, _ in cands], [bruciato])

    def test_il_declassamento_tocca_solo_il_pool_di_quel_bersaglio(self):
        ip = "212.102.54.143"
        rec = {"endpoint_ip": ip, "last_ok": E._now(), "fail_count": 0}
        sofa, tm = E.target(E.SOFASCORE), E.target(E.TRANSFERMARKT)
        E.save_pool(sofa, [dict(rec)])
        E.save_pool(tm, [dict(rec)])
        E._demote(tm, E.load_pool(tm), ip)
        self.assertEqual(len(E.good_servers(E.load_pool(sofa))), 1)
        self.assertEqual(len(E.good_servers(E.load_pool(tm))), 0)

    def test_un_verdetto_qualificato_conta_come_passato(self):
        """Colto dalla prima prova vera: sei uscite buone scartate in silenzio.

        La sonda TM dice ``PASS (20 clubs, 25 players)`` — il dettaglio serve nel
        log per vedere un pool che va alla deriva. Il refill confrontava l'intera
        stringa con "PASS", quindi nessun IP entrava mai e il giro chiudeva
        annunciando "0 good IP(s) in pool" senza un errore da nessuna parte."""
        self.assertTrue(E.passed("PASS"))
        self.assertTrue(E.passed("PASS (20 clubs, 25 players)"))
        self.assertFalse(E.passed("CHALLENGE (competition)"))
        self.assertFalse(E.passed("THIN (3 clubs)"))
        self.assertFalse(E.passed("HTTP_403 (rounds)"))
        self.assertFalse(E.passed("EXC ConnectError (competition)"))

    def test_il_refill_mette_in_pool_un_verdetto_qualificato(self):
        """Lo stesso difetto un livello piu' su, dov'e' costato."""
        tgt = E.target(E.TRANSFERMARKT)
        catalogo = [{"connectionName": "it-rom.prod.surfshark.com",
                     "pubKey": "k", "countryCode": "it", "load": 5}]
        with mock.patch.object(E, "_catalog", return_value=catalogo), \
             mock.patch.object(E, "_resolve_ips", return_value=["185.183.105.5"]), \
             mock.patch.object(E, "_client_identity", return_value=("p", "10.0.0.2/32")), \
             mock.patch.object(E, "netns_up", return_value=True), \
             mock.patch.object(E, "netns_down"), \
             mock.patch.object(E, "probe_in_netns",
                               return_value=("146.70.182.86",
                                             "PASS (20 clubs, 25 players)")), \
             mock.patch.object(time, "sleep"):
            E.refill(tgt, want=1, max_probes=3, delay=0)
        self.assertEqual([s["exit_ip"] for s in E.good_servers(E.load_pool(tgt))],
                         ["146.70.182.86"])

    def test_tm_non_eredita_la_preferenza_geografica_di_sofascore(self):
        """Skopje e Asunción servivano TM mentre SofaScore le rifiutava: filtrare
        TM sull'Europa occidentale importerebbe una mappa che non e' la sua."""
        self.assertNotEqual(E.PREFERRED_CC, E.TM_PREFERRED_CC)
        self.assertNotIn("gb", E.TM_PREFERRED_CC)


class IlPollingPassaDallEgress(TestCase):
    """Dal server la strada diretta legge zero club: il default deve essere l'altra."""

    N_CLUBS = 20

    def setUp(self):
        comp = Competition.objects.create(name="Serie A")
        seas = Season.objects.create(code="2026-2027")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=seas, name="Serie A 2026-2027")
        # I nomi devono agganciarsi: l'import rifiuta un club che non mappa, ed e'
        # una guardia sua, non cio' che si sta provando qui.
        for i in range(self.N_CLUBS):
            TeamSeason.objects.create(
                competition_season=self.cs,
                team=Team.objects.create(name=f"Club {i}"))

    def _clubs(self, n: int):
        return [{"id": str(100 + i), "name": f"Club {i}", "slug": f"club-{i}",
                 "url": f"https://tm.invalid/{i}"} for i in range(n)]

    def _fake_egress(self, listed: int, read: int, players_each: int = 20):
        """Sta al posto della meta' root: scrive in cache cio' che avrebbe scaricato."""
        def _run(cache_dir, competition, season, **kw):
            out = Path(cache_dir)
            out.mkdir(parents=True, exist_ok=True)
            clubs = self._clubs(listed)
            (out / "clubs.json").write_text(json.dumps(clubs))
            for club in clubs[:read]:
                (out / f"club_{club['id']}.json").write_text(json.dumps({
                    "club": club,
                    "players": [{"tm_id": f"{club['id']}-{k}", "name": f"P{k}",
                                 "dob": "1995-01-01", "shirt": "5",
                                 "position": "Centre-Back", "nationality": ["Italy"],
                                 "market_value": "€5.00m"}
                                for k in range(players_each)],
                }))
            return read > 0
        return _run

    def _poll(self, **kw):
        out = StringIO()
        call_command("poll_transfermarkt", competition_season=self.cs.id,
                     dry_run=True, stdout=out, stderr=out, **kw)
        return out.getvalue()

    def test_di_default_scrape_dall_egress_e_non_in_processo(self):
        with mock.patch.object(egress_client, "scrape_tm_squads",
                               side_effect=self._fake_egress(20, 20)) as eg, \
             mock.patch.object(poll_tm, "TM") as diretto:
            self._poll()
        eg.assert_called_once()
        diretto.assert_not_called()

    def test_no_egress_torna_alla_strada_diretta(self):
        """Resta per una macchina che TM la raggiunge davvero (il PC di casa)."""
        scrivi = self._fake_egress(self.N_CLUBS, self.N_CLUBS)

        def _diretto(out, competition, season, opts):
            scrivi(out, competition, season)
            return self.N_CLUBS, 0, self.N_CLUBS * 20

        with mock.patch.object(egress_client, "scrape_tm_squads") as eg, \
             mock.patch.object(poll_tm.Command, "_scrape_in_process",
                               side_effect=_diretto) as diretto:
            self._poll(no_egress=True)
        eg.assert_not_called()
        diretto.assert_called_once()

    def test_i_conteggi_vengono_dai_file_non_dallo_stdout_dell_egress(self):
        """JobRun deve riportare cio' che l'import leggera', non cio' che l'altro
        processo ha dichiarato."""
        with mock.patch.object(egress_client, "scrape_tm_squads",
                               side_effect=self._fake_egress(20, 17)):
            self._poll()
        run = JobRun.objects.filter(job="poll_transfermarkt").latest("id")
        self.assertEqual(run.did.get("clubs_scraped"), 17)
        self.assertEqual(run.did.get("clubs_failed"), 3)
        self.assertEqual(run.did.get("players"), 17 * 20)

    def test_uno_scrape_parziale_importa_lo_stesso(self):
        """Diciassette club letti non pagano per i tre mancati: l'uscita non zero
        butterebbe via diciassette rose buone per un timeout."""
        txt = self._poll_ok(self._fake_egress(20, 17))
        self.assertIn("17", txt)

    def test_zero_club_resta_un_errore_e_non_importa_niente(self):
        """La guardia che l'11/08 ha salvato il listone: se non si e' letto nulla,
        l'assenza di tutti NON e' una prova che se ne siano andati tutti."""
        with mock.patch.object(egress_client, "scrape_tm_squads",
                               side_effect=self._fake_egress(20, 0)), \
             self.assertRaises(CommandError):
            self._poll()

    def _poll_ok(self, fake):
        with mock.patch.object(egress_client, "scrape_tm_squads", side_effect=fake):
            return self._poll()


def _hold(lock_path: str, started, release):
    """Figlio: prende il lock e lo tiene finche' non gli si dice di mollare."""
    import sofascore_egress as child  # reimport nel processo figlio
    child.LOCK_FILE = Path(lock_path)
    with child.egress_lock(wait=None, what="test-holder"):
        started.set()
        release.wait(timeout=10)


class UnSoloNamespace(SimpleTestCase):
    """Il lock non protegge dati: protegge il namespace, che e' uno.

    ``netns_up`` comincia distruggendo ``sofa`` e ``wgsofa``. Due utenti
    dell'egress non possono coesistere nemmeno volendo IP diversi e scrivendo file
    diversi — e senza lock il refill delle 21:00 cancella il namespace sotto un
    tick che ci sta dentro a meta' richiesta.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lock = Path(tmp.name) / "egress.lock"
        p = mock.patch.object(E, "LOCK_FILE", self.lock)
        p.start(); self.addCleanup(p.stop)

    def test_libero_si_prende(self):
        with E.egress_lock(wait=0, what="uno"):
            pass

    def test_rientrare_e_possibile_dopo_il_rilascio(self):
        with E.egress_lock(wait=0, what="uno"):
            pass
        with E.egress_lock(wait=0, what="due"):
            pass

    def test_occupato_con_wait_zero_non_aspetta(self):
        """Il contratto del tick: meglio saltare un minuto che accodarsi.

        Gira ogni sessanta secondi; mettersi in coda dietro un giro TM da mezz'ora
        accumulerebbe tick invece di perderne uno."""
        ctx = multiprocessing.get_context("fork")
        started, release = ctx.Event(), ctx.Event()
        child = ctx.Process(target=_hold, args=(str(self.lock), started, release))
        child.start()
        self.addCleanup(child.join)
        self.addCleanup(release.set)
        self.assertTrue(started.wait(timeout=10), "il figlio non ha preso il lock")
        t0 = time.monotonic()
        with self.assertRaises(E.EgressBusy):
            with E.egress_lock(wait=0, what="tick"):
                pass
        self.assertLess(time.monotonic() - t0, 2.0)
        release.set()
        child.join(timeout=10)

    def test_occupato_con_attesa_breve_si_arrende_e_non_resta_appeso(self):
        ctx = multiprocessing.get_context("fork")
        started, release = ctx.Event(), ctx.Event()
        child = ctx.Process(target=_hold, args=(str(self.lock), started, release))
        child.start()
        self.addCleanup(child.join)
        self.addCleanup(release.set)
        self.assertTrue(started.wait(timeout=10))
        t0 = time.monotonic()
        with self.assertRaises(E.EgressBusy):
            with E.egress_lock(wait=0.5, what="calendario"):
                pass
        self.assertGreaterEqual(time.monotonic() - t0, 0.4)
        release.set()
        child.join(timeout=10)

    def test_il_tunnel_tiene_il_lock_per_tutta_la_vita_del_namespace(self):
        """Il punto delicato: rilasciare il lock restando dentro ``sofa`` lascerebbe
        al prossimo la facolta' di cancellare il namespace sotto di noi."""
        visto = {}

        def _up(*_a, **_kw):
            visto["locked_durante_up"] = self._occupato()
            return True

        with mock.patch.object(E, "netns_up", side_effect=_up), \
             mock.patch.object(E, "netns_down") as down:
            with E.tunnel("1.2.3.4", "k", "priv", "10.0.0.2/32",
                          wait=0, what="test") as up:
                self.assertTrue(up)
                visto["locked_dentro"] = self._occupato()
            visto["locked_dopo"] = self._occupato()
        self.assertTrue(visto["locked_durante_up"])
        self.assertTrue(visto["locked_dentro"])
        self.assertFalse(visto["locked_dopo"])
        down.assert_called_once()

    def _occupato(self) -> bool:
        """True se il lock e' preso da qualcuno (qui: da noi)."""
        ctx = multiprocessing.get_context("fork")
        q = ctx.Queue()

        def probe(path, out):
            import fcntl
            import os
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                out.put(False)
                fcntl.flock(fd, fcntl.LOCK_UN)
            except BlockingIOError:
                out.put(True)
            finally:
                os.close(fd)

        p = ctx.Process(target=probe, args=(str(self.lock), q))
        p.start(); p.join(timeout=10)
        return q.get(timeout=5)
