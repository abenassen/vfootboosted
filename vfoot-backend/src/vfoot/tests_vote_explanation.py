"""A vote nobody can interrogate is a vote nobody will trust."""
from __future__ import annotations

from django.test import SimpleTestCase

from vfoot.services.vote_explanation import (
    COUNT, EVENT, SIGNAL, LABELS, QUANTIFIERS, _phrase, explain,
    role_average_terms, to_sentence,
)
from vfoot.services.classic_rating import (
    VOTE_CENTER, VOTE_MAX, VOTE_MIN, VOTE_SPREAD_K, SHRINKAGE_MINUTES,
    index_for_role,
)


class VoteExplanationTests(SimpleTestCase):
    # Realistic v2 scale (cf. the calibrated season: DIF mean ~0.42 std ~0.22).
    REFERENCE = {"DIF": {"mean": 0.42, "std": 0.22, "n": 100},
                 "POR": {"mean": 0.7, "std": 2.1, "n": 100},
                 "ATT": {"mean": 0.16, "std": 0.24, "n": 100}}

    def _averages(self, role, feats, minutes=90):
        return role_average_terms([(role, feats, minutes, 0.0)])

    # --- phrasing --------------------------------------------------------
    def test_volume_features_use_absolute_quantifiers(self):
        """Volume stats (1 is nothing, only the amount vs the role average matters)
        read as "tanti/pochi", with gender/number agreement."""
        self.assertEqual(_phrase("DIF", "clearances", +0.3, 8.0), "tante respinte")
        self.assertEqual(_phrase("DIF", "clearances", -0.3, 1.0), "poche respinte")
        self.assertEqual(_phrase("DIF", "duels_won", +0.3, 10.0), "tanti duelli vinti")

    def test_negative_weight_feature_flips_direction(self):
        """More duels LOST is above average yet worsens the vote — the phrase must
        still say "tanti duelli persi", not invert with the weight's sign."""
        # term_delta < 0 (more losses lower the index), weight < 0 -> raw above avg.
        self.assertEqual(_phrase("DIF", "duels_lost", -0.3, 20.0), "tanti duelli persi")
        self.assertEqual(_phrase("DIF", "duels_lost", +0.3, 2.0), "pochi duelli persi")

    def test_signal_features_read_as_one_or_more(self):
        """The small high-value continuous quantities (xA/SGA) never claim "molte"
        (false for one big pass): "una o più ...", the noun carrying the sense. The
        low side of creation is a non-event, so it stays silent."""
        self.assertEqual(_phrase("ATT", "expected_assists", +0.3, 0.8),
                         "una o più occasioni create per i compagni")
        self.assertIsNone(_phrase("ATT", "expected_assists", -0.3, 0.0))

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
                                         "clearances": 8.0, "touches": 60.0})
        # Strong clearances keep the vote above the faint-praise cutoff, so the
        # duels directions are still surfaced.
        e = explain("DIF", {"duels_won": 4.0, "duels_lost": 4.0,
                            "clearances": 80.0, "touches": 90.0},
                    90, self.REFERENCE, average)
        self.assertGreaterEqual(e["voto"], 5.5)
        self.assertIn("pochi duelli persi", [x["label"] for x in e["positives"]])
        self.assertIn("pochi duelli vinti", [x["label"] for x in e["negatives"]])

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
        self.assertIn("una o più conclusioni pericolose", labels)
        for lab in labels:
            self.assertNotIn("posizioni di tiro", lab)

    # --- numbers reconcile ----------------------------------------------
    def test_contributions_are_in_vote_points(self):
        average = self._averages("DIF", {"touches": 10.0})
        e = explain("DIF", {"clearances": 80.0, "duels_won": 30.0, "touches": 100.0},
                    90, self.REFERENCE, average)
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

    def test_missed_penalty_reconciles_and_is_named_by_relevance(self):
        average = self._averages("DIF", {"clearances": 8.0, "touches": 60.0})
        feats = {"clearances": 20.0, "touches": 90.0}
        # a decisive miss (-1) reads "decisivo"; a dead-rubber miss (-0.5) does not
        dec = explain("DIF", feats, 90, self.REFERENCE, average, penalty_adjustment=-1.0)
        self.assertIn("rigore decisivo sbagliato", [c["label"] for c in dec["contributions"]])
        self.assertIn("Rigore decisivo sbagliato.", to_sentence(dec))
        shown = dec["base"] + sum(c["points"] for c in dec["contributions"]) + dec["other_points"]
        self.assertAlmostEqual(shown, dec["subtotal"], places=2)
        dead = explain("DIF", feats, 90, self.REFERENCE, average, penalty_adjustment=-0.5)
        self.assertIn("rigore sbagliato", [c["label"] for c in dead["contributions"]])
        self.assertIn("Rigore sbagliato.", to_sentence(dead))
        self.assertNotIn("decisivo", to_sentence(dead))

    def test_a_clearly_poor_vote_drops_the_faint_positives(self):
        """Below 5.5 the "positives" are only least-bad deviations; naming them is
        faint praise for a bad game. They fold into "other" so the sum still holds."""
        average = self._averages("DIF", {"clearances": 6.0, "touches": 60.0})
        feats = {"errors_led_to_goal": 1.0, "clearances": 30.0, "touches": 30.0}
        e = explain("DIF", feats, 90, self.REFERENCE, average)
        self.assertLess(e["voto"], 5.5)
        self.assertEqual(e["positives"], [])
        self.assertNotIn("Bene", to_sentence(e))
        shown = e["base"] + sum(c["points"] for c in e["contributions"]) + e["other_points"]
        self.assertAlmostEqual(shown, e["subtotal"], places=2)

    def test_a_clearly_good_vote_drops_the_nitpick_negatives(self):
        """Above 6.5 the "negatives" are trivialities on a fine game (a striker's
        "dribbling concessi all'avversario"); a 7.5 should read as praise. They fold
        into "other" so the sum still holds."""
        average = self._averages("DIF", {"clearances": 8.0, "duels_won": 6.0,
                                         "touches": 60.0})
        feats = {"clearances": 200.0, "duels_won": 60.0, "touches": 150.0,
                 "dribbled_past": 3.0}
        e = explain("DIF", feats, 90, self.REFERENCE, average)
        self.assertGreater(e["voto"], 6.5)
        self.assertEqual(e["negatives"], [])
        self.assertNotIn("Male", to_sentence(e))
        shown = e["base"] + sum(c["points"] for c in e["contributions"]) + e["other_points"]
        self.assertAlmostEqual(shown, e["subtotal"], places=2)

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
            self.assertIn(kind, (COUNT, SIGNAL, EVENT), key)
            self.assertEqual(len(entry), 3, key)
            if kind == COUNT:
                self.assertIn(entry[2], QUANTIFIERS,
                              f"{key}: senza accordo si ottiene 'tanti respinte'")
            elif kind == EVENT:
                self.assertTrue(entry[1] and entry[2],
                                f"{key}: (EVENT, singolare, plurale)")
            else:  # SIGNAL — positive required, negative may be None
                self.assertTrue(entry[1], f"{key}: manca la frase positiva")
