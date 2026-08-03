"""Senza voto is a verdict on a FINISHED performance, not on a match in progress.

At the tenth minute every player on the pitch is below the minutes/involvement
gate, so the pagella used to print the whole XI as s.v. — which reads as "they did
nothing" when what is true is "the match has barely started". A manager watching
his round live saw ten S.V. badges and a bench frantically substituting itself in.

The rule these tests pin down:

* the match is being PLAYED and he is ON THE PITCH -> never s.v.; he gets the vote
  his minutes so far are worth, and it moves as he plays;
* he has already come OFF (substituted, sent off) -> his performance is complete
  even though the match is not, so the ordinary gate applies;
* the match is OVER -> nothing changes, which is the whole safety of the thing:
  the s.v. that ends up in the ledger is exactly the one that was there before.
"""
from __future__ import annotations

from django.test import TestCase

from realdata.models import (
    Competition, CompetitionSeason, Match, MatchAppearance, Player,
    PlayerZoneFeature, Season, Team, TeamSeason,
)
from vfoot.services.classic_pagella import (
    match_in_progress, pagella_for_match, players_on_pitch,
)


class LiveSenzaVotoTests(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        self.home = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Torino"))
        self.away = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Inter"))
        # Kicked off a few minutes ago: the case the whole module is about.
        self.match = Match.objects.create(
            competition_season=self.cs, matchday=22, home_team=self.home,
            away_team=self.away, home_goals=0, away_goals=0,
            status=Match.STATUS_LIVE, data_ready=False)

    # -- fixtures ---------------------------------------------------------
    def _player(self, name, *, minutes, starter=True, role="CEN", touches=4.0,
                side="home"):
        p = Player.objects.create(full_name=name, short_name=name,
                                  classic_role_seed=role)
        MatchAppearance.objects.create(
            match=self.match, player=p,
            team_season=self.home if side == "home" else self.away, side=side,
            minutes_played=minutes, is_starter=starter)
        if touches:
            PlayerZoneFeature.objects.create(
                match=self.match, player=p, provider="sofascore",
                feature_key="touches", zone_key="Z_2_2", value=touches,
                team_side=side)
        return p

    def _lines(self):
        pag = pagella_for_match(self.match)
        out = {}
        for side in ("home", "away"):
            for group in ("starters", "bench"):
                for line in pag[side][group]:
                    out[line["player_id"]] = line
        return out

    # -- who is out there --------------------------------------------------
    def test_the_clock_is_read_from_the_longest_appearance(self):
        on = self._player("In campo", minutes=8)
        off = self._player("Uscito", minutes=3)
        unused = self._player("Panchina", minutes=0, starter=False, touches=0)

        apps = list(MatchAppearance.objects.filter(match=self.match))
        pitch = players_on_pitch(apps)
        self.assertIn(on.id, pitch)
        self.assertNotIn(off.id, pitch, "sostituito al 3': la sua partita è finita")
        self.assertNotIn(unused.id, pitch)

    def test_at_kick_off_the_whole_starting_eleven_is_on_the_pitch(self):
        """Everyone reads 0' — and calling the starters 'not on the pitch' there is
        exactly the misreading this exists to remove."""
        starter = self._player("Titolare", minutes=0)
        sub = self._player("Riserva", minutes=0, starter=False, touches=0)

        pitch = players_on_pitch(list(MatchAppearance.objects.filter(match=self.match)))
        self.assertEqual(pitch, {starter.id})
        self.assertNotIn(sub.id, pitch)

    def test_a_finished_match_is_not_in_progress_even_before_its_data_settles(self):
        self.match.status = Match.STATUS_FINISHED
        self.assertFalse(match_in_progress(self.match))

    # -- the verdict -------------------------------------------------------
    def test_a_player_on_the_pitch_of_a_live_match_is_never_senza_voto(self):
        on = self._player("In campo", minutes=8)
        off = self._player("Uscito", minutes=3)

        lines = self._lines()
        self.assertFalse(lines[on.id]["sv"], "8' in una partita in corso non è un s.v.")
        self.assertIsNotNone(lines[on.id]["voto_puro"])
        # ...and whoever has come off is judged normally: for him it IS over.
        self.assertTrue(lines[off.id]["sv"])
        self.assertEqual(lines[off.id]["sv_reason"], "impiego_insufficiente")

    def test_no_data_yet_on_a_player_in_the_field_is_not_a_hole_in_our_data(self):
        """At the fifth minute a player can have no feature rows at all. Neither
        'non entrato' nor 'dati mancanti' is true of him — he is simply playing."""
        fresh = self._player("Appena entrato", minutes=2, starter=False, touches=0)
        self._player("Titolare", minutes=3)

        line = self._lines()[fresh.id]
        self.assertTrue(line["sv"])
        self.assertEqual(line["sv_reason"], "in_campo")

    def test_an_unused_substitute_still_reads_as_the_bench(self):
        self._player("Titolare", minutes=8)
        unused = self._player("Panchina", minutes=0, starter=False, touches=0)

        self.assertEqual(self._lines()[unused.id]["sv_reason"], "non_entrato")

    def test_once_the_match_is_over_the_gate_applies_again(self):
        """The safety of the whole change: the s.v. that reaches the ledger is the
        one that was always there. Nothing about the conclusion has moved."""
        cameo = self._player("Cameo", minutes=8)
        self.match.status = Match.STATUS_FINISHED
        self.match.data_ready = True
        self.match.save(update_fields=["status", "data_ready"])

        line = self._lines()[cameo.id]
        self.assertTrue(line["sv"], "8' a fine partita restano un senza voto")
        self.assertEqual(line["sv_reason"], "impiego_insufficiente")
