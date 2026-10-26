"""The shotmap and the heatmap must end up in the same coordinate frame."""
from __future__ import annotations

from django.test import SimpleTestCase

from realdata.services.sofascore_adapter import _norm_point, _point_xy, _shot_point_xy


class ShotFrameTests(SimpleTestCase):
    """Regression guard for a defect that was invisible in every vote.

    SofaScore reports a heatmap point in the player's attacking direction (own
    goal at x=0) but a shot's playerCoordinates from the goal being ATTACKED. Fed
    through the same normalisation, every shot landed in the shooter's own
    defensive third — and nothing looked wrong, because the voto puro sums xG
    across zones and never asks where the shot was. Only the zone vectors cared.
    """

    def test_a_shot_from_the_opponent_box_lands_in_the_attacking_third(self):
        # Raw shot near the attacked goal: SofaScore gives x ~ 10.
        px, py = _shot_point_xy({"x": 10.0, "y": 50.0})
        nx, _ = _norm_point(px, py, "home", False)
        self.assertGreater(nx, 0.8, "un tiro in area avversaria deve stare nel "
                                    "terzo offensivo, non davanti alla propria porta")

    def test_the_flip_is_a_rotation_so_the_flank_is_inverted_too(self):
        """Not a mirror of the long axis alone: measured on 1295 real shots, the
        y correlation with the taker's own heatmap is -0.47."""
        px, py = _shot_point_xy({"x": 10.0, "y": 20.0})
        self.assertAlmostEqual(px, 90.0)
        self.assertAlmostEqual(py, 80.0)

    def test_heatmap_points_are_left_alone(self):
        """The heatmap frame is already correct — flipping it too would just move
        the bug to the other payload."""
        self.assertEqual(_point_xy({"x": 10.0, "y": 20.0}), (10.0, 20.0))

    def test_malformed_coordinates_do_not_raise(self):
        self.assertEqual(_shot_point_xy({}), (None, None))
        self.assertEqual(_shot_point_xy({"x": "n/d", "y": 1}), (None, None))


class ShotDistanceTests(SimpleTestCase):
    """``MatchShot.distance_m`` feeds the keeper channel: a goal from close is
    forgiven, a goal from far is charged (``keeper_channel.goal_cost_factor``).
    The distance is read off the shotmap's ``playerCoordinates`` — percent of a
    105 x 68 pitch, x from the goal line being attacked, y across — so a wrong
    frame or a wrong unit would move every keeper's vote without an error."""

    def test_the_penalty_spot_is_eleven_metres_out(self):
        from realdata.services.sofascore_adapter import shot_distance_m
        self.assertAlmostEqual(shot_distance_m({"x": 11.0 / 1.05, "y": 50.0}), 11.0, places=2)
        self.assertEqual(shot_distance_m({"x": 0.0, "y": 50.0}), 0.0)

    def test_the_width_counts_too_and_is_symmetric(self):
        from math import hypot
        from realdata.services.sofascore_adapter import shot_distance_m
        self.assertAlmostEqual(shot_distance_m({"x": 20.0, "y": 25.0}),
                               round(hypot(21.0, 17.0), 2), places=2)
        self.assertEqual(shot_distance_m({"x": 20.0, "y": 25.0}),
                         shot_distance_m({"x": 20.0, "y": 75.0}))
        self.assertEqual(shot_distance_m([20.0, 25.0]), shot_distance_m({"x": 20.0, "y": 25.0}))

    def test_no_coordinates_is_no_distance_not_a_made_up_one(self):
        """The keeper channel reads None as its default distance; a 0 here would
        turn every unplaced goal into a point-blank one."""
        from realdata.services.sofascore_adapter import shot_distance_m
        for bad in (None, {}, {"x": "n/d", "y": 1}, {"x": float("nan"), "y": 50}, [1]):
            self.assertIsNone(shot_distance_m(bad), bad)


class ShotInterceptionTests(SimpleTestCase):
    """``MatchShot.interception_m``: dove il pallone e' stato fermato, in metri dal
    punto di tiro verso la porta. Negativo = dietro il tiratore, la firma del tiro
    che non e' partito (v. classic_rating.is_interrupted_shot)."""

    def test_behind_the_shooter_is_negative(self):
        from realdata.services.sofascore_adapter import shot_interception_m
        # il 40' di Bartesaghi in Udinese-Milan, coordinate del fornitore
        shot = {"playerCoordinates": {"x": 4.5, "y": 47.1}, "blockCoordinates": {"x": 7.6, "y": 47.3}}
        self.assertAlmostEqual(shot_interception_m(shot), -3.25, places=2)
        shot["blockCoordinates"] = {"x": 2.5, "y": 48}
        self.assertAlmostEqual(shot_interception_m(shot), 2.1, places=2)

    def test_no_block_point_is_none(self):
        from realdata.services.sofascore_adapter import shot_interception_m
        self.assertIsNone(shot_interception_m({"playerCoordinates": {"x": 4.5, "y": 47.1}}))
        self.assertIsNone(shot_interception_m({"playerCoordinates": {"x": 4.5},
                                               "blockCoordinates": {"x": "n/d"}}))

    def test_only_a_miss_behind_the_shooter_is_interrupted(self):
        from vfoot.services.classic_rating import is_interrupted_shot
        self.assertTrue(is_interrupted_shot("miss", -0.5))
        self.assertFalse(is_interrupted_shot("miss", 0.5))
        self.assertFalse(is_interrupted_shot("miss", None))
        self.assertFalse(is_interrupted_shot("block", -0.5))
