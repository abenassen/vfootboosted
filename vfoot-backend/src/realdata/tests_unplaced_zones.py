"""What happens to a player's numbers when nobody has measured WHERE he was.

The light round of a live match does not pull heatmaps — a request per player is
the whole reason the heavy pass is rare. Until now the adapter answered that by
writing nothing at all for such a player (``sofascore_adapter``: ``if total == 0:
continue``), so the voto puro had nothing to sum and a live vote was impossible
without the expensive pass.

The totals do not need the heatmap: ``classic_rating._features`` sums each feature
over ALL zones, and the sum of a distributed stat is the stat. What DOES need it is
the positional half — the defensive exposure, and Aura's zone duel. So the totals
are written anyway, and the distinction is carried by the row itself:

* placed rows sit in a grid cell, measured or carried over from the last heavy pass;
* unplaced rows sit in ``ZONE_UNPLACED``, which is deliberately NOT a cell, and
  declare it in ``source_method``. Whoever reads a zone as a POSITION must skip
  them; whoever sums over zones must not.
"""
from __future__ import annotations

from django.test import TestCase

from realdata.models import (
    Match, MatchAppearance, PlayerZoneFeature, PROVIDER_SOFASCORE, SIDE_HOME,
)
from realdata.services.sofascore_adapter import (
    METHOD_UNPLACED, ZONE_UNPLACED, _ingest_match,
)
from realdata.tests_import_by_id import (
    MATCH_ID, _Recording, _event, _payloads,
)


class _Fixture(TestCase):
    """One match imported through the real adapter, heavy or light."""

    def _import(self, *, with_heatmaps: bool, payloads=None, sub=""):
        import tempfile

        from realdata.services.sofascore_adapter import (
            _get_or_create_competition_season,
        )

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        client = _Recording(tmp.name + sub, payloads or _payloads())
        return _ingest_match(
            scraper=client, event=_event(),
            competition_season=_get_or_create_competition_season("2026-2027"),
            team_cache={}, player_cache={}, zone_cols=5, zone_rows=4,
            flip_away=False, feature_totals={}, stat_keys_seen=set(),
            diagnostics={}, log=lambda _m: None, with_heatmaps=with_heatmaps)

    def _match(self) -> Match:
        return Match.objects.get(external_source=PROVIDER_SOFASCORE,
                                 external_id=str(MATCH_ID))

    def _rows(self, feature="touches"):
        """{(player, zone, method): value}. Keyed by player too, or three players
        in the same zone would collapse into one row and the sums would lie."""
        return {(p, z, m): v for p, z, m, v in
                PlayerZoneFeature.objects.filter(match=self._match(),
                                                 feature_key=feature)
                .values_list("player_id", "zone_key", "source_method", "value")}


class LightImportTests(_Fixture):
    def test_a_light_import_writes_no_heatmap_request_at_all(self):
        """Not "downloads them and ignores them": the request is the cost."""
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        client = _Recording(tmp.name, _payloads())
        from realdata.services.sofascore_adapter import (
            _get_or_create_competition_season,
        )
        _ingest_match(
            scraper=client, event=_event(),
            competition_season=_get_or_create_competition_season("2026-2027"),
            team_cache={}, player_cache={}, zone_cols=5, zone_rows=4,
            flip_away=False, feature_totals={}, stat_keys_seen=set(),
            diagnostics={}, log=lambda _m: None, with_heatmaps=False)
        self.assertEqual([p for p in client.requested if "heatmap" in p], [])

    def test_the_totals_are_written_even_with_no_heatmap(self):
        """The regression this whole step exists to remove: without it a light
        import produces no row, and the voto puro finds nothing to sum."""
        self._import(with_heatmaps=False)
        rows = self._rows()
        self.assertTrue(rows)
        self.assertEqual({z for _p, z, _m in rows}, {ZONE_UNPLACED})
        self.assertEqual({m for _p, _z, m in rows}, {METHOD_UNPLACED})

    def test_the_totals_are_the_same_number_the_heavy_pass_would_write(self):
        """Distributing over zones and summing back is the identity; that is why
        the light vote is a real vote and not an approximation of one."""
        self._import(with_heatmaps=True)
        pesante = sum(self._rows().values())
        PlayerZoneFeature.objects.all().delete()
        self._import(with_heatmaps=False)
        self.assertAlmostEqual(sum(self._rows().values()), pesante, places=6)

    def test_the_unplaced_zone_is_not_a_cell_of_the_grid(self):
        """Belt and braces: the method DECLARES the provenance, and the key makes a
        reader that forgot to filter break instead of quietly placing a player in
        the corner of the pitch."""
        self.assertNotRegex(ZONE_UNPLACED, r"^Z_\d+_\d+$")


class CarriedPresenceTests(_Fixture):
    """A light round after a heavy one must not throw the positions away.

    ``_upsert_zone_features`` removes whatever stopped arriving — correct, and the
    reason the heavy pass cleans up after a light one. Read the other way round it
    is a trap: a light pass that wrote everything unplaced would delete the zones
    the heavy pass had just measured, so the defensive exposure would come and go
    every k rounds and every defender's vote would saw up and down with it.
    """

    def test_a_light_round_keeps_the_positions_the_heavy_one_measured(self):
        self._import(with_heatmaps=True)
        misurate = {(p, z) for p, z, _m in self._rows()}
        self._import(with_heatmaps=False, sub="b")
        self.assertEqual({(p, z) for p, z, _m in self._rows()}, misurate)
        self.assertNotIn(ZONE_UNPLACED, {z for _p, z, _m in self._rows()})

    def test_the_carried_totals_still_add_up_to_the_new_ones(self):
        """Carried is the SHAPE, not the amount: the values are this minute's."""
        self._import(with_heatmaps=True)
        self._import(with_heatmaps=False, sub="b")
        rows = self._rows()
        self.assertAlmostEqual(sum(rows.values()), 40.0 * 3, places=6)

    def test_a_player_with_no_measured_past_still_gets_his_totals(self):
        """The substitute who came on after the last heavy pass. He is unplaced —
        and unplaced is exactly what he is."""
        self._import(with_heatmaps=False)
        self.assertEqual({z for _p, z, _m in self._rows()}, {ZONE_UNPLACED})


class HeavyPassOverwritesTests(_Fixture):
    def test_the_heavy_pass_clears_the_unplaced_rows(self):
        """The second half of the doc's open question, on the adapter rather than
        on the upsert helper: after one complete pass nothing unplaced is left."""
        self._import(with_heatmaps=False)
        self.assertTrue(PlayerZoneFeature.objects
                        .filter(match=self._match(), zone_key=ZONE_UNPLACED).exists())
        self._import(with_heatmaps=True, sub="b")
        self.assertFalse(PlayerZoneFeature.objects
                         .filter(match=self._match(),
                                 zone_key=ZONE_UNPLACED).exists())
        self.assertFalse(PlayerZoneFeature.objects
                         .filter(match=self._match(),
                                 source_method=METHOD_UNPLACED).exists())

    def test_the_appearances_are_written_either_way(self):
        result = self._import(with_heatmaps=False)
        self.assertEqual(result.appearances, 3)
        self.assertEqual(MatchAppearance.objects.filter(
            match=self._match()).count(), 3)


class PositionalReadersTests(_Fixture):
    """Whoever reads a zone as a POSITION must skip the unplaced rows. Verified on
    the two that matter live: the defensive exposure and Aura's zone duel."""

    def test_the_defensive_exposure_ignores_them(self):
        from vfoot.services.classic_rating import _zone_presence

        self._import(with_heatmaps=False)
        self.assertEqual(_zone_presence([self._match().id]), {})

    def test_aura_ignores_them(self):
        from vfoot.services import realdata_scoring

        self._import(with_heatmaps=False)
        match = self._match()
        pid = MatchAppearance.objects.filter(match=match).first().player_id
        self.assertIsNone(realdata_scoring.build_player_real_zone_profile(
            match=match, player_id=pid))

    def test_aura_reads_them_once_the_heavy_pass_has_placed_him(self):
        """The mirror of the test above: skipping unplaced rows must not mean
        skipping the player for ever."""
        from vfoot.services import realdata_scoring

        self._import(with_heatmaps=True)
        match = self._match()
        pid = MatchAppearance.objects.filter(match=match, side=SIDE_HOME).first().player_id
        self.assertIsNotNone(realdata_scoring.build_player_real_zone_profile(
            match=match, player_id=pid))
