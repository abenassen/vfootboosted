"""Classic formation rules + bench substitution (order-aware) tests."""

from django.test import SimpleTestCase

from vfoot.services.formation_rules import validate_classic_lineup, is_legal_classic
from vfoot.services.lineup_substitution import (
    apply_aura_substitutions,
    apply_classic_substitutions,
)


def _xi(gk=1, df=4, mf=4, at=2):
    return ["GK"] * gk + ["DEF"] * df + ["MID"] * mf + ["ATT"] * at


class FormationRulesTests(SimpleTestCase):
    def test_legal_442(self):
        self.assertTrue(is_legal_classic(_xi(1, 4, 4, 2)))

    def test_legal_352_and_343(self):
        self.assertTrue(is_legal_classic(_xi(1, 3, 5, 2)))
        self.assertTrue(is_legal_classic(_xi(1, 3, 4, 3)))

    def test_no_gk(self):
        self.assertIn("Manca il portiere.", validate_classic_lineup(_xi(0, 4, 5, 2)))

    def test_two_gk(self):
        errs = validate_classic_lineup(_xi(2, 4, 3, 2))
        self.assertTrue(any("Un solo portiere" in e for e in errs))

    def test_too_few_defenders(self):
        errs = validate_classic_lineup(_xi(1, 2, 5, 3))
        self.assertTrue(any("Almeno 3 difensori" in e for e in errs))

    def test_attacker_bounds(self):
        self.assertTrue(any("Almeno 1 attaccante" in e for e in validate_classic_lineup(_xi(1, 5, 5, 0))))
        self.assertTrue(any("Al massimo 3 attaccanti" in e for e in validate_classic_lineup(_xi(1, 3, 3, 4))))

    def test_legal_361(self):
        # Il sesto centrocampista e' legale: il tetto dei sei vale in difesa, non a
        # centrocampo. E' la sola differenza fra il 3-6-1 e il 6-3-1 qui sotto.
        self.assertTrue(is_legal_classic(_xi(1, 3, 6, 1)))

    def test_too_many_defenders(self):
        errs = validate_classic_lineup(_xi(1, 6, 3, 1))
        self.assertTrue(any("Al massimo 5 DIF" in e for e in errs))

    def test_too_many_midfielders(self):
        errs = validate_classic_lineup(_xi(1, 3, 7, 0))
        self.assertTrue(any("Al massimo 6 CEN" in e for e in errs))

    def test_wrong_total(self):
        self.assertTrue(any("esattamente 11" in e for e in validate_classic_lineup(_xi(1, 4, 4, 1))))


class ClassicSubstitutionTests(SimpleTestCase):
    def setUp(self):
        # 4-4-2 starters 1..11; roles by position
        self.starters = list(range(1, 12))
        self.roles = {}
        for pid, r in zip(self.starters, _xi(1, 4, 4, 2)):
            self.roles[pid] = r
        # bench: a DEF, a MID, an ATT, a GK — priority order as listed
        self.bench = [101, 102, 103, 104]
        self.roles.update({101: "DEF", 102: "MID", 103: "ATT", 104: "GK"})

    def test_first_eligible_in_order_wins(self):
        # starter 6 (MID) is s.v.; bench priority 101(DEF) then 102(MID).
        # Replacing a MID with a DEF -> 5 DEF / 3 MID, still legal -> 101 comes in.
        voted = set(self.starters) - {6} | {101, 102, 103}
        res = apply_classic_substitutions(self.starters, self.bench, self.roles, voted)
        self.assertEqual(res.subs, [(6, 101)])
        self.assertIn(101, res.effective)
        self.assertNotIn(6, res.effective)

    def test_skips_bench_that_breaks_constraints(self):
        # starter 2 (DEF) s.v. Bench priority 103(ATT) first, but DEF->ATT makes
        # 3 ATT? we have 2 ATT, +1 = 3 ok... craft a case that DOES break:
        # make 3 ATT already, so DEF->ATT would be 4 ATT (illegal) -> skip 103.
        starters = list(range(1, 12))
        roles = {}
        for pid, r in zip(starters, _xi(1, 4, 3, 3)):
            roles[pid] = r
        bench = [201, 202]
        roles.update({201: "ATT", 202: "DEF"})
        sv = 2  # a DEF
        voted = set(starters) - {sv} | {201, 202}
        res = apply_classic_substitutions(starters, bench, roles, voted)
        # 201 (ATT) would make 4 ATT -> illegal, so 202 (DEF) comes in
        self.assertEqual(res.subs, [(2, 202)])

    def test_unvoted_bench_is_skipped(self):
        voted = set(self.starters) - {6}  # bench all s.v.
        res = apply_classic_substitutions(self.starters, self.bench, self.roles, voted)
        self.assertEqual(res.subs, [])
        self.assertEqual(res.unresolved, [6])

    def test_max_subs_cap(self):
        # 4 MID starters all s.v.; 4 valid MID bench; cap at 2 -> only 2 subs.
        starters = list(range(1, 12))
        roles = {}
        for pid, r in zip(starters, _xi(1, 4, 4, 2)):
            roles[pid] = r
        bench = [401, 402, 403, 404]
        for b in bench:
            roles[b] = "MID"
        sv = [6, 7, 8, 9]  # the 4 MIDs (positions 6-9 in 1+4 offset)
        voted = (set(starters) - set(sv)) | set(bench)
        res = apply_classic_substitutions(starters, bench, roles, voted, max_subs=2)
        self.assertEqual(len(res.subs), 2)
        self.assertEqual(len(res.unresolved), 2)

    def test_bench_player_used_once(self):
        starters = list(range(1, 12))
        roles = {}
        for pid, r in zip(starters, _xi(1, 4, 4, 2)):
            roles[pid] = r
        bench = [301]
        roles[301] = "MID"
        voted = set(starters) - {6, 7} | {301}  # two MID s.v., one bench
        res = apply_classic_substitutions(starters, bench, roles, voted)
        self.assertEqual(len(res.subs), 1)
        self.assertEqual(res.unresolved, [7])


class DefenseBonusTests(SimpleTestCase):
    """Eligibility for the defence modifier. The BANDS themselves are pinned in
    ``tests_classic_scoring.DefenseBandsTest``, which is the only place that
    should assert them: a duplicate lived here and survived the 2026-07-28 fix
    that removed the wrong +3.5 half-step and the +4 cap, so it went on asserting
    the behaviour that fix had just deleted."""

    def test_requires_four_starting_defenders(self):
        from vfoot.services.defense_bonus import compute_defense_bonus
        # only 3 starting DEF -> not eligible even with great votes
        r = compute_defense_bonus(["GK", "DEF", "DEF", "DEF", "MID", "MID", "MID",
                                    "MID", "ATT", "ATT", "ATT"],
                                   [7.0, 7.0, 7.0], 7.0)
        self.assertFalse(r["eligible"])

    def test_eligible_and_average(self):
        from vfoot.services.defense_bonus import compute_defense_bonus, defense_bonus_value
        roles = ["GK"] + ["DEF"] * 4 + ["MID"] * 3 + ["ATT"] * 3
        # i 3 voti piu' alti (7,7,6) piu' il portiere (6) -> media 6.5. Il QUARTO
        # difensore (5.0) non entra: e' li' per verificare che si prendano i tre
        # migliori e non i primi tre.
        r = compute_defense_bonus(roles, [7.0, 7.0, 6.0, 5.0], 6.0)
        self.assertTrue(r["eligible"])
        self.assertAlmostEqual(r["avg"], 6.5)
        # La BANDA non si scrive a numero qui: e' esattamente il duplicato contro cui
        # mette in guardia il docstring di questa classe, e il 01/09/2026 ci e'
        # ricascata — asseriva +2 per la media 6.5 dopo che la correzione delle
        # fasce l'aveva portata a +3. Legata alla fonte unica, non puo' piu' divergere.
        self.assertEqual(r["bonus"], defense_bonus_value(6.5))

    # -- the league's gate: which lineup has to hold four defenders -----------
    #
    # The two readings differ on exactly two lineups, and both are tested here:
    # the 3-4-3 that became a back four through the bench (the "starters" gate
    # refuses, the "effective" one pays) and the back four that lost a man to an
    # s.v. nobody covered (the other way round).

    def test_effective_gate_pays_a_back_four_reached_from_the_bench(self):
        from vfoot.services.defense_bonus import GATE_EFFECTIVE, compute_defense_bonus
        # Schierato 3-4-3, un centrocampista s.v., entra un difensore: quattro
        # difensori a voto, tre titolari.
        starters = ["GK", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID",
                    "ATT", "ATT", "ATT"]
        votes = [7.0, 7.0, 6.0, 6.0]
        self.assertFalse(compute_defense_bonus(starters, votes, 6.0)["eligible"])
        r = compute_defense_bonus(starters, votes, 6.0, GATE_EFFECTIVE)
        self.assertTrue(r["eligible"])
        self.assertAlmostEqual(r["avg"], 6.5)   # 7+7+6 + gk 6, /4

    def test_effective_gate_refuses_a_back_four_that_lost_a_man(self):
        from vfoot.services.defense_bonus import GATE_EFFECTIVE, compute_defense_bonus
        # Quattro difensori schierati, uno senza voto e nessuno in panchina che lo
        # copra: tre a voto.
        roles = ["GK"] + ["DEF"] * 4 + ["MID"] * 3 + ["ATT"] * 3
        self.assertTrue(compute_defense_bonus(roles, [7.0, 7.0, 6.0], 6.0)["eligible"])
        r = compute_defense_bonus(roles, [7.0, 7.0, 6.0], 6.0, GATE_EFFECTIVE)
        self.assertFalse(r["eligible"])
        self.assertEqual(r["reason"], "meno_di_4_difensori_con_voto")

    def test_the_keeper_is_needed_under_either_gate(self):
        from vfoot.services.defense_bonus import GATE_EFFECTIVE, compute_defense_bonus
        roles = ["GK"] + ["DEF"] * 4 + ["MID"] * 3 + ["ATT"] * 3
        for gate in ("starters", GATE_EFFECTIVE):
            r = compute_defense_bonus(roles, [7.0, 7.0, 6.0, 6.0], None, gate)
            self.assertFalse(r["eligible"], gate)
            self.assertEqual(r["reason"], "portiere_senza_voto", gate)

    def test_the_reason_names_the_gate_that_refused(self):
        """The tabellino words the refusal from this, so the two gates must not
        answer with each other's rule."""
        from vfoot.services.defense_bonus import GATE_EFFECTIVE, compute_defense_bonus
        three = ["GK", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID",
                 "ATT", "ATT", "ATT"]
        self.assertEqual(compute_defense_bonus(three, [7.0, 7.0, 7.0], 6.0)["reason"],
                         "meno_di_4_difensori_titolari")
        self.assertEqual(
            compute_defense_bonus(three, [7.0, 7.0, 7.0], 6.0, GATE_EFFECTIVE)["reason"],
            "meno_di_4_difensori_con_voto")


class AuraSubstitutionTests(SimpleTestCase):
    def test_best_score_wins_ignoring_order(self):
        starters = [1, 2, 3]
        bench = [10, 11]  # order puts 10 first
        voted = {2, 3, 10, 11}  # starter 1 s.v.
        score = {10: 5.0, 11: 9.0}  # 11 is better despite being later
        res = apply_aura_substitutions(starters, bench, voted, score)
        self.assertEqual(res.subs, [(1, 11)])

    def test_order_breaks_ties(self):
        starters = [1, 2]
        bench = [10, 11]
        voted = {2, 10, 11}
        score = {10: 7.0, 11: 7.0}
        res = apply_aura_substitutions(starters, bench, voted, score)
        self.assertEqual(res.subs, [(1, 10)])  # equal score -> first in order
