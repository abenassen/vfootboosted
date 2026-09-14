"""SofaScore live pipeline wiring: egress warms the cache, the offline code reads it.

The egress (root, netns, network) is mocked, so this exercises the DB-aware half —
a live round's status/score update and import, finalize's warm+import, and the tick
advancing state only on success — with no root and no tunnel.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from realdata.models import (
    Competition, CompetitionSeason, JobRun, Match, Season, Team, TeamSeason,
)
from realdata.services import alerting, egress_client, live_ingest
from realdata.services.sofascore_adapter import SofaIngestResult

_RESOLVED = SofaIngestResult(matches=1)
_UNRESOLVED = SofaIngestResult(unresolved=1)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class _Base(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            external_source="sofascore", external_id="95836")
        self.home = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Torino"))
        self.away = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Inter"))

    def _match(self, ext="111", **kw):
        return Match.objects.create(
            external_source="sofascore", external_id=ext,
            competition_season=self.cs, home_team=self.home, away_team=self.away, **kw)


class LiveIngestTests(_Base):
    def test_year_for(self):
        self.assertEqual(live_ingest.year_for(self._match()), "26/27")

    def test_a_round_updates_status_and_score_from_warm_cache(self):
        m = self._match(status=Match.STATUS_LIVE)
        event = {"id": 111, "status": {"type": "finished"},
                 "homeScore": {"current": 2}, "awayScore": {"current": 1}}
        with mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=True), \
             mock.patch.object(live_ingest, "_cached_event", return_value=event), \
             mock.patch.object(live_ingest, "ingest_sofascore_matches",
                               return_value=_RESOLVED):
            self.assertTrue(live_ingest.live_round(m, heavy=False))
        m.refresh_from_db()
        self.assertEqual(m.status, Match.STATUS_FINISHED)
        self.assertEqual((m.home_goals, m.away_goals), (2, 1))

    def test_a_round_blocked_at_the_egress_leaves_the_match_untouched(self):
        m = self._match(status=Match.STATUS_LIVE)
        with mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=False), \
             mock.patch.object(live_ingest, "ingest_sofascore_matches") as ing:
            self.assertFalse(live_ingest.live_round(m, heavy=False))
        ing.assert_not_called()
        m.refresh_from_db()
        self.assertEqual(m.status, Match.STATUS_LIVE)

    def test_a_light_round_asks_for_the_cheap_fetch_and_no_heatmaps(self):
        """The two halves of the saving, in one place: what the egress is asked to
        fetch, and what the importer is asked to read."""
        m = self._match(status=Match.STATUS_LIVE)
        with mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=True) as wm, \
             mock.patch.object(live_ingest, "_cached_event", return_value=None), \
             mock.patch.object(live_ingest, "ingest_sofascore_matches",
                               return_value=_RESOLVED) as ing:
            self.assertTrue(live_ingest.live_round(m, heavy=False))
        wm.assert_called_once_with([m.external_id], "live")
        self.assertIs(ing.call_args.kwargs["with_heatmaps"], False)

    def test_a_heavy_round_asks_for_everything(self):
        m = self._match(status=Match.STATUS_LIVE)
        with mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=True) as wm, \
             mock.patch.object(live_ingest, "_cached_event", return_value=None), \
             mock.patch.object(live_ingest, "ingest_sofascore_matches",
                               return_value=_RESOLVED) as ing:
            self.assertTrue(live_ingest.live_round(m, heavy=True))
        wm.assert_called_once_with([m.external_id], "final")
        self.assertIs(ing.call_args.kwargs["with_heatmaps"], True)

    def test_the_egress_is_warmed_once_per_round_not_twice(self):
        """The status update and the import share the fetch: they are one round,
        not a poll followed by an import that warms the same match again."""
        m = self._match(status=Match.STATUS_LIVE)
        with mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=True) as wm, \
             mock.patch.object(live_ingest, "_cached_event", return_value=None), \
             mock.patch.object(live_ingest, "ingest_sofascore_matches",
                               return_value=_RESOLVED):
            live_ingest.live_round(m, heavy=True)
        self.assertEqual(wm.call_count, 1)

    def test_finalize_warms_then_imports_the_right_match(self):
        m = self._match(status=Match.STATUS_FINISHED)
        with mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=True) as wm, \
             mock.patch.object(live_ingest, "ingest_sofascore_matches",
                               return_value=_RESOLVED) as ing:
            self.assertTrue(live_ingest.finalize(m))
        wm.assert_called_once_with([m.external_id], "final")
        self.assertEqual(ing.call_args.kwargs["match_ids"], [111])

    def test_the_import_does_not_pull_the_calendar(self):
        """The whole saving of step 1: a match we can already address by id costs
        no seasons -> rounds -> events pass."""
        m = self._match(status=Match.STATUS_FINISHED)
        with mock.patch.object(live_ingest.egress_client, "warm_schedule",
                               return_value=True) as ws, \
             mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=True), \
             mock.patch.object(live_ingest, "ingest_sofascore_matches",
                               return_value=_RESOLVED), \
             mock.patch.object(live_ingest, "ingest_sofascore_season") as season:
            self.assertTrue(live_ingest.finalize(m))
        ws.assert_not_called()
        season.assert_not_called()

    def test_an_unresolvable_id_falls_back_to_the_calendar(self):
        """The address is static but not guaranteed: when it stops answering with a
        usable fixture, the calendar is still there — the safety net, not the road."""
        m = self._match(status=Match.STATUS_FINISHED)
        with mock.patch.object(live_ingest.egress_client, "warm_schedule",
                               return_value=True) as ws, \
             mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=True), \
             mock.patch.object(live_ingest, "ingest_sofascore_matches",
                               return_value=_UNRESOLVED), \
             mock.patch.object(live_ingest, "ingest_sofascore_season") as season:
            self.assertTrue(live_ingest.finalize(m))
        ws.assert_called_once()
        self.assertEqual(season.call_args.kwargs["match_ids"], [111])

    def test_the_fallback_keeps_the_ROUND_s_weight(self):
        """A light warm dropped the heatmaps and did not fetch them back. Asking the
        fallback import for them would send the reading side to the network, which
        from there is a block — so a light round would fail outright instead of
        merely taking the long way round."""
        m = self._match(status=Match.STATUS_LIVE)
        with mock.patch.object(live_ingest.egress_client, "warm_schedule",
                               return_value=True), \
             mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=True), \
             mock.patch.object(live_ingest, "_cached_event", return_value=None), \
             mock.patch.object(live_ingest, "ingest_sofascore_matches",
                               return_value=_UNRESOLVED), \
             mock.patch.object(live_ingest, "ingest_sofascore_season") as season:
            self.assertTrue(live_ingest.live_round(m, heavy=False))
        self.assertIs(season.call_args.kwargs["with_heatmaps"], False)

    def test_a_blocked_calendar_fallback_reports_failure(self):
        m = self._match(status=Match.STATUS_FINISHED)
        with mock.patch.object(live_ingest.egress_client, "warm_schedule",
                               return_value=False), \
             mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=True), \
             mock.patch.object(live_ingest, "ingest_sofascore_matches",
                               return_value=_UNRESOLVED), \
             mock.patch.object(live_ingest, "ingest_sofascore_season") as season:
            self.assertFalse(live_ingest.finalize(m))
        season.assert_not_called()

    def test_finalize_bails_when_egress_blocked_and_never_imports(self):
        m = self._match(status=Match.STATUS_FINISHED)
        with mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=False), \
             mock.patch.object(live_ingest, "ingest_sofascore_matches") as ing:
            self.assertFalse(live_ingest.finalize(m))
        ing.assert_not_called()

    def test_a_round_does_not_require_a_finished_match(self):
        """The importer skips whatever the provider does not call finished. Without
        only_finished=False a live round would report success and import nothing
        at all."""
        m = self._match(status=Match.STATUS_LIVE)
        with mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=True), \
             mock.patch.object(live_ingest, "_cached_event", return_value=None), \
             mock.patch.object(live_ingest, "ingest_sofascore_matches",
                               return_value=_RESOLVED) as ing:
            self.assertTrue(live_ingest.live_round(m, heavy=False))
        self.assertIs(ing.call_args.kwargs["only_finished"], False)
        # And it must not skip a match it has already written rows for: the whole
        # point of the second import is what changed since the first.
        self.assertIs(ing.call_args.kwargs["skip_existing"], False)

    def test_no_round_ever_promotes_the_match(self):
        """Heavy or light: data_ready means "the provider has stopped changing this
        match", and a match being played has not."""
        m = self._match(status=Match.STATUS_LIVE)
        for heavy in (False, True):
            with mock.patch.object(live_ingest.egress_client, "warm_matches",
                                   return_value=True), \
                 mock.patch.object(live_ingest, "_cached_event", return_value=None), \
                 mock.patch.object(live_ingest, "ingest_sofascore_matches",
                                   return_value=_RESOLVED):
                live_ingest.live_round(m, heavy=heavy)
            m.refresh_from_db()
            self.assertFalse(m.data_ready)


class TickWiringTests(_Base):
    def test_final_confirm_sets_data_ready_only_on_success(self):
        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        m = self._match(status=Match.STATUS_FINISHED,
                        finished_at=now - timedelta(hours=3))
        with mock.patch.object(live_ingest, "finalize", return_value=True) as fin:
            call_command("tick", "--now", _iso(now))
        fin.assert_called_once()
        m.refresh_from_db()
        self.assertTrue(m.data_ready)

    def test_final_confirm_leaves_data_ready_false_when_blocked(self):
        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        m = self._match(status=Match.STATUS_FINISHED,
                        finished_at=now - timedelta(hours=3))
        with mock.patch.object(live_ingest, "finalize", return_value=False):
            call_command("tick", "--now", _iso(now))
        m.refresh_from_db()
        self.assertFalse(m.data_ready)

    def test_dry_run_does_not_touch_the_egress(self):
        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        self._match(status=Match.STATUS_FINISHED, finished_at=now - timedelta(hours=3))
        with mock.patch.object(live_ingest, "finalize") as fin:
            call_command("tick", "--now", _iso(now), "--dry-run")
        fin.assert_not_called()

    def test_the_first_round_is_heavy_and_stamps_both_clocks(self):
        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        m = self._match(status=Match.STATUS_LIVE,
                        kickoff=now - timedelta(minutes=30))
        with mock.patch.object(live_ingest, "live_round", return_value=True) as rnd:
            call_command("tick", "--now", _iso(now))
        rnd.assert_called_once()
        self.assertIs(rnd.call_args.kwargs["heavy"], True)
        m.refresh_from_db()
        self.assertEqual(m.data_checked_at, now)
        self.assertEqual(m.data_imported_at, now)
        self.assertFalse(m.data_ready)

    @override_settings(VFOOT_LIVE_POLL_MINUTES=2, VFOOT_LIVE_HEAVY_EVERY=4)
    def test_a_light_round_stamps_only_the_round_clock(self):
        """Otherwise the light round would keep pushing the heavy one's due time
        out and it would never come round — the exact trap the two separate clocks
        existed to avoid, which one clock has to avoid differently."""
        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        imported = now - timedelta(minutes=4)
        m = self._match(status=Match.STATUS_LIVE,
                        kickoff=now - timedelta(minutes=30),
                        data_checked_at=now - timedelta(minutes=2),
                        data_imported_at=imported)
        with mock.patch.object(live_ingest, "live_round", return_value=True) as rnd:
            call_command("tick", "--now", _iso(now))
        self.assertIs(rnd.call_args.kwargs["heavy"], False)
        m.refresh_from_db()
        self.assertEqual(m.data_checked_at, now)
        self.assertEqual(m.data_imported_at, imported)   # untouched

    def test_a_blocked_round_stamps_nothing(self):
        """So the next tick retries it instead of waiting out the whole interval."""
        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        m = self._match(status=Match.STATUS_LIVE,
                        kickoff=now - timedelta(minutes=30))
        with mock.patch.object(live_ingest, "live_round", return_value=False):
            call_command("tick", "--now", _iso(now))
        m.refresh_from_db()
        self.assertIsNone(m.data_checked_at)
        self.assertIsNone(m.data_imported_at)

    def test_full_time_is_announced_at_the_stamp_and_not_again(self):
        """The full-time push belongs to ``stamp_ft``, which by construction happens
        exactly once per match — the later finalization steps must stay silent."""
        from vfoot.services import live_updates

        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        m = self._match(status=Match.STATUS_FINISHED)
        with mock.patch.object(live_updates, "announce_full_time",
                               return_value=0) as ann:
            call_command("tick", "--now", _iso(now))          # stamps FT
            ann.assert_called_once()
            ann.reset_mock()
            with mock.patch.object(live_ingest, "finalize", return_value=True):
                call_command("tick", "--now", _iso(now + timedelta(hours=2)))
            ann.assert_not_called()


@override_settings(VFOOT_HEALTH_EMAIL="guasti@vfoot.it")
class IlTickDaLAllarmeMentreLaPartitaEInCampo(_Base):
    """Chi se ne accorge, e quando.

    Il 14/09/2026 l'egress e' rimasto bloccato per novanta minuti con due partite
    in corso. Il controllo che descrive esattamente quel guasto esisteva gia' e la
    sua condizione era soddisfatta, ma lo faceva il rapporto quotidiano delle
    07:30: la mail sarebbe arrivata la mattina dopo. Il tick invece era li', ogni
    minuto, e non diceva niente a nessuno.
    """

    def _partita_in_corso(self, now):
        return self._match(status=Match.STATUS_LIVE,
                           kickoff=now - timedelta(minutes=30))

    def _giri(self, quanti, start, *, riuscito=False):
        for i in range(quanti):
            with mock.patch.object(live_ingest, "live_round",
                                   return_value=riuscito):
                call_command("tick", "--now", _iso(start + timedelta(minutes=i)))

    def test_dopo_una_serie_di_giri_ciechi_parte_una_mail(self):
        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        self._partita_in_corso(now)
        self._giri(8, now)
        self.assertEqual(len(mail.outbox), 1)
        testo = mail.outbox[0].subject + mail.outbox[0].body
        self.assertIn("egress", testo)
        self.assertIn("partite in corso sono ferme", testo)

    def test_novanta_giri_ciechi_restano_UNA_mail(self):
        """La ragione per cui l'allarme non sta in un `if` e basta: la serie vera
        e' durata novanta esecuzioni, e novanta mail non le legge nessuno."""
        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        self._partita_in_corso(now)
        self._giri(40, now)
        self.assertEqual(len(mail.outbox), 1)

    def test_il_giro_che_ha_spedito_lo_segna_nel_registro(self):
        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        self._partita_in_corso(now)
        self._giri(8, now)
        segnati = [r for r in JobRun.objects.filter(job="tick")
                   if r.did.get("alarm_mailed")]
        self.assertEqual(len(segnati), 1)

    def test_una_pipeline_sana_non_manda_niente(self):
        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        self._partita_in_corso(now)
        self._giri(20, now, riuscito=True)
        self.assertEqual(mail.outbox, [])

    def test_se_la_mail_non_parte_non_si_segna_e_si_riprova(self):
        """Segnare «detto» su un invio fallito e' il modo di stare zitti per
        un'ora dopo aver taciuto del tutto."""
        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        self._partita_in_corso(now)
        with mock.patch.object(alerting, "mail", return_value=False) as spedisci:
            self._giri(8, now)
        self.assertGreater(spedisci.call_count, 1)
        self.assertEqual([r for r in JobRun.objects.filter(job="tick")
                          if r.did.get("alarm_mailed")], [])

    def test_un_server_di_posta_rotto_non_ferma_il_tick(self):
        """La sorveglianza non puo' diventare il guasto di cui parla: il tick e'
        cio' che tiene vive le partite in corso."""
        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        m = self._partita_in_corso(now)
        with mock.patch.object(alerting, "mail",
                               side_effect=OSError("SMTP a terra")):
            self._giri(8, now)   # non deve sollevare
        m.refresh_from_db()
        self.assertEqual(m.status, Match.STATUS_LIVE)


class QuandoLEgressFallisceLoDiceTests(TestCase):
    """Il 14/09/2026 il journal di una serata intera diceva solo «egress blocked;
    will retry». Vero, ripetuto novanta volte, e inservibile: l'errore che aveva
    inchiodato la pipeline era gia' passato per questo processo — letto in un
    ``subprocess.run`` e buttato via un'istruzione dopo. E' saltato fuori solo
    rilanciando la stessa fetch a mano, un'ora e mezza dopo.
    """

    def _run(self, *, rc, stdout="", stderr=""):
        finto = mock.Mock(returncode=rc, stdout=stdout, stderr=stderr)
        with mock.patch.object(egress_client.subprocess, "run", return_value=finto):
            return egress_client.run_egress(["fetch", "--match-ids", "1"])

    def test_il_motivo_del_fallimento_finisce_nel_log(self):
        vero = ("ERROR: SSLError: Failed to perform, curl: (35) TLS connect "
                "error: error:00000000:invalid library (0)")
        with self.assertLogs("realdata.services.egress_client", "WARNING") as reg:
            self.assertFalse(self._run(rc=1, stderr=vero))
        detto = "\n".join(reg.output)
        self.assertIn("TLS connect error", detto)
        self.assertIn("rc=1", detto)

    def test_senza_stderr_vale_la_narrazione_su_stdout(self):
        """Quale IP si stava usando e quante rotazioni sono state fatte lo dice
        l'orchestratore su stdout: senza stderr e' comunque meglio di niente."""
        with self.assertLogs("realdata.services.egress_client", "WARNING") as reg:
            self._run(rc=3, stdout="using 1.2.3.4 via it-rom\nexhausted rotations.")
        self.assertIn("exhausted rotations.", "\n".join(reg.output))

    def test_una_corsa_riuscita_non_scrive_niente(self):
        """Il tick gira 1440 volte al giorno: se parlasse anche quando va tutto
        bene, il journal smetterebbe di essere leggibile proprio nei giorni in cui
        serve."""
        import logging
        with self.assertNoLogs("realdata.services.egress_client", logging.WARNING):
            self.assertTrue(self._run(rc=0, stdout="  OK — cache warmed."))

    def test_un_wrapper_che_non_parte_si_distingue_da_un_rifiuto(self):
        with mock.patch.object(egress_client.subprocess, "run",
                               side_effect=FileNotFoundError("sudo")), \
             self.assertLogs("realdata.services.egress_client", "WARNING") as reg:
            self.assertFalse(egress_client.run_egress(["fetch"]))
        self.assertIn("non eseguibile", "\n".join(reg.output))
