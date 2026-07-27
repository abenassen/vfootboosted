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
    RESULT_MITIGATION_CAP, red_card_penalty, result_mitigation,
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
        # A small over so the ±cap isn't hit at either margin (with the stronger
        # BASE=0.40 an over of 2 saturates the cap even at gd -1).
        self.assertLess(result_mitigation(6.5, -4), result_mitigation(6.5, -1))

    def test_a_defeat_costs_a_discrete_base_beyond_the_margin(self):
        # The result base makes ANY defeat cost more than the pure per-goal term.
        self.assertLess(result_mitigation(8.0, -1),
                        result_mitigation(8.0, -1, base=0.0))

    def test_crossing_into_defeat_weighs_more_than_a_further_goal(self):
        # draw->defeat (0->1) should drop the vote more than 1->2 (base on the first).
        d01 = result_mitigation(6.5, -1) - result_mitigation(6.5, 0)
        d12 = result_mitigation(6.5, -2) - result_mitigation(6.5, -1)
        self.assertLess(d01, d12)  # both negative; the first step is the bigger drop

    def test_base_zero_reproduces_the_pure_linear_rule(self):
        self.assertAlmostEqual(result_mitigation(8.0, -2, base=0.0),
                               -max(0.0, 8.0 - 6.0) * 0.15 * 2)


class RedCardPenaltyTests(SimpleTestCase):
    def test_earlier_sending_off_costs_more(self):
        early = red_card_penalty("Foul", 10, 95)
        late = red_card_penalty("Foul", 85, 95)
        self.assertGreater(early, late)

    def test_severity_orders_dogso_below_foul_below_violent(self):
        dogso = red_card_penalty("Professional foul last man", 20, 95)
        foul = red_card_penalty("Foul", 20, 95)
        violent = red_card_penalty("Violent conduct", 20, 95)
        self.assertLess(dogso, foul)
        self.assertLess(foul, violent)

    def test_indefensible_reasons_carry_a_fixed_floor(self):
        # A violent conduct at the final whistle still costs the fixed 0.3, unlike a
        # last-second foul which fades to ~0.
        self.assertAlmostEqual(red_card_penalty("Violent conduct", 95, 95), 0.3)
        self.assertAlmostEqual(red_card_penalty("Foul", 95, 95), 0.0)

    def test_an_unknown_reason_uses_the_default_severity(self):
        self.assertAlmostEqual(red_card_penalty("Unheard of", 20, 95),
                               red_card_penalty("Foul", 20, 95))
