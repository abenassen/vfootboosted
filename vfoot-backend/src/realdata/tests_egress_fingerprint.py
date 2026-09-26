"""Il guasto del 25/09/2026: SofaScore rifiutava l'IMPRONTA, e noi buttavamo gli IP.

Dal 25/09 l'API rispondeva ``403 {"reason": "challenge"}`` a ogni Chrome che
curl_cffi 0.15 sapesse imitare, da qualunque indirizzo — anche da casa. Safari,
Firefox e Tor passavano sullo stesso IP nello stesso minuto. Per l'egress era
indistinguibile da un'uscita bruciata: il refill ha provato venti IP a giro in tre
paesi, li ha trovati tutti a 403, e ha svuotato il pool per un difetto che nessun
IP poteva avere. L'allarme, intanto, consigliava proprio il refill.

Qui si fissano le quattro risposte, dal primo strato all'ultimo:

* il client percorre una CATENA di impronte, e solo su quel rifiuto preciso;
* il worker racconta all'orchestratore quale impronta ha usato e quali no;
* l'orchestratore, quando curl non passa da nessuna parte, ripiega su un browser
  vero, e per un'ora ci resta;
* la salute distingue «IP bruciati» da «impronta rifiutata», e avvisa PRIMA:
  un'impronta caduta mentre un'altra regge è il preavviso che il 25/09 non c'era.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "egress"))
import fetch_worker  # noqa: E402
import sofascore_egress as E  # noqa: E402
from sofascore_client import IMPERSONATE_CHAIN  # noqa: E402  (the one fetch_worker uses)

from realdata.services import health  # noqa: E402

MID = 16283209
CHALLENGE = '{"error": {"code": 403, "reason": "challenge" }}'


class _Resp:
    def __init__(self, status: int, text: str):
        self.status_code = status
        self.text = text

    def json(self):
        return json.loads(self.text)


class _Session:
    """Risponde secondo l'impronta: quelle in ``refused`` si prendono il 403 di
    sfida, le altre un JSON buono. Registra chi ha chiesto cosa."""

    def __init__(self, refused=(), status_for_refused=403, body_for_refused=CHALLENGE):
        self.refused = set(refused)
        self.status = status_for_refused
        self.body = body_for_refused
        self.calls: list[tuple[str, str]] = []

    def get(self, url, *, headers, impersonate, timeout):
        self.calls.append((impersonate, url))
        if impersonate in self.refused:
            return _Resp(self.status, self.body)
        if url.endswith("/lineups"):
            return _Resp(200, json.dumps({"home": {"players": []},
                                          "away": {"players": []}}))
        return _Resp(200, '{"ok": true}')


_REAL_CLIENT = fetch_worker.SofaScoreClient   # before any test patches it


def _client_on(session, cache_dir):
    class _Wire(_REAL_CLIENT):
        def _ensure_session(inner):
            inner._session = session
            return session
    return _Wire(cache_dir, min_delay=0.0, jitter=0.0, max_retries=1)


class _Tmp(SimpleTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)


class LaCatenaDiImpronte(_Tmp):

    def test_se_la_prima_e_rifiutata_passa_alla_seconda_e_ci_resta(self):
        s = _Session(refused={"safari"})
        c = _client_on(s, self.dir)
        c.get(f"/api/v1/event/{MID}")
        c.get(f"/api/v1/event/{MID}/incidents")
        self.assertEqual([fp for fp, _ in s.calls], ["safari", "firefox", "firefox"],
                         "la testa rifiutata deve costare UNA richiesta per giro, "
                         "non una per percorso")
        self.assertEqual(c.challenged, ["safari"])
        self.assertEqual(c.fingerprint, "firefox")

    def test_tutte_rifiutate_e_un_blocco_che_dice_di_essere_un_impronta(self):
        s = _Session(refused=set(IMPERSONATE_CHAIN))
        c = _client_on(s, self.dir)
        with self.assertRaises(fetch_worker.SofaScoreChallenged):
            c.get(f"/api/v1/event/{MID}")
        self.assertIsInstance(fetch_worker.SofaScoreChallenged("x"),
                              fetch_worker.SofaScoreBlocked,
                              "resta un blocco: l'orchestratore deve ruotare")

    def test_un_403_qualunque_non_percorre_la_catena(self):
        """Un'uscita bruciata che risponde 403 senza la parola 'challenge' non è
        l'impronta: quattro impronte contro un IP che non ne serve nessuna sono
        quattro richieste per non imparare niente."""
        s = _Session(refused={"safari", "firefox", "chrome", "tor"},
                     body_for_refused="Forbidden")
        c = _client_on(s, self.dir)
        with self.assertRaises(fetch_worker.SofaScoreBlocked) as ctx:
            c.get(f"/api/v1/event/{MID}")
        self.assertNotIsInstance(ctx.exception, fetch_worker.SofaScoreChallenged)
        self.assertEqual(len(s.calls), 1)

    def test_la_catena_usa_alias_che_seguono_la_libreria(self):
        """Un numero di versione nella catena congelerebbe l'impronta: e' proprio
        aggiornando curl_cffi che si rinfrescano tutte in una volta."""
        for fp in IMPERSONATE_CHAIN:
            self.assertFalse(any(ch.isdigit() for ch in fp), fp)


class IlWorkerRaccontaLImpronta(_Tmp):

    def _run(self, session, *argv) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch.object(sys, "argv",
                               ["fetch_worker", "--cache-dir", str(self.dir),
                                "--delay", "0", *argv]), \
             mock.patch.object(fetch_worker, "SofaScoreClient",
                               lambda cache_dir, **kw: _client_on(session, cache_dir)), \
             redirect_stdout(out):
            rc = fetch_worker.main()
        return rc, out.getvalue()

    def test_riuscito_dice_quale_ha_usato_e_quali_no(self):
        rc, out = self._run(_Session(refused={"safari"}),
                            "--match-ids", str(MID), "--kind", "live")
        self.assertEqual(rc, 0)
        rep = E.worker_report(out)
        self.assertEqual((rep["used"], rep["challenged"], rep["challenged_all"]),
                         ("firefox", ["safari"], False))

    def test_tutte_rifiutate_esce_3_e_lo_dice(self):
        rc, out = self._run(_Session(refused={"safari", "firefox", "chrome", "tor"}),
                            "--match-ids", str(MID), "--kind", "live")
        self.assertEqual(rc, 3)
        self.assertTrue(E.worker_report(out)["challenged_all"])


def _done(rc: int, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], rc, stdout=stdout, stderr="")


CHALLENGED_ALL_OUT = ("CHALLENGED_ALL: HTTP 403 challenge on every fingerprint\n"
                      "FINGERPRINT used=safari challenged=safari,firefox,chrome,tor\n")


class IlRipiegoSulBrowser(_Tmp):
    """L'orchestratore, con la rete e il worker sostituiti. Il worker finto
    risponde secondo il trasporto che gli si chiede."""

    def setUp(self):
        super().setUp()
        for attr, name in (("POOL_FILE", "sofa_pool.json"),
                           ("BROWSER_POOL_FILE", "sofa_browser_pool.json"),
                           ("TRANSPORT_FILE", "sofa_transport.json"),
                           ("LOCK_FILE", "egress.lock")):
            p = mock.patch.object(E, attr, self.dir / name)
            p.start(); self.addCleanup(p.stop)
        self.refill = mock.MagicMock()
        for name, kw in (("_client_identity", {"return_value": ("p", "10.0.0.2/32")}),
                         ("netns_up", {"return_value": True}),
                         ("netns_down", {}),
                         ("browser_installed", {"return_value": True}),
                         ("refill", {"new": self.refill})):
            p = mock.patch.object(E, name, **kw)
            p.start(); self.addCleanup(p.stop)
        self.tgt = E.target(E.SOFASCORE)
        E.save_pool(self.tgt, [
            {"endpoint_ip": ip, "pubKey": "k", "cluster": "it-mil.prod.surfshark.com",
             "exit_ip": ip, "last_ok": E._now(), "last_checked": E._now()}
            for ip in ("1.1.1.1", "2.2.2.2", "3.3.3.3")])
        self.calls: list[list[str]] = []
        self.curl = _done(3, CHALLENGED_ALL_OUT)
        self.browser = _done(0, "TRANSPORT=browser\n")

    def _fake_run(self, cmd, **kw):
        self.calls.append(cmd)
        if "browser" not in cmd:
            return self.curl
        # The browser answers per exit when told to (a list of verdicts by the
        # endpoint the tunnel was pinned to), otherwise the same for all.
        if isinstance(self.browser, dict):
            return self.browser.get(self.pinned, _done(3, "BLOCKED: HTTP 403\n"))
        return self.browser

    def _warm(self) -> int:
        def up(ip, *a, **kw):
            self.pinned = ip
            return True
        with mock.patch.object(E, "_run", side_effect=self._fake_run), \
             mock.patch.object(E, "netns_up", side_effect=up), \
             redirect_stdout(io.StringIO()):
            return E._warm(["--match-ids", str(MID), "--kind", "live"],
                           self.dir / "cache", max_rotations=3)

    def _transports(self) -> list[str]:
        return ["browser" if "browser" in c else "curl" for c in self.calls]

    def test_curl_rifiutato_ovunque_il_browser_salva_il_giro(self):
        self.assertEqual(self._warm(), 0)
        self.assertEqual(self._transports(), ["curl", "curl", "curl", "browser"])
        self.assertTrue(E.browser_mode(E.load_transport()))

    def test_solo_il_primo_giro_butta_la_cache(self):
        """Il browser è lo stesso giro che continua: se ributtasse la cache,
        pagherebbe di nuovo quello che curl aveva già preso."""
        self._warm()
        self.assertNotIn("--resume", self.calls[0])
        self.assertTrue(all("--resume" in c for c in self.calls[1:]))

    def test_in_modalita_browser_curl_non_si_prova(self):
        self._warm()
        self.calls.clear()
        self.assertEqual(self._warm(), 0)
        self.assertEqual(self._transports(), ["browser"])
        self.assertNotIn("--resume", self.calls[0],
                         "il primo giro del tick deve buttare la cache anche col "
                         "browser, o il live si congela")

    def test_scaduta_l_ora_curl_riprova_e_se_passa_la_modalita_finisce(self):
        self._warm()
        state = E.load_transport()
        state["browser"]["until"] = "2000-01-01T00:00:00+00:00"
        E.save_transport(state)
        # Nel frattempo curl_cffi è stato aggiornato. Il pool, svuotato dai
        # declassamenti, lo riempirebbe il refill; qui si rimette a mano.
        E.save_pool(self.tgt, [dict(s, last_ok=E._now()) for s in E.load_pool(self.tgt)])
        self.curl = _done(0, "FINGERPRINT used=chrome challenged=\n")
        self.calls.clear()
        self.assertEqual(self._warm(), 0)
        self.assertEqual(self._transports(), ["curl"])
        self.assertNotIn("browser", E.load_transport())

    def test_una_modalita_che_funziona_non_si_rinnova_da_sola(self):
        """Se ogni successo del browser spostasse la scadenza, curl non avrebbe
        mai più un'altra occasione."""
        self._warm()
        until = E.load_transport()["browser"]["until"]
        self._warm()
        self.assertEqual(E.load_transport()["browser"]["until"], until)

    def test_il_browser_non_certifica_uscite_per_curl(self):
        self._warm()
        self.assertEqual(E.good_servers(E.load_pool(self.tgt)), [])

    def test_senza_browser_installato_non_consuma_le_altre_uscite(self):
        self.browser = _done(1, "ERROR: SofaScoreError: playwright is not installed\n")
        self.assertEqual(self._warm(), 3)
        self.assertEqual(self._transports().count("browser"), 1)

    def _browser_pool(self, *ips, ok=True):
        E.save_pool(E.target(E.SOFASCORE_BROWSER), [
            {"endpoint_ip": ip, "pubKey": "k", "cluster": "it-rom.prod.surfshark.com",
             "exit_ip": ip, "last_ok": E._now() if ok else None,
             "last_checked": E._now()} for ip in ips])

    def _browser_calls(self) -> int:
        return self._transports().count("browser")

    def test_il_browser_prova_prima_le_uscite_del_suo_pool(self):
        self._browser_pool("9.9.9.9")
        self.browser = {"9.9.9.9": _done(0, "TRANSPORT=browser\n")}
        self.assertEqual(self._warm(), 0)
        self.assertEqual(self._browser_calls(), 1)
        self.assertEqual(E.load_transport()["browser"]["ip"], "9.9.9.9")

    def test_un_uscita_rifiutata_al_browser_esce_dal_suo_pool(self):
        self._browser_pool("9.9.9.9")
        self.browser = {"1.1.1.1": _done(0, "TRANSPORT=browser\n")}
        self.assertEqual(self._warm(), 0)
        bpool = E.load_pool(E.target(E.SOFASCORE_BROWSER))
        self.assertEqual([s["endpoint_ip"] for s in E.good_servers(bpool)], ["1.1.1.1"],
                         "9.9.9.9 declassata, e l'uscita che ha funzionato entra "
                         "nel pool del browser")

    def test_finite_le_uscite_riempie_il_pool_del_browser_e_riprova(self):
        """Il buco che questo chiude: prima il ripiego provava due uscite e poi si
        arrendeva, senza modo di trovarne di nuove."""
        self.browser = {"7.7.7.7": _done(0, "TRANSPORT=browser\n")}

        def refill(tgt, **kw):
            if tgt.name == E.SOFASCORE_BROWSER:
                self._browser_pool("7.7.7.7")
        self.refill.side_effect = refill
        self.assertEqual(self._warm(), 0)
        self.assertIn(E.SOFASCORE_BROWSER,
                      [c.args[0].name for c in self.refill.call_args_list])
        self.assertEqual(E.load_transport()["browser"]["ip"], "7.7.7.7")

    def test_senza_chromium_non_si_prova_nemmeno(self):
        with mock.patch.object(E, "browser_installed", return_value=False):
            self.assertEqual(self._warm(), 3)
        self.assertEqual(self._browser_calls(), 0)
        self.assertNotIn(E.SOFASCORE_BROWSER,
                         [c.args[0].name for c in self.refill.call_args_list])

    def test_un_ip_bruciato_normale_non_scomoda_il_browser(self):
        """La rotazione ordinaria: il primo IP è bruciato, il secondo passa."""
        results = iter([_done(3, "BLOCKED: transport\nFINGERPRINT used=safari challenged=\n"),
                        _done(0, "FINGERPRINT used=safari challenged=\n")])
        self.curl = None

        def run(cmd, **kw):
            self.calls.append(cmd)
            return next(results)

        with mock.patch.object(E, "_run", side_effect=run), \
             redirect_stdout(io.StringIO()):
            rc = E._warm(["--match-ids", str(MID)], self.dir / "cache", max_rotations=3)
        self.assertEqual(rc, 0)
        self.assertEqual(self._transports(), ["curl", "curl"])
        self.assertNotIn("browser", E.load_transport())


class IlRefillRiconosceLImpronta(_Tmp):

    def setUp(self):
        super().setUp()
        p = mock.patch.object(E, "POOL_FILE", self.dir / "sofa_pool.json")
        p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(E, "LOCK_FILE", self.dir / "egress.lock")
        p.start(); self.addCleanup(p.stop)
        self.tgt = E.target(E.SOFASCORE)

    def _refill(self, clusters, verdict):
        verdicts = verdict if isinstance(verdict, list) else [verdict] * len(clusters)
        cands = [(f"10.0.0.{i}", c, "k") for i, c in enumerate(clusters)]
        with mock.patch.object(E, "candidate_ips", return_value=cands), \
             mock.patch.object(E, "_client_identity", return_value=("p", "a")), \
             mock.patch.object(E, "netns_up", return_value=True), \
             mock.patch.object(E, "netns_down"), \
             mock.patch.object(E, "probe_in_netns",
                               side_effect=[("9.9.9.9", v) for v in verdicts]), \
             mock.patch.object(E.time, "sleep"), \
             redirect_stdout(io.StringIO()) as out:
            E.refill(self.tgt, want=6, max_probes=10, delay=0)
        return json.loads(self.tgt.pool_file.read_text())["last_refill"], out.getvalue()

    def test_tutte_le_impronte_rifiutate_in_piu_paesi_e_l_impronta(self):
        last, out = self._refill(["it-mil.prod", "it-rom.prod", "uk-lon.prod"],
                                 "CHALLENGE_ALL (rounds; safari,firefox,chrome,tor)")
        self.assertTrue(last["fingerprint_refused"])
        self.assertIn("not IP", out)

    def test_in_un_paese_solo_puo_essere_un_vicinato_bruciato(self):
        last, _ = self._refill(["it-mil.prod"] * 4,
                               "CHALLENGE_ALL (rounds; safari,firefox,chrome,tor)")
        self.assertFalse(last["fingerprint_refused"])

    def test_se_un_uscita_passa_nello_stesso_giro_l_impronta_e_buona(self):
        """Il refill del 26/09 dopo la correzione: quattro uscite di Londra
        rifiutavano ogni impronta mentre Milano e Roma passavano con Safari. Era
        reputazione, con la stessa parola 'challenge'."""
        ca = "CHALLENGE_ALL (rounds; safari,firefox,chrome,tor)"
        last, out = self._refill(["uk-lon.prod", "uk-gla.prod", "es-bcn.prod", "it-mil.prod"],
                                 [ca, ca, ca, "PASS (safari)"])
        self.assertFalse(last["fingerprint_refused"])
        self.assertNotIn("not IP", out)

    def test_i_403_ordinari_non_sono_l_impronta(self):
        last, _ = self._refill(["it-mil.prod", "uk-lon.prod", "es-bcn.prod"],
                               "HTTP_403 (rounds)")
        self.assertFalse(last["fingerprint_refused"])

    def test_l_impronta_rifiutata_prepara_subito_le_uscite_del_browser(self):
        with mock.patch.object(E, "refill_browser_pool") as prepara:
            self._refill(["it-mil.prod", "it-rom.prod", "uk-lon.prod"], "CHALLENGE_ALL")
        prepara.assert_called_once()

    def test_un_refill_normale_non_accende_chromium(self):
        with mock.patch.object(E, "refill_browser_pool") as prepara:
            self._refill(["it-mil.prod", "uk-lon.prod", "es-bcn.prod"], "HTTP_403 (rounds)")
        prepara.assert_not_called()

    def test_il_declassamento_non_cancella_quello_che_il_refill_ha_scoperto(self):
        self._refill(["it-mil.prod", "it-rom.prod", "uk-lon.prod"], "CHALLENGE_ALL")
        E._demote(self.tgt, E.load_pool(self.tgt), "10.0.0.1")
        self.assertIn("last_refill", json.loads(self.tgt.pool_file.read_text()))


NOW = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)


class LaSaluteDistingueIPDaImpronta(_Tmp):

    def _checks(self, *, pool=None, transport=None):
        pool_path = self.dir / "sofa_pool.json"
        tr_path = self.dir / "sofa_transport.json"
        if pool is not None:
            pool_path.write_text(json.dumps(pool))
        if transport is not None:
            tr_path.write_text(json.dumps(transport))
        pools = {"sofascore": (pool_path, 2, "SofaScore sta per tornare a bloccarci")}
        h = health.Health()
        with mock.patch.object(health, "EGRESS_POOLS", pools), \
             mock.patch.object(health, "EGRESS_TRANSPORT", tr_path):
            health._check_egress_pool(h, NOW)
            health._check_egress_transport(h, NOW)
        return {c.code: c for c in h.checks}

    def _iso(self, **delta):
        return (NOW - timedelta(**delta)).isoformat()

    def test_pool_vuoto_per_colpa_dell_impronta_non_consiglia_il_refill(self):
        checks = self._checks(pool={"servers": [], "last_refill": {
            "fingerprint_refused": True, "challenged_all": 20,
            "countries": ["it", "uk", "es"]}})
        msg = checks["egress:pool-low:sofascore"].message
        self.assertIn("non e' reputazione", msg)
        self.assertNotIn("vfoot-egress-refill.service", msg)

    def test_pool_vuoto_ordinario_consiglia_ancora_il_refill(self):
        checks = self._checks(pool={"servers": []})
        self.assertIn("vfoot-egress-refill.service",
                      checks["egress:pool-low:sofascore"].message)

    def test_il_preavviso_un_impronta_caduta_mentre_un_altra_regge(self):
        checks = self._checks(transport={"curl": {
            "checked_at": self._iso(hours=1), "ok_at": self._iso(hours=1),
            "used": "firefox", "challenged": ["safari"]}})
        self.assertEqual(checks["egress:fingerprint-refused"].level, "warn")
        self.assertIn("firefox", checks["egress:fingerprint-refused"].message)

    def test_il_browser_e_un_allarme(self):
        checks = self._checks(transport={
            "curl": {"checked_at": self._iso(hours=1),
                     "challenged": ["safari", "firefox", "chrome", "tor"]},
            "browser": {"since": self._iso(hours=3), "last_ok": self._iso(minutes=5),
                        "until": self._iso(minutes=-30)}})
        self.assertEqual(checks["egress:browser-fallback"].level, "alarm")

    def test_tutto_a_posto_tace(self):
        checks = self._checks(transport={"curl": {
            "checked_at": self._iso(hours=1), "ok_at": self._iso(hours=1),
            "used": "safari", "challenged": []}})
        self.assertEqual(set(checks), set())

    def test_un_rifiuto_di_giorni_fa_e_storia(self):
        checks = self._checks(transport={"curl": {
            "checked_at": self._iso(days=5), "ok_at": self._iso(days=5),
            "used": "firefox", "challenged": ["safari"]}})
        self.assertNotIn("egress:fingerprint-refused", checks)


class LaSimulazione(_Tmp):
    """SOFA_SIMULATE_CURL_REFUSED: la prova generale sul server vero, mentre il
    SofaScore vero lascia ancora passare curl."""

    def setUp(self):
        super().setUp()
        p = mock.patch.dict("os.environ", {"SOFA_SIMULATE_CURL_REFUSED": "1"})
        p.start(); self.addCleanup(p.stop)

    def test_il_client_si_prende_la_sfida_senza_uscire(self):
        s = _Session()
        c = _client_on(s, self.dir)
        with self.assertRaises(fetch_worker.SofaScoreChallenged):
            c.get(f"/api/v1/event/{MID}")
        self.assertEqual(s.calls, [], "nessuna richiesta deve partire davvero")
        self.assertEqual(c.challenged, list(IMPERSONATE_CHAIN))

    def test_il_probe_curl_dice_challenge_all(self):
        import sofa_probe_netns as probe
        self.assertEqual(probe.get(None, "https://x", "safari"), (None, "FP_CHALLENGE"))

    def test_senza_la_variabile_non_cambia_niente(self):
        with mock.patch.dict("os.environ", {"SOFA_SIMULATE_CURL_REFUSED": ""}):
            s = _Session()
            _client_on(s, self.dir).get(f"/api/v1/event/{MID}")
        self.assertEqual(len(s.calls), 1)
