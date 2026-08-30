"""The result-mitigation nudge is DIVERGENCE-ONLY, and ASYMMETRIC.

The whole point of the mechanism is that it corrects a vote only when it diverges
from the team's on-pitch fortunes — a high vote in a defeat, a low vote in a win —
and NEVER when the two already agree. An earlier symmetric additive version failed
exactly here: it further inflated a high vote in a win (De Ketelaere). These tests
pin the asymmetry so a refactor cannot quietly reintroduce that.

Dal 30/08/2026 i due lati non hanno più lo stesso bersaglio, e la differenza è il
punto della modifica: nella SCONFITTA la tirata punta a ``centro − ancora``, quindi
una goleada subita può portare il voto sotto il centro di ruolo; nella VITTORIA il
bersaglio resta il centro e nessuno lo scavalca. I test qui sotto tengono ferme
entrambe le metà — è facile, rifattorizzando, riunificarle per simmetria e
riportare un 6.0 in un 0-4 a valere 6.0.
"""
from __future__ import annotations

from django.test import SimpleTestCase

from vfoot.services.classic_rating import (
    RESULT_MITIGATION_CAP, RESULT_MITIGATION_LOSS_ANCHOR,
    RESULT_MITIGATION_LOSS_BASE, RESULT_MITIGATION_LOSS_K,
    RESULT_MITIGATION_LOSS_MAX_SHARE, RESULT_MITIGATION_MAX_SHARE,
    red_card_penalty, result_mitigation,
)


class ResultMitigationTests(SimpleTestCase):
    def test_high_vote_in_a_defeat_comes_down(self):
        self.assertLess(result_mitigation(8.0, -2), 0)

    def test_low_vote_in_a_win_goes_up(self):
        self.assertGreater(result_mitigation(4.0, 2), 0)

    def test_high_vote_in_a_win_is_left_alone(self):
        # The regression guard: an aligned high vote must NOT be inflated further.
        self.assertEqual(result_mitigation(8.5, 3), 0.0)

    def test_a_vote_below_the_anchor_is_left_alone_in_a_defeat(self):
        # Chi ha già preso meno dell'ancora non viene spinto ancora più giù: la
        # sconfitta abbassa il bersaglio, non sfonda il pavimento.
        self.assertEqual(result_mitigation(4.0, -3), 0.0)

    def test_a_draw_gets_nothing(self):
        self.assertEqual(result_mitigation(9.0, 0), 0.0)

    def test_it_only_ever_pulls_toward_the_result(self):
        self.assertLessEqual(8.0 + result_mitigation(8.0, -5), 8.0)
        self.assertGreaterEqual(4.0 + result_mitigation(4.0, 5), 4.0)

    # -- il lato SCONFITTA: sotto il centro si può andare, sotto l'ancora no ----

    def test_a_defeat_can_take_a_vote_below_the_centre(self):
        """Il motivo per cui esiste l'asimmetria. Prima della modifica il voto
        medio, in una goleada subita, si fermava sul 6: lo scarto residuo contro
        le pagelle era +0.21 a tre gol di differenza."""
        self.assertLess(6.0 + result_mitigation(6.0, -3), 6.0)

    def test_a_defeat_never_crosses_the_anchor_at_any_margin(self):
        """L'invariante nuovo, che sostituisce «sempre verso il 6, mai oltre»:
        il pavimento è ``centro − ancora``, e la quota < 1 lo rende irraggiungibile
        per costruzione a qualunque scarto."""
        floor = 6.0 - RESULT_MITIGATION_LOSS_ANCHOR
        for gd in range(1, 10):
            for raw in (6.0, 6.5, 6.876, 8.0):
                self.assertGreater(raw + result_mitigation(raw, -gd), floor,
                                   f"grezzo {raw} a scarto -{gd}: sfondata l'ancora")

    def test_the_defeat_leaves_a_share_of_the_divergence(self):
        """Il risultato tempera, non azzera — vale ora rispetto all'ANCORA. Se la
        quota arrivasse a 1 l'intera squadra sconfitta finirebbe inchiodata sullo
        stesso voto e l'ordine di merito interno sparirebbe."""
        # 6.5 e non 6.876: su quest'ultimo morde il cap in punti di voto, che è
        # l'altro limite e risponde a un'altra domanda (v. il test qui sotto).
        raw, floor = 6.5, 6.0 - RESULT_MITIGATION_LOSS_ANCHOR
        residuo = raw + result_mitigation(raw, -6) - floor
        self.assertAlmostEqual(residuo,
                               (raw - floor) * (1 - RESULT_MITIGATION_LOSS_MAX_SHARE),
                               places=6)

    # -- il lato VITTORIA: invariato, e si ferma sul centro --------------------

    def test_a_win_never_lifts_a_vote_past_the_centre(self):
        """Chiesto esplicitamente: una goleada inflitta può portare un voto basso
        al massimo AL 6, mai al 6.5. Qui l'ancora non entra."""
        for gd in range(1, 10):
            for raw in (4.0, 5.2, 5.9):
                self.assertLessEqual(raw + result_mitigation(raw, gd), 6.0,
                                     f"grezzo {raw} a scarto +{gd}: scavalcato il 6")

    def test_the_win_side_keeps_the_old_constants(self):
        """Se qualcuno riunifica i due lati, questo test cade: la vittoria usa
        ancora BASE 0.40 + K 0.15 con quota 0.70, che è quel che rende il suo
        effetto a un gol diverso da quello della sconfitta."""
        self.assertAlmostEqual(result_mitigation(5.0, 2),
                               (6.0 - 5.0) * min(RESULT_MITIGATION_MAX_SHARE,
                                                 0.40 + 0.15 * 2))

    def test_the_two_sides_are_not_mirror_images(self):
        """La stessa distanza dal centro, lo stesso scarto: la sconfitta morde di
        più perché misura da più in basso."""
        giu = -result_mitigation(6.8, -3)
        su = result_mitigation(5.2, 3)
        self.assertGreater(giu, su)

    # -- forma della severità ---------------------------------------------------

    def test_the_share_stops_growing_once_capped(self):
        """Oltre il tetto, un gol in più non toglie più niente."""
        self.assertEqual(result_mitigation(6.5, -5), result_mitigation(6.5, -9))

    def test_the_nudge_is_capped(self):
        huge = result_mitigation(10.0, -9)  # would be -3.7 uncapped
        self.assertAlmostEqual(huge, -RESULT_MITIGATION_CAP)

    def test_it_grows_with_the_margin_on_both_sides(self):
        self.assertLess(result_mitigation(6.5, -4), result_mitigation(6.5, -1))
        self.assertGreater(result_mitigation(5.5, 4), result_mitigation(5.5, 1))

    def test_a_defeat_costs_a_discrete_base_beyond_the_margin(self):
        # The result base makes ANY defeat cost more than the pure per-goal term.
        self.assertLess(result_mitigation(8.0, -1),
                        result_mitigation(8.0, -1, loss_base=0.0))

    def test_crossing_into_defeat_weighs_more_than_a_further_goal(self):
        # draw->defeat (0->1) should drop the vote more than 1->2 (base on the first).
        d01 = result_mitigation(6.5, -1) - result_mitigation(6.5, 0)
        d12 = result_mitigation(6.5, -2) - result_mitigation(6.5, -1)
        self.assertLess(d01, d12)  # both negative; the first step is the bigger drop

    def test_loss_base_zero_reproduces_the_pure_linear_rule(self):
        floor = 6.0 - RESULT_MITIGATION_LOSS_ANCHOR
        self.assertAlmostEqual(
            result_mitigation(8.0, -2, loss_base=0.0),
            -(8.0 - floor) * RESULT_MITIGATION_LOSS_K * 2)

    def test_one_goal_of_margin_still_costs_what_it_used_to(self):
        """Il vincolo della taratura: con l'ancora a 0.35 la severità a un gol è
        stata riportata a 0.35 (da 0.55) perché l'effetto MEDIO su una sconfitta di
        misura restasse quello di prima. Sul singolo voto le due formule non
        coincidono — è il punto — ma sul voto tipico devono restare vicine."""
        vecchia = -(6.5 - 6.0) * (0.40 + 0.15 * 1)                 # -0.275
        nuova = result_mitigation(6.5, -1)
        self.assertAlmostEqual(nuova, vecchia, delta=0.05)
        self.assertAlmostEqual(RESULT_MITIGATION_LOSS_BASE + RESULT_MITIGATION_LOSS_K,
                               0.35, places=6)

    def test_the_anchor_is_measured_from_the_role_centre_not_from_six(self):
        """Un difensore è costruito attorno a 5.91, non a 6: se l'ancora partisse
        dal 6 fisso, in ogni sconfitta il difensore medio verrebbe trattato come un
        voto alto da temperare."""
        self.assertEqual(result_mitigation(5.91 - RESULT_MITIGATION_LOSS_ANCHOR, -3,
                                           centre=5.91), 0.0)
        self.assertLess(result_mitigation(5.91, -3, centre=5.91), 0.0)


class RedCardPenaltyTests(SimpleTestCase):
    def test_earlier_sending_off_costs_more(self):
        early = red_card_penalty("Foul", 10, 95)
        late = red_card_penalty("Foul", 85, 95)
        self.assertGreater(early, late)

    def test_severity_orders_dogso_below_foul_below_violent(self):
        dogso = red_card_penalty("Professional foul last man", 20, 95)
        foul = red_card_penalty("Foul", 20, 95)
        violent = red_card_penalty("Violent conduct", 20, 95)
        self.assertLess(dogso, foul)
        self.assertLess(foul, violent)

    def test_indefensible_reasons_carry_a_fixed_floor(self):
        # A violent conduct at the final whistle still costs the fixed 0.3, unlike a
        # last-second foul which fades to ~0.
        self.assertAlmostEqual(red_card_penalty("Violent conduct", 95, 95), 0.3)
        self.assertAlmostEqual(red_card_penalty("Foul", 95, 95), 0.0)

    def test_an_unknown_reason_uses_the_default_severity(self):
        self.assertAlmostEqual(red_card_penalty("Unheard of", 20, 95),
                               red_card_penalty("Foul", 20, 95))
