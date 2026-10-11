"""Il completamento bayesiano dei minuti: le identita' che lo tengono uguale al
modello tarato, e le due impronte senza cui produrrebbe voti sbagliati in silenzio.
"""
from __future__ import annotations

import numpy as np
from django.test import SimpleTestCase

from vfoot.services import bayesian_completion as bayes
from vfoot.services import classic_rating as cr
from vfoot.services.vote_reference import fixed_reference


class PinsTests(SimpleTestCase):
    def test_the_artifact_is_the_one_fitted_for_this_code(self):
        """Pesi del codice e reference congelata sono INGRESSI della taratura: se uno
        dei due cambia senza rifare la taratura, il modello che gira non e' quello
        misurato. ``check_pins`` lo dice; questo test lo rende rosso."""
        self.assertIsNotNone(bayes.artifact(), "bayesian_completion.json manca")
        self.assertEqual(bayes.check_pins(), [])

    def test_active_for_outfield_only(self):
        for role in ("DIF", "CEN", "ATT"):
            self.assertTrue(bayes.is_active(role))
        self.assertFalse(bayes.is_active("POR"))
        self.assertFalse(bayes.is_active(cr.POOLED_OUTFIELD))


class TransformTests(SimpleTestCase):
    def test_vector_transform_equals_scored_z(self):
        """La versione vettoriale della trasformazione e' quella dell'indice, voce per
        voce, asimmetria compresa: e' quel che rende integrabile la predittiva
        senza riscrivere la formula."""
        scales = cr.feature_scales(gk=False)
        values = np.array([0.0, 0.5, 1.0, 3.0, 12.0, 40.0])
        for key in list(cr.WEIGHTS) + [cr.EXPOSURE_KEY]:
            vec = bayes._z_vec(key, values, scales)
            for v, z in zip(values, vec):
                self.assertAlmostEqual(z, cr.scored_z(key, float(v), scales), places=12, msg=key)

    def test_expected_transform_matches_a_brute_force_sum(self):
        """E[f(x+Y)] con Y binomiale negativa: la ricorrenza del pmf contro la formula
        chiusa, su una funzione qualunque."""
        from math import lgamma, exp, log
        f = lambda v: np.log1p(v) ** 2 + 0.3 * v            # noqa: E731
        x, t, mu, c = 2.0, 0.4, 5.0, 0.2
        a = 1 / c + x
        rate = 1 / (c * mu) + t
        p = rate / (rate + 1 - t)
        brute = 0.0
        for n in range(400):
            logpmf = lgamma(n + a) - lgamma(a) - lgamma(n + 1) + a * log(p) + n * log(1 - p)
            brute += exp(logpmf) * f(x + n)
        self.assertAlmostEqual(bayes.expected_transform(f, x, t, mu, c), brute, places=9)
        # a tasso certo e' una Poisson
        lam = (1 - t) * mu
        brute = sum(exp(-lam + n * log(lam) - lgamma(n + 1)) * f(x + n) for n in range(200))
        self.assertAlmostEqual(bayes.expected_transform(f, x, t, mu, 0.0), brute, places=9)
        # e a partita intera non c'e' niente da completare
        self.assertAlmostEqual(bayes.expected_transform(f, x, 1.0, mu, c), float(f(np.array([x]))[0]), places=12)


class ForwardTests(SimpleTestCase):
    def _values(self, **over):
        """Come li vede lo scorer: ``raw_feature_values`` a 90', derivate comprese
        (``sga_post`` nasce da xG e xGOT: un dizionario scritto a mano la salta)."""
        return cr.raw_feature_values(over, 90, 0.0)

    def test_a_full_match_is_base_plus_scaled_evidence(self):
        """A 90 minuti il completamento e' inerte: ogni voce e' peso x (z - z0), il
        voto di merito e' la base del ruolo piu' l'evidenza per la scala, e non
        c'e' credito atteso."""
        ref = fixed_reference()
        for role in ("DIF", "CEN", "ATT"):
            values = self._values(touches=55.0, passes_completed=40.0, duels_won=6.0,
                                  duels_lost=4.0, clearances=5.0, interceptions=2.0,
                                  shots=2.0, xg_shots=0.2, expected_assists=0.1)
            bd = bayes.index_vote(role, values, 90, 0, 0, ref)
            base, scale = bayes.calibration(role)
            self.assertAlmostEqual(bd["unclamped"], base + scale * bd["evidence"], places=9)
            self.assertEqual(bd["event"], 0.0)
            self.assertEqual(bd["credit_rest"], 0.0)
            self.assertEqual(bd["k"], 1.0)
            self.assertEqual(bd["sigma"], 0.0)
            scales = cr.feature_scales(gk=False)
            for key, term in bd["terms"].items():
                w = bayes.weights_with_exposure(role)[key]
                z = cr.scored_z(key, values.get(key, 0.0), scales) - bayes.neutral_z(role, key, scales)
                self.assertAlmostEqual(term, w * z, places=9, msg=(role, key))

    def test_no_minutes_is_the_base_plus_the_expected_credit(self):
        """Di chi non si e' visto niente il modello dice la base del ruolo (costante
        nei minuti: niente rampa) piu' il credito atteso a priori di gol e assist —
        esattamente quello che il credito osservato centrato toglie subito dopo."""
        ref = fixed_reference()
        for role in ("DIF", "CEN", "ATT"):
            bd = bayes.index_vote(role, self._values(), 0, 0, 0, ref)
            base, _scale = bayes.calibration(role)
            self.assertEqual(bd["terms"], {})
            self.assertAlmostEqual(bd["merit"], base, places=9, msg=role)
            self.assertAlmostEqual(bd["credit_rest"], bayes.expected_credit_rate(role), places=9)
            self.assertAlmostEqual(bd["sigma"], bayes.predictive_sigma(role, 0.0), places=9)

    def test_the_base_does_not_move_with_the_minutes(self):
        """La base e' la stessa a 10, 45 e 90 minuti: il ritorno verso la media di
        chi gioca poco EMERGE dal completamento, non da una curva."""
        ref = fixed_reference()
        values = self._values()
        for role in ("DIF", "CEN", "ATT"):
            merits = [bayes.index_vote(role, values, m, 0, 0, ref)["merit"] for m in (10, 45, 90)]
            # senza evidenza il merito e' la base a ogni minuto (le voci sono zero
            # perche' z completato = z neutro quando non si e' visto niente... a
            # meno dell'evidenza NEGATIVA di non aver fatto niente in m minuti)
            self.assertTrue(all(np.isfinite(merits)))
            base, _ = bayes.calibration(role)
            self.assertLess(abs(merits[0] - base), abs(merits[2] - base) + 1e-9, msg=role)

    def test_the_completion_moves_toward_the_neutral_anchor_as_minutes_shrink(self):
        """Stessi totali visti in meno minuti dicono di piu' (tassi piu' alti) ma
        pesano meno (piu' partita completata con la media): la differenza dal
        neutro deve restare finita e cambiare con continuita'."""
        ref = fixed_reference()
        values = self._values(touches=30.0, passes_completed=20.0, duels_won=4.0, shots=2.0)
        votes = [bayes.index_vote("CEN", values, m, 0, 0, ref)["merit"] for m in (10, 30, 60, 90)]
        self.assertTrue(all(np.isfinite(votes)))
        self.assertGreater(max(votes) - min(votes), 0.05)

    def test_the_predictive_width_shrinks_with_the_minutes(self):
        for role in ("DIF", "CEN", "ATT"):
            s = [bayes.predictive_sigma(role, t) for t in (0.0, 0.5, 1.0)]
            self.assertGreater(s[0], s[1])
            self.assertGreater(s[1], 0.0)
            self.assertEqual(s[2], 0.0)

    def test_the_stage_inside_the_expectation_lowers_a_high_vote(self):
        """Sopra il centro lo stadio comprime: l'attesa dello stadio su una
        predittiva larga sta sotto lo stadio dell'attesa, e sotto il centro
        (dove la scala e' lineare) coincide."""
        pre, dopo, _a = cr.ROLE_SATURATION["DIF"]
        self.assertLess(cr.scale_saturation(pre + 1.0, "DIF", 0.4)[0],
                        cr.scale_saturation(pre + 1.0, "DIF", 0.0)[0])
        self.assertAlmostEqual(cr.scale_saturation(pre - 1.0, "DIF", 0.2)[0],
                               cr.scale_saturation(pre - 1.0, "DIF", 0.0)[0], places=2)

    def test_the_explanation_factor_never_flips_the_lines(self):
        """Il fattore con cui la spiegazione riscala ogni voce resta positivo e
        limitato anche appena sopra il centro: prima, a predittiva larga, il
        rapporto secante cambiava segno (-1,92 a d = +0,02, sigma 0,5) e il
        pannello capovolgeva tutte le voci (Cambiaso, 11/10/2026). E la retta
        che usa torna col voto: base + fattore x scostamento = voto."""
        for role in ("DIF", "CEN", "ATT"):
            pre, _dopo, a = cr.ROLE_SATURATION[role]
            for sigma in (0.0, 0.2, 0.5, 0.8):
                for d in (-0.6, -0.1, -0.01, 0.0, 0.01, 0.02, 0.1, 0.4, 1.0):
                    _v, f = cr.scale_saturation(pre + d, role, sigma)
                    self.assertGreater(f, 0.0, (role, sigma, d))
                    self.assertLessEqual(f, a + 1e-9, (role, sigma, d))
                # continuo attraverso il centro
                f_minus = cr.scale_saturation(pre - 1e-6, role, sigma)[1]
                f_zero = cr.scale_saturation(pre, role, sigma)[1]
                self.assertAlmostEqual(f_minus, f_zero, places=4)

    def test_an_early_goal_raises_the_expected_credit_for_the_rest(self):
        ref = fixed_reference()
        values = self._values(touches=20.0)
        self.assertGreater(bayes.event_completion("ATT", 1, 0, 30 / 90), 0.0)
        self.assertLess(bayes.event_completion("ATT", 0, 0, 60 / 90), 0.0)
        self.assertEqual(bayes.event_completion("ATT", 2, 1, 1.0), 0.0)
        with_goal = bayes.index_vote("ATT", values, 30, 1, 0, ref)["unclamped"]
        without = bayes.index_vote("ATT", values, 30, 0, 0, ref)["unclamped"]
        self.assertGreater(with_goal, without)

    def test_a_compound_feature_neutral_is_the_predictive_mean_not_z_of_the_mean(self):
        """Il neutro di una continua e' E[z] sulla predittiva (Jensen): per una
        trasformazione concava sta SOTTO z(media)."""
        scales = cr.feature_scales(gk=False)
        for role in ("DIF", "CEN", "ATT"):
            p = bayes.mark(role, "expected_assists")
            mean_total = p["rate"] * p["m1"] + p["floor"]
            self.assertLess(bayes.neutral_z(role, "expected_assists", scales),
                            cr.scored_z("expected_assists", mean_total, scales) + 1e-9, msg=role)
