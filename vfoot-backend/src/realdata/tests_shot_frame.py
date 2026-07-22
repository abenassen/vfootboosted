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
