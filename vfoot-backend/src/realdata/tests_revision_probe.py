"""The revision probe: a measurement of when SofaScore stops revising a match.

What must hold is mostly what it must NOT do: import, touch the application's cache,
or run when it was not switched on.
"""
from __future__ import annotations

import io
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import override_settings

from realdata.management.commands.analyze_revision_probe import distance
from realdata.models import JobRun, Match, MatchShot
from realdata.services import egress_client, live_ingest, revision_probe
from realdata.tests_live_pipeline import _LateBase, _iso


class _ProbeBase(_LateBase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ov = override_settings(VFOOT_REVISION_PROBE=True,
                               VFOOT_REVISION_PROBE_DIR=self.tmp.name)
        ov.enable()
        self.addCleanup(ov.disable)

    def _written(self):
        f = Path(self.tmp.name) / "readings.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []


class PlanTests(_ProbeBase):
    def test_e_dovuta_nella_finestra_dell_offset(self):
        m = self._finished(hours_ago=4.5)
        self.assertEqual(revision_probe.plan(self.NOW, [m], set()), [(m, "4h")])

    def test_non_e_dovuta_prima(self):
        m = self._finished(hours_ago=0.5)
        self.assertEqual(revision_probe.plan(self.NOW, [m], set()), [])

    def test_una_lettura_fatta_non_si_ripete(self):
        m = self._finished(hours_ago=4.5)
        self.assertEqual(revision_probe.plan(self.NOW, [m], {("111", "4h")}), [])

    def test_un_tick_fermo_non_riempie_il_file_di_letture_false(self):
        """Una lettura a 30h non puo' passare per quella delle 6h."""
        m = self._finished(hours_ago=30)
        self.assertEqual([lab for _m, lab in revision_probe.plan(self.NOW, [m], set())], [])

    def test_la_piu_in_ritardo_va_per_prima(self):
        a = self._finished(hours_ago=24.5)
        b = self._match(ext="222", status=Match.STATUS_FINISHED, data_ready=True,
                        finished_at=self.NOW - timedelta(hours=5.5))
        # scaduta prima = dovuta da piu' tempo: il 4h di b (1,5h fa) batte il 24h di a (0,5h fa)
        self.assertEqual([lab for _m, lab in revision_probe.plan(self.NOW, [a, b], set())],
                         ["4h", "24h"])


class TakeTests(_ProbeBase):
    def _take(self, *, ok=True, shots=None):
        m = self._finished(hours_ago=4.5)
        digest = {"shots": shots or {"1": [0.1, 0.2]}, "players": {}}
        with mock.patch.object(egress_client, "run_egress", return_value=ok) as run, \
             mock.patch.object(revision_probe, "digest", return_value=digest):
            return m, revision_probe.take(m, "4h", self.NOW), run

    def test_scrive_una_riga_e_non_importa_niente(self):
        before = MatchShot.objects.count()
        m, ok, _run = self._take()
        self.assertTrue(ok)
        (row,) = self._written()
        self.assertEqual((row["match"], row["offset"], row["elapsed_min"]), ("111", "4h", 270))
        self.assertEqual(MatchShot.objects.count(), before)
        m.refresh_from_db()
        self.assertEqual(m.data_imported_at, m.finished_at + timedelta(hours=1))

    def test_va_in_una_cartella_sua_mai_in_quella_dell_app(self):
        _m, _ok, run = self._take()
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("--cache-dir") + 1], str(Path(self.tmp.name) / "cache"))
        self.assertEqual(args[args.index("--kind") + 1], "live")

    def test_un_egress_bloccato_non_scrive_e_si_riprova(self):
        _m, ok, _run = self._take(ok=False)
        self.assertFalse(ok)
        self.assertEqual(self._written(), [])


class TickTests(_ProbeBase):
    def test_spenta_di_serie(self):
        self._finished(hours_ago=4.5)
        with override_settings(VFOOT_REVISION_PROBE=False), \
             mock.patch.object(revision_probe, "take") as take:
            call_command("tick", "--now", _iso(self.NOW))
        take.assert_not_called()

    def test_accesa_fa_una_lettura_per_tick(self):
        self._finished(hours_ago=4.5)
        self._match(ext="222", status=Match.STATUS_FINISHED, data_ready=True,
                    finished_at=self.NOW - timedelta(hours=4.2))
        with mock.patch.object(revision_probe, "take", return_value=True) as take:
            call_command("tick", "--now", _iso(self.NOW))
        take.assert_called_once()
        self.assertEqual(JobRun.objects.latest("id").did.get("probe_readings"), 1)

    def test_una_partita_in_corso_ha_la_precedenza(self):
        self._finished(hours_ago=4.5)
        self._match(ext="333", status=Match.STATUS_LIVE,
                    kickoff=self.NOW - timedelta(minutes=30))
        with mock.patch.object(revision_probe, "take") as take, \
             mock.patch.object(live_ingest, "live_round", return_value=True):
            call_command("tick", "--now", _iso(self.NOW))
        take.assert_not_called()

    def test_il_controllo_tardivo_viene_prima(self):
        self._finished(hours_ago=13)
        with mock.patch.object(live_ingest, "late_check", return_value=(True, [])), \
             mock.patch.object(revision_probe, "take") as take:
            call_command("tick", "--now", _iso(self.NOW))
        take.assert_not_called()

    def test_dry_run_non_legge(self):
        self._finished(hours_ago=4.5)
        with mock.patch.object(revision_probe, "take") as take:
            call_command("tick", "--now", _iso(self.NOW), "--dry-run")
        take.assert_not_called()


class AnalyzeTests(_ProbeBase):
    def _row(self, match, offset, shots, gp=None):
        players = {"9": {"goalsPrevented": gp}} if gp is not None else {}
        return {"match": match, "offset": offset, "shots": shots, "players": players}

    def test_distanza_dal_riferimento(self):
        ref = self._row("1", "48h", {"a": [0.2, 0.3], "b": [0.1, 0.0]}, gp=-0.003)
        r = self._row("1", "1h", {"a": [0.1, 0.2], "b": [0.1, 0.0], "c": [0.5, 0.5]}, gp=-0.031)
        d, changed, gp = distance(ref, r)
        self.assertAlmostEqual(d, 0.2)      # solo i tiri presenti in entrambi
        self.assertEqual(changed, 1)
        self.assertAlmostEqual(gp, 0.028)

    def test_trova_il_primo_offset_gia_assestato(self):
        rows = []
        for m in ("1", "2", "3"):
            ref = {"a": [0.30, 0.30]}
            rows += [self._row(m, "1h", {"a": [0.10, 0.10]}),
                     self._row(m, "4h", {"a": [0.30, 0.30]}),
                     self._row(m, "48h", ref)]
        f = Path(self.tmp.name) / "r.jsonl"
        f.write_text("\n".join(json.dumps(r) for r in rows))
        out = io.StringIO()
        call_command("analyze_revision_probe", "--file", str(f), stdout=out)
        self.assertIn("+4h", out.getvalue().splitlines()[-1])
