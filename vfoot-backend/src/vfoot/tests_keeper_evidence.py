"""Il portiere poco impegnato: cosa lo tiene sul 6, e cosa NON deve tenercelo.

Il canale del portiere e' ancorato a ``goals_prevented``, una DIFFERENZA contro
l'xGOT affrontato. Su uno o due tiri quella differenza e' in gran parte rumore, e
leggerla a piena forza e' come un portiere che affronta un tiro solo e lo incassa
usciva a 5.0 mentre ogni pagella lo lasciava a 6.0.

La cura, fino al 31/08/2026, era uno smorzamento sotto i quattro tiri in porta
(``GK_EVIDENCE_FULL``). NON C'E' PIU', e questi test inchiodano le due meta' di
quella decisione:

* cio' che PROTEGGE il portiere inoperoso — il centro di ruolo e il credito
  d'assenza — e che rende il freno superfluo;
* cio' che PUNISCE la papera, e che il freno dimezzava proprio quando serviva.

Le tre misure che hanno chiuso il caso stanno nella lapide di GK_EVIDENCE_FULL,
in ``services/classic_rating``.
"""
from __future__ import annotations

from django.test import SimpleTestCase

from vfoot.services.classic_rating import (
    GK_TOTAL_WEIGHTS, GK_WEIGHTS, _raw_vote_from_index, index_for_role,
    vote_center_for,
)
from vfoot.services.vote_explanation import explain, role_average_terms

REFERENCE = {"POR": {"mean": 0.66, "std": 2.17, "n": 764}}
# Il centro del PORTIERE, non il 6 di tutti (6.15 dal 30/08/2026, v.
# ROLE_VOTE_CENTER): e' quello il "par" del ruolo.
GK_CENTER = vote_center_for("POR")


class TheKeeperIsJudgedOnWhatHeDidTests(SimpleTestCase):
    """Nessun secondo freno oltre ai minuti: una partita magra si legge per
    quello che dice, non attenuata perche' dice poco."""

    def test_the_vote_no_longer_takes_a_second_shrinkage(self):
        """L'unico restringimento e' quello dei minuti. Il conto e' esplicito
        perche' e' la riga che il freno modificava."""
        r = REFERENCE["POR"]
        index = r["mean"] - 2 * r["std"]
        vote = _raw_vote_from_index(index, "POR", 90, REFERENCE)
        w = 90 / (90 + 25)          # SHRINKAGE_MINUTES
        from vfoot.services.classic_rating import spread_k_for
        atteso = GK_CENTER + spread_k_for("POR") * w * (-2.0)
        self.assertAlmostEqual(vote, atteso, places=6)

    def test_a_bad_thin_match_is_not_pulled_back_toward_par(self):
        """IL CASO SKORUPSKI: due tiri in porta, quello incassato valeva 0.042 di
        xGOT. Prima il voto grezzo saliva da 5.41 a 5.78 — e siccome cadeva a
        cavallo della griglia dei mezzi punti, da 5.5 diventava 6.0. La papera
        c'era ed era misurata; il freno la dimezzava."""
        r = REFERENCE["POR"]
        index = r["mean"] - 2 * r["std"]
        self.assertLess(_raw_vote_from_index(index, "POR", 90, REFERENCE),
                        GK_CENTER - 0.5)

    def test_a_good_thin_match_is_not_capped_either(self):
        """La grande parata e la grande papera sono la stessa quantita' di
        evidenza: se non attenuiamo l'una non attenuiamo l'altra."""
        r = REFERENCE["POR"]
        index = r["mean"] + 2 * r["std"]
        self.assertGreater(_raw_vote_from_index(index, "POR", 90, REFERENCE),
                           GK_CENTER + 0.5)


class TheIdleKeeperIsProtectedWithoutTheBrakeTests(SimpleTestCase):
    """Il motivo per cui il freno era nato — l'inoperoso punito senza colpe — e'
    coperto da altro. Misurato: con zero tiri affrontati, acceso e spento davano
    lo stesso identico risultato (media 6.00, nessuno sotto il 6)."""

    def test_a_keeper_who_faced_nothing_sits_at_his_role_centre(self):
        """Nessun tiro in porta, niente da prevenire: l'indice non lo condanna."""
        feats = {"gk_saves": 0.0, "gk_goals_prevented": 0.0, "touches": 28.0}
        vote = _raw_vote_from_index(index_for_role("POR", feats, 90), "POR", 90,
                                    REFERENCE)
        self.assertGreaterEqual(vote, GK_CENTER - 0.5)

    def test_the_role_centre_is_above_six(self):
        """Meta' della protezione sta qui: il par del portiere non e' il 6."""
        self.assertGreater(GK_CENTER, 6.0)


class ThePaperaIsPricedTests(SimpleTestCase):
    def test_an_error_leading_to_a_goal_costs_the_keeper_a_real_amount(self):
        """Quando il fornitore la marca. Vale un sesto dell'ancora e le pagelle la
        pagano tre quarti; sotto-pesarla faceva leggere chi la combina come chi ha
        semplicemente subito."""
        clean = {"gk_saves": 3.0, "gk_goals_prevented": 0.2, "touches": 30.0}
        papera = {**clean, "errors_led_to_goal": 1.0}
        drop = index_for_role("POR", clean, 90) - index_for_role("POR", papera, 90)
        self.assertGreater(drop, 0.0)
        v_clean = _raw_vote_from_index(index_for_role("POR", clean, 90), "POR", 90,
                                       REFERENCE)
        v_papera = _raw_vote_from_index(index_for_role("POR", papera, 90), "POR", 90,
                                        REFERENCE)
        self.assertGreater(v_clean - v_papera, 0.15)
        self.assertGreaterEqual(abs(GK_TOTAL_WEIGHTS["errors_led_to_goal"]),
                                0.3 * GK_TOTAL_WEIGHTS["gk_goals_prevented"])

    def test_the_unflagged_papera_is_still_paid_through_goals_prevented(self):
        """E QUANDO NON LA MARCA, che e' il caso piu' frequente: su Skorupski il
        fornitore non ha messo ``errorLeadToAGoal``, e a vedere l'errore e' stato
        ``gk_goals_prevented`` — xGOT affrontato meno gol subiti, gia' pesato per
        la difficolta'. Un gol da 0.04 di xGOT vale -0.96 li' dentro."""
        parato = {"gk_saves": 1.0, "gk_goals_prevented": 0.05, "touches": 28.0}
        incassato = {"gk_saves": 1.0, "gk_goals_prevented": -0.95, "touches": 28.0}
        self.assertGreater(index_for_role("POR", parato, 90),
                           index_for_role("POR", incassato, 90))
        v = _raw_vote_from_index(index_for_role("POR", incassato, 90), "POR", 90,
                                 REFERENCE)
        self.assertLess(v, GK_CENTER)

    def test_a_keepers_inaccurate_passes_are_not_an_error(self):
        """Per un portiere i 'passaggi sbagliati' del fornitore sono soprattutto
        rilancio lungo — uno stile, non uno sbaglio. Non lo premiamo; abbiamo
        smesso di punirlo."""
        self.assertNotIn("errors_bad_passes", GK_WEIGHTS)


class TheBreakdownFollowsTheVoteTests(SimpleTestCase):
    def test_the_breakdown_of_a_thin_match_still_adds_up(self):
        """La spiegazione sottrae le stesse medie e applica lo stesso
        restringimento, quindi base + mostrato + resto deve cadere sul voto."""
        feats = {"gk_saves": 1.0, "gk_goals_prevented": -0.6, "touches": 25.0}
        averages = role_average_terms([("POR", feats, 90, 0.0)])
        his = {"gk_saves": 1.0, "gk_goals_prevented": -1.1, "touches": 28.0}
        x = explain("POR", his, 90, REFERENCE, averages)
        shown = sum(c["points"] for c in x["contributions"])
        self.assertAlmostEqual(x["base"] + shown + x["other_points"], x["subtotal"],
                               places=2)

    def test_no_note_about_few_shots_survives(self):
        """La nota diceva «ogni voce pesa meno e il voto resta vicino al 6»: non e'
        piu' vera, e una spiegazione che descrive un meccanismo rimosso e' peggio
        di nessuna spiegazione."""
        feats = {"gk_saves": 1.0, "gk_goals_prevented": -0.6, "touches": 25.0}
        averages = role_average_terms([("POR", feats, 90, 0.0)])
        x = explain("POR", {"gk_saves": 1.0, "gk_goals_prevented": -1.1,
                            "touches": 28.0}, 90, REFERENCE, averages)
        self.assertNotIn("pochi tiri", x.get("note") or "")
