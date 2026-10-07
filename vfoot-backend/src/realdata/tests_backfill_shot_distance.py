"""Il riempimento della distanza dei tiri dalle mappe in cache: un passo di deploy,
e il suo rapporto deve dire se ha riempito TUTTO (il canale del portiere legge una
distanza mancante come 16 m, e il voto non se ne accorge)."""
from __future__ import annotations

import io
import json
import tempfile
from datetime import timedelta
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from realdata.models import (
    Competition, CompetitionSeason, Match, MatchShot, Player, Season, Team, TeamSeason,
)


class BackfillShotDistanceTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
        self.cache = self.data_dir / "historical-data" / "serie-a" / "sofascore" / "cache"
        self.cache.mkdir(parents=True)
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            external_source="sofascore", external_id="95836")
        home = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Bologna"))
        away = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Torino"))
        now = timezone.now()
        self.played = Match.objects.create(
            external_source="sofascore", external_id="777", competition_season=self.cs,
            home_team=home, away_team=away, matchday=1, kickoff=now - timedelta(days=3),
            status=Match.STATUS_FINISHED, data_ready=True)
        # In calendario e non giocata: nessuna mappa, e NON e' una mancanza.
        Match.objects.create(
            external_source="sofascore", external_id="778", competition_season=self.cs,
            home_team=away, away_team=home, matchday=2, kickoff=now + timedelta(days=4))
        p = Player.objects.create(full_name="Tiratore", short_name="Tiratore")
        for sid in ("901", "902"):
            MatchShot.objects.create(match=self.played, player=p, team_side="home",
                                     minute=10, zone_key="Z_4_2", xg=0.1, xgot=0.2,
                                     provider="sofascore", external_id=sid)
        (self.cache / "api_v1_event_777_shotmap.json").write_text(json.dumps({"shotmap": [
            {"id": 901, "timeSeconds": 600, "situation": "regular",
             "playerCoordinates": {"x": 11.0 / 1.05, "y": 50.0}},
            # Il fornitore a volte non manda le coordinate: l'unico caso legittimo.
            {"id": 902, "timeSeconds": 700, "situation": "regular"},
        ]}))

    def _run(self, **opts) -> str:
        out = io.StringIO()
        with override_settings(VFOOT_DATA_DIR=self.data_dir):
            call_command("backfill_shot_seconds", season=self.cs.id, stdout=out, **opts)
        return out.getvalue()

    def test_fills_the_distance_and_reports_what_is_left(self):
        out = self._run()
        by_id = {s.external_id: s for s in MatchShot.objects.filter(match=self.played)}
        self.assertAlmostEqual(by_id["901"].distance_m, 11.0, places=2)
        self.assertIsNone(by_id["902"].distance_m)
        self.assertEqual(by_id["901"].elapsed_seconds, 600)
        # Il rapporto: la partita non giocata non e' «mancante», e il residuo si vede.
        self.assertIn("shotmap lette: 1/1 (mancanti: 0)", out)
        self.assertIn("tiri aggiornati: 2", out)
        self.assertIn("tiri senza coordinate nella mappa: 1", out)
        self.assertIn("senza distanza dopo il passaggio: 1 su 2", out)

    def test_dry_run_touches_nothing(self):
        out = self._run(dry_run=True)
        self.assertIn("tiri sarebbero aggiornati: 2", out)
        self.assertFalse(MatchShot.objects.filter(distance_m__isnull=False).exists())

    def test_a_played_match_without_a_cached_map_is_a_missing_one(self):
        (self.cache / "api_v1_event_777_shotmap.json").unlink()
        out = self._run()
        self.assertIn("shotmap lette: 0/1 (mancanti: 1)", out)
        self.assertIn("senza distanza dopo il passaggio: 2 su 2", out)
