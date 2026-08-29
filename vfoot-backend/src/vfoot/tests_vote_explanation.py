"""A vote nobody can interrogate is a vote nobody will trust."""
from __future__ import annotations

from django.test import SimpleTestCase

from vfoot.services.vote_explanation import (
    COUNT, EVENT, SIGNAL, LABELS, QUANTIFIERS, _phrase, explain, ledger_phrase,
    readable_label, role_average_terms, to_sentence,
)
from vfoot.services.classic_rating import (
    VOTE_CENTER, VOTE_MAX, VOTE_MIN, VOTE_SPREAD_K, SHRINKAGE_MINUTES,
    vote_center_for,
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
        # vote_center_for: dal 25/08/2026 il centro dipende dal ruolo, e questo
        # fixture e' un DIF (ROLE_VOTE_CENTER).
        raw = max(VOTE_MIN, min(VOTE_MAX,
                                vote_center_for("DIF") + VOTE_SPREAD_K * w * z))
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
        # vote_center_for, non 6.0: il centro dipende dal ruolo (ROLE_VOTE_CENTER).
        self.assertAlmostEqual(vote_center_for("DIF") + total, e["subtotal"], places=2)
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
        nome."""
        # ``shots_off`` e' rimasta l'unica feature pesata senza frase parlata:
        # compare solo dentro la riga unita delle conclusioni, mai da sola.
        self.assertEqual(ledger_phrase("ATT", "shots_off", -0.02, 0.0), "tiri fuori")
        self.assertEqual(ledger_phrase("DIF", "shots_goal", -0.03, 0.0), "nessun gol")
        self.assertEqual(ledger_phrase("DIF", "big_chance_created", -0.02, 0.0),
                         "nessun'occasione nitida creata")
        self.assertEqual(ledger_phrase("DIF", "expected_assists", -0.03, 0.0),
                         "occasioni create per i compagni")
        # e quando la frase c'e', e' la stessa del riassunto
        self.assertEqual(ledger_phrase("DIF", "clearances", +0.3, 8.0), "tante respinte")
        # ``defensive_value`` una frase ce l'ha dal 24/08/2026, generica per forza:
        # e' una sintesi che non si scompone in un gesto del tabellino, ed e' in
        # parte collettiva. Prima taceva, ed era la voce piu' grande del voto.
        self.assertEqual(ledger_phrase("DIF", "defensive_value", +0.28, 0.44),
                         "buon contributo difensivo d'insieme")
        self.assertEqual(ledger_phrase("DIF", "defensive_value", -0.28, -0.44),
                         "poco contributo difensivo d'insieme")

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
        # un indice normalizzato non porta MAI un numero accanto: "0,44" non
        # spiega niente. Ora e' la voce piu' grande e sta nel riassunto, dove i
        # numeri accanto non ci vanno per costruzione.
        shown = {c["label"]: c for c in e["contributions"]}
        self.assertIn("buon contributo difensivo d'insieme", shown)
        self.assertNotIn("value", shown["buon contributo difensivo d'insieme"])

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
        self.assertIn("pallone di poco valore", cheap["assist_note"])
        self.assertNotIn("gol", cheap["assist_note"])
        self.assertIn("valgono 0.05 di xA", cheap["assist_note"])
        self.assertIn("poco valore", to_sentence(cheap))
        # Il passaggio che VALEVA non ha piu' bisogno di una nota: da quando
        # big_chance_created pesa zero, la creazione la leggono xA e key_passes e
        # il voto la paga per intero. Non c'e' niente da scusare.
        rich = explain("CEN", {"expected_assists": 0.6, "touches": 60.0}, 90,
                       self.REFERENCE | {"CEN": {"mean": 0.41, "std": 0.44}},
                       average, assists=1)
        self.assertEqual(rich["assist_note"], "")
        due = explain("CEN", {"expected_assists": 0.05, "touches": 60.0}, 90,
                      self.REFERENCE | {"CEN": {"mean": 0.41, "std": 0.44}},
                      average, assists=2)
        self.assertIn("gli assist nascono da palloni di poco valore", due["assist_note"])
        self.assertIn("palloni di poco valore", due["assist_note"])
        for nota in (cheap["assist_note"], due["assist_note"]):
            self.assertNotIn("pesa a parte", nota)
            self.assertNotIn("valore atteso", nota)
            # key_passes ora paga quel passaggio: la negazione secca era diventata falsa
            self.assertNotIn("non nel voto base", nota)
            # key_passes E assists pesano: il voto base legge entrambi
            self.assertNotIn("non il gol", nota)
        # con l'occasione riconosciuta non c'e' niente da spiegare: il voto ha gia'
        # pagato il gesto per intero, da entrambe le voci
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
        # Rinforzato una seconda volta il 25/08/2026: ``dribbled_past`` e' passato a
        # -0.045 PER I DIFENSORI (ROLE_WEIGHTS), e 3 dribbling concessi valgono ora
        # -0.16 invece di -0.12, che bastava a riportare il fixture da 6.780 a
        # 6.730 — sotto la soglia dell'arrotondamento. La lezione, la stessa della
        # prima volta: questo fixture deve avere MARGINE, non appoggiarsi al
        # confine. Ora sta a 6.920, +0.17 sopra.
        # Il gol arriva dal 29/08/2026 come voce A LIVELLO DI VOTO e non piu' come
        # feature dell'indice (v. services/goal_impact): senza passarlo qui il
        # fixture non e' piu' "un difensore che segna dominando", e' un difensore
        # che domina — che sul confine del 6.5 non ci arriva.
        average = self._averages("DIF", {"clearances": 8.0, "duels_won": 6.0,
                                         "touches": 60.0})
        feats = {"clearances": 12.0, "duels_won": 18.0, "touches": 95.0,
                 "interceptions": 4.0, "tackles_won": 5.0,
                 "xg_on_target": 0.6, "dribbled_past": 3.0}
        e = explain("DIF", feats, 90, self.REFERENCE, average,
                    goal_adjustment=0.52,
                    goal_detail=[{"minute": 70, "own_after": 1, "opp_after": 0,
                                  "importance": 1.34}])
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
        # a novanta minuti l'avvertenza sui minuti non si dice (quel fixture e' una
        # prestazione piatta, quindi ``note`` porta l'altra avvertenza: si controlla
        # che manchi QUESTA, non che la riga sia vuota)
        self.assertNotIn("pochi minuti",
                         explain("DIF", {"touches": 60.0}, 90,
                                 self.REFERENCE, average)["note"])

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

    # --- lo zero non e' "poco" -------------------------------------------
    def test_a_count_at_zero_is_named_as_nothing_not_as_few(self):
        """"pochi duelli vinti" a chi non ne ha giocato nessuno implica che qualcuno
        l'abbia vinto, e chi va a cercarlo nel tabellino non lo trova. Sulla 25-26
        una riga cosi' compariva nel 39,6% delle spiegazioni."""
        self.assertEqual(_phrase("DIF", "duels_won", -0.3, 0.0), "nessun duello vinto")
        self.assertEqual(_phrase("DIF", "clearances", -0.3, 0.0), "nessuna respinta")
        self.assertEqual(_phrase("CEN", "long_balls_completed", -0.3, 0.0),
                         "nessun lancio lungo riuscito")
        # ma UNO e' ancora "pochi": lo zero e' l'unico caso speciale
        self.assertEqual(_phrase("DIF", "clearances", -0.3, 1.0), "poche respinte")

    def test_a_zero_that_helps_the_vote_is_not_praised(self):
        """Elogiare per un duello non perso chi non e' mai entrato in un duello e'
        rumore: era l'UNICO lato positivo di 449 spiegazioni della 25-26. I punti
        restano e finiscono in "altre voci", quindi il conto torna lo stesso."""
        self.assertIsNone(_phrase("DIF", "duels_lost", +0.3, 0.0))
        self.assertIsNone(_phrase("DIF", "dribbled_past", +0.3, 0.0))
        # con un duello perso davvero la lode torna a essere legittima
        self.assertEqual(_phrase("DIF", "duels_lost", +0.3, 2.0), "pochi duelli persi")

    def test_a_grandezza_continua_a_zero_resta_col_quantificatore(self):
        """Solo le grandezze che si CONTANO hanno un "nessuno": per un indice
        normalizzato lo zero e' un valore come un altro, non un'assenza."""
        self.assertEqual(_phrase("POR", "gk_goals_prevented", -0.3, 0.0),
                         "pochi gol evitati rispetto ai tiri affrontati")

    def test_a_family_with_no_attempt_says_it_never_tried(self):
        """Il netto della famiglia si sceglieva col solo segno, e con tutti i tiri a
        zero il segno e' negativo perche' il pari ruolo medio qualche tiro lo fa: la
        pagina diceva "una o piu' occasioni fallite" a chi non aveva tirato mai —
        il 43,1% delle spiegazioni della 25-26."""
        average = self._averages("DIF", {"shots": 2.0, "shots_on_target": 1.0,
                                         "touches": 60.0})
        e = explain("DIF", {"touches": 60.0}, 90, self.REFERENCE, average)
        said = [c["label"] for c in e["contributions"]]
        self.assertIn("nessuna conclusione tentata", said)
        self.assertNotIn("una o più occasioni fallite", said)
        # e chi ha tirato male resta rimproverato per come ha tirato
        shot = explain("DIF", {"shots": 3.0, "touches": 60.0}, 90,
                       self.REFERENCE, average)
        self.assertIn("una o più occasioni fallite",
                      [c["label"] for c in shot["contributions"]])

    # --- la partita senza sporgenze --------------------------------------
    def test_a_flat_game_shows_its_largest_entries_instead_of_nothing(self):
        """113 spiegazioni della 25-26 non dicevano NIENTE perche' nessuna voce
        arrivava al ventesimo di voto — fra queste portieri che avevano giocato
        novanta minuti. Si mostrano lo stesso le piu' grandi, e ``flat`` avverte chi
        scrive la frase di non spacciarle per un giudizio."""
        average = self._averages("DIF", {"touches": 60.0, "duels_won": 3.0})
        e = explain("DIF", {"touches": 61.0, "duels_won": 3.0}, 90,
                    self.REFERENCE, average)
        self.assertTrue(e["flat"])
        self.assertTrue(e["positives"] or e["negatives"])
        self.assertIn("in linea con la media", to_sentence(e))
        self.assertIn("si avvicinano a spostarla", to_sentence(e))

    def test_a_big_unnamed_driver_keeps_the_summary_silent(self):
        """"Piatta" vuol dire che non c'e' niente di grosso, non che il pezzo grosso
        non ha un nome: promuovere due voci da 0,01 direbbe che la partita e' stata
        insignificante mentre il voto lo muoveva un'altra.

        Da quando ``defensive_value`` parla, il caso resta solo per gli EVENT che
        non sono accaduti — chi non conquista un rigore perde il credito che il
        pari ruolo medio prende dai rigori conquistati, e "nessun rigore
        conquistato" nella frase parlata non si dice per scelta di sempre.

        L'esempio era ``shots_goal`` fino al 29/08/2026; da quando il gol e' uscito
        dall'indice quella feature non muove piu' niente, e il caso si mostra con
        un altro EVENT raro dello stesso tipo."""
        average = self._averages("ATT", {"penalties_won": 1.0, "touches": 60.0})
        e = explain("ATT", {"touches": 60.0}, 90, self.REFERENCE, average)
        self.assertFalse(e["flat"])
        self.assertEqual(to_sentence(e),
                         "Prestazione in linea con la media del suo ruolo.")

    def test_no_label_mentions_who_supplies_the_data(self):
        """Le etichette parlano al lettore della pagella, non della nostra catena di
        fornitura: "indice del fornitore" chiede a chi legge di sapere che esiste un
        fornitore. Forma impersonale ovunque."""
        from vfoot.services.vote_explanation import LEDGER_LABELS, TABLE_ONLY_LABELS
        for table in (LABELS, LEDGER_LABELS, TABLE_ONLY_LABELS):
            for key, entry in table.items():
                text = " ".join(x for x in (entry if isinstance(entry, tuple) else (entry,))
                                if isinstance(x, str))
                for banned in ("fornitore", "provider", "SofaScore"):
                    self.assertNotIn(banned.lower(), text.lower(), key)

    def test_the_creation_line_names_the_clear_chances_it_contains(self):
        """La xA e' un valore atteso e si dice vaga ("una o piu'"). Ma quando ci sono
        occasioni nitide riconosciute un intero da contare esiste, ed e' il fatto piu'
        verificabile della partita di chi crea: Dybala in Roma-Fiorentina ne ha tre e
        la sua spiegazione non le nominava. Il peso ZERO di big_chance_created dice
        quanto quel dato vale nel voto, non se si puo' usare per raccontarlo."""
        from vfoot.services.vote_explanation import creation_detail
        base = "una o più occasioni create per i compagni"
        self.assertEqual(creation_detail(base, 0, 0.05), base)   # xA bassa: si tace
        self.assertEqual(creation_detail(base, 0, 0.34), f"{base} (nessuna nitida)")
        self.assertEqual(creation_detail(base, 1), f"{base} (una nitida)")
        self.assertEqual(creation_detail(base, 3), f"{base} (3 nitide)")
        # e nella spiegazione vera
        average = self._averages("ATT", {"touches": 60.0})
        e = explain("ATT", {"expected_assists": 1.09, "big_chance_created": 3.0,
                            "touches": 60.0}, 79,
                    self.REFERENCE | {"ATT": {"mean": 0.47, "std": 0.44}}, average)
        said = " ".join(c["label"] for c in e["contributions"])
        self.assertIn("(3 nitide)", said)
        # e il verso opposto: creazione sostanziosa ma nessuna palla-gol vera.
        # Due partite che la sola xA confonderebbe.
        senza = explain("CEN", {"expected_assists": 0.34, "key_passes": 3.0,
                                "touches": 41.0}, 75,
                        self.REFERENCE | {"CEN": {"mean": 0.41, "std": 0.44}},
                        self._averages("CEN", {"touches": 60.0}))
        self.assertIn("(nessuna nitida)",
                      " ".join(c["label"] for c in senza["contributions"]))
        # la riga e' la famiglia CREAZIONE (xA + assist): la parentesi porta i due
        # numeri del tabellino, i punti sono il netto delle due voci
        riga = [c for c in e["contributions"] if "nitide" in c["label"]][0]
        self.assertEqual(riga.get("family"), "creazione")

    def test_creation_says_chances_and_assists_in_one_line(self):
        """xA e assist sono due voci dello stesso gesto: separate raccontavano la
        stessa cosa due volte. Unite dicono la storia intera in una riga."""
        from vfoot.services.vote_explanation import creation_detail
        base = "una o più occasioni create per i compagni"
        self.assertEqual(creation_detail(base, 3, 1.09, 3), f"{base} (3 nitide, 3 assist)")
        self.assertEqual(creation_detail(base, 0, 0.34, 2), f"{base} (nessuna nitida, 2 assist)")
        self.assertEqual(creation_detail(base, 1, 0.20, 1), f"{base} (una nitida, un assist)")
        self.assertEqual(creation_detail(base, 0, 0.02, 0), base)
        average = self._averages("CEN", {"touches": 60.0})
        e = explain("CEN", {"expected_assists": 0.34, "assists": 2.0, "touches": 60.0}, 75,
                    self.REFERENCE | {"CEN": {"mean": 0.41, "std": 0.44}}, average)
        said = " ".join(c["label"] for c in e["contributions"])
        self.assertIn("(nessuna nitida, 2 assist)", said)
        # una riga sola, non due
        self.assertEqual(sum(1 for c in e["contributions"] if "occasioni create" in c["label"]), 1)
        self.assertNotIn("2 assist,", said.replace("(nessuna nitida, 2 assist)", ""))

    def test_a_small_count_is_written_as_a_number_not_as_many(self):
        """"tanti falli commessi · 1" dice "molti" di UNO. Il quantificatore
        confronta con la media del ruolo, e su un numero piccolo quel confronto
        produce frasi assurde: su Malen (tripletta col Milan) sei righe su 23 erano
        cosi'. Fino a COUNT_SAY_NUMBER_UPTO si scrive il numero."""
        from vfoot.services.vote_explanation import _phrase as ph
        self.assertEqual(ph("ATT", "errors_fouls_committed", -0.01, 1.3, count=1),
                         "1 fallo commesso")
        self.assertEqual(ph("ATT", "was_fouled", +0.01, 2.6, count=2),
                         "2 falli subiti")
        self.assertEqual(ph("ATT", "key_passes", +0.06, 1.3, count=1),
                         "1 passaggio chiave")
        # "solo" quando e' SOTTO la media del ruolo: il numero nudo perde la
        # direzione che il quantificatore portava, e "3 duelli persi" accanto a un
        # PIU' sembra una contraddizione senza di essa.
        self.assertEqual(ph("DIF", "clearances", -0.3, 3.9, count=3),
                         "solo 3 respinte")
        self.assertEqual(ph("ATT", "duels_lost", +0.02, 4.0, count=3),
                         "solo 3 duelli persi")
        self.assertEqual(ph("ATT", "duels_lost", -0.02, 4.0, count=3),
                         "3 duelli persi")
        # sopra la soglia il quantificatore torna, perche' li' porta l'informazione
        # in piu' che il numero da solo non da'
        self.assertEqual(ph("ATT", "touches", +0.01, 49.0, count=37),
                         "tanti palloni giocati")
        # e senza count (il riassunto parlato) il comportamento e' quello di sempre
        self.assertEqual(ph("ATT", "was_fouled", +0.01, 2.6), "tanti falli subiti")

    def test_the_number_is_not_written_twice(self):
        """"2 falli subiti · 2" e "nessun gol · 0" scrivono lo stesso numero due
        volte: quando la frase lo DICE gia', la colonna del conteggio tace."""
        average = self._averages("DIF", {"clearances": 8.0, "touches": 60.0,
                                         "was_fouled": 4.0, "duels_won": 6.0})
        e = explain("DIF", {"clearances": 2.0, "touches": 40.0, "was_fouled": 1.0,
                            "duels_won": 1.0}, 45, self.REFERENCE, average,
                    ledger=True)
        rows = {r["label"]: r for r in e["other_terms"]}
        rows.update({c["label"]: c for c in e["contributions"]})
        detto = [l for l in rows
                 if l.startswith(("1 ", "2 ", "3 ", "nessun", "solo "))]
        self.assertTrue(detto, "il ramo numerico non ha prodotto nessuna riga")
        for l in detto:
            self.assertNotIn("value", rows[l], f"numero scritto due volte: {l}")

    def test_a_continuous_quantity_never_carries_a_count(self):
        """Un indice normalizzato o un valore atteso non e' un numero di cose:
        "pericolo concesso nella sua zona · 0" su un'esposizione di 0,004 afferma
        una precisione che non esiste. Il test "e' quasi intero" lasciava passare
        proprio i quasi-zero."""
        from vfoot.services.vote_explanation import CONTINUOUS_KEYS
        average = self._averages("ATT", {"touches": 60.0, "defensive_value": 0.1})
        e = explain("ATT", {"touches": 60.0, "defensive_value": 0.44,
                            "expected_assists": 0.004}, 90,
                    self.REFERENCE | {"ATT": {"mean": 0.47, "std": 0.44}},
                    average, exposure=0.004, ledger=True)
        for r in e["other_terms"]:
            if r["key"] in CONTINUOUS_KEYS:
                self.assertNotIn("value", r, f"{r['key']} non si conta")
