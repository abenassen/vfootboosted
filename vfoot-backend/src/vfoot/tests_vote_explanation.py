"""A vote nobody can interrogate is a vote nobody will trust."""
from __future__ import annotations

from django.test import SimpleTestCase

from vfoot.services.vote_explanation import (
    COUNT, EVENT, LABELS, QUANTIFIERS, explain, role_average_terms, to_sentence,
)


class VoteExplanationTests(SimpleTestCase):
    REFERENCE = {"DIF": {"mean": 1.5, "std": 0.9, "n": 100},
                 "POR": {"mean": 0.7, "std": 2.1, "n": 100}}

    def _averages(self, role, feats, minutes=90):
        return role_average_terms([(role, feats, minutes, 0.0)])

    def test_it_reports_the_direction_not_just_the_feature(self):
        """The first draft said "Bene: duelli persi" of a defender who had lost
        FEWER than his peers — arithmetically right, and nonsense to read."""
        average = self._averages("DIF", {"duels_lost": 16.0, "touches": 60.0})
        few = explain("DIF", {"duels_lost": 4.0, "touches": 60.0}, 90,
                      self.REFERENCE, average)
        labels = [e["label"] for e in few["positives"]]
        self.assertIn("pochi duelli persi", labels)
        self.assertNotIn("molti duelli persi", labels)

        many = explain("DIF", {"duels_lost": 36.0, "touches": 60.0}, 90,
                       self.REFERENCE, average)
        self.assertIn("molti duelli persi", [e["label"] for e in many["negatives"]])

    def test_losing_fewer_duels_is_good_and_winning_fewer_is_bad(self):
        average = self._averages("DIF", {"duels_won": 16.0, "duels_lost": 16.0,
                                         "touches": 60.0})
        e = explain("DIF", {"duels_won": 4.0, "duels_lost": 4.0, "touches": 60.0},
                    90, self.REFERENCE, average)
        self.assertIn("pochi duelli persi", [x["label"] for x in e["positives"]])
        self.assertIn("pochi duelli vinti", [x["label"] for x in e["negatives"]])

    def test_rare_events_are_named_only_when_they_happened(self):
        """"Fewer penalties conceded than average" is not something to read back
        to anyone."""
        average = self._averages("DIF", {"penalties_conceded": 1.0, "touches": 60.0})
        clean = explain("DIF", {"touches": 60.0}, 90, self.REFERENCE, average)
        for entry in clean["positives"] + clean["negatives"]:
            self.assertNotIn("rigore", entry["label"])

        guilty = explain("DIF", {"penalties_conceded": 1.0, "touches": 60.0}, 90,
                         self.REFERENCE, self._averages("DIF", {"touches": 60.0}))
        self.assertIn("un rigore concesso",
                      [e["label"] for e in guilty["negatives"]])

    def test_contributions_are_in_vote_points(self):
        """Index units would be unfalsifiable: nobody can say whether 0.42 of an
        index is a lot."""
        average = self._averages("DIF", {"touches": 10.0})
        e = explain("DIF", {"touches": 400.0}, 90, self.REFERENCE, average)
        self.assertTrue(e["positives"])
        for entry in e["positives"]:
            self.assertLess(abs(entry["points"]), 7.0)   # a vote-sized number

    def test_a_short_appearance_says_so(self):
        average = self._averages("DIF", {"touches": 60.0})
        e = explain("DIF", {"touches": 20.0}, 15, self.REFERENCE, average)
        self.assertIn("giocato poco", e["note"])
        self.assertEqual(explain("DIF", {"touches": 60.0}, 90,
                                 self.REFERENCE, average)["note"], "")

    def test_no_measured_terms_explains_nothing_rather_than_guessing(self):
        e = explain("DIF", {}, 0, self.REFERENCE, {})
        self.assertEqual(e["positives"], [])
        self.assertEqual(e["negatives"], [])
        self.assertEqual(to_sentence(e), "Prestazione in linea con la media del suo ruolo.")

    def test_every_label_declares_how_to_say_it(self):
        for key, entry in LABELS.items():
            label, kind, quant = entry
            self.assertTrue(label, key)
            self.assertIn(kind, (COUNT, EVENT), key)
            if kind == COUNT:
                self.assertIn(quant, QUANTIFIERS,
                              f"{key}: senza accordo grammaticale si ottiene "
                              f"'molti respinte'")
            else:
                self.assertIsNone(quant, key)
