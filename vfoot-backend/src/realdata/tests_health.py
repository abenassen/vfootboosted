"""Il registro delle esecuzioni, i controlli di salute e il canarino sui dati.

Il guasto che tutto questo esiste per prendere non somiglia a un guasto: SofaScore
rinomina una colonna, la richiesta riesce, il comando esce 0, e quello che entra in
banca dati è una stagione di giocatori senza statistiche. Nessun codice d'uscita se
ne accorge, e nemmeno un occhio umano sul journal, perché non c'è niente da leggere.

Qui si fissano le tre risposte a quel problema, e soprattutto i loro **confini** —
perché un allarme che scatta quando non deve viene spento entro una settimana, e si
porta via anche quello vero:

* la riga di esecuzione distingue «non dovevo fare niente» da «dovevo e non ho
  fatto», che nel journal sono la stessa riga e sono fatti opposti;
* i controlli tacciono sui job che nessuno ha acceso;
* il canarino non grida per l'assenza di un rigore parato (succede nel 6% delle
  partite): guarda solo le colonne che SofaScore manda **sempre**, e le guarda
  sull'unione di due partite, che è la finestra in cui su 600 partite vere non ha
  mai sbagliato una volta.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from django.test import TestCase
from django.utils.timezone import now as django_now

from realdata.models import (
    Competition, CompetitionSeason, JobRun, Match, Season, Team, TeamSeason,
)
from realdata.services import health, job_log, shape_canary

UTC = timezone.utc
NOW = datetime(2026, 9, 20, 20, 0, tzinfo=UTC)


class RegistroEsecuzioni(TestCase):
    """La riga che ogni job lascia: aperta all'inizio, chiusa alla fine."""

    def test_una_esecuzione_riuscita_lascia_i_suoi_numeri(self):
        with job_log.record("tick") as run:
            run.due(live_round=2)
            run.did(imported=1)
            run.did(imported=1)          # i contatori si sommano
            run.note("due partite lette")

        row = JobRun.objects.get()
        self.assertTrue(row.ok)
        self.assertIsNotNone(row.finished_at)
        self.assertEqual(row.due, {"live_round": 2})
        self.assertEqual(row.did, {"imported": 2})
        self.assertEqual(row.note, "due partite lette")

    def test_un_errore_viene_registrato_e_poi_rilanciato(self):
        # Rilanciato senza toccarlo: systemd deve continuare a vedere il
        # fallimento che sa già vedere. Un monitor che se lo mangia è peggio di
        # nessun monitor.
        with self.assertRaises(ValueError):
            with job_log.record("sync_calendar"):
                raise ValueError("egress bloccato")

        row = JobRun.objects.get()
        self.assertFalse(row.ok)
        self.assertIn("egress bloccato", row.error)

    def test_lo_zero_non_e_un_debito(self):
        """`due` vuoto è la definizione di esecuzione tranquilla: ci si appoggia
        la pulizia del registro, quindi uno zero non deve sporcarlo."""
        with job_log.record("tick") as run:
            run.due(live_round=0, final_check=0)
        self.assertEqual(JobRun.objects.get().due, {})

    def test_la_pulizia_tiene_cio_che_vale(self):
        # L'orologio vero, non NOW: `prune` misura da adesso, ed è giusto che lo
        # faccia — una pulizia che accetta una data da fuori è una pulizia che un
        # giorno cancella l'anno sbagliato.
        vecchio = django_now() - timedelta(days=30)
        quiete = JobRun.objects.create(job="tick", started_at=vecchio, ok=True)
        fallita = JobRun.objects.create(job="tick", started_at=vecchio, ok=False,
                                        error="boom")
        dovuta = JobRun.objects.create(job="tick", started_at=vecchio, ok=True,
                                       due={"live_round": 3})
        JobRun.prune(keep_idle_days=14, keep_days=90)

        vivi = set(JobRun.objects.values_list("id", flat=True))
        self.assertNotIn(quiete.id, vivi)     # mille tick al giorno di nulla
        self.assertIn(fallita.id, vivi)       # una prova
        self.assertIn(dovuta.id, vivi)        # dovuta: interessa comunque


class ControlliDiSalute(TestCase):
    """I controlli deterministici. Nessuno di loro chiede niente a un modello."""

    def _run(self, job, *, minutes_ago, ok=True, due=None, did=None, error=""):
        return JobRun.objects.create(
            job=job, started_at=NOW - timedelta(minutes=minutes_ago),
            finished_at=NOW - timedelta(minutes=minutes_ago), ok=ok,
            due=due or {}, did=did or {}, error=error)

    def _codes(self, level=None, **kwargs):
        rep = health.report(now=NOW, skip_shape=True, **kwargs)
        return {c.code for c in rep.checks if level is None or c.level == level}

    def test_un_job_spento_non_fa_rumore(self):
        # Nessun timer acceso e nessuna riga: il rapporto lo dice e non allarma.
        # È la postura in cui sta il server oggi (installato, spento).
        rep = health.report(now=NOW, skip_shape=True)
        self.assertEqual(rep.verdict, "ok")

    def test_un_job_acceso_e_muto_e_un_allarme(self):
        self._run("tick", minutes_ago=90)
        with self._systemd({"vfoot-tick.timer"}):
            self.assertIn("tick:silent", self._codes("alarm"))

    def test_un_job_acceso_e_puntuale_tace(self):
        self._run("tick", minutes_ago=2)
        with self._systemd({"vfoot-tick.timer"}):
            self.assertNotIn("tick:silent", self._codes())

    def test_un_contatore_che_crolla_e_un_allarme_anche_se_il_job_riesce(self):
        """Il guasto silenzioso, in forma pura: venti club scrapati con successo,
        e i giocatori passano da 500 a 40. Exit code 0 in tutte e sei le passate."""
        for i in range(6):
            self._run("poll_transfermarkt", minutes_ago=(i + 1) * 720,
                      did={"clubs_scraped": 20, "players": 500})
        self._run("poll_transfermarkt", minutes_ago=10,
                  did={"clubs_scraped": 20, "players": 40})

        codes = self._codes("alarm")
        self.assertIn("poll_transfermarkt:players-collapsed", codes)
        self.assertNotIn("poll_transfermarkt:clubs_scraped-collapsed", codes)

    def test_senza_storia_non_si_grida_al_crollo(self):
        # Due passate non fanno una mediana: al primo giro sul server ogni numero
        # sarebbe "anomalo" rispetto al nulla che lo precede.
        self._run("poll_transfermarkt", minutes_ago=800, did={"players": 500})
        self._run("poll_transfermarkt", minutes_ago=10, did={"players": 40})
        self.assertEqual(self._codes("alarm"), set())

    def test_il_tick_cieco(self):
        """Aveva partite da leggere e non ne ha importata nessuna, cinque volte di
        fila: l'egress è a terra e le partite in corso sono ferme."""
        for i in range(health.BLIND_STREAK):
            self._run("tick", minutes_ago=i + 1, due={"live_round": 2},
                      did={"egress_blocked": 2})
        self.assertIn("tick:blind", self._codes("alarm"))

    def test_un_solo_tick_bloccato_non_e_un_allarme(self):
        # Un IP di uscita che rimbalza è la normalità: si riprova fra un minuto.
        self._run("tick", minutes_ago=1, due={"live_round": 2},
                  did={"egress_blocked": 2})
        for i in range(health.BLIND_STREAK):
            self._run("tick", minutes_ago=i + 2, due={"live_round": 2},
                      did={"imported": 2})
        self.assertNotIn("tick:blind", self._codes())

    def test_il_calendario_che_chiede_turni_e_torna_a_mani_vuote(self):
        """Cinque turni chiesti, zero partite lette, comando riuscito. Nel journal
        è «0 created, 0 updated», cioè identico a una settimana senza notizie."""
        self._run("sync_calendar", minutes_ago=30,
                  due={"rounds": 5}, did={"fixtures": 0})
        self.assertIn("calendar:empty", self._codes("alarm"))

    def test_il_calendario_che_legge_quello_che_deve_tace(self):
        # Il numero di partite oscilla per costruzione (--auto-rounds chiede da uno
        # a cinque turni): il confronto è con i turni chiesti, non con la storia.
        self._run("sync_calendar", minutes_ago=30,
                  due={"rounds": 5}, did={"fixtures": 50})
        self.assertEqual(self._codes("alarm"), set())
        self._run("sync_calendar", minutes_ago=10,
                  due={"rounds": 1}, did={"fixtures": 10})
        self.assertEqual(self._codes("alarm"), set())

    def test_una_partita_finita_e_mai_promossa(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            external_source="sofascore", external_id="95836", num_rounds=38)
        home = TeamSeason.objects.create(
            competition_season=cs, team=Team.objects.create(name="Torino"))
        away = TeamSeason.objects.create(
            competition_season=cs, team=Team.objects.create(name="Inter"))
        Match.objects.create(
            external_source="sofascore", external_id="1", competition_season=cs,
            home_team=home, away_team=away, matchday=3,
            kickoff=NOW - timedelta(hours=6), status=Match.STATUS_FINISHED,
            data_ready=False)

        self.assertIn("matches:stuck", self._codes("alarm"))

    def _pending_consultation(self, *, hours_ago):
        """Una consultazione aperta e mai spedita, vecchia di N ore."""
        from django.contrib.auth.models import User
        from vfoot.models import FantasyLeague, LeagueDecision
        owner = User.objects.create_user(f"boss{hours_ago}", password="x")
        league = FantasyLeague.objects.create(name="L", owner=owner, mode="classic")
        return LeagueDecision.objects.create(
            league=league, title="Ruolo di X", options=[], consultation_open=True,
            created_at=NOW - timedelta(hours=hours_ago),
            consult_opened_at=NOW - timedelta(hours=hours_ago))

    def test_una_consultazione_ferma_in_coda_e_un_allarme(self):
        """Il caso che il controllo dei timer NON prende. Un'unità mai installata
        non è fra quelle abilitate, quindi la regola «non allarmo su ciò che è
        spento» la lascia passare in silenzio — ma il digest è l'unica strada per
        cui una consultazione raggiunge qualcuno, e quella coda che si allunga è
        il solo sintomo che esista."""
        self._pending_consultation(hours_ago=9)
        self.assertIn("digest:stuck", self._codes("alarm"))

    def test_una_consultazione_appena_aperta_non_allarma(self):
        """La finestra deve poter fare il suo lavoro senza essere un guasto."""
        self._pending_consultation(hours_ago=0)
        self.assertNotIn("digest:stuck", self._codes())

    # -- utilità ----------------------------------------------------------

    def _systemd(self, units):
        from unittest.mock import patch
        return patch.object(health, "enabled_units", return_value=units)


class CanarinoFormaDati(TestCase):
    """La forma del JSON che arriva, misurata contro quella su cui è costruito
    il modello. Le soglie sono tarate su 600 partite vere: vedi il docstring di
    services/shape_canary."""

    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp(prefix="canary_")

    def _lineups(self, event_id, *, keys=None, players=22, broken=0):
        from pathlib import Path
        keys = shape_canary.CORE_STAT_KEYS if keys is None else keys
        def entry(i, ok=True):
            return {"player": ({"id": 1000 + i, "name": f"G{i}"} if ok
                               else {"id": None, "name": ""}),
                    "position": "M", "substitute": False,
                    "statistics": {k: 1 for k in keys}}
        rows = [entry(i) for i in range(players)] + \
               [entry(900 + i, ok=False) for i in range(broken)]
        half = len(rows) // 2
        path = Path(self.dir) / f"api_v1_event_{event_id}_lineups.json"
        path.write_text(json.dumps({"home": {"players": rows[:half]},
                                    "away": {"players": rows[half:]}}))
        return path

    def _run(self, **kw):
        return shape_canary.run(cache_dir=self.dir, now=NOW, **kw)

    def test_le_colonne_sorvegliate_sono_davvero_lette_dal_modello(self):
        """Rete di sicurezza al contrario: se qualcuno toglie una colonna dalla
        mappa dell'adapter senza toccare il canarino, il canarino resterebbe a
        sorvegliare una cosa che non ci serve più — e tacerebbe su quella nuova."""
        self.assertTrue(
            shape_canary.CORE_STAT_KEYS <= shape_canary.MAPPED_STAT_KEYS)

    def test_forma_intatta(self):
        for eid in (1, 2, 3):
            self._lineups(eid)
        rep = self._run()
        self.assertTrue(rep.ok)
        self.assertEqual(rep.checked, 3)

    def test_una_colonna_sparita_viene_nominata(self):
        for eid in (1, 2):
            self._lineups(eid, keys=shape_canary.CORE_STAT_KEYS - {"duelWon"})
        rep = self._run()
        self.assertFalse(rep.ok)
        alarm = rep.alarms[0]
        self.assertEqual(alarm.code, "stat-keys-lost")
        self.assertIn("duelWon", alarm.message)

    def test_una_colonna_rinominata_mostra_il_nome_nuovo(self):
        """La diagnosi, non solo l'allarme: sparisce `duelWon`, compare
        `duelsWon`, e le due righe una sotto l'altra dicono cosa fare."""
        keys = (shape_canary.CORE_STAT_KEYS - {"duelWon"}) | {"duelsWon"}
        for eid in (1, 2):
            self._lineups(eid, keys=keys)
        rep = self._run()
        self.assertIn("duelsWon", rep.stats.get("new_keys", []))
        self.assertIn("duelsWon", " ".join(f.message for f in rep.findings))

    def test_una_sola_partita_non_basta_per_giudicare(self):
        # Quattro partite su 600 mancano di una colonna per puro caso. Con una
        # sola in cache il canarino si astiene invece di sbagliare.
        self._lineups(1, keys=shape_canary.CORE_STAT_KEYS - {"penaltySave"})
        rep = self._run()
        self.assertTrue(rep.ok)
        self.assertEqual([f.code for f in rep.findings], ["no-data"])

    def test_un_giocatore_senza_identita_e_un_allarme(self):
        for eid in (1, 2):
            self._lineups(eid, broken=2)
        rep = self._run()
        self.assertIn("player-identity", [a.code for a in rep.alarms])

    def test_le_colonne_rare_non_fanno_rumore(self):
        """`penaltySave` c'è nel 6% delle partite: la sua assenza è calcio, non un
        guasto. È la ragione per cui CORE_STAT_KEYS non è tutta la mappa."""
        self.assertNotIn("penaltySave", shape_canary.CORE_STAT_KEYS)
        self.assertIn("penaltySave", shape_canary.MAPPED_STAT_KEYS)
        for eid in (1, 2):
            self._lineups(eid)
        self.assertTrue(self._run().ok)


class DoppioTesseramento(TestCase):
    """Lo stesso giocatore in due club insieme: si segnala, non si corregge.

    E' un errore del fornitore (in finestra di mercato Transfermarkt tiene un
    giocatore in due rose per qualche ora) e di norma si ripara da solo — ma
    nessun'altra parte del sistema se ne accorgerebbe. La risoluzione del club
    corrente prende il primo tesseramento aperto che trova, senza ordinamento:
    finche' dura, il giocatore viene valutato sulla partita di una delle due
    squadre in modo non deterministico, e senza un errore a schermo.

    Sta a `warn` e non ad `alarm` di proposito: non c'e' niente da fare a mano, e
    il rosso speso per una cosa che si ripara da se' e' rosso che poi non viene
    piu' guardato. Il giallo basta — con --mail la posta parte lo stesso.
    """

    def setUp(self):
        from realdata.models import Player, PlayerTeamStint
        comp = Competition.objects.create(name="Serie A")
        seas = Season.objects.create(code="2026-2027")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=seas, name="Serie A 2026-2027")
        self.inter = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Inter"))
        self.milan = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Milan"))
        self.p = Player.objects.create(full_name="Marco Rossi")
        self._Stint = PlayerTeamStint

    def _stint(self, ts, start, end=None):
        self._Stint.objects.create(player=self.p, team_season=ts,
                                   start_date=start, end_date=end)

    def test_due_club_insieme_sono_un_avviso(self):
        self._stint(self.inter, datetime(2026, 8, 1).date())
        self._stint(self.milan, datetime(2026, 8, 10).date())
        rep = health.report(now=NOW, skip_shape=True)
        self.assertIn("roster:overlap", {c.code for c in rep.warns})
        self.assertEqual(rep.verdict, "warn")

    def test_un_trasferimento_regolare_non_dice_niente(self):
        """Il confine che tiene in vita il controllo: se gridasse a ogni
        trasferimento verrebbe spento entro una settimana."""
        self._stint(self.inter, datetime(2026, 8, 1).date(),
                    end=datetime(2026, 8, 10).date())
        self._stint(self.milan, datetime(2026, 8, 10).date())
        rep = health.report(now=NOW, skip_shape=True)
        self.assertEqual(rep.verdict, "ok")
