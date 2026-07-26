"""A vote nobody can interrogate is a vote nobody will trust."""
from __future__ import annotations

from django.test import SimpleTestCase

from vfoot.services.vote_explanation import (
    COUNT, EVENT, LABELS, _phrase, explain, role_average_terms, to_sentence,
)
from vfoot.services.classic_rating import (
    VOTE_CENTER, VOTE_MAX, VOTE_MIN, VOTE_SPREAD_K, SHRINKAGE_MINUTES,
    index_for_role,
)


class VoteExplanationTests(SimpleTestCase):
    REFERENCE = {"DIF": {"mean": 1.5, "std": 0.9, "n": 100},
                 "POR": {"mean": 0.7, "std": 2.1, "n": 100},
                 "ATT": {"mean": 0.0, "std": 0.9, "n": 100}}

    def _averages(self, role, feats, minutes=90):
        return role_average_terms([(role, feats, minutes, 0.0)])

    # --- phrasing --------------------------------------------------------
    def test_count_phrasing_is_comparative_never_absolute(self):
        """The bug this closes: "molte occasioni create" read as MANY chances even
        when a single dangerous pass drove a high (continuous) xA. Comparative
        "più/meno" says only what the number says — more/less than the role's usual."""
        more = _phrase("DIF", "clearances", +0.3, 8.0)
        less = _phrase("DIF", "clearances", -0.3, 1.0)
        self.assertEqual(more, "più respinte")
        self.assertEqual(less, "meno respinte")
        for word in ("molti", "molte", "pochi", "poche"):
            self.assertNotIn(word, f"{more} {less}")

    def test_negative_weight_feature_flips_direction(self):
        """More duels LOST is above average yet worsens the vote — the phrase must
        still say "più duelli persi", not invert with the weight's sign."""
        # term_delta < 0 (more losses lower the index), weight < 0 -> raw above avg.
        self.assertEqual(_phrase("DIF", "duels_lost", -0.3, 20.0), "più duelli persi")
        self.assertEqual(_phrase("DIF", "duels_lost", +0.3, 2.0), "meno duelli persi")

    def test_events_report_the_real_count(self):
        """Three last-man tackles are "3 interventi da ultimo uomo", not "un
        intervento" — the old code was hardcoded singular."""
        self.assertEqual(_phrase("DIF", "last_man_tackle", 0.5, 1.0),
                         "un intervento da ultimo uomo")
        self.assertEqual(_phrase("DIF", "last_man_tackle", 0.5, 3.0),
                         "3 interventi da ultimo uomo")

    def test_events_are_silent_when_they_did_not_happen(self):
        self.assertIsNone(_phrase("DIF", "penalties_conceded", -0.2, 0.0))

    # --- direction in context -------------------------------------------
    def test_losing_fewer_duels_is_good_and_winning_fewer_is_bad(self):
        average = self._averages("DIF", {"duels_won": 16.0, "duels_lost": 16.0,
                                         "touches": 60.0})
        e = explain("DIF", {"duels_won": 4.0, "duels_lost": 4.0, "touches": 60.0},
                    90, self.REFERENCE, average)
        self.assertIn("meno duelli persi", [x["label"] for x in e["positives"]])
        self.assertIn("meno duelli vinti", [x["label"] for x in e["negatives"]])

    def test_rare_events_are_named_only_when_they_happened(self):
        clean = explain("DIF", {"touches": 60.0}, 90, self.REFERENCE,
                        self._averages("DIF", {"penalties_conceded": 1.0,
                                               "touches": 60.0}))
        for entry in clean["positives"] + clean["negatives"]:
            self.assertNotIn("rigore", entry["label"])

        guilty = explain("DIF", {"penalties_conceded": 1.0, "touches": 60.0}, 90,
                         self.REFERENCE, self._averages("DIF", {"touches": 60.0}))
        self.assertIn("un rigore concesso",
                      [e["label"] for e in guilty["negatives"]])

    def test_the_sga_shooting_pair_reads_as_one_line(self):
        """xg_on_target (+) and xg_shots (-) are the two halves of one design term
        (execution over positioning); shown apart, xg_shots reads as "Male: più
        posizioni di tiro conquistate". They must merge into finishing quality."""
        average = self._averages("ATT", {"xg_on_target": 0.3, "xg_shots": 0.3,
                                         "touches": 40.0})
        e = explain("ATT", {"xg_on_target": 1.0, "xg_shots": 0.2, "touches": 40.0},
                    90, self.REFERENCE, average)
        labels = [c["label"] for c in e["contributions"]]
        self.assertIn("più incisività nelle conclusioni", labels)
        for lab in labels:
            self.assertNotIn("posizioni di tiro", lab)

    # --- numbers reconcile ----------------------------------------------
    def test_contributions_are_in_vote_points(self):
        average = self._averages("DIF", {"touches": 10.0})
        e = explain("DIF", {"touches": 400.0}, 90, self.REFERENCE, average)
        self.assertTrue(e["positives"])
        for entry in e["positives"]:
            self.assertLess(abs(entry["points"]), 7.0)

    def test_the_breakdown_adds_up_to_the_vote(self):
        average = self._averages("DIF", {"duels_won": 12.0, "clearances": 8.0,
                                         "touches": 60.0, "key_passes": 1.0})
        feats = {"duels_won": 30.0, "clearances": 20.0, "touches": 90.0,
                 "key_passes": 4.0, "interceptions": 5.0}
        e = explain("DIF", feats, 90, self.REFERENCE, average)
        shown = e["base"] + sum(c["points"] for c in e["contributions"]) + e["other_points"]
        self.assertAlmostEqual(shown, e["subtotal"], places=2)

        idx = index_for_role("DIF", feats, 90)
        z = (idx - self.REFERENCE["DIF"]["mean"]) / self.REFERENCE["DIF"]["std"]
        w = 90 / (90 + SHRINKAGE_MINUTES)
        raw = max(VOTE_MIN, min(VOTE_MAX, VOTE_CENTER + VOTE_SPREAD_K * w * z))
        self.assertAlmostEqual(e["voto"], round(raw * 2) / 2, places=2)

    def test_result_nudge_and_red_card_reconcile_and_are_named(self):
        average = self._averages("DIF", {"clearances": 8.0, "touches": 60.0})
        feats = {"clearances": 20.0, "touches": 90.0}
        e = explain("DIF", feats, 90, self.REFERENCE, average,
                    result_nudge=-0.4, red_adjustment=-1.0)
        labels = [c["label"] for c in e["contributions"]]
        self.assertIn("adeguamento al risultato di squadra", labels)
        self.assertIn("espulsione", labels)
        shown = e["base"] + sum(c["points"] for c in e["contributions"]) + e["other_points"]
        self.assertAlmostEqual(shown, e["subtotal"], places=2)
        self.assertIn("Espulso.", to_sentence(e))

    # --- housekeeping ----------------------------------------------------
    def test_reports_minutes_played(self):
        average = self._averages("DIF", {"touches": 60.0})
        self.assertEqual(explain("DIF", {"touches": 60.0}, 47,
                                 self.REFERENCE, average)["minutes"], 47)

    def test_a_short_appearance_says_so(self):
        average = self._averages("DIF", {"touches": 60.0})
        e = explain("DIF", {"touches": 20.0}, 15, self.REFERENCE, average)
        self.assertIn("pochi minuti", e["note"])
        self.assertEqual(explain("DIF", {"touches": 60.0}, 90,
                                 self.REFERENCE, average)["note"], "")

    def test_no_measured_terms_explains_nothing_rather_than_guessing(self):
        e = explain("DIF", {}, 0, self.REFERENCE, {})
        self.assertEqual(e["positives"], [])
        self.assertEqual(to_sentence(e),
                         "Prestazione in linea con la media del suo ruolo.")

    def test_every_label_declares_how_to_say_it(self):
        for key, entry in LABELS.items():
            kind = entry[0]
            self.assertIn(kind, (COUNT, EVENT), key)
            if kind == COUNT:
                self.assertEqual(len(entry), 2, f"{key}: (COUNT, label)")
                self.assertTrue(entry[1], key)
            else:
                self.assertEqual(len(entry), 3,
                                 f"{key}: (EVENT, singolare, plurale)")
                self.assertTrue(entry[1] and entry[2], key)
