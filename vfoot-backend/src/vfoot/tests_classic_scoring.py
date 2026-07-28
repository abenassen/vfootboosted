"""Unit tests for the shared classic scoring engine (services/classic_scoring.py).

Pure computation, no DB — SimpleTestCase. Fantavoto is set equal to voto puro in
these fixtures (no bonus/malus) so the expected totals are easy to read.
"""

from django.test import SimpleTestCase

from vfoot.services.classic_scoring import (
    Ruleset,
    score_team,
    resolve_fixture,
)
from vfoot.services.defense_bonus import defense_bonus_value
from vfoot.services.scoring_engine import fantavote_to_goals


class DefenseBandsTest(SimpleTestCase):
    """+1 every 0.25 above 6.00, linear and uncapped (inclusive upper bound)."""

    def test_bands(self):
        cases = {
            6.00: 0.0, 6.10: 1.0, 6.25: 1.0, 6.26: 2.0, 6.50: 2.0,
            6.75: 3.0, 7.00: 4.0, 7.25: 5.0, 7.50: 6.0, 8.00: 8.0,
        }
        for avg, expected in cases.items():
            self.assertEqual(defense_bonus_value(avg), expected, f"avg={avg}")


def line(pid, role, vp, sv=False, conceded=0):
    """A per-player line; fantavoto == voto_puro (no bonus/malus) for readable sums."""
    return {
        "player_id": pid,
        "name": f"P{pid}",
        "lineup_role": role,           # GK/DEF/MID/ATT
        "voto_puro": None if sv else float(vp),
        "fantavoto": None if sv else float(vp),
        "sv": sv,
        "conceded": conceded,
    }


def legal_xi(vp=6.0, gk_conceded=0, n_def=4, n_mid=4, n_att=2):
    """A legal starting XI (1 GK + n_def + n_mid + n_att = 11) all rated `vp`."""
    assert 1 + n_def + n_mid + n_att == 11
    xi = [line(1, "GK", vp, conceded=gk_conceded)]
    pid = 2
    for _ in range(n_def):
        xi.append(line(pid, "DEF", vp)); pid += 1
    for _ in range(n_mid):
        xi.append(line(pid, "MID", vp)); pid += 1
    for _ in range(n_att):
        xi.append(line(pid, "ATT", vp)); pid += 1
    return xi


class ClassicScoringTest(SimpleTestCase):
    def test_base_total_is_sum_of_fantavoti(self):
        rs = Ruleset(defense_enabled=False)
        team = score_team(legal_xi(6.0), [], rs)
        self.assertEqual(team["base_total"], 66.0)  # 11 x 6.0

    def test_sv_starter_is_substituted_by_bench(self):
        rs = Ruleset(defense_enabled=False, max_substitutions=5)
        starters = legal_xi(6.0)
        # Make one MID starter s.v. (pid 6 is a MID: GK=1, DEF=2..5, MID=6..9).
        starters[5] = line(6, "MID", 0, sv=True)
        bench = [line(20, "MID", 7.0)]  # priority bench MID with a vote
        team = score_team(starters, bench, rs)
        # 10 rated starters x6 (=60) + bench 7.0 = 67
        self.assertEqual(team["base_total"], 67.0)
        self.assertEqual(len(team["substitutions"]), 1)
        self.assertEqual(team["unresolved_sv"], [])

    def test_unresolved_sv_is_excluded_not_zero_not_six(self):
        rs = Ruleset(defense_enabled=False, max_substitutions=5)
        starters = legal_xi(6.0)
        starters[5] = line(6, "MID", 0, sv=True)  # s.v. MID
        team = score_team(starters, [], rs)  # no bench -> cannot substitute
        # The s.v. contributes NOTHING: 10 rated x6 = 60 (not 66, not 54).
        self.assertEqual(team["base_total"], 60.0)
        self.assertEqual(team["unresolved_sv"], [6])

    def test_max_substitutions_cap(self):
        rs = Ruleset(defense_enabled=False, max_substitutions=1)
        starters = legal_xi(6.0)
        starters[5] = line(6, "MID", 0, sv=True)
        starters[6] = line(7, "MID", 0, sv=True)  # two s.v. MIDs
        bench = [line(20, "MID", 7.0), line(21, "MID", 7.0)]
        team = score_team(starters, bench, rs)
        # cap=1: one sub applied (+7), the other s.v. excluded. 9x6=54 +7 = 61.
        self.assertEqual(team["base_total"], 61.0)
        self.assertEqual(len(team["substitutions"]), 1)
        self.assertEqual(team["unresolved_sv"], [7])

    def test_defense_bonus_add_own(self):
        rs = Ruleset(defense_enabled=True, defense_mode="add_own")
        home = score_team(legal_xi(6.5), [], rs)   # 4 DEF starters -> eligible
        away = score_team(legal_xi(6.5, n_def=3, n_mid=5), [], rs)  # 3 DEF -> not eligible
        out = resolve_fixture(home, away, rs)
        # avg = (6.5*3 + 6.5)/4 = 6.5 -> band +2. Home 71.5 + 2 = 73.5.
        self.assertTrue(home["defense"]["eligible"])
        self.assertEqual(home["defense"]["bonus"], 2.0)
        self.assertEqual(home["total"], 73.5)
        self.assertFalse(away["defense"]["eligible"])
        self.assertEqual(away["total"], 71.5)
        self.assertEqual(out["home_goals"], fantavote_to_goals(73.5))

    def test_defense_bonus_subtract_opponent(self):
        rs = Ruleset(defense_enabled=True, defense_mode="subtract_opponent")
        home = score_team(legal_xi(6.5), [], rs)                    # eligible +2
        away = score_team(legal_xi(6.5, n_def=3, n_mid=5), [], rs)  # not eligible
        resolve_fixture(home, away, rs)
        # Home's +2 is taken OFF the opponent: away 71.5 - 2 = 69.5; home unchanged.
        self.assertEqual(home["total"], 71.5)
        self.assertEqual(away["total"], 69.5)
        self.assertEqual(away["applied"], -2.0)

    def test_keeper_clean_sheet_bonus(self):
        rs = Ruleset(defense_enabled=False, keeper_clean_sheet_enabled=True)
        clean = score_team(legal_xi(6.0, gk_conceded=0), [], rs)
        conceded = score_team(legal_xi(6.0, gk_conceded=2), [], rs)
        resolve_fixture(clean, conceded, rs)
        self.assertEqual(clean["total"], 67.0)     # 66 + 1 clean sheet
        self.assertEqual(conceded["total"], 66.0)  # no bonus

    def test_keeper_clean_sheet_disabled_by_default(self):
        rs = Ruleset(defense_enabled=False)  # keeper_clean_sheet_enabled defaults False
        team = score_team(legal_xi(6.0, gk_conceded=0), [], rs)
        resolve_fixture(team, score_team(legal_xi(6.0), [], rs), rs)
        self.assertEqual(team["total"], 66.0)
