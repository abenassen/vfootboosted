"""Il cancello del senza voto: taglio netto a 20', sotto un punteggio morbido.

Le cifre vengono dal confronto con fantacalcio.it del 27/10/2026 (v. il commento di
``classic_rating.ALWAYS_RATED_MINUTES``); qui si fissa soltanto la FORMA della regola.
"""
from django.test import SimpleTestCase

from realdata.services.sofascore_intervals import second_half_added_minutes
from vfoot.services import classic_rating as cr


class IsRatedTests(SimpleTestCase):
    def test_from_the_cut_on_minutes_alone_decide(self):
        self.assertTrue(cr.is_rated(20, {}))
        self.assertTrue(cr.is_rated(34, {"touches": 0.0}))

    def test_below_the_cut_a_quiet_cameo_has_no_vote(self):
        self.assertFalse(cr.is_rated(15, {"touches": 4.0}))
        self.assertFalse(cr.is_rated(0, {"touches": 90.0}))

    def test_contribution_buys_minutes(self):
        # 15' + 0.15 * 40 touches = 21 equivalent minutes
        self.assertTrue(cr.is_rated(15, {"touches": 40.0}))
        # a shot weighs double a touch, and a shot on target adds to the shot
        self.assertEqual(cr.gate_contribution(
            {"touches": 10.0, "shots": 1.0, "shots_on_target": 1.0}), 14.0)

    def test_the_boundary_is_inclusive_and_monotone(self):
        # 15 + 0.15 * 30 = 19.5 exactly: it has a vote
        self.assertTrue(cr.is_rated(15, {"touches": 30.0}))
        self.assertFalse(cr.is_rated(15, {"touches": 29.0}))
        votes = [cr.is_rated(m, {"touches": 12.0}) for m in range(0, 25)]
        self.assertEqual(votes, sorted(votes))    # more minutes never loses a vote

    def test_spinazzola_napoli_roma(self):
        """Entered at the 80th: 10 provider minutes, 5 of stoppage, 12 touches, one
        shot (on target). 15 + 0.15 * 18 = 17.7: still senza voto, by design — the
        pagelle of fantacalcio.it rate roughly one cameo in four like this one."""
        self.assertFalse(cr.is_rated(15, {"touches": 12.0, "shots": 1.0,
                                          "shots_on_target": 1.0}))


class AnnouncedStoppageTests(SimpleTestCase):
    def test_reads_the_second_half_announcement(self):
        rows = [{"incidentType": "injuryTime", "time": 45, "length": 2},
                {"incidentType": "injuryTime", "time": 90, "length": 5}]
        self.assertEqual(second_half_added_minutes(rows), 5)

    def test_unknown_is_not_zero(self):
        """Not announced yet (mid-match) must say «non lo sappiamo»: a zero would read
        as «no stoppage», and the gate would withhold votes it should give."""
        self.assertIsNone(second_half_added_minutes(
            [{"incidentType": "injuryTime", "time": 45, "length": 2}]))
        self.assertIsNone(second_half_added_minutes([]))
