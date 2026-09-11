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

    def test_a_full_match_is_the_calibrated_full_match_vote(self):
        """A 90 minuti il completamento e' inerte: il voto-indice e' la formula di
        partita intera (``_raw_vote_from_index`` a 90'), e sopra ci sta solo la
        calibrazione affine del ruolo."""
        ref = fixed_reference()
        for role in ("DIF", "CEN", "ATT"):
            values = self._values(touches=55.0, passes_completed=40.0, duels_won=6.0,
                                  duels_lost=4.0, clearances=5.0, interceptions=2.0,
                                  shots=2.0, xg_shots=0.2, expected_assists=0.1)
            totals = dict(touches=55.0, passes_completed=40.0, duels_won=6.0, duels_lost=4.0,
                          clearances=5.0, interceptions=2.0, shots=2.0, xg_shots=0.2,
                          expected_assists=0.1)
            idx = cr.index_for_role(role, totals, 90, 0.0)
            obs = cr.observed_index(role, totals, 90, 0.0)
            full = cr._raw_vote_from_index(idx, role, 90, ref, observed=obs)
            bd = bayes.index_vote(role, values, 90, 0, 0, ref)
            self.assertAlmostEqual(bd["v_index"], full, places=9, msg=role)
            dc, s, c0 = bayes.calibration(role)
            self.assertAlmostEqual(bd["unclamped"], c0 + dc + s * (full - c0), places=9)
            self.assertEqual(bd["event"], 0.0)

    def test_no_minutes_is_exactly_six_after_the_scale(self):
        """Di chi non si e' visto niente si dice 6: l'ancora neutra passa per la
        calibrazione (che la lascia dove sta a meno di delta_c) e per lo stadio
        finale, e il credito medio di gol/assist che porta con se' e' esattamente
        quello che il credito osservato centrato toglie."""
        from vfoot.services import goal_impact
        ref = fixed_reference()
        for role in ("DIF", "CEN", "ATT"):
            bd = bayes.index_vote(role, self._values(), 0, 0, 0, ref)
            old_mean = (goal_impact.role_mean_credit().get(role, 0.0)
                        + goal_impact.role_mean_assist_credit().get(role, 0.0))
            dc, s, c0 = bayes.calibration(role)
            self.assertAlmostEqual(bd["v_index"], c0 + old_mean, places=9, msg=role)
            self.assertAlmostEqual(cr.scale_saturation(c0, role)[0], 6.0, places=9)
            self.assertEqual(bd["terms"], {})

    def test_the_completion_moves_toward_the_neutral_anchor_as_minutes_shrink(self):
        """Stessi totali visti in meno minuti dicono di piu' (tassi piu' alti) ma
        pesano meno (piu' partita completata con la media): la differenza dal
        neutro deve restare finita e cambiare con continuita'."""
        ref = fixed_reference()
        values = self._values(touches=30.0, passes_completed=20.0, duels_won=4.0, shots=2.0)
        votes = [bayes.index_vote("CEN", values, m, 0, 0, ref)["v_index"] for m in (10, 30, 60, 90)]
        self.assertTrue(all(np.isfinite(votes)))
        self.assertGreater(max(votes) - min(votes), 0.05)

    def test_an_early_goal_raises_the_expected_credit_for_the_rest(self):
        ref = fixed_reference()
        values = self._values(touches=20.0)
        self.assertGreater(bayes.event_completion("ATT", 1, 0, 30 / 90), 0.0)
        self.assertLess(bayes.event_completion("ATT", 0, 0, 60 / 90), 0.0)
        self.assertEqual(bayes.event_completion("ATT", 2, 1, 1.0), 0.0)
        with_goal = bayes.index_vote("ATT", values, 30, 1, 0, ref)["unclamped"]
        without = bayes.index_vote("ATT", values, 30, 0, 0, ref)["unclamped"]
        self.assertGreater(with_goal, without)
