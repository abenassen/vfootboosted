"""Rilascio 1.20: gli spezzoni tornano verso la media e il subentrato risente del
risultato con cui e' entrato (caso Woltemade, 29/10/2026). Cio' che va tenuto fermo:
a 90' nulla si muove, e le due leve sono simmetriche/monotone come decise."""
from __future__ import annotations

from django.test import SimpleTestCase

from vfoot.services import classic_rating as cr


class ContractionTests(SimpleTestCase):
    def test_identity_at_ninety_and_beyond(self):
        for v in (3.0, 5.5, 6.0, 7.5):
            self.assertEqual(cr.contracted_vote(v, 90, centre=6.0), v)
            self.assertEqual(cr.contracted_vote(v, 97, centre=6.0), v)

    def test_symmetric_around_the_centre(self):
        up = cr.contracted_vote(7.0, 45, centre=6.0) - 6.0
        down = 6.0 - cr.contracted_vote(5.0, 45, centre=6.0)
        self.assertAlmostEqual(up, down)
        self.assertAlmostEqual(up, 1.0 * (1 - 0.3 * 0.5))  # lam = 0.85 a 45'

    def test_grows_with_the_unplayed_minutes_and_never_flips_sign(self):
        prev = 1.0
        for m in (80, 60, 45, 20, 5, 0):
            cur = cr.contracted_vote(7.0, m, centre=6.0) - 6.0
            self.assertLess(cur, prev)
            self.assertGreater(cur, 0.0)
            prev = cur


class EntryMarginTests(SimpleTestCase):
    def test_weight_rises_with_minutes_and_stops_at_the_cap(self):
        ws = [cr.entry_margin_weight(m) for m in (0, 10, 22, 45, 70, 90)]
        self.assertEqual(ws[0], 0.0)
        self.assertEqual(ws, sorted(ws))
        self.assertAlmostEqual(cr.entry_margin_weight(45), cr.ENTRY_MARGIN_CAP)
        self.assertAlmostEqual(cr.entry_margin_weight(90), cr.ENTRY_MARGIN_CAP)
        self.assertAlmostEqual(cr.entry_margin_weight(22.5), cr.ENTRY_MARGIN_CAP / 4)

    def test_blended_equals_the_integer_mitigation_on_integers(self):
        for gd in (-3, -1, 0, 2):
            self.assertEqual(cr.result_mitigation_blended(7.0, gd, centre=6.0),
                             cr.result_mitigation(7.0, gd, centre=6.0))

    def test_blended_interpolates_between_neighbours(self):
        a = cr.result_mitigation(7.0, -1, centre=6.0)
        mid = cr.result_mitigation_blended(7.0, -0.5, centre=6.0)
        self.assertAlmostEqual(mid, 0.5 * a)
