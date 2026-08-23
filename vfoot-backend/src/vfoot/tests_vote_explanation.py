"""A vote nobody can interrogate is a vote nobody will trust."""
from __future__ import annotations

from django.test import SimpleTestCase

from vfoot.services.vote_explanation import (
    COUNT, EVENT, SIGNAL, LABELS, QUANTIFIERS, _phrase, explain, ledger_phrase,
    readable_label, role_average_terms, to_sentence,
)
from vfoot.services.classic_rating import (
    VOTE_CENTER, VOTE_MAX, VOTE_MIN, VOTE_SPREAD_K, SHRINKAGE_MINUTES,
    index_for_role,
)


class VoteExplanationTests(SimpleTestCase):
    # The scale of the real calibration (see vote_reference.json), so a fixture
    # vote means roughly what the same index would mean in production. Outfield
    # roles share one spread by design — see POOLED_ROLE_SPREAD.
    REFERENCE = {"DIF": {"mean": 0.28, "std": 0.44, "n": 100},
                 "POR": {"mean": 0.66, "std": 2.17, "n": 100},
                 "ATT": {"mean": 0.47, "std": 0.44, "n": 100}}

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
        # the sentence now carries the cost, and is matched on ``kind`` rather than
        # on its text (the label grew a minute and a reason)
        self.assertIn("Espulsione (-1.00).", to_sentence(e))
        self.assertEqual([c["kind"] for c in e["contributions"] if c.get("kind")],
                         ["result", "red"])

    def test_missed_penalty_reconciles_and_is_named_by_relevance(self):
        average = self._averages("DIF", {"clearances": 8.0, "touches": 60.0})
        feats = {"clearances": 20.0, "touches": 90.0}
        # a decisive miss (-1) reads "decisivo"; a dead-rubber miss (-0.5) does not
        dec = explain("DIF", feats, 90, self.REFERENCE, average, penalty_adjustment=-1.0)
        self.assertIn("rigore decisivo sbagliato", [c["label"] for c in dec["contributions"]])
        self.assertIn("Rigore decisivo sbagliato (-1.00).", to_sentence(dec))
        shown = dec["base"] + sum(c["points"] for c in dec["contributions"]) + dec["other_points"]
        self.assertAlmostEqual(shown, dec["subtotal"], places=2)
        dead = explain("DIF", feats, 90, self.REFERENCE, average, penalty_adjustment=-0.5)
        self.assertIn("rigore sbagliato", [c["label"] for c in dead["contributions"]])
        self.assertIn("Rigore sbagliato (-0.50).", to_sentence(dead))
        self.assertNotIn("decisivo", to_sentence(dead))

    # --- the full per-feature ledger -------------------------------------
    def test_the_full_ledger_covers_every_weighted_feature_and_adds_up(self):
        """``full=True`` returns one row per weighted feature of the channel, with
        nothing merged and nothing folded away. Its points must sum to the merit
        vote minus 6 — that identity is the whole reason the table is trustworthy
        enough to publish next to the vote."""
        from vfoot.services.classic_rating import EXPOSURE_KEY, WEIGHTS

        average = self._averages("DIF", {"clearances": 8.0, "touches": 60.0})
        # The identity holds under the condition production guarantees and this
        # fixture otherwise would not: the reference mean of the INDEX and the
        # per-feature averages describe the SAME population (see the note in
        # ``explain`` about get_role_averages having to filter like build_reference).
        # The average appearance's index is exactly the sum of its per-feature terms.
        reference = {**self.REFERENCE,
                     "DIF": {**self.REFERENCE["DIF"],
                             "mean": sum(average["DIF"].values())}}
        feats = {"clearances": 20.0, "touches": 90.0, "duels_won": 6.0}
        e = explain("DIF", feats, 90, reference, average, full=True)

        keys = {t["key"] for t in e["all_terms"]}
        # every feature of the channel, zero-weight ones included: a deliberate zero
        # is a decision the table has to show (see last_man_tackle)
        self.assertEqual(keys, set(WEIGHTS) | {EXPOSURE_KEY})
        zeroed = [t for t in e["all_terms"] if t["weight"] == 0]
        self.assertTrue(all(t["points"] == 0 and t["index"] == 0 for t in zeroed))
        total = sum(t["points"] for t in e["all_terms"])
        # the merit vote before the adjustments the summary lists separately
        self.assertAlmostEqual(6.0 + total, e["subtotal"], places=2)
        # and it agrees with the summary's own accounting
        shown = sum(c["points"] for c in e["contributions"]) + e["other_points"]
        self.assertAlmostEqual(total, shown, places=2)

    # --- the ledger behind "altre N voci" --------------------------------
    def test_the_ledger_names_every_unshown_entry_and_adds_up_to_the_fold(self):
        """Il riassunto ne mostra tre e chiude con "altre N voci". Su una
        prestazione buona dappertutto quelle N sono la maggior parte del voto, e
        allora devono essere apribili: una per una, con un nome, e la loro somma
        deve fare ESATTAMENTE il numero della riga che si e' aperta — altrimenti si
        e' solo spostato il buco piu' in basso."""
        average = self._averages("DIF", {"clearances": 8.0, "touches": 60.0,
                                         "duels_won": 5.0, "tackles_won": 1.0,
                                         "defensive_value": 0.1})
        feats = {"clearances": 20.0, "touches": 90.0, "duels_won": 13.0,
                 "tackles_won": 4.0, "defensive_value": 0.44}
        e = explain("DIF", feats, 90, self.REFERENCE, average, ledger=True)

        self.assertTrue(e["other_terms"], "il registro non puo' essere vuoto")
        self.assertTrue(all(r["label"] for r in e["other_terms"]))
        # nessuna riga e' insieme mostrata e nascosta
        shown = {c["label"] for c in e["contributions"]}
        self.assertFalse(shown & {r["label"] for r in e["other_terms"]})
        # e il conto torna: righe + resto = la riga che si e' aperta
        total = (sum(r["points"] for r in e["other_terms"])
                 + e["other_tiny"]["points"])
        self.assertAlmostEqual(total, e["other_points"], places=2)
        # quante voci dice la riga, tante ce ne sono sotto
        self.assertEqual(len(e["other_terms"]) + e["other_tiny"]["count"],
                         e["other_count"])
        # il registro si costruisce solo se lo si chiede: viaggia dentro il
        # tabellino di ventidue giocatori, che si ricarica a ogni spinta live
        self.assertEqual(explain("DIF", feats, 90, self.REFERENCE, average)["other_terms"], [])

    def test_the_ledger_names_what_the_spoken_summary_never_can(self):
        """Le tre cose su cui ``_phrase`` tace apposta — l'evento che non e'
        successo, il lato muto di un SIGNAL, e la feature senza etichetta parlata —
        nel registro hanno una riga con dei punti accanto, quindi devono avere un
        nome. ``defensive_value`` e' il caso che conta: puo' essere la voce piu'
        grande del voto di un difensore e non e' nominabile in una frase."""
        self.assertEqual(ledger_phrase("DIF", "defensive_value", +0.28, 0.44),
                         "valore difensivo (indice del fornitore)")
        self.assertEqual(ledger_phrase("DIF", "shots_goal", -0.03, 0.0), "nessun gol")
        self.assertEqual(ledger_phrase("DIF", "big_chance_created", -0.02, 0.0),
                         "nessun'occasione nitida creata")
        self.assertEqual(ledger_phrase("DIF", "expected_assists", -0.03, 0.0),
                         "occasioni create per i compagni")
        # e quando la frase c'e', e' la stessa del riassunto
        self.assertEqual(ledger_phrase("DIF", "clearances", +0.3, 8.0), "tante respinte")

    def test_the_ledger_quotes_counts_the_way_the_tabellino_does(self):
        """Il numero accanto alla voce e' quello OSSERVATO, non quello proiettato
        sui 90' che l'indice consuma: "4,14 respinte" non sta da nessuna parte,
        4 sta nel tabellino. E si scrive solo quando e' un numero di cose: un
        indice normalizzato messo li' nudo non spiega niente."""
        average = self._averages("DIF", {"clearances": 8.0, "touches": 60.0,
                                         "defensive_value": 0.1})
        feats = {"clearances": 4.0, "touches": 40.0, "defensive_value": 0.44}
        e = explain("DIF", feats, 45, self.REFERENCE, average, ledger=True)
        rows = {r["label"]: r for r in e["other_terms"]}
        self.assertEqual(rows["poche respinte"]["value"], 4)   # non 8, la proiezione
        self.assertNotIn("value", rows["valore difensivo (indice del fornitore)"])

    # --- the graded events explain their own size ------------------------
    def test_a_sending_off_says_why_it_cost_what_it_cost(self):
        """The drop is severity x man-down time plus a fixed extra: "espulsione"
        alone leaves the whole of that unexplained. Two sendings-off costing 0.6 and
        1.5 have to read differently."""
        average = self._averages("DIF", {"clearances": 8.0, "touches": 60.0})
        feats = {"clearances": 20.0, "touches": 90.0}
        violent = explain("DIF", feats, 90, self.REFERENCE, average,
                          red_adjustment=-1.3,
                          red_detail={"reason": "Violent conduct", "minute": 63,
                                      "man_down": 32, "second_yellow": False})
        label = next(c["label"] for c in violent["contributions"]
                     if c.get("kind") == "red")
        self.assertEqual(label, "espulsione al 63' per condotta violenta (32' in dieci)")
        tactical = explain("DIF", feats, 90, self.REFERENCE, average,
                           red_adjustment=-0.2,
                           red_detail={"reason": "Professional foul last man",
                                       "minute": 88, "man_down": 7,
                                       "second_yellow": True})
        label2 = next(c["label"] for c in tactical["contributions"]
                      if c.get("kind") == "red")
        self.assertIn("fallo tattico da ultimo uomo", label2)
        self.assertIn("secondo giallo", label2)
        self.assertIn("(7' in dieci)", label2)

    def test_an_own_goal_says_which_kind_it_was(self):
        """Deflection and own error differ by a factor of 2.5 in the drop, so the
        label has to distinguish them; an ungraded one claims nothing."""
        average = self._averages("DIF", {"clearances": 8.0, "touches": 60.0})
        feats = {"clearances": 20.0, "touches": 90.0}

        def label(detail, adj):
            e = explain("DIF", feats, 90, self.REFERENCE, average,
                        own_goal_adjustment=adj, own_goal_detail=detail)
            return next(c["label"] for c in e["contributions"]
                        if c.get("kind") == "own_goal")

        self.assertEqual(label({"kind": "deflection", "count": 1}, -0.2),
                         "autogol su deviazione")
        self.assertEqual(label({"kind": "solo", "count": 1}, -0.5),
                         "autogol in prima persona")
        self.assertEqual(label({"kind": "ungraded", "count": 1}, -0.3), "autogol")
        self.assertEqual(label({"kind": "solo", "count": 2}, -1.0),
                         "2 autogol in prima persona")

    def test_an_assist_from_a_cheap_pass_says_so(self):
        """The base vote reads the PASS, the bonus pays the outcome. When the two
        part company — half of all assists come from a pass worth under 0.15 of xA —
        the explanation says which of the two it was, or our vote looks broken next
        to a pagella that rewarded the assist."""
        average = self._averages("CEN", {"touches": 60.0})
        cheap = explain("CEN", {"expected_assists": 0.05, "touches": 60.0}, 90,
                        self.REFERENCE | {"CEN": {"mean": 0.41, "std": 0.44}},
                        average, assists=1)
        self.assertIn("basso valore atteso", cheap["assist_note"])
        self.assertIn("xA 0.05", cheap["assist_note"])
        self.assertIn("basso valore atteso", to_sentence(cheap))
        # a real chance created, or a valuable pass, says nothing of the sort
        rich = explain("CEN", {"expected_assists": 0.6, "touches": 60.0}, 90,
                       self.REFERENCE | {"CEN": {"mean": 0.41, "std": 0.44}},
                       average, assists=1)
        self.assertEqual(rich["assist_note"], "")
        clear = explain("CEN", {"expected_assists": 0.05, "big_chance_created": 1.0,
                                "touches": 60.0}, 90,
                        self.REFERENCE | {"CEN": {"mean": 0.41, "std": 0.44}},
                        average, assists=1)
        self.assertEqual(clear["assist_note"], "")
        # and no assist, no note
        none = explain("CEN", {"expected_assists": 0.05, "touches": 60.0}, 90,
                       self.REFERENCE | {"CEN": {"mean": 0.41, "std": 0.44}},
                       average, assists=0)
        self.assertEqual(none["assist_note"], "")

    def test_a_merged_line_says_it_is_a_sum_and_names_its_family(self):
        """The summary collapses the shooting block into one line, so its number
        matches no single row of the full ledger. Without saying so, that reads as
        an inconsistency — it was reported as one. The line carries the family name
        and how many features it stands for; the ledger rows carry the same name,
        and they add up to it."""
        from vfoot.services.vote_explanation import MERGE_FAMILY

        average = self._averages("ATT", {"shots": 1.0, "touches": 40.0})
        feats = {"shots": 4.0, "shots_on_target": 3.0, "xg_shots": 0.8,
                 "xg_on_target": 1.1, "touches": 60.0}
        e = explain("ATT", feats, 90, self.REFERENCE, average, full=True)
        merged = [c for c in e["contributions"] if c.get("family")]
        self.assertTrue(merged, "la riga fusa del blocco tiro dovrebbe esserci")
        line = merged[0]
        self.assertEqual(line["family"], "conclusioni")
        self.assertGreater(line["family_size"], 1)
        # the rows of that family, in the full ledger, sum to the merged line
        rows = [t for t in e["all_terms"] if t["family"] == line["family"]]
        self.assertEqual({t["key"] for t in rows},
                         {k for k, f in MERGE_FAMILY.items() if f == line["family"]})
        self.assertAlmostEqual(sum(t["points"] for t in rows), line["points"],
                               places=2)

    def test_an_ordinary_line_claims_no_family(self):
        average = self._averages("DIF", {"clearances": 8.0, "touches": 60.0})
        e = explain("DIF", {"clearances": 25.0, "touches": 90.0}, 90,
                    self.REFERENCE, average)
        plain = [c for c in e["contributions"] if "clearances" not in c["label"]]
        self.assertTrue(all("family" not in c for c in plain
                            if "conclusioni" not in c["label"]
                            and "dribbling" not in c["label"]))

    def test_the_full_ledger_is_off_by_default(self):
        """It is several times the size of the vote it explains, so an API response
        must not carry it unasked."""
        average = self._averages("DIF", {"clearances": 8.0})
        e = explain("DIF", {"clearances": 20.0, "touches": 90.0}, 90,
                    self.REFERENCE, average)
        self.assertEqual(e["all_terms"], [])

    def test_every_weighted_feature_can_be_named_in_a_table(self):
        """A row with a technical name and no description is a row nobody can read.
        Features never spoken in a sentence get their description from
        TABLE_ONLY_LABELS instead."""
        from vfoot.services.classic_rating import EXPOSURE_KEY, GK_WEIGHTS, WEIGHTS

        every = ({k for k, w in WEIGHTS.items() if w} | {EXPOSURE_KEY}
                 | {k for k, w in GK_WEIGHTS.items() if w})
        missing = sorted(k for k in every if not readable_label(k))
        self.assertEqual(missing, [])

    def test_the_ledger_reports_the_scale_it_used(self):
        """``per_unit`` is what the page multiplies by to go from index points to
        vote points; if it did not travel with the rows they could not be read."""
        average = self._averages("ATT", {"shots": 2.0, "touches": 40.0})
        e = explain("ATT", {"shots": 5.0, "touches": 60.0}, 90, self.REFERENCE,
                    average, full=True)
        expected = VOTE_SPREAD_K * (90 / (90 + SHRINKAGE_MINUTES)) / self.REFERENCE["ATT"]["std"]
        self.assertAlmostEqual(e["per_unit"], expected, places=5)
        # a keeper with thin evidence carries the damper in the same number
        thin = explain("POR", {"gk_saves": 1.0, "touches": 25.0}, 90, self.REFERENCE,
                       self._averages("POR", {"gk_saves": 2.0, "touches": 25.0}),
                       evidence_weight=0.25, full=True)
        self.assertAlmostEqual(
            thin["per_unit"],
            VOTE_SPREAD_K * (90 / (90 + SHRINKAGE_MINUTES)) * 0.25
            / self.REFERENCE["POR"]["std"], places=5)

    def test_a_clearly_poor_vote_drops_the_faint_positives(self):
        """Below 5.5 the "positives" are only least-bad deviations; naming them is
        faint praise for a bad game. They fold into "other" so the sum still holds."""
        # Symmetrically to the good case: a bad game has to be bad for reasons the
        # model weighs, not just a low touch count. Losing your duels and being
        # charged with the danger conceded in your zone is what sinks a defender.
        average = self._averages("DIF", {"clearances": 6.0, "touches": 60.0})
        feats = {"errors_led_to_goal": 1.0, "clearances": 3.0, "touches": 30.0,
                 "duels_lost": 8.0, "dribbled_past": 3.0}
        e = explain("DIF", feats, 90, self.REFERENCE, average, exposure=0.6)
        self.assertLess(e["voto"], 5.5)
        self.assertEqual(e["positives"], [])
        self.assertNotIn("Bene", to_sentence(e))
        shown = e["base"] + sum(c["points"] for c in e["contributions"]) + e["other_points"]
        self.assertAlmostEqual(shown, e["subtotal"], places=2)

    def test_a_clearly_good_vote_drops_the_nitpick_negatives(self):
        """Above 6.5 the "negatives" are trivialities on a fine game (a striker's
        "dribbling concessi all'avversario"); a 7.5 should read as praise. They fold
        into "other" so the sum still holds."""
        # A great game has to be great for a REASON the model weighs heavily, not
        # just an absurd pile of volume: the compression is logarithmic, so 200
        # clearances is worth barely more than 20 and the vote used to land on the
        # 6.5 boundary by luck. A defender who scores while dominating is the case
        # this test is about.
        average = self._averages("DIF", {"clearances": 8.0, "duels_won": 6.0,
                                         "touches": 60.0})
        feats = {"clearances": 12.0, "duels_won": 14.0, "touches": 95.0,
                 "interceptions": 4.0, "shots_goal": 1.0, "xg_on_target": 0.6,
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
