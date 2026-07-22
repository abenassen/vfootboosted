"""Tests for the status-aware real-match resolver (player+matchday -> outcome)."""
from __future__ import annotations

from django.test import TestCase

from realdata.models import (
    Competition,
    CompetitionSeason,
    Match,
    MatchAppearance,
    Player,
    PlayerTeamStint,
    Season,
    Team,
    TeamSeason,
)
from vfoot.services.match_resolver import (
    NO_MATCH,
    PENDING,
    SENZA_VOTO,
    VOTO,
    resolve_player,
)


class MatchResolverTests(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        season = Season.objects.create(code="2026-2027")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=season, name="Serie A 2026-2027")
        a = Team.objects.create(name="Alpha")
        b = Team.objects.create(name="Beta")
        self.tsa = TeamSeason.objects.create(competition_season=self.cs, team=a)
        self.tsb = TeamSeason.objects.create(competition_season=self.cs, team=b)
        self.player = Player.objects.create(full_name="P One", short_name="P. One",
                                            classic_role="DIF")
        PlayerTeamStint.objects.create(player=self.player, team_season=self.tsa,
                                       end_date=None)
        # empty reference: no features -> outfield players are unrated (sv), which
        # is fine for exercising the STATE MACHINE (pending/no_match/duplicate).
        self.ref = {}

    def _match(self, matchday, status, data_ready, ext):
        return Match.objects.create(
            competition_season=self.cs, matchday=matchday, home_team=self.tsa,
            away_team=self.tsb, status=status, data_ready=data_ready,
            external_source="sofascore", external_id=ext)

    def _appear(self, match):
        MatchAppearance.objects.create(
            match=match, player=self.player, team_season=self.tsa, side="home",
            minutes_played=90, is_starter=True)

    def test_no_match_when_club_has_no_fixture(self):
        self._match(5, Match.STATUS_FINISHED, True, "m5")  # different matchday
        o = resolve_player(self.player.id, self.cs.id, 1, self.ref)
        self.assertEqual(o["status"], NO_MATCH)
        self.assertIsNone(o["match_id"])

    def test_pending_when_scheduled(self):
        m = self._match(1, Match.STATUS_SCHEDULED, False, "m1")
        o = resolve_player(self.player.id, self.cs.id, 1, self.ref)
        self.assertEqual(o["status"], PENDING)
        self.assertEqual(o["match_id"], m.id)

    def test_pending_when_postponed(self):
        self._match(1, Match.STATUS_POSTPONED, False, "m1")
        self.assertEqual(resolve_player(self.player.id, self.cs.id, 1, self.ref)["status"],
                         PENDING)

    def test_pending_when_finished_but_not_data_ready(self):
        # finished but data not yet stabilised -> still pending (no final vote)
        self._match(1, Match.STATUS_FINISHED, False, "m1")
        self.assertEqual(resolve_player(self.player.id, self.cs.id, 1, self.ref)["status"],
                         PENDING)

    def test_concluded_with_appearance_is_sv_here(self):
        # data_ready + player appeared, but no features -> senza voto (not pending)
        m = self._match(1, Match.STATUS_FINISHED, True, "m1")
        self._appear(m)
        o = resolve_player(self.player.id, self.cs.id, 1, self.ref)
        self.assertEqual(o["status"], SENZA_VOTO)
        self.assertEqual(o["match_id"], m.id)
        self.assertIsNotNone(o["line"])

    def test_concluded_without_appearance_is_sv(self):
        self._match(1, Match.STATUS_FINISHED, True, "m1")  # player did not appear
        o = resolve_player(self.player.id, self.cs.id, 1, self.ref)
        self.assertEqual(o["status"], SENZA_VOTO)
        self.assertIsNone(o["line"])

    def test_postponed_duplicate_prefers_data_ready_replay(self):
        # SofaScore keeps both: a postponed shell AND the data_ready replay.
        shell = self._match(1, Match.STATUS_POSTPONED, False, "shell")
        replay = self._match(1, Match.STATUS_FINISHED, True, "replay")
        self._appear(replay)
        o = resolve_player(self.player.id, self.cs.id, 1, self.ref)
        # resolves to the REPLAY (not pending on the shell)
        self.assertEqual(o["match_id"], replay.id)
        self.assertNotEqual(o["match_id"], shell.id)
        self.assertEqual(o["status"], SENZA_VOTO)

    def test_no_stint_is_no_match(self):
        other = Player.objects.create(full_name="No Club", classic_role="ATT")
        self._match(1, Match.STATUS_FINISHED, True, "m1")
        self.assertEqual(resolve_player(other.id, self.cs.id, 1, self.ref)["status"],
                         NO_MATCH)
