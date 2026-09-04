from __future__ import annotations

import numpy as np

from django.test import SimpleTestCase

from vfoot.services.goalkeeper_tuning import GoalkeeperBench, pearson


class GoalkeeperTuningTests(SimpleTestCase):
    def test_correlation_is_well_defined_only_for_a_variable_vote(self):
        self.assertAlmostEqual(pearson(np.array([1., 2., 3.]), np.array([2., 4., 6.])), 1.0)
        self.assertTrue(np.isnan(pearson(np.array([6., 6., 6.]), np.array([1., 2., 3.]))))

    def test_post_vote_flattening_uses_only_the_calibration_population(self):
        bench = GoalkeeperBench.__new__(GoalkeeperBench)
        bench.w0 = np.array([1.6, 0.3])
        base = np.array([5.5, 6.5, 6.0])
        target = np.array([6.0, 6.0, 6.0])
        minutes = np.array([90., 90., 90.])
        ref = {"mean": 0.0, "std": 1.0}
        # With the production window threshold (30), this tiny synthetic sample
        # cannot create a curve: in particular it must not silently use the test
        # observations as a post-vote correction.
        self.assertEqual(bench._flatten(base, target, minutes, ref, 1.0, 25.0, 1.0), {})

    def test_relative_distance_penalty_is_zero_at_production(self):
        bench = GoalkeeperBench.__new__(GoalkeeperBench)
        bench.w0 = np.array([1.6, 0.3])
        bench.population = np.array([[0., 0.], [1., 1.], [2., 2.]])
        bench.curve_z = np.empty((0, 2)); bench.curve_minutes = np.empty(0)
        z = np.array([[0., 0.], [1., 1.], [2., 2.]])
        minutes = np.array([90., 90., 90.])
        target = np.array([5., 6., 7.])
        self.assertEqual(bench.objective(bench.w0, z, minutes, target, 0.0, 25.0, 0.0, 0.1)[2], 0.0)
