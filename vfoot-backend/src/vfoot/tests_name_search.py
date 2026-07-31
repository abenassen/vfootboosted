"""The forgiving name matcher, and the cases it exists for.

These are also the cases pinned on the frontend twin
(`vfoot-frontend/src/utils/text.ts`): the auction room searches through this
module while the listone and the market filter in the browser, and a search that
answers differently depending on the page is worse than a strict one.
"""
from __future__ import annotations

from django.test import TestCase

from vfoot.services.name_search import fold, matches


class FoldTests(TestCase):
    def test_strips_diacritics(self):
        self.assertEqual(fold("Leão"), "leao")
        self.assertEqual(fold("Martínez"), "martinez")
        self.assertEqual(fold("Çalhanoğlu"), "calhanoglu")
        self.assertEqual(fold("Szczęsny"), "szczesny")

    def test_strips_punctuation_including_the_doubled_apostrophes_in_our_data(self):
        self.assertEqual(fold("D'Ambrosio"), "dambrosio")
        self.assertEqual(fold("D’Ambrosio"), "dambrosio")
        self.assertEqual(fold("D''Ambrosio"), "dambrosio")
        self.assertEqual(fold("Paul-José"), "pauljose")


class MatchTests(TestCase):
    def test_accents_are_not_required(self):
        self.assertTrue(matches("leao", "R. Leão", "Rafael Leão"))
        self.assertTrue(matches("calhanoglu", "H. Çalhanoğlu", "Hakan Çalhanoğlu"))

    def test_finds_by_first_name_though_the_list_shows_the_short_form(self):
        # The reason full_name is sent alongside: the row reads "L. Martínez".
        self.assertTrue(matches("lautaro", "L. Martínez", "Lautaro Martínez"))

    def test_tolerates_a_misspelling(self):
        self.assertTrue(matches("mkitarian", "H. Mkhitaryan", "Henrikh Mkhitaryan"))
        self.assertTrue(matches("donarumma", "G. Donnarumma", "Gianluigi Donnarumma"))
        self.assertTrue(matches("martines", "L. Martínez", "Lautaro Martínez"))

    def test_typo_in_a_prefix_still_lands(self):
        self.assertTrue(matches("gianluigy", "G. Donnarumma", "Gianluigi Donnarumma"))

    def test_short_needles_get_no_slack(self):
        # One error on three letters would match a good part of any roster.
        self.assertFalse(matches("leo", "R. Leão", "Rafael Leão") and
                         matches("leo", "M. Kean", "Moise Kean"))
        self.assertFalse(matches("kea", "L. Martínez", "Lautaro Martínez"))

    def test_does_not_match_an_unrelated_name(self):
        self.assertFalse(matches("mkhitaryan", "L. Martínez", "Lautaro Martínez"))
        self.assertFalse(matches("dybala", "R. Leão", "Rafael Leão"))

    def test_empty_needle_matches_everything(self):
        self.assertTrue(matches("", "R. Leão", "Rafael Leão"))
        self.assertTrue(matches("   ", None, None))

    def test_missing_fields_are_not_a_match(self):
        self.assertFalse(matches("leao", None, None))
