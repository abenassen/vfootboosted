"""A keeper's match is judged by how much of it reached him.

The keeper channel is anchored on goals_prevented, a DIFFERENCE against expected
goals on target. Measured over one or two shots that difference is mostly noise,
and reading it at full strength is how a keeper who faced a single shot and
conceded it came out at 5.0 while every pagella left him at 6.0 — not generosity
on their part, a refusal to judge a keeper who had nothing to do.

These tests pin the two halves of the fix: the evidence count itself, and the
fact that a thin match is pulled toward the centre rather than over-read.
"""
from __future__ import annotations

from django.test import SimpleTestCase

from vfoot.services.classic_rating import (
    GK_EVIDENCE_FULL, GK_TOTAL_WEIGHTS, GK_WEIGHTS,
    _raw_vote_from_index, gk_evidence, gk_evidence_weight, index_for_role,
    vote_center_for,
)
from vfoot.services.vote_explanation import explain, role_average_terms

REFERENCE = {"POR": {"mean": 0.66, "std": 2.17, "n": 764}}
# Il centro del PORTIERE, non il 6 di tutti: l'attenuazione fa regredire verso
# il centro del RUOLO (6.15 dal 30/08/2026, v. ROLE_VOTE_CENTER), ed e' quello
# il "par" rispetto a cui una partita magra si dice temperata.
GK_CENTER = vote_center_for("POR")


class KeeperEvidenceTests(SimpleTestCase):
    # --- the count -------------------------------------------------------
    def test_evidence_is_what_he_saved_plus_what_went_in(self):
        """Shots ON TARGET faced. A save and a goal are both evidence; they are
        the two outcomes of the same event."""
        self.assertEqual(gk_evidence({"gk_saves": 3.0}, 2), 5.0)
        self.assertEqual(gk_evidence({"gk_saves": 0.0}, 1), 1.0)
        self.assertEqual(gk_evidence({}, 0), 0.0)

    def test_shots_he_never_had_to_touch_are_not_evidence(self):
        """Fifteen efforts flying over the bar still make a quiet afternoon: only
        what reached the goal says anything about the keeper."""
        wild = {"gk_saves": 1.0, "shots_off": 14.0, "shots_blocked": 6.0}
        self.assertEqual(gk_evidence(wild, 0), 1.0)

    def test_weight_is_full_from_the_threshold_up_and_proportional_below(self):
        self.assertEqual(gk_evidence_weight(GK_EVIDENCE_FULL), 1.0)
        self.assertEqual(gk_evidence_weight(GK_EVIDENCE_FULL * 3), 1.0)
        self.assertAlmostEqual(gk_evidence_weight(GK_EVIDENCE_FULL / 2), 0.5)
        self.assertEqual(gk_evidence_weight(0.0), 0.0)

    # --- what it does to the vote ---------------------------------------
    def test_a_thin_match_is_pulled_toward_six(self):
        """Same reading of the same performance; the only difference is how much
        of the match there was to read."""
        index = REFERENCE["POR"]["mean"] - 2 * REFERENCE["POR"]["std"]  # a poor one
        full = _raw_vote_from_index(index, "POR", 90, REFERENCE, evidence_weight=1.0)
        thin = _raw_vote_from_index(index, "POR", 90, REFERENCE, evidence_weight=0.25)
        self.assertLess(full, thin)                 # thin is less harsh
        self.assertLess(thin, GK_CENTER)            # but still below par
        self.assertAlmostEqual(GK_CENTER - thin, (GK_CENTER - full) * 0.25,
                               places=6)

    def test_a_good_thin_match_is_damped_the_same_way(self):
        """Symmetry matters: the damper is about evidence, not about mercy. A
        keeper who made one fine save has not proved a 7 either."""
        index = REFERENCE["POR"]["mean"] + 2 * REFERENCE["POR"]["std"]
        full = _raw_vote_from_index(index, "POR", 90, REFERENCE, evidence_weight=1.0)
        thin = _raw_vote_from_index(index, "POR", 90, REFERENCE, evidence_weight=0.25)
        self.assertGreater(full, thin)
        self.assertGreater(thin, GK_CENTER)

    def test_no_damping_leaves_the_vote_exactly_as_it_was(self):
        index = REFERENCE["POR"]["mean"] + REFERENCE["POR"]["std"]
        self.assertEqual(_raw_vote_from_index(index, "POR", 90, REFERENCE),
                         _raw_vote_from_index(index, "POR", 90, REFERENCE,
                                              evidence_weight=1.0))

    # --- the papera ------------------------------------------------------
    def test_an_error_leading_to_a_goal_costs_the_keeper_a_real_amount(self):
        """It was priced at a sixth of the anchor and the pagelle price it at about
        three quarters; under-weighting it let a keeper who threw one in read like
        a keeper who simply conceded."""
        clean = {"gk_saves": 3.0, "gk_goals_prevented": 0.2, "touches": 30.0}
        papera = {**clean, "errors_led_to_goal": 1.0}
        drop = index_for_role("POR", clean, 90) - index_for_role("POR", papera, 90)
        self.assertGreater(drop, 0.0)
        # in vote points, through the same scale the vote uses
        v_clean = _raw_vote_from_index(index_for_role("POR", clean, 90), "POR", 90,
                                       REFERENCE)
        v_papera = _raw_vote_from_index(index_for_role("POR", papera, 90), "POR", 90,
                                        REFERENCE)
        self.assertGreater(v_clean - v_papera, 0.15)
        self.assertGreaterEqual(abs(GK_TOTAL_WEIGHTS["errors_led_to_goal"]),
                                0.3 * GK_TOTAL_WEIGHTS["gk_goals_prevented"])

    def test_a_keepers_inaccurate_passes_are_not_an_error(self):
        """For a keeper the provider's 'bad passes' are mostly long distribution —
        a style, not a mistake. We do not reward it; we stopped punishing it."""
        self.assertNotIn("errors_bad_passes", GK_WEIGHTS)

    # --- the explanation must follow the vote ----------------------------
    def test_the_breakdown_of_a_damped_vote_still_adds_up(self):
        """The explanation subtracts the same means and applies the same
        shrinkages, so base + shown + other must land on the vote — otherwise a
        damped keeper reads as a broken one."""
        feats = {"gk_saves": 1.0, "gk_goals_prevented": -0.6, "touches": 25.0}
        averages = role_average_terms([("POR", feats, 90, 0.0)])
        # a different keeper-match, so the deviation from the average is non-zero
        his = {"gk_saves": 1.0, "gk_goals_prevented": -1.1, "touches": 28.0}
        ev = gk_evidence_weight(gk_evidence(his, 1))   # 2 tiri in porta: meta' prova
        self.assertLess(ev, 1.0)
        x = explain("POR", his, 90, REFERENCE, averages, evidence_weight=ev)
        shown = sum(c["points"] for c in x["contributions"])
        self.assertAlmostEqual(x["base"] + shown + x["other_points"], x["subtotal"],
                               places=2)
        self.assertIn("pochi tiri in porta", x["note"])

    def test_a_busy_keeper_gets_no_evidence_note(self):
        feats = {"gk_saves": 5.0, "gk_goals_prevented": 0.9, "touches": 30.0}
        averages = role_average_terms([("POR", feats, 90, 0.0)])
        x = explain("POR", {"gk_saves": 6.0, "gk_goals_prevented": 1.4,
                            "touches": 32.0}, 90, REFERENCE, averages,
                    evidence_weight=gk_evidence_weight(gk_evidence({"gk_saves": 6.0}, 1)))
        self.assertNotIn("pochi tiri", x["note"])
