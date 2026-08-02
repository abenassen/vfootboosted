"""Writing a match's zone features twice, which is what a live import does.

Delete-and-reinsert was right while a match was imported once, after full time.
Imported every ten minutes for two hours it rebuilds ~4.800 rows and their indexes
to change a few hundred numbers — so the write is now an upsert on the natural key,
and only the rows whose value actually moved are sent.

Three properties, one test each: the identity of a row survives a re-import, an
unchanged value is not written, and a key that stops arriving is removed.
"""
from __future__ import annotations

from django.test import TestCase

from realdata.models import (
    Competition, CompetitionSeason, Match, Player, PlayerZoneFeature,
    PROVIDER_SOFASCORE, Season, SIDE_HOME, Team, TeamSeason,
)
from realdata.services.sofascore_adapter import _upsert_zone_features

ATTNAMES = ("player_id", "team_side", "zone_key", "feature_key")
UNIQUE = ("player", "team_side", "zone_key", "feature_key")


class ZoneFeatureUpsertTests(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"))
        ts = TeamSeason.objects.create(
            competition_season=cs, team=Team.objects.create(name="Napoli"))
        self.match = Match.objects.create(
            competition_season=cs, home_team=ts, away_team=ts,
            external_source=PROVIDER_SOFASCORE, external_id="1")
        self.player = Player.objects.create(full_name="Un Giocatore")

    def _write(self, values: dict) -> tuple[int, int]:
        """values: {(zone, feature): number} -> (rows written, rows the match has)."""
        return _upsert_zone_features(
            PlayerZoneFeature, self.match, attnames=ATTNAMES, unique_names=UNIQUE,
            rows={(self.player.id, SIDE_HOME, zone, key): (value, "heatmap_points")
                  for (zone, key), value in values.items()})

    def _rows(self) -> dict:
        return {(z, k): v for z, k, v in
                PlayerZoneFeature.objects.filter(match=self.match)
                .values_list("zone_key", "feature_key", "value")}

    def test_a_second_import_updates_the_same_row(self):
        self._write({("Z_1_1", "touches"): 10.0})
        row_id = PlayerZoneFeature.objects.get(match=self.match).id
        written, total = self._write({("Z_1_1", "touches"): 25.0})
        self.assertEqual((written, total), (1, 1))
        self.assertEqual(self._rows(), {("Z_1_1", "touches"): 25.0})
        # Same row, not a delete and a new one: the identity is what the upsert buys.
        self.assertEqual(PlayerZoneFeature.objects.get(match=self.match).id, row_id)

    def test_unchanged_values_are_not_written(self):
        self._write({("Z_1_1", "touches"): 10.0, ("Z_2_1", "touches"): 4.0})
        written, total = self._write({("Z_1_1", "touches"): 12.0,
                                      ("Z_2_1", "touches"): 4.0})
        # He has left the pitch as far as Z_2_1 is concerned; only one row moved.
        self.assertEqual((written, total), (1, 2))
        self.assertEqual(self._rows(),
                         {("Z_1_1", "touches"): 12.0, ("Z_2_1", "touches"): 4.0})

    def test_a_key_that_stops_arriving_is_removed(self):
        """An upsert never deletes by itself. During a live match values only grow so
        this should never fire — but a provider correction that reassigns a shot
        would otherwise leave the old row behind for ever, and in a long-format table
        a stale row is indistinguishable from a real one."""
        self._write({("Z_1_1", "shots"): 1.0, ("Z_4_2", "shots"): 1.0})
        self._write({("Z_1_1", "shots"): 2.0})
        self.assertEqual(self._rows(), {("Z_1_1", "shots"): 2.0})
