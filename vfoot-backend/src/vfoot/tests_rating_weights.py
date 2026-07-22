"""The voto-puro weight tables must only reference features that exist.

Why this test exists: the tables carried four keys SofaScore never reports —
``passes_into_box`` (at 0.40, the largest weight in its block),
``progressive_passes_completed``, ``progressive_carries`` and ``pressures``.
They contributed exactly zero to every vote ever computed, so nothing looked
wrong; the model simply read as if it rewarded progression and pressing while
doing nothing of the sort. A weight on a feature that is never written is
invisible in the output, which is precisely why it needs a test rather than a
review.
"""
from __future__ import annotations

from django.test import SimpleTestCase

from realdata.services.sofascore_adapter import KNOWN_FEATURE_KEYS
from vfoot.services.classic_rating import (
    GK_PER90_WEIGHTS, GK_TOTAL_WEIGHTS, PER90_WEIGHTS, TOTAL_WEIGHTS,
)


class RatingWeightsTests(SimpleTestCase):
    def test_every_weighted_feature_is_one_the_provider_supplies(self):
        supplied = set(KNOWN_FEATURE_KEYS)
        for name, table in (("TOTAL_WEIGHTS", TOTAL_WEIGHTS),
                            ("PER90_WEIGHTS", PER90_WEIGHTS),
                            ("GK_TOTAL_WEIGHTS", GK_TOTAL_WEIGHTS),
                            ("GK_PER90_WEIGHTS", GK_PER90_WEIGHTS)):
            phantom = sorted(set(table) - supplied)
            self.assertEqual(
                phantom, [],
                f"{name} pesa feature che SofaScore non fornisce: {phantom}. "
                "Un peso su una feature mai scritta vale zero e non si vede nei "
                "voti: o la si rimuove, o l'adapter deve iniziare a produrla.")

    def test_no_feature_is_weighted_twice_within_a_channel(self):
        """A key in both the totals and the per-90 block of the same channel would
        be counted twice under two different scalings — plausible-looking and
        silently wrong."""
        self.assertEqual(set(TOTAL_WEIGHTS) & set(PER90_WEIGHTS), set())
        self.assertEqual(set(GK_TOTAL_WEIGHTS) & set(GK_PER90_WEIGHTS), set())

    def test_error_features_carry_a_negative_weight(self):
        """An 'error' rewarded by a positive sign is the kind of typo that is
        impossible to spot in an aggregate index."""
        for table in (TOTAL_WEIGHTS, PER90_WEIGHTS, GK_TOTAL_WEIGHTS, GK_PER90_WEIGHTS):
            for key, w in table.items():
                if key.startswith("errors_") or key == "big_chance_missed":
                    self.assertLess(w, 0, f"{key} dovrebbe penalizzare, pesa {w}")
