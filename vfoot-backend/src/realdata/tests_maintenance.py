"""L'agente propone, il codice esegue — e qui si fissa il confine fra i due.

Tutto questo file gira **senza chiamare nessun modello**: l'agente è finto, il ponte
privilegiato è simulato. È voluto, ed è la ragione per cui il finto esiste. La catena
che questi test coprono — validazione, approvazione, applicazione, controllo di fumo,
ripristino — è quella che non ci si può permettere di scoprire rotta alle tre di
notte, ed è anche quella che sarebbe scomoda da provare per davvero: servirebbe un
verdetto rosso, un modello, dei soldi e qualche minuto a tentativo.

Le due proprietà che difendono:

* **la lista di ciò che è permesso sta in un `if`, non in un prompt.** L'ingresso
  dell'agente contiene testo che viene dai siti che scrapiamo, quindi nessuna frase
  può essere l'ultima difesa. Un modello completamente dirottato deve poter proporre
  al massimo una cosa dell'insieme chiuso — e un umano deve comunque cliccare;
* **il ripristino cade dalla parte giusta.** Il timer non legge un biglietto scritto
  da qualcuno prima: rifà il controllo lui, e ripristina *a meno che* il server non
  risulti sano. Se a morire è il controllore stesso, si torna indietro lo stesso.
"""
from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from realdata.models import MaintenanceProposal, MaintenanceRun
from realdata.services import agent_client, maintenance

SIMULATED = dict(VFOOT_MAINTENANCE_SIMULATED=True, VFOOT_AGENT_SIMULATED=True)


def _run(**kw) -> MaintenanceRun:
    return MaintenanceRun.objects.create(trigger=MaintenanceRun.TRIGGER_ALARM, **kw)


class InsiemeChiuso(TestCase):
    """Cosa l'agente può proporre. Tutto il resto viene respinto e registrato."""

    def test_unita_fuori_lista_respinta(self):
        with self.assertRaises(maintenance.Refused):
            maintenance.validate("restart_unit", {"unit": "sshd"})

    def test_unita_in_lista_accettata_col_suffisso(self):
        # 'vfoot-tick' e 'vfoot-tick.service' sono la stessa unita': normalizzare
        # evita che il modello venga respinto per una convenzione di scrittura.
        self.assertEqual(maintenance.validate("restart_unit",
                                              {"unit": "vfoot-tick.service"}),
                         {"unit": "vfoot-tick"})

    def test_comando_fuori_lista_respinto(self):
        with self.assertRaises(maintenance.Refused):
            maintenance.validate("rerun_command", {"command": "flush"})

    def test_comando_con_argomenti_respinto(self):
        """Gli argomenti sono una seconda grammatica da validare, e ogni comando
        della lista fa la cosa giusta senza."""
        with self.assertRaises(maintenance.Refused):
            maintenance.validate("rerun_command",
                                 {"command": "tick", "args": ["--now", "..."]})

    def test_cache_fuori_dalla_cartella_respinta(self):
        with self.assertRaises(maintenance.Refused):
            maintenance.validate("clear_cache_file", {"path": "/etc/passwd"})

    def test_traversal_respinto(self):
        """Il controllo è sul percorso RISOLTO: '..' e i link simbolici sono
        esattamente il modo in cui si esce da un confronto fatto sulla stringa."""
        from django.conf import settings

        escape = f"{settings.VFOOT_SOFASCORE_CACHE}/../../../etc/passwd"
        with self.assertRaises(maintenance.Refused):
            maintenance.validate("clear_cache_file", {"path": escape})

    def test_kind_sconosciuto_respinto(self):
        with self.assertRaises(maintenance.Refused):
            maintenance.validate("rm_rf", {"path": "/"})

    def test_una_proposta_respinta_viene_registrata_non_persa(self):
        """Un modello che continua a proporre cose vietate è esso stesso una
        scoperta: inghiottirla in silenzio la nasconderebbe."""
        run = _run()
        p = maintenance.record(run, {"kind": "restart_unit", "payload": {"unit": "sshd"}})
        self.assertEqual(p.status, MaintenanceProposal.STATUS_REFUSED)
        self.assertIn("sshd", p.result)


class PatchSoloCodice(TestCase):
    """Il diff che tocca lo schema non entra nel livello «approvi dal telefono»."""

    def _fake_git(self, diff_files):
        def fake(*args, **kw):
            if args[:2] == ("rev-parse", "--verify"):
                return True, "abc123"
            if args[0] == "diff":
                return True, "\n".join(diff_files)
            return True, ""
        return patch.object(maintenance, "git", side_effect=fake)

    def test_patch_di_solo_codice_accettata(self):
        with self._fake_git(["vfoot-backend/src/realdata/services/sofascore_adapter.py"]):
            cleaned = maintenance.validate("apply_patch", {"branch": "fix/duelswon"})
        self.assertEqual(cleaned["branch"], "fix/duelswon")

    def test_patch_con_migrazione_respinta(self):
        """Il ripristino rimette il CODICE e non lo schema: una patch che migra al
        volo lascerebbe una banca dati che il codice ripristinato non si aspetta —
        un guasto peggiore di quello da cui si sta scappando."""
        with self._fake_git(["vfoot-backend/src/realdata/migrations/0024_x.py"]):
            with self.assertRaises(maintenance.Refused) as ctx:
                maintenance.validate("apply_patch", {"branch": "fix/schema"})
        self.assertIn("migrazioni", str(ctx.exception))

    def test_branch_fuori_da_fix_respinto(self):
        # Uno spazio dei nomi che appartiene all'agente: non puo' proporre di
        # fondere il ramo su cui sta lavorando un umano.
        with self.assertRaises(maintenance.Refused):
            maintenance.validate("apply_patch", {"branch": "main"})

    def test_branch_che_non_cambia_niente_respinto(self):
        with self._fake_git([]):
            with self.assertRaises(maintenance.Refused):
                maintenance.validate("apply_patch", {"branch": "fix/vuoto"})


@override_settings(**SIMULATED)
class LivelloAutomatico(TestCase):
    """Parte spento, e `apply_patch` non ci entra mai."""

    def test_spento_di_default_tutto_aspetta_un_umano(self):
        run = _run()
        p = maintenance.record(run, {"kind": "restart_unit",
                                     "payload": {"unit": "vfoot-tick"}})
        self.assertEqual(p.status, MaintenanceProposal.STATUS_PROPOSED)

    @override_settings(VFOOT_MAINTENANCE_AUTO=True, **SIMULATED)
    def test_acceso_il_riavvio_si_approva_da_solo(self):
        run = _run()
        p = maintenance.record(run, {"kind": "restart_unit",
                                     "payload": {"unit": "vfoot-tick"}})
        self.assertEqual(p.status, MaintenanceProposal.STATUS_APPROVED)

    @override_settings(VFOOT_MAINTENANCE_AUTO=True, **SIMULATED)
    def test_acceso_la_patch_aspetta_comunque(self):
        """L'asimmetria che non deve mai sparire: nessun livello automatico,
        a nessuna impostazione, esegue una patch."""
        self.assertTrue(MaintenanceProposal(
            kind=MaintenanceProposal.KIND_APPLY_PATCH).needs_human)
        with patch.object(maintenance, "git",
                          side_effect=lambda *a, **k: (True, "un/file.py")):
            run = _run()
            p = maintenance.record(run, {"kind": "apply_patch",
                                         "payload": {"branch": "fix/x"}})
        self.assertEqual(p.status, MaintenanceProposal.STATUS_PROPOSED)


@override_settings(**SIMULATED)
class SecondaValidazione(TestCase):
    """Fra la proposta e l'esecuzione passano ore: il controllo che conta è quello
    più vicino all'effetto collaterale."""

    def test_un_payload_manomesso_dopo_l_approvazione_viene_respinto(self):
        run = _run()
        p = maintenance.record(run, {"kind": "restart_unit",
                                     "payload": {"unit": "vfoot-tick"}})
        p.status = MaintenanceProposal.STATUS_APPROVED
        p.payload = {"unit": "sshd"}          # come se qualcuno avesse toccato la riga
        p.save()

        self.assertFalse(maintenance.execute(p))
        p.refresh_from_db()
        self.assertEqual(p.status, MaintenanceProposal.STATUS_REFUSED)
        self.assertIn("seconda validazione", p.result)


@override_settings(**SIMULATED)
class RipristinoArmatoPrima(TestCase):
    """L'ordine dei passi È la proprietà di sicurezza."""

    def _proposal(self) -> MaintenanceProposal:
        run = _run()
        with patch.object(maintenance, "git",
                          side_effect=lambda *a, **k: (True, "un/file.py")):
            p = maintenance.record(run, {"kind": "apply_patch",
                                         "payload": {"branch": "fix/x"}})
        p.status = MaintenanceProposal.STATUS_APPROVED
        p.save()
        return p

    def test_si_arma_prima_di_toccare_qualsiasi_cosa(self):
        """Armare dopo aver applicato lascerebbe una finestra in cui il codice rotto
        è vivo e nessuno è programmato per disfarlo."""
        ordine: list[str] = []

        def git(*args, **kw):
            ordine.append(f"git {args[0]}")
            return True, "abc123" if args[0] == "rev-parse" else "un/file.py"

        def bridge(args, **kw):
            ordine.append(f"bridge {args[0]}")
            return True, "ok"

        with patch.object(maintenance, "git", side_effect=git), \
             patch("realdata.services.maintenance_bridge.run", side_effect=bridge), \
             patch.object(maintenance, "_run_tests", return_value=(True, "")):
            maintenance.execute(self._proposal())

        self.assertLess(ordine.index("bridge arm-rollback"), ordine.index("git merge"))

    def test_se_non_si_riesce_ad_armare_non_si_applica(self):
        """Niente rete, niente salto."""
        def bridge(args, **kw):
            return (False, "systemd assente") if args[0] == "arm-rollback" else (True, "")

        with patch.object(maintenance, "git",
                          side_effect=lambda *a, **k: (True, "abc123")) as git, \
             patch("realdata.services.maintenance_bridge.run", side_effect=bridge):
            p = self._proposal()
            self.assertFalse(maintenance.execute(p))

        p.refresh_from_db()
        self.assertIn("NON e' stata applicata", p.result)
        self.assertNotIn("merge", [c.args[0] for c in git.call_args_list])

    def test_i_test_li_rigira_l_esecutore_e_se_falliscono_non_si_applica(self):
        """L'agente dice «la suite passa». Quella frase l'ha scritta un modello,
        quindi non è una prova: il cancello è questa esecuzione."""
        with patch.object(maintenance, "git",
                          side_effect=lambda *a, **k: (True, "abc123")) as git, \
             patch("realdata.services.maintenance_bridge.run",
                   side_effect=lambda a, **k: (True, "ok")), \
             patch.object(maintenance, "_run_tests",
                          return_value=(False, "1 test fallito")):
            p = self._proposal()
            self.assertFalse(maintenance.execute(p))

        self.assertNotIn("merge", [c.args[0] for c in git.call_args_list])

    def test_fumo_fallito_ripristina_subito_senza_aspettare_il_timer(self):
        chiamate: list[str] = []

        def bridge(args, **kw):
            chiamate.append(args[0])
            return (False, "l'app non risponde") if args[0] == "check" else (True, "ok")

        with patch.object(maintenance, "git",
                          side_effect=lambda *a, **k: (True, "abc123")), \
             patch("realdata.services.maintenance_bridge.run", side_effect=bridge), \
             patch.object(maintenance, "_run_tests", return_value=(True, "")):
            p = self._proposal()
            self.assertFalse(maintenance.execute(p))

        self.assertIn("rollback", chiamate)
        p.refresh_from_db()
        self.assertIn("ripristino immediato", p.result)

    def test_fumo_passato_non_ripristina(self):
        chiamate: list[str] = []

        def bridge(args, **kw):
            chiamate.append(args[0])
            return True, "ok"

        with patch.object(maintenance, "git",
                          side_effect=lambda *a, **k: (True, "abc123")), \
             patch("realdata.services.maintenance_bridge.run", side_effect=bridge), \
             patch.object(maintenance, "_run_tests", return_value=(True, "")):
            p = self._proposal()
            self.assertTrue(maintenance.execute(p))

        self.assertNotIn("rollback", chiamate)


class LetturaDellaRisposta(TestCase):
    """Tollerante sull'involucro, severa sul contenuto: ogni CLI incarta la sua
    risposta a modo suo, e l'incarto non è il contratto."""

    def test_json_nudo(self):
        self.assertEqual(agent_client.parse('{"proposals": []}')["proposals"], [])

    def test_json_dentro_i_backtick(self):
        raw = 'Ecco:\n```json\n{"proposals": [], "summary": "x"}\n```\n'
        self.assertEqual(agent_client.parse(raw)["summary"], "x")

    def test_involucro_col_payload_come_stringa(self):
        raw = json.dumps({"type": "result",
                          "result": '{"proposals": [], "summary": "dentro"}'})
        self.assertEqual(agent_client.parse(raw)["summary"], "dentro")

    def test_graffe_dentro_una_stringa_non_confondono(self):
        raw = '{"summary": "ha risposto {questo}", "proposals": []}'
        self.assertEqual(agent_client.parse(raw)["summary"], "ha risposto {questo}")

    def test_senza_proposals_e_un_errore(self):
        with self.assertRaises(agent_client.AgentError):
            agent_client.parse('{"summary": "niente"}')

    def test_uscita_vuota_e_un_errore(self):
        with self.assertRaises(agent_client.AgentError):
            agent_client.parse("   ")


@override_settings(**SIMULATED)
class CatenaCompleta(TestCase):
    """Dalla passata dell'agente all'esecuzione, passando dal sì di un umano."""

    def test_proponi_approva_esegui(self):
        from django.core.management import call_command
        from io import StringIO

        run = _run()
        p = maintenance.record(run, {"kind": "restart_unit",
                                     "payload": {"unit": "vfoot-egress-refill"},
                                     "rationale": "pool a secco"})
        self.assertEqual(p.status, MaintenanceProposal.STATUS_PROPOSED)

        # Il tick non tocca ciò che nessuno ha approvato.
        call_command("maintenance_tick", stdout=StringIO())
        p.refresh_from_db()
        self.assertEqual(p.status, MaintenanceProposal.STATUS_PROPOSED)

        call_command("maintenance_review", approve=p.id, stdout=StringIO())
        call_command("maintenance_tick", stdout=StringIO())
        p.refresh_from_db()
        self.assertEqual(p.status, MaintenanceProposal.STATUS_DONE)

    def test_un_rifiuto_torna_all_agente_e_non_si_ripropone(self):
        from django.core.management import call_command
        from io import StringIO

        run = _run()
        p = maintenance.record(run, {"kind": "restart_unit",
                                     "payload": {"unit": "vfoot-tick"}})
        call_command("maintenance_review", reject=p.id, why="non c'entra",
                     stdout=StringIO())

        impronte = [r["fingerprint"] for r in maintenance.rejected_fingerprints()]
        p.refresh_from_db()
        self.assertIn(p.fingerprint, impronte)

    def test_una_proposta_si_decide_una_volta_sola(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from io import StringIO

        run = _run()
        p = maintenance.record(run, {"kind": "restart_unit",
                                     "payload": {"unit": "vfoot-tick"}})
        call_command("maintenance_review", approve=p.id, stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("maintenance_review", reject=p.id, stdout=StringIO())


@override_settings(**SIMULATED)
class ContestoDellAgente(TestCase):
    """Cosa gli diamo in pasto — e cosa no."""

    def test_porta_la_memoria_e_i_rifiuti(self):
        run = _run(summary="ieri")
        p = maintenance.record(run, {"kind": "restart_unit",
                                     "payload": {"unit": "vfoot-tick"}})
        p.status = MaintenanceProposal.STATUS_REJECTED
        p.save()

        ctx = agent_client.build_context(trigger="alarm")
        self.assertEqual(ctx["journal"][0]["summary"], "ieri")
        self.assertEqual(len(ctx["already_rejected"]), 1)
        self.assertIn("vfoot-tick", ctx["allowed_units"])

    def test_non_gli_passiamo_i_payload_grezzi(self):
        """Il contesto è il rapporto DIGERITO. Meno testo scaricato arriva
        all'agente parola per parola, più piccola è la superficie di iniezione."""
        ctx = agent_client.build_context(trigger="alarm")
        self.assertEqual(set(ctx) - {
            "trigger", "verdict", "checks", "journal", "already_rejected",
            "allowed_kinds", "allowed_units", "allowed_commands", "max_actions",
            "repo"}, set())


@override_settings(**SIMULATED)
class ApiDellaPagina(TestCase):
    """Il cancello dei permessi e le due risposte che la pagina deve dare bene.

    L'area riservata al gestore del SITO è la prima del progetto: ogni altra zona
    di amministrazione qui dentro riguarda i membri di una lega. Per questo il
    controllo va provato esplicitamente — un endpoint di manutenzione aperto a
    tutti i loggati sarebbe un bottone «riavvia il server» per chiunque giochi.
    """

    def setUp(self):
        from rest_framework.authtoken.models import Token

        self.gestore = User.objects.create_user("gestore", password="x", is_staff=True)
        self.tizio = User.objects.create_user("tizio", password="x")
        self.t_gestore = Token.objects.create(user=self.gestore).key
        self.t_tizio = Token.objects.create(user=self.tizio).key
        run = _run(summary="qualcosa non va")
        self.p = maintenance.record(run, {"kind": "restart_unit",
                                          "payload": {"unit": "vfoot-tick"},
                                          "rationale": "il timer non scatta"})

    def _get(self, url, token=None):
        headers = {"HTTP_AUTHORIZATION": f"Token {token}"} if token else {}
        return self.client.get(url, **headers)

    def test_un_utente_qualunque_non_entra(self):
        self.assertEqual(self._get("/api/v1/maintenance/state/", self.t_tizio).status_code, 403)

    def test_senza_credenziali_non_si_entra(self):
        self.assertIn(self._get("/api/v1/maintenance/state/").status_code, (401, 403))

    def test_il_gestore_vede_verdetto_e_proposte(self):
        r = self._get("/api/v1/maintenance/state/", self.t_gestore)
        self.assertEqual(r.status_code, 200)
        self.assertIn(r.json()["verdict"], ("ok", "warn", "alarm"))
        self.assertEqual([p["id"] for p in r.json()["pending"]], [self.p.id])
        # Lo stato del livello automatico è scritto, non lasciato indovinare.
        self.assertFalse(r.json()["auto_enabled"])

    def test_decidere_richiede_lo_staff(self):
        r = self.client.post(f"/api/v1/maintenance/proposals/{self.p.id}/decide/",
                             {"decision": "approve"},
                             HTTP_AUTHORIZATION=f"Token {self.t_tizio}")
        self.assertEqual(r.status_code, 403)
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, MaintenanceProposal.STATUS_PROPOSED)

    def test_approvare_mette_in_coda_e_non_esegue(self):
        r = self.client.post(f"/api/v1/maintenance/proposals/{self.p.id}/decide/",
                             {"decision": "approve"},
                             HTTP_AUTHORIZATION=f"Token {self.t_gestore}")
        self.assertEqual(r.status_code, 200)
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, MaintenanceProposal.STATUS_APPROVED)
        self.assertEqual(self.p.decided_by, self.gestore)
        # Non eseguita QUI: la fa l'esecutore su timer, e la risposta lo dice.
        self.assertIsNone(self.p.executed_at)
        self.assertIn("esecutore", r.json()["note"])

    def test_decidere_due_volte_da_conflitto(self):
        """Due persone (o due tocchi) non devono entrambi credere di aver deciso."""
        url = f"/api/v1/maintenance/proposals/{self.p.id}/decide/"
        auth = {"HTTP_AUTHORIZATION": f"Token {self.t_gestore}"}
        self.assertEqual(self.client.post(url, {"decision": "approve"}, **auth).status_code, 200)
        self.assertEqual(self.client.post(url, {"decision": "reject"}, **auth).status_code, 409)

    def test_decisione_non_valida_respinta(self):
        r = self.client.post(f"/api/v1/maintenance/proposals/{self.p.id}/decide/",
                             {"decision": "esegui-tutto"},
                             HTTP_AUTHORIZATION=f"Token {self.t_gestore}")
        self.assertEqual(r.status_code, 400)

    def test_il_dettaglio_di_una_patch_porta_il_diff(self):
        with patch.object(maintenance, "git",
                          side_effect=lambda *a, **k: (True, "un/file.py"
                                                       if a[0] == "diff" else "abc")):
            p = maintenance.record(_run(), {"kind": "apply_patch",
                                            "payload": {"branch": "fix/x"}})
        with patch.object(maintenance, "git",
                          side_effect=lambda *a, **k: (True, "--- a\n+++ b\n+riga")):
            r = self._get(f"/api/v1/maintenance/proposals/{p.id}/", self.t_gestore)
        self.assertEqual(r.status_code, 200)
        self.assertIn("+riga", r.json()["diff"])
