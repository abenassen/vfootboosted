"""Charging a player with the danger conceded where — and while — he played."""
from __future__ import annotations

from django.test import TestCase

from realdata.models import (
    Competition, CompetitionSeason, Match, MatchAppearance, MatchShot, Player,
    PlayerOnPitchInterval, PlayerZoneFeature, Season, Team, TeamSeason,
    INTERVAL_SUBSTITUTION_OFF, INTERVAL_SUBSTITUTION_ON,
)
from vfoot.services.classic_rating import (
    EXPOSURE_KERNEL, EXPOSURE_LAMBDA, EXPOSURE_POST_OUTCOME,
    defensive_exposure, index_for_role,
)

GOAL_CHARGE = EXPOSURE_LAMBDA          # a goal with no xGOT recorded
NOT_LAMBDA = 1.0 - EXPOSURE_LAMBDA


class DefensiveExposureTests(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2025-2026"),
            name="Serie A 2025-2026")
        self.home = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Torino"))
        self.away = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Sassuolo"))
        self.match = Match.objects.create(
            competition_season=self.cs, matchday=1, home_team=self.home,
            away_team=self.away, home_goals=0, away_goals=2,
            status=Match.STATUS_FINISHED)
        self._n = 0

    # -- fixtures ---------------------------------------------------------
    def _home_player(self, name, zones, minutes=90, starter=True, role="DIF",
                     keeper=False):
        """A home player whose positional heatmap is ``{(col, row): touches}``."""
        p = Player.objects.create(full_name=name, short_name=name,
                                  classic_role_seed=role, is_goalkeeper=keeper)
        MatchAppearance.objects.create(match=self.match, player=p,
                                       team_season=self.home, side="home",
                                       minutes_played=minutes, is_starter=starter)
        for (col, row), touches in zones.items():
            PlayerZoneFeature.objects.create(
                match=self.match, player=p, provider="sofascore",
                feature_key="touches", zone_key=f"Z_{col}_{row}", value=touches,
                team_side="home")
        return p

    def _defender(self, name, col, row, **kw):
        return self._home_player(name, {(col, row): 50.0}, **kw)

    def _away_shot(self, col, row, minute, *, goal=False, xgot=0.0,
                   shot_type="", situation=""):
        """A shot by the AWAY side, in the away side's own attacking frame."""
        self._n += 1
        return MatchShot.objects.create(
            match=self.match, team_side="away", minute=minute,
            zone_key=f"Z_{col}_{row}", xg=0.5, xgot=xgot, is_goal=goal,
            shot_type=shot_type or ("goal" if goal else "save"),
            situation=situation, provider="sofascore", external_id=f"s{self._n}")

    def _exposure(self):
        minutes = {(a["match_id"], a["player_id"]): a["minutes_played"]
                   for a in MatchAppearance.objects.filter(match=self.match)
                   .values("match_id", "player_id", "minutes_played")}
        return defensive_exposure([self.match.id], minutes)

    # -- where the danger lands -------------------------------------------
    def test_danger_is_charged_to_the_player_who_occupied_that_zone(self):
        """The two teams' grids are a 180 degree rotation: an away attack in
        (4, 0) happens in the home defence's (0, 3)."""
        exposed = self._defender("Esposto", col=0, row=3)
        elsewhere = self._defender("Altrove", col=4, row=0)
        self._away_shot(col=4, row=0, minute=30, goal=True)

        e = self._exposure()
        self.assertAlmostEqual(e[(self.match.id, exposed.id)], GOAL_CHARGE)
        self.assertNotIn((self.match.id, elsewhere.id), e)

    def test_one_shot_is_split_in_full_across_who_was_there(self):
        """The share is RELATIVE to the team-mates on the pitch, so a shot is
        distributed entirely — never more, never less."""
        whole = self._defender("Tutto li", col=0, row=3)
        half = self._home_player("Meta li", {(0, 3): 50.0, (4, 0): 50.0})
        self._away_shot(col=4, row=0, minute=30, goal=True)

        e = self._exposure()
        a = e[(self.match.id, whole.id)]
        b = e[(self.match.id, half.id)]
        self.assertAlmostEqual(a + b, GOAL_CHARGE)      # nothing created or lost
        self.assertAlmostEqual(a, 2 * b)                # presence 1.0 vs 0.5

    def test_the_keeper_is_left_out_of_the_split(self):
        """His heatmap sits exactly where the danger arrives, so including him
        would swallow the share the defenders in front of him must carry."""
        d = self._defender("Difensore", col=0, row=3)
        self._defender("Portiere", col=0, row=3, role="POR", keeper=True)
        self._away_shot(col=4, row=0, minute=30, goal=True)

        e = self._exposure()
        self.assertAlmostEqual(e[(self.match.id, d.id)], GOAL_CHARGE)

    def test_a_neighbouring_zone_carries_a_smaller_share(self):
        """The 5x4 grid is coarse: a shot just across a boundary must not be
        charged entirely to the next man along."""
        inside = self._defender("Dentro", col=0, row=3)
        next_to = self._defender("Accanto", col=0, row=2)   # adjacent to (0, 3)
        self._away_shot(col=4, row=0, minute=30, goal=True)

        e = self._exposure()
        a = e[(self.match.id, inside.id)]
        b = e[(self.match.id, next_to.id)]
        self.assertAlmostEqual(a + b, GOAL_CHARGE)
        self.assertAlmostEqual(b / a, EXPOSURE_KERNEL)

    # -- what is charged --------------------------------------------------
    def test_a_goal_carries_the_outcome_and_its_own_xgot(self):
        d = self._defender("Difensore", col=0, row=3)
        self._away_shot(col=4, row=0, minute=30, goal=True, xgot=0.8)

        e = self._exposure()
        self.assertAlmostEqual(e[(self.match.id, d.id)],
                               EXPOSURE_LAMBDA + NOT_LAMBDA * 0.8)

    def test_an_error_the_keeper_saved_still_costs_something(self):
        """The whole point of the xGOT half: a clear chance sventata by the keeper
        is a defensive failure, and charging goals alone erases it."""
        d = self._defender("Difensore", col=0, row=3)
        self._away_shot(col=4, row=0, minute=30, goal=False, xgot=0.6)

        e = self._exposure()
        self.assertAlmostEqual(e[(self.match.id, d.id)], NOT_LAMBDA * 0.6)

    def test_a_shot_off_target_or_blocked_costs_nothing(self):
        """No outcome and no xGOT: the defence dealt with it."""
        self._defender("Difensore", col=0, row=3)
        self._away_shot(col=4, row=0, minute=30, shot_type="miss")
        self._away_shot(col=4, row=0, minute=40, shot_type="block")

        self.assertEqual(self._exposure(), {})

    def test_woodwork_is_charged_at_our_own_attacking_rate(self):
        """The provider gives no xGOT to a shot off the frame, so it is charged on
        the outcome side at the value our own weights give a post against a goal —
        the same event read identically from both ends of the pitch."""
        d = self._defender("Difensore", col=0, row=3)
        self._away_shot(col=4, row=0, minute=30, shot_type="post")

        e = self._exposure()
        self.assertAlmostEqual(e[(self.match.id, d.id)],
                               EXPOSURE_LAMBDA * EXPOSURE_POST_OUTCOME)

    def test_a_penalty_is_not_charged_by_zone(self):
        """Standing near the spot means nothing, and the foul is already charged
        to whoever conceded it."""
        self._defender("Difensore", col=0, row=3)
        self._away_shot(col=4, row=0, minute=30, goal=True, xgot=0.9,
                        situation="penalty")

        self.assertEqual(self._exposure(), {})

    # -- when he was on the pitch -----------------------------------------
    def test_a_substituted_player_does_not_answer_for_what_came_after(self):
        """The defect this replaced: scaling a whole-match total by minutes played
        charged him for danger conceded once he was already off."""
        off = self._defender("Uscito", col=0, row=3, minutes=60)
        PlayerOnPitchInterval.objects.create(
            match=self.match, player=off, team_season=self.home, team_side="home",
            start_minute=0, end_minute=60, end_reason=INTERVAL_SUBSTITUTION_OFF,
            provider="sofascore")
        self._away_shot(col=4, row=0, minute=20, goal=True)   # while he was on
        self._away_shot(col=4, row=0, minute=80, goal=True)   # after he came off

        e = self._exposure()
        self.assertAlmostEqual(e[(self.match.id, off.id)], GOAL_CHARGE)

    def test_a_substitute_answers_only_from_the_minute_he_came_on(self):
        on = self._defender("Entrato", col=0, row=3, minutes=30, starter=False)
        PlayerOnPitchInterval.objects.create(
            match=self.match, player=on, team_season=self.home, team_side="home",
            start_minute=60, end_minute=90, start_reason=INTERVAL_SUBSTITUTION_ON,
            provider="sofascore")
        self._away_shot(col=4, row=0, minute=20, goal=True)
        self._away_shot(col=4, row=0, minute=80, goal=True)

        e = self._exposure()
        self.assertAlmostEqual(e[(self.match.id, on.id)], GOAL_CHARGE)

    def test_a_substitute_later_withdrawn_is_bounded_at_both_ends(self):
        """The case an inferred window cannot express at all — 34 of them in a
        single real season."""
        p = self._defender("Dentro e fuori", col=0, row=3, minutes=30, starter=False)
        PlayerOnPitchInterval.objects.create(
            match=self.match, player=p, team_season=self.home, team_side="home",
            start_minute=45, end_minute=75, start_reason=INTERVAL_SUBSTITUTION_ON,
            end_reason=INTERVAL_SUBSTITUTION_OFF, provider="sofascore")
        for minute in (20, 60, 85):
            self._away_shot(col=4, row=0, minute=minute, goal=True)

        e = self._exposure()
        self.assertAlmostEqual(e[(self.match.id, p.id)], GOAL_CHARGE)  # only the 60th

    def test_the_split_only_counts_team_mates_who_were_on_the_pitch(self):
        """A defender already withdrawn must not dilute the share of the men who
        were actually there when the shot was struck."""
        stayed = self._defender("Rimasto", col=0, row=3)
        off = self._defender("Uscito", col=0, row=3, minutes=45)
        PlayerOnPitchInterval.objects.create(
            match=self.match, player=off, team_season=self.home, team_side="home",
            start_minute=0, end_minute=45, end_reason=INTERVAL_SUBSTITUTION_OFF,
            provider="sofascore")
        self._away_shot(col=4, row=0, minute=70, goal=True)

        e = self._exposure()
        self.assertAlmostEqual(e[(self.match.id, stayed.id)], GOAL_CHARGE)
        self.assertNotIn((self.match.id, off.id), e)


class ExposureInTheIndexTests(TestCase):
    def test_every_outfield_role_carries_the_charge(self):
        """Attackers used to be exempt: they computed a share and did not pay it,
        an asymmetry with no argument behind it."""
        feats = {"touches": 60.0}
        for role in ("DIF", "CEN", "ATT"):
            self.assertLess(index_for_role(role, feats, 90, 0.9),
                            index_for_role(role, feats, 90, 0.0),
                            msg=f"{role} should pay for the danger in his zone")

    def test_the_keeper_does_not(self):
        """His own channel already answers for what reached him (goals prevented =
        xGOT faced minus goals conceded), so charging him here would double it."""
        feats = {"gk_saves": 3.0, "gk_goals_prevented": 0.4}
        self.assertEqual(index_for_role(Player.ROLE_GK, feats, 90, 0.0),
                         index_for_role(Player.ROLE_GK, feats, 90, 0.9))

    def test_the_penalty_grows_with_the_danger_but_with_diminishing_returns(self):
        """Exposure goes through the same compression as every other feature, so
        four times the danger costs MORE but not four times more — the shape that
        keeps one catastrophic match from swamping the index."""
        feats = {"touches": 60.0}
        base = index_for_role("DIF", feats, 90, 0.0)
        small = base - index_for_role("DIF", feats, 90, 0.25)
        large = base - index_for_role("DIF", feats, 90, 1.0)
        self.assertGreater(small, 0)
        self.assertGreater(large, small)
        self.assertLess(large, 4 * small)
