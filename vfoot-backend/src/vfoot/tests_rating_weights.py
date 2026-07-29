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
    DEFENSIVE_VALUE_SOURCE, DERIVED_FEATURES, DERIVED_INPUTS, GK_PER90_WEIGHTS,
    GK_TOTAL_WEIGHTS, MERGED_FEATURES, PER90_WEIGHTS, SHOT_DETAIL_FEATURES,
    TOTAL_WEIGHTS, derived_features,
)


class RatingWeightsTests(SimpleTestCase):
    def test_every_weighted_feature_is_one_the_provider_supplies(self):
        # Shot-outcome detail (shots_post/blocked/...) is supplied too, but from the
        # event-level shot map (MatchShot.shot_type), not the zone features — see
        # classic_rating._merge_shot_detail. DERIVED_FEATURES are computed from
        # supplied ones rather than reported, and are covered by their own test.
        supplied = (set(KNOWN_FEATURE_KEYS) | set(SHOT_DETAIL_FEATURES)
                    | set(DERIVED_FEATURES) | set(MERGED_FEATURES))
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

    def test_derived_features_are_built_from_features_the_provider_supplies(self):
        """A derived feature escapes the check above, so its INPUTS must not: an
        input the provider never writes would make the derivation silently zero,
        which is exactly the failure this file exists to prevent."""
        supplied = set(KNOWN_FEATURE_KEYS) | set(SHOT_DETAIL_FEATURES)
        phantom = sorted(DERIVED_INPUTS - supplied)
        self.assertEqual(phantom, [],
                         f"input derivati che il provider non fornisce: {phantom}")
        # and every declared derived feature must actually be produced
        self.assertEqual(sorted(derived_features({})), sorted(DERIVED_FEATURES))

    def test_derived_inputs_are_fetched_even_when_unweighted(self):
        """xg_on_target carries no weight of its own now — it only feeds sga_post.
        If the fetch list were built from the weights alone it would never be read
        and the execution term would be silently wrong for every player."""
        from vfoot.services.classic_rating import GK_WEIGHTS, WEIGHTS
        fetched = (set(WEIGHTS) | set(GK_WEIGHTS) | DERIVED_INPUTS) - set(DERIVED_FEATURES)
        self.assertLessEqual(DERIVED_INPUTS, fetched)
        self.assertNotIn("sga_post", fetched)

    def test_the_provider_proxy_is_pinned_to_its_field_name(self):
        """defensive_value is the one feature we cannot rebuild from anything else:
        if SofaScore renames the field it silently reads as 0 for everyone. Pin the
        name so a rename breaks a test instead of the defender vote."""
        self.assertEqual(DEFENSIVE_VALUE_SOURCE, "defensiveValueNormalized")
        self.assertIn("defensive_value", MERGED_FEATURES)
        # and it must NOT be looked for among the zone features
        fetched = ((set(TOTAL_WEIGHTS) | set(PER90_WEIGHTS)) | DERIVED_INPUTS) \
            - set(DERIVED_FEATURES) - set(MERGED_FEATURES)
        self.assertNotIn("defensive_value", fetched)

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
