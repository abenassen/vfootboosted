"""Charging a defender with the danger conceded where — and while — he played."""
from __future__ import annotations

from django.test import TestCase

from realdata.models import (
    Competition, CompetitionSeason, Match, MatchAppearance, MatchShot, Player,
    PlayerOnPitchInterval, PlayerZoneFeature, Season, Team, TeamSeason,
    INTERVAL_SUBSTITUTION_OFF, INTERVAL_SUBSTITUTION_ON,
)
from vfoot.services.classic_rating import (
    DEF_EXPOSURE_WEIGHT, defensive_exposure, index_for_role,
)


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

    def _defender(self, name, col, row, minutes=90, starter=True):
        """A home defender whose touches sit in one zone of his own half."""
        p = Player.objects.create(full_name=name, short_name=name, classic_role="DIF")
        MatchAppearance.objects.create(match=self.match, player=p,
                                       team_season=self.home, side="home",
                                       minutes_played=minutes, is_starter=starter)
        PlayerZoneFeature.objects.create(
            match=self.match, player=p, provider="sofascore", feature_key="touches",
            zone_key=f"Z_{col}_{row}", value=50.0, team_side="home")
        return p

    def _away_shot(self, col, row, minute, xg=0.5):
        """A shot by the AWAY side, in the away side's own attacking frame."""
        return MatchShot.objects.create(
            match=self.match, team_side="away", minute=minute,
            zone_key=f"Z_{col}_{row}", xg=xg, provider="sofascore",
            external_id=f"s{col}{row}{minute}")

    def _exposure(self):
        minutes = {(a["match_id"], a["player_id"]): a["minutes_played"]
                   for a in MatchAppearance.objects.filter(match=self.match)
                   .values("match_id", "player_id", "minutes_played")}
        return defensive_exposure([self.match.id], minutes)

    def test_danger_is_charged_to_the_defender_who_patrolled_that_zone(self):
        """The two teams' grids are a 180 degree rotation: an away attack in
        (4, 0) happens in the home defence's (0, 3)."""
        exposed = self._defender("Esposto", col=0, row=3)
        elsewhere = self._defender("Altrove", col=0, row=0)
        self._away_shot(col=4, row=0, minute=30)

        e = self._exposure()
        self.assertAlmostEqual(e[(self.match.id, exposed.id)], 0.5)
        self.assertNotIn((self.match.id, elsewhere.id), e)

    def test_a_substituted_defender_does_not_answer_for_what_came_after(self):
        """The defect this replaced: scaling a whole-match total by minutes played
        charged him for danger conceded once he was already off."""
        off = self._defender("Uscito", col=0, row=3, minutes=60)
        PlayerOnPitchInterval.objects.create(
            match=self.match, player=off, team_season=self.home, team_side="home",
            start_minute=0, end_minute=60, end_reason=INTERVAL_SUBSTITUTION_OFF,
            provider="sofascore")
        self._away_shot(col=4, row=0, minute=20)   # while he was on
        self._away_shot(col=4, row=0, minute=80)   # after he came off

        e = self._exposure()
        self.assertAlmostEqual(e[(self.match.id, off.id)], 0.5)

    def test_a_substitute_answers_only_from_the_minute_he_came_on(self):
        on = self._defender("Entrato", col=0, row=3, minutes=30, starter=False)
        PlayerOnPitchInterval.objects.create(
            match=self.match, player=on, team_season=self.home, team_side="home",
            start_minute=60, end_minute=90, start_reason=INTERVAL_SUBSTITUTION_ON,
            provider="sofascore")
        self._away_shot(col=4, row=0, minute=20)
        self._away_shot(col=4, row=0, minute=80)

        e = self._exposure()
        self.assertAlmostEqual(e[(self.match.id, on.id)], 0.5)

    def test_a_substitute_later_withdrawn_is_bounded_at_both_ends(self):
        """The case an inferred window cannot express at all — 34 of them in a
        single real season."""
        p = self._defender("Dentro e fuori", col=0, row=3, minutes=30, starter=False)
        PlayerOnPitchInterval.objects.create(
            match=self.match, player=p, team_season=self.home, team_side="home",
            start_minute=45, end_minute=75, start_reason=INTERVAL_SUBSTITUTION_ON,
            end_reason=INTERVAL_SUBSTITUTION_OFF, provider="sofascore")
        for minute in (20, 60, 85):
            self._away_shot(col=4, row=0, minute=minute)

        e = self._exposure()
        self.assertAlmostEqual(e[(self.match.id, p.id)], 0.5)  # only the 60th

    def test_only_defenders_carry_the_penalty(self):
        feats = {"touches": 60.0}
        for role in ("CEN", "ATT"):
            self.assertEqual(index_for_role(role, feats, 90, 0.0),
                             index_for_role(role, feats, 90, 0.9))
        self.assertLess(index_for_role("DIF", feats, 90, 0.9),
                        index_for_role("DIF", feats, 90, 0.0))

    def test_the_penalty_grows_with_the_danger_but_is_compressed(self):
        feats = {"touches": 60.0}
        base = index_for_role("DIF", feats, 90, 0.0)
        small = base - index_for_role("DIF", feats, 90, 0.25)
        large = base - index_for_role("DIF", feats, 90, 1.0)
        self.assertGreater(large, small)
        self.assertLess(large, 4 * small)   # sqrt, not linear
        self.assertAlmostEqual(large, DEF_EXPOSURE_WEIGHT * 1.0)
