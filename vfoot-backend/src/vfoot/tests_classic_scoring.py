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


class ComposeLinesTest(SimpleTestCase):
    """Pure lineup composition: sold players -> s.v. slots, absent players -> s.v.,
    sold bench players dropped."""

    def _index_and_roles(self):
        # Full XI present at 6.0 (1 GK + 4 DEF + 4 MID + 2 ATT), plus two DEF bench at 7.0.
        roles = ["GK"] + ["DEF"] * 4 + ["MID"] * 4 + ["ATT"] * 2  # players 1..11
        role_map, index = {}, {}
        for pid, r in enumerate(roles, start=1):
            role_map[pid] = r
            index[pid] = {"player_id": pid, "name": f"P{pid}", "lineup_role": r,
                          "voto_puro": 6.0, "fantavoto": 6.0, "sv": False, "conceded": 0}
        for b in (20, 21):
            role_map[b] = "DEF"
            index[b] = {"player_id": b, "name": f"B{b}", "lineup_role": "DEF",
                        "voto_puro": 7.0, "fantavoto": 7.0, "sv": False, "conceded": 0}
        return index, role_map

    def test_absent_player_is_sv_and_the_lineup_is_taken_as_sent(self):
        """The submitted lineup is authoritative: only "did he play" decides a line.

        It used to be filtered against the CURRENT roster, so a player sold after the
        matchday was silently turned into an s.v. slot — which made the same round
        score differently depending on WHEN the admin got round to concluding it.
        Ownership is now enforced where it belongs: at the transfer, which repairs
        every lineup still open and never touches one already locked
        (services/lineup_repair).
        """
        from vfoot.services.classic_matchday_scoring import compose_team_lines
        index, role_map = self._index_and_roles()
        del index[4]  # player 4 did NOT play (absent from the index)
        starters, bench = compose_team_lines(
            1, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11], [20, 21], index, role_map)
        self.assertEqual(len(starters), 11)
        by = {l["player_id"]: l for l in starters}
        self.assertTrue(by[4]["sv"])    # absent -> s.v.
        self.assertFalse(by[5]["sv"])   # played -> scores, whoever owns him today
        self.assertFalse(by[2]["sv"])
        self.assertEqual([l["player_id"] for l in bench], [20, 21])

    def test_compose_then_score(self):
        from vfoot.services.classic_matchday_scoring import (
            compose_team_lines,
            score_composed_fixture,
        )
        index, role_map = self._index_and_roles()
        # Home: DEF player 5 did not play -> s.v.; bench 20 (DEF) subs in (7.0).
        # 10 played at 6.0 (=60) + 7.0 = 67. Away: full XI at 6.0 = 66.
        home_index = {k: v for k, v in index.items() if k != 5}
        home = compose_team_lines(1, list(range(2, 12)), [20, 21], home_index, role_map)
        away = compose_team_lines(1, list(range(2, 12)), [20, 21], index, role_map)
        rs = Ruleset(defense_enabled=False, max_substitutions=5)
        payload = score_composed_fixture(home, away, rs, {
            "fixture_id": 7, "fantasy_round": 1, "real_matchday": 3,
            "home_team": "Alpha", "away_team": "Beta", "stage": None,
        })
        self.assertEqual(payload["mode"], "classic")
        self.assertEqual(payload["home_total"], 67.0)  # sold DEF replaced by bench DEF 7.0
        self.assertEqual(payload["away_total"], 66.0)  # full XI at 6.0
        self.assertIn("home", payload)
        self.assertIsInstance(payload["home"]["modifiers"], list)


class VoteCenteringReportTests(SimpleTestCase):
    """The arithmetic behind `manage.py check_vote_centering`.

    The check itself needs a real season and lives as a command, not a test — a
    test that skips itself on an empty database protects nothing. What IS testable
    here is the decomposition it prints, because that is what tells whoever reads a
    failure WHERE to look: a drift in the centre term means the index being scored
    has stopped matching the one the reference was calibrated on (an argument not
    passed, a feature not arriving), while the covariance term is structural.
    """

    def test_a_centred_role_reports_no_drift(self):
        from vfoot.management.commands.check_vote_centering import centering_report
        # z averaging zero, w constant -> the vote sits on 6 and both terms vanish.
        rows = [(-1.0, 0.8, 5.5), (0.0, 0.8, 6.0), (1.0, 0.8, 6.5)]
        r = centering_report({"DIF": rows}, 0.8)["DIF"]
        self.assertEqual(r["n"], 3)
        self.assertAlmostEqual(r["mean"], 6.0)
        self.assertAlmostEqual(r["drift"], 0.0)
        self.assertAlmostEqual(r["centre_term"], 0.0)
        self.assertAlmostEqual(r["cov_term"], 0.0)

    def test_an_off_centre_index_shows_up_in_the_centre_term(self):
        """Every z shifted up by the same amount — the signature of scoring an
        index the reference was not calibrated on. This is the exposure bug."""
        from vfoot.management.commands.check_vote_centering import centering_report
        rows = [(0.5, 0.8, 6.5), (0.5, 0.8, 6.5)]
        r = centering_report({"DIF": rows}, 0.8)["DIF"]
        self.assertAlmostEqual(r["centre_term"], 0.8 * 0.8 * 0.5)
        self.assertAlmostEqual(r["cov_term"], 0.0)   # no spread in w, nothing to correlate

    def test_minutes_correlated_with_z_show_up_in_the_covariance_term(self):
        """Long games earning a higher z is structural, not a defect — so it has to
        land in its own term rather than be mistaken for a miscalibration."""
        from vfoot.management.commands.check_vote_centering import centering_report
        rows = [(-1.0, 0.4, 5.5), (1.0, 0.9, 6.5)]   # E[z] = 0, but w tracks z
        r = centering_report({"DIF": rows}, 0.8)["DIF"]
        self.assertAlmostEqual(r["centre_term"], 0.0)
        self.assertGreater(r["cov_term"], 0.0)

    def test_roles_are_reported_independently(self):
        from vfoot.management.commands.check_vote_centering import centering_report
        out = centering_report({"DIF": [(0.0, 0.8, 6.0)],
                                "POR": [(0.0, 0.8, 5.0)]}, 0.8)
        self.assertAlmostEqual(out["DIF"]["drift"], 0.0)
        self.assertAlmostEqual(out["POR"]["drift"], -1.0)
