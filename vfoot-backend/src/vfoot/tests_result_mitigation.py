"""The result-mitigation nudge is DIVERGENCE-ONLY.

The whole point of the mechanism is that it corrects a vote only when it diverges
from the team's on-pitch fortunes — a high vote in a defeat, a low vote in a win —
and NEVER when the two already agree. An earlier symmetric additive version failed
exactly here: it further inflated a high vote in a win (De Ketelaere). These tests
pin the asymmetry so a refactor cannot quietly reintroduce that.
"""
from __future__ import annotations

from django.test import SimpleTestCase

from vfoot.services.classic_rating import (
    RESULT_MITIGATION_CAP, result_mitigation,
)


class ResultMitigationTests(SimpleTestCase):
    def test_high_vote_in_a_defeat_comes_down(self):
        self.assertLess(result_mitigation(8.0, -2), 0)

    def test_low_vote_in_a_win_goes_up(self):
        self.assertGreater(result_mitigation(4.0, 2), 0)

    def test_high_vote_in_a_win_is_left_alone(self):
        # The regression guard: an aligned high vote must NOT be inflated further.
        self.assertEqual(result_mitigation(8.5, 3), 0.0)

    def test_low_vote_in_a_defeat_is_left_alone(self):
        self.assertEqual(result_mitigation(4.0, -3), 0.0)

    def test_a_six_or_a_draw_gets_nothing(self):
        self.assertEqual(result_mitigation(6.0, -3), 0.0)   # vote already at centre
        self.assertEqual(result_mitigation(9.0, 0), 0.0)    # no net on-pitch result

    def test_it_only_ever_pulls_toward_six(self):
        # A defeat can only push a high vote down (never below 6 by construction of
        # the sign), a win only push a low vote up.
        self.assertLessEqual(8.0 + result_mitigation(8.0, -5), 8.0)
        self.assertGreaterEqual(4.0 + result_mitigation(4.0, 5), 4.0)

    def test_the_nudge_is_capped(self):
        huge = result_mitigation(10.0, -9)  # would be -5.4 uncapped
        self.assertAlmostEqual(huge, -RESULT_MITIGATION_CAP)

    def test_it_grows_with_the_margin(self):
        self.assertLess(result_mitigation(8.0, -4), result_mitigation(8.0, -1))
