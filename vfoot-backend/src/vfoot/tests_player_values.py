"""Tests for the progressive player VALUE blend (previous season -> current form)."""
from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase

from vfoot.services import player_ratings as pr


class _CS:
    """Minimal CompetitionSeason stand-in (only .id is used by the blend)."""

    def __init__(self, cs_id):
        self.id = cs_id


CURRENT, PREVIOUS = _CS(3), _CS(2)


class PlayerValueBlendTests(SimpleTestCase):
    def _values(self, current: dict, previous: dict, has_previous: bool = True,
                market: dict | None = None):
        def fake_ratings(cs_id):
            return current if cs_id == CURRENT.id else previous

        with patch.object(pr, "season_player_ratings", side_effect=fake_ratings), \
                patch.object(pr, "previous_season_with_data",
                             return_value=PREVIOUS if has_previous else None):
            values, prev_cs, _fit = pr.player_values(CURRENT, market or {})
        return values, prev_cs

    def test_preseason_uses_previous_season(self):
        # no current-season data at all (championship not started)
        values, _ = self._values({}, {7: {"avg": 6.8, "n": 30}})
        # (30*6.8 + 5*6.0)/35 — lightly shrunk, a full season is trusted
        self.assertAlmostEqual(values[7]["value"], 6.69, places=2)
        self.assertEqual(values[7]["basis"], pr.VALUE_PREVIOUS)
        self.assertEqual(values[7]["n_cur"], 0)

    def test_newcomer_without_history_has_no_value(self):
        # a player in neither season simply isn't in the map -> the view emits null
        values, _ = self._values({}, {7: {"avg": 6.8, "n": 30}})
        self.assertNotIn(99, values)

    def test_newcomer_with_only_current_data_uses_current(self):
        values, _ = self._values({99: {"avg": 7.2, "n": 3}}, {})
        # only 3 games -> pulled well toward 6: (3*7.2 + 5*6.0)/8
        self.assertAlmostEqual(values[99]["value"], 6.45, places=2)
        self.assertEqual(values[99]["basis"], pr.VALUE_CURRENT)

    def test_blend_is_half_and_half_at_shrinkage_point(self):
        n = pr.SHRINKAGE_APPEARANCES  # weight = n/(n+K) = 0.5
        values, _ = self._values({7: {"avg": 8.0, "n": n}}, {7: {"avg": 6.0, "n": 30}})
        self.assertEqual(values[7]["basis"], pr.VALUE_MIXED)
        # cur (5 games) shrinks 8.0->7.0, prev (30) stays 6.0, blended half/half
        self.assertAlmostEqual(values[7]["value"], 6.5, places=2)

    def test_current_form_dominates_late_season(self):
        values, _ = self._values({7: {"avg": 8.0, "n": 45}}, {7: {"avg": 6.0, "n": 30}})
        # cur shrinks 8.0->7.8 (45 games), prev 6.0; w=0.9 -> 0.9*7.8 + 0.1*6.0
        self.assertAlmostEqual(values[7]["value"], 7.62, places=2)

    def test_value_moves_monotonically_toward_current_form(self):
        prev = {7: {"avg": 6.0, "n": 30}}
        seen = [self._values({7: {"avg": 8.0, "n": n}}, prev)[0][7]["value"]
                for n in (1, 5, 15, 30)]
        self.assertEqual(seen, sorted(seen))       # never goes backwards
        self.assertLess(seen[0], 7.0)              # early: closer to last season
        self.assertGreater(seen[-1], 7.4)          # late: closer to current form

    def test_no_previous_season_falls_back_to_current_only(self):
        values, prev_cs = self._values({7: {"avg": 7.1, "n": 10}}, {},
                                       has_previous=False)
        self.assertIsNone(prev_cs)
        self.assertEqual(values[7]["basis"], pr.VALUE_CURRENT)
        self.assertAlmostEqual(values[7]["value"], 6.73, places=2)  # 10 games, shrunk


class MarketEstimateTests(SimpleTestCase):
    """The market->voto estimate that makes the listone a single ranked list."""

    def _run(self, current, previous, market):
        def fake_ratings(cs_id):
            return current if cs_id == CURRENT.id else previous

        with patch.object(pr, "season_player_ratings", side_effect=fake_ratings), \
                patch.object(pr, "previous_season_with_data", return_value=PREVIOUS):
            return pr.player_values(CURRENT, market)

    def _calibration_set(self, n=60):
        """n players whose voto rises with market value -> a fittable relation."""
        previous, market = {}, {}
        for i in range(n):
            mv = 1_000_000 * (i + 1)
            previous[i] = {"avg": 5.0 + i * 0.02, "n": 20}
            market[i] = mv
        return previous, market

    def test_estimates_a_value_for_a_player_with_no_history(self):
        previous, market = self._calibration_set()
        market[999] = 30_000_000  # newcomer: market value only
        values, _prev, fit = self._run({}, previous, market)

        self.assertIsNotNone(fit)
        row = values[999]
        self.assertIsNone(row["value"])                       # nothing measured
        self.assertIsNotNone(row["estimated_value"])          # but still rankable
        self.assertEqual(row["basis"], pr.VALUE_ESTIMATED)

    def test_estimate_is_monotonic_in_market_value(self):
        previous, market = self._calibration_set()
        market[901], market[902] = 5_000_000, 50_000_000
        values, _p, _f = self._run({}, previous, market)
        self.assertLess(values[901]["estimated_value"],
                        values[902]["estimated_value"])

    def test_estimate_stays_inside_the_central_band(self):
        previous, market = self._calibration_set()
        market[903] = 500_000_000  # absurd valuation must not out-rank real form
        values, _p, _f = self._run({}, previous, market)
        self.assertLessEqual(values[903]["estimated_value"], pr.VOTE_MAX_EST)

    def test_measured_players_keep_their_own_value(self):
        previous, market = self._calibration_set()
        values, _p, _f = self._run({}, previous, market)
        self.assertEqual(values[0]["estimated_value"], values[0]["value"])
        self.assertNotEqual(values[0]["basis"], pr.VALUE_ESTIMATED)

    def test_no_fit_without_enough_overlap(self):
        # too few players with both signals -> no estimate is invented
        values, _p, fit = self._run({}, {1: {"avg": 6.0, "n": 10}},
                                    {1: 10_000_000, 2: 5_000_000})
        self.assertIsNone(fit)
        self.assertNotIn(2, values)


class SmallSampleShrinkageTests(SimpleTestCase):
    """One brilliant game must not top the listone."""

    def _values(self, previous):
        with patch.object(pr, "season_player_ratings",
                          side_effect=lambda cs_id: {} if cs_id == CURRENT.id else previous), \
                patch.object(pr, "previous_season_with_data", return_value=PREVIOUS):
            values, _prev, _fit = pr.player_values(CURRENT, {})
        return values

    def test_single_game_regresses_hard_toward_neutral(self):
        values = self._values({1: {"avg": 9.0, "n": 1}})
        self.assertLess(values[1]["value"], 7.0)   # 9.0 on one game is not a 9.0

    def test_full_season_average_is_barely_touched(self):
        values = self._values({1: {"avg": 7.0, "n": 35}})
        self.assertGreater(values[1]["value"], 6.85)

    def test_regular_outranks_a_one_game_wonder(self):
        values = self._values({1: {"avg": 9.5, "n": 1},     # one dazzling night
                               2: {"avg": 7.0, "n": 34}})   # a whole good season
        self.assertGreater(values[2]["value"], values[1]["value"])
