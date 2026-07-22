"""Tests for the data-driven classic role inference."""
from __future__ import annotations

from django.test import TestCase

from realdata.models import (
    Competition, CompetitionSeason, Match, MatchAppearance, Player,
    PlayerTeamStint, PlayerZoneFeature, Season, Team, TeamSeason,
)
from vfoot.services.role_inference import (
    TM_AMBIGUOUS, TM_DEFAULT, TM_DETERMINISTIC, infer_roles, tm_positions,
)


class RoleInferenceTests(TestCase):
    """The pipeline is built on a tiny synthetic league: three archetypes with
    deliberately separated profiles, so the categories are unambiguous and the
    test asserts the LOGIC, not the calibration on real football."""

    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.prev = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2025-2026"),
            name="Serie A 2025-2026")
        self.cur = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        self.ts_prev = TeamSeason.objects.create(
            competition_season=self.prev, team=Team.objects.create(name="Torino"))
        self.ts_cur = TeamSeason.objects.create(
            competition_season=self.cur, team=Team.objects.create(name="Torino B"))
        self.match = Match.objects.create(
            competition_season=self.prev, matchday=1, home_team=self.ts_prev,
            away_team=self.ts_prev, home_goals=0, away_goals=0,
            status=Match.STATUS_FINISHED)

    def _player(self, name, tm_position, *, col, box=0.0, shots=0.0, defensive=0.0,
                minutes=900, seasons=("prev", "cur")):
        """A player whose touches sit in pitch column ``col`` (0 = own goal)."""
        p = Player.objects.create(full_name=name, short_name=name)
        if "cur" in seasons:
            PlayerTeamStint.objects.create(player=p, team_season=self.ts_cur,
                                           tm_position=tm_position)
        if "prev" not in seasons:
            return p
        PlayerTeamStint.objects.create(player=p, team_season=self.ts_prev,
                                       tm_position=tm_position)
        MatchAppearance.objects.create(match=self.match, player=p,
                                       team_season=self.ts_prev, side="home",
                                       minutes_played=minutes, is_starter=True)
        for row in range(4):
            PlayerZoneFeature.objects.create(
                match=self.match, player=p, provider="sofascore",
                feature_key="touches", zone_key=f"Z_{col}_{row}", value=25.0,
                team_side="home")
        for key, val in (("touches_in_box", box), ("shots", shots),
                         ("clearances", defensive)):
            if val:
                PlayerZoneFeature.objects.create(
                    match=self.match, player=p, provider="sofascore",
                    feature_key=key, zone_key=f"Z_{col}_1", value=val,
                    team_side="home")
        return p

    def _population(self):
        """Enough of each archetype for clustering to have something to find."""
        for i in range(6):
            self._player(f"CB{i}", "centre-back", col=0, defensive=40.0)
            self._player(f"MID{i}", "central midfield", col=2)
            self._player(f"FW{i}", "centre-forward", col=4, box=40.0, shots=30.0)

    def test_unmeasured_ambiguous_player_needs_a_human_decision(self):
        self._population()
        newcomer = self._player("Esordiente", "left winger", col=4,
                                seasons=("cur",))       # no previous season at all
        rep = infer_roles(self.cur.id, self.prev.id, runs=6, n_categories=3)
        r = next(x for x in rep.results if x.player_id == newcomer.id)
        self.assertEqual(r.method, "default")
        self.assertTrue(r.needs_decision)
        # ...and meanwhile he still gets the positional fallback, not a hole.
        self.assertEqual(r.role_mitigated, TM_DEFAULT["left winger"])

    def test_unambiguous_position_never_needs_a_decision(self):
        self._population()
        newcomer = self._player("Difensore nuovo", "centre-back", col=0,
                                seasons=("cur",))
        rep = infer_roles(self.cur.id, self.prev.id, runs=6, n_categories=3)
        r = next(x for x in rep.results if x.player_id == newcomer.id)
        self.assertFalse(r.needs_decision)
        self.assertEqual(r.role_mitigated, TM_DETERMINISTIC["centre-back"])
        self.assertEqual(r.method, "tm")

    def test_mitigated_keeps_the_provider_position_where_it_is_certain(self):
        """A full-back who plays like a winger: the two variants must disagree,
        which is the whole point of offering both."""
        self._population()
        hybrid = self._player("Terzino avanzato", "left-back", col=4, box=40.0,
                              shots=30.0)
        rep = infer_roles(self.cur.id, self.prev.id, runs=6, n_categories=3)
        r = next(x for x in rep.results if x.player_id == hybrid.id)
        self.assertEqual(r.method, "category")
        self.assertEqual(r.role_mitigated, Player.ROLE_DEF)   # TM wins
        self.assertEqual(r.role_data, Player.ROLE_FWD)        # the data win

    def test_categories_are_seed_independent(self):
        """Consensus is the reason we can put a role in front of a user at all:
        a category that moved with the random seed would be arbitrary."""
        self._population()
        a = infer_roles(self.cur.id, self.prev.id, runs=10, n_categories=3)
        b = infer_roles(self.cur.id, self.prev.id, runs=10, n_categories=3)
        self.assertEqual({r.player_id: r.category for r in a.results},
                         {r.player_id: r.category for r in b.results})

    def test_positions_are_read_from_the_season_being_listed(self):
        p = self._player("Uno", "right winger", col=3, seasons=("cur",))
        self.assertEqual(tm_positions(self.cur.id)[p.id], "right winger")
        self.assertNotIn(p.id, tm_positions(self.prev.id))

    def test_ambiguous_set_and_deterministic_set_do_not_overlap(self):
        self.assertFalse(TM_AMBIGUOUS & set(TM_DETERMINISTIC))
        self.assertEqual(set(TM_DEFAULT), TM_AMBIGUOUS)
