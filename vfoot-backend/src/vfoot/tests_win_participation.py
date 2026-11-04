"""Il lato VITTORIA della mitigazione guarda la PARTECIPAZIONE (rilascio 1.21).

Caso Modric, Milan-Inter 3-1 (31/10/2026): 88 tocchi, merito sul centro del ruolo,
6,0 come Goncalo Ramos (32 tocchi, nessuna azione), che la vittoria portava da 5,5 a
6,0. Questi test tengono ferme le tre cose decise: chi partecipa sale oltre il
centro, chi partecipa poco riceve meno, e la sconfitta non cambia di un centesimo.
"""
from __future__ import annotations

from django.test import SimpleTestCase

from vfoot.services import classic_rating as cr, participation as pt


class WinParticipationTests(SimpleTestCase):
    def test_a_central_vote_is_lifted_only_with_participation(self):
        """Il caso Modric: sul centro la forma di prima non dava niente."""
        self.assertEqual(cr.result_mitigation(6.0, 2, centre=6.0), 0.0)
        self.assertEqual(cr.result_mitigation(6.0, 2, centre=6.0, participation=0.0), 0.0)
        self.assertGreater(cr.result_mitigation(6.0, 2, centre=6.0, participation=0.9), 0.15)

    def test_the_win_never_passes_centre_plus_target(self):
        for gd in range(1, 10):
            for p in (0.0, 0.3, 0.7, 1.0):
                for raw in (4.0, 5.5, 6.0, 6.2):
                    top = 6.0 + cr.WIN_PARTICIPATION_TARGET * p
                    v = raw + cr.result_mitigation(raw, gd, centre=6.0, participation=p)
                    self.assertLessEqual(v, max(raw, top) + 1e-12)

    def test_more_participation_never_lifts_less(self):
        for raw in (4.5, 5.6, 6.0, 6.25):
            lifts = [cr.result_mitigation(raw, 2, centre=6.0, participation=p)
                     for p in (0.0, 0.25, 0.5, 0.75, 1.0)]
            self.assertEqual(lifts, sorted(lifts))

    def test_low_participation_gets_half_the_old_share(self):
        old = cr.result_mitigation(5.0, 2, centre=6.0)
        self.assertAlmostEqual(cr.result_mitigation(5.0, 2, centre=6.0, participation=0.0),
                               old * cr.WIN_PARTICIPATION_FLOOR)

    def test_full_participation_is_the_old_share_towards_a_higher_target(self):
        sev = min(cr.RESULT_MITIGATION_MAX_SHARE,
                  cr.RESULT_MITIGATION_BASE + cr.RESULT_MITIGATION_K * 3)
        self.assertAlmostEqual(
            cr.result_mitigation(5.5, 3, centre=6.0, participation=1.0),
            (6.0 + cr.WIN_PARTICIPATION_TARGET - 5.5) * sev)

    def test_a_defeat_ignores_participation(self):
        for p in (None, 0.0, 1.0):
            self.assertEqual(cr.result_mitigation(6.8, -2, centre=6.0, participation=p),
                             cr.result_mitigation(6.8, -2, centre=6.0))

    def test_modric_and_ramos(self):
        """I due voti di Milan-Inter, dai numeri di produzione (merito prima della
        spinta, percentili di tocchi della 26-27). Stanno a ~0,01 dal bordo: se cade,
        la regola si e' mossa davvero, non il caso."""
        def shown(raw, role, p):
            pre = raw + cr.result_mitigation(raw, 2, centre=cr.vote_center_for(role),
                                             participation=p)
            return cr._round_half(cr.scale_saturation(pre, role)[0])
        self.assertEqual(shown(5.958, "CEN", 0.888), 6.5)
        self.assertEqual(shown(5.604, "ATT", 0.337), 5.5)


class ParticipationMeasureTests(SimpleTestCase):
    def setUp(self):
        pt.clear_cache()

    def test_the_max_lets_actions_compensate_few_touches(self):
        few = {"touches": 25.0}
        busy = {"touches": 25.0, "key_passes": 2.0, "shots": 2.0, "dribbles_won": 1.0}
        self.assertGreater(pt.participation("ATT", busy, 90), pt.participation("ATT", few, 90))

    def test_defensive_actions_do_not_count(self):
        a = {"touches": 30.0}
        b = {"touches": 30.0, "tackles_won": 3.0, "interceptions": 4.0}
        self.assertEqual(pt.participation("ATT", a, 90), pt.participation("ATT", b, 90))

    def test_a_short_stint_is_pulled_to_neutral(self):
        feats = {"touches": 20.0, "key_passes": 1.0}
        full = pt.participation("CEN", {k: v * 9 for k, v in feats.items()}, 90)
        short = pt.participation("CEN", feats, 10)
        self.assertLess(abs(short - pt.NEUTRAL), abs(full - pt.NEUTRAL))

    def test_bounds_and_unknown_role(self):
        self.assertEqual(pt.participation("POR", {"touches": 50.0}, 90), pt.NEUTRAL)
        for t in (0.0, 300.0):
            self.assertTrue(0.0 <= pt.participation("CEN", {"touches": t}, 90) <= 1.0)
