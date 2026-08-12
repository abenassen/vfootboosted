"""Tests for the real reference-championship pagella service + views."""
from __future__ import annotations

from datetime import date
from io import StringIO

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from realdata.models import (
    CARD_RED,
    CARD_YELLOW,
    Competition,
    CompetitionSeason,
    Match,
    MatchAppearance,
    MatchDisciplinaryEvent,
    PlayerTeamStint,
    PlayerZoneFeature,
    Player,
    Season,
    Team,
    TeamSeason,
)
from vfoot.api.league_views import (
    LeagueRealFixturesView,
    LeagueRealMatchDetailView,
)
from vfoot.models import (
    CurrentPlayerRole, FantasyLeague, LeagueMembership, LeaguePlayerRole,
)
from vfoot.services import matchday_state
from vfoot.services.classic_pagella import pagella_for_match


class ReferenceSeasonImmutabilityTests(TestCase):
    """The league→championship association is mandatory at creation and immutable."""

    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs_a = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        self.cs_b = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2025-2026"),
            name="Serie A 2025-2026")
        self.user = User.objects.create_user("owner", password="x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_create_requires_reference_season(self):
        r = self.client.post("/api/v1/leagues",
                             {"name": "L", "team_name": "T"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("reference_season_id", r.json())

    def test_create_sets_reference_season(self):
        r = self.client.post(
            "/api/v1/leagues",
            {"name": "L", "team_name": "T", "reference_season_id": self.cs_a.id},
            format="json")
        self.assertEqual(r.status_code, 201)
        league = FantasyLeague.objects.get(id=r.json()["league_id"])
        self.assertEqual(league.reference_season_id, self.cs_a.id)

    def test_reference_season_cannot_be_changed(self):
        r = self.client.post(
            "/api/v1/leagues",
            {"name": "L", "team_name": "T", "reference_season_id": self.cs_a.id},
            format="json")
        lid = r.json()["league_id"]
        chg = self.client.patch(f"/api/v1/leagues/{lid}/reference-season",
                                {"reference_season_id": self.cs_b.id}, format="json")
        self.assertEqual(chg.status_code, 400)
        self.assertEqual(FantasyLeague.objects.get(id=lid).reference_season_id,
                         self.cs_a.id)
        # re-sending the SAME season is a harmless no-op
        same = self.client.patch(f"/api/v1/leagues/{lid}/reference-season",
                                 {"reference_season_id": self.cs_a.id}, format="json")
        self.assertEqual(same.status_code, 200)


class RealChampionshipTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(external_id="23", name="Serie A")
        self.season = Season.objects.create(code="2026-2027")
        self.cs = CompetitionSeason.objects.create(
            competition=self.comp, season=self.season, name="Serie A 2026-2027",
            external_source="sofascore", external_id="95836")
        home = Team.objects.create(name="Torino", short_name="Torino")
        away = Team.objects.create(name="Sassuolo", short_name="Sassuolo")
        self.home_ts = TeamSeason.objects.create(competition_season=self.cs, team=home)
        self.away_ts = TeamSeason.objects.create(competition_season=self.cs, team=away)

        self.gk = Player.objects.create(full_name="Keeper One", short_name="K. One",
                                        classic_role_seed="POR")
        self.df = Player.objects.create(full_name="Def One", short_name="D. One",
                                        classic_role_seed="DIF")

        self.match = Match.objects.create(
            competition_season=self.cs, matchday=1, home_team=self.home_ts,
            away_team=self.away_ts, home_goals=1, away_goals=2,
            status=Match.STATUS_FINISHED, external_source="sofascore",
            external_id="16283045")
        # Home GK conceded 2; home defender played (no features -> senza voto).
        MatchAppearance.objects.create(match=self.match, player=self.gk,
                                       team_season=self.home_ts, side="home",
                                       minutes_played=90, is_starter=True)
        MatchAppearance.objects.create(match=self.match, player=self.df,
                                       team_season=self.home_ts, side="home",
                                       minutes_played=90, is_starter=True)
        MatchDisciplinaryEvent.objects.create(
            match=self.match, player=self.gk, team_season=self.home_ts,
            team_side="home", card_type=CARD_YELLOW, provider="sofascore")

        # empty reference is fine: outfield players with no features are unrated.
        self.reference = {}

    def test_gk_malus_and_sv_outfield(self):
        # Give the keeper enough involvement to go 'a voto'. With an empty reference
        # his index maps to the centre (6.0), which keeps this test focused on the
        # MALUS arithmetic rather than on the GK weights.
        PlayerZoneFeature.objects.create(
            match=self.match, player=self.gk, provider="sofascore",
            feature_key="touches", zone_key="z0101", value=20.0, team_side="home")

        pag = pagella_for_match(self.match, self.reference)
        home = pag["home"]
        gk_line = next(l for l in home["starters"] if l["player_id"] == self.gk.id)
        df_line = next(l for l in home["starters"] if l["player_id"] == self.df.id)

        # GK: 6.0 - 2 conceded - 0.5 yellow = 3.5
        self.assertEqual(gk_line["voto_puro"], 6.0)
        self.assertEqual(gk_line["malus"], 2.5)
        self.assertEqual(gk_line["fantavoto"], 3.5)
        self.assertFalse(gk_line["sv"])
        # Outfield with no features -> senza voto
        self.assertTrue(df_line["sv"])
        self.assertIsNone(df_line["fantavoto"])
        # Team total = sum of rated starters = only the GK
        self.assertEqual(home["total"], 3.5)
        self.assertEqual(pag["away"]["starters"], [])  # no away appearances seeded

    def test_own_goal_carries_the_minus_two_malus(self):
        """An own goal (raw_stats.ownGoals) is a -2 in the fantavoto. The voto puro
        is feature-based and blind to it, so the malus is the only place it lands."""
        og = Player.objects.create(full_name="Own Goal", short_name="O. Goal",
                                   classic_role_seed="DIF")
        MatchAppearance.objects.create(match=self.match, player=og,
                                       team_season=self.home_ts, side="home",
                                       minutes_played=90, is_starter=True,
                                       raw_stats={"ownGoals": 1})
        PlayerZoneFeature.objects.create(
            match=self.match, player=og, provider="sofascore",
            feature_key="touches", zone_key="z0101", value=30.0, team_side="home")

        line = next(l for l in pagella_for_match(self.match, self.reference)["home"]
                    ["starters"] if l["player_id"] == og.id)
        self.assertEqual(line["events"]["own_goals"], 1)
        self.assertEqual(line["voto_puro"], 6.0)   # empty reference -> centre
        self.assertEqual(line["malus"], 2.0)
        self.assertEqual(line["fantavoto"], 4.0)

    def test_own_goal_flat_penalty_without_sub_minute_timing(self):
        """Rows with no elapsed_seconds (imported before we captured it) cannot be
        graded — a minute is too coarse — so a single flat penalty applies."""
        from realdata.models import MatchShot
        from vfoot.services.classic_rating import own_goal_adjustments, OWN_GOAL_VOTE_FLAT
        MatchShot.objects.create(match=self.match, player=self.df, team_side="away",
                                 minute=50, shot_type="goal", is_goal=True, xg=0.0,
                                 xgot=0.0, elapsed_seconds=None,
                                 provider="sofascore", zone_key="z_4_2")
        # Even a same-minute opponent shot does not change it without seconds.
        opp = Player.objects.create(full_name="Opp Shooter", short_name="O. Shooter")
        MatchShot.objects.create(match=self.match, player=opp, team_side="away",
                                 minute=50, shot_type="save", is_goal=False, xg=0.1,
                                 xgot=0.2, elapsed_seconds=None,
                                 provider="sofascore", zone_key="z_4_2")
        self.assertEqual(own_goal_adjustments(self.match.id)[self.df.id],
                         OWN_GOAL_VOTE_FLAT)

    def test_own_goal_graded_by_seconds_when_available(self):
        """With sub-minute timing: an opponent shot within the window is the shot it
        deflected (unlucky); a coincidental shot 40s away leaves it a solo error."""
        from realdata.models import MatchShot
        from vfoot.services.classic_rating import (
            own_goal_adjustments, OWN_GOAL_VOTE_DEFLECTION, OWN_GOAL_VOTE_SOLO)
        opp = Player.objects.create(full_name="Opp Shooter", short_name="O. Shooter")
        # own goal at 50'02" (3002s from kick-off)
        MatchShot.objects.create(match=self.match, player=self.df, team_side="away",
                                 minute=50, shot_type="goal", is_goal=True, xg=0.0,
                                 xgot=0.0, elapsed_seconds=3002,
                                 provider="sofascore", zone_key="z_4_2")
        # a coincidental opponent shot 40s earlier -> still a solo error
        MatchShot.objects.create(match=self.match, player=opp, team_side="away",
                                 minute=50, shot_type="save", is_goal=False, xg=0.1,
                                 xgot=0.2, elapsed_seconds=2962,
                                 provider="sofascore", zone_key="z_4_2")
        self.assertEqual(own_goal_adjustments(self.match.id)[self.df.id],
                         OWN_GOAL_VOTE_SOLO)
        # the shot it actually deflected, 2s before -> a deflection
        MatchShot.objects.create(match=self.match, player=opp, team_side="away",
                                 minute=50, shot_type="miss", is_goal=False, xg=0.3,
                                 xgot=0.0, elapsed_seconds=3000,
                                 provider="sofascore", zone_key="z_4_2")
        self.assertEqual(own_goal_adjustments(self.match.id)[self.df.id],
                         OWN_GOAL_VOTE_DEFLECTION)

    def test_missed_penalty_malus_and_result_scaled_drop(self):
        """A missed penalty (shot situation='penalty', not scored) is -3 in the
        fantavoto, like a goal is +3. In the voto puro it also carries a result-scaled
        drop: -1 when converting it would have flipped the result (the taker's team
        drew or lost by one), -0.5 when the result was already decided."""
        from realdata.models import MatchShot
        from vfoot.services.classic_rating import (
            penalty_missed_adjustments, PENALTY_MISSED_VOTE_RELEVANT,
            PENALTY_MISSED_VOTE_IRRELEVANT)
        # home lost 1-2: the home taker's miss was decisive (a goal -> 2-2)
        MatchShot.objects.create(match=self.match, player=self.df, team_side="home",
                                 minute=88, shot_type="save", is_goal=False, xg=0.79,
                                 xgot=0.7, situation="penalty",
                                 provider="sofascore", zone_key="z_4_2")
        self.assertEqual(penalty_missed_adjustments(self.match.id)[self.df.id],
                         PENALTY_MISSED_VOTE_RELEVANT)
        # an away taker whose team won 2-1: the miss did not change the result
        fw = Player.objects.create(full_name="Fwd Away", short_name="F. Away",
                                   classic_role_seed="ATT")
        MatchAppearance.objects.create(match=self.match, player=fw,
                                       team_season=self.away_ts, side="away",
                                       minutes_played=90, is_starter=True)
        MatchShot.objects.create(match=self.match, player=fw, team_side="away",
                                 minute=70, shot_type="miss", is_goal=False, xg=0.79,
                                 xgot=0.0, situation="penalty",
                                 provider="sofascore", zone_key="z_4_2")
        self.assertEqual(penalty_missed_adjustments(self.match.id)[fw.id],
                         PENALTY_MISSED_VOTE_IRRELEVANT)
        # the -3 malus and the -1 drop both reach the pagella (df rated via touches)
        PlayerZoneFeature.objects.create(
            match=self.match, player=self.df, provider="sofascore",
            feature_key="touches", zone_key="z_1_1", value=30.0, team_side="home")
        line = next(l for l in pagella_for_match(self.match, self.reference)["home"]
                    ["starters"] if l["player_id"] == self.df.id)
        self.assertEqual(line["events"]["missed_penalties"], 1)
        self.assertEqual(line["malus"], 3.0)
        self.assertEqual(line["voto_puro"], 5.0)      # 6.0 centre - 1.0 drop
        self.assertEqual(line["fantavoto"], 2.0)      # 5.0 - 3 malus

    def test_saved_penalty_credited_to_the_keeper_on_pitch(self):
        """A saved penalty (+3 Rp) goes to the keeper defending it — the opposite
        side from the taker — and, after a keeper change, to the one on the pitch."""
        from realdata.models import MatchShot
        from vfoot.services.classic_pagella import _penalties_saved_for_match
        Player.objects.filter(id=self.gk.id).update(is_goalkeeper=True)
        # away take a penalty at 30', the home starting keeper saves it
        MatchShot.objects.create(match=self.match, player=None, team_side="away",
                                 minute=30, shot_type="save", is_goal=False, xg=0.79,
                                 xgot=0.7, situation="penalty", provider="sofascore",
                                 zone_key="z_4_2")
        self.assertEqual(_penalties_saved_for_match(self.match.id), {self.gk.id: 1})
        # a back-up keeper comes on at 60'; a save at 75' is his, not the starter's
        MatchAppearance.objects.filter(match=self.match,
                                       player=self.gk).update(minutes_played=60)
        gk2 = Player.objects.create(full_name="Keeper Two", short_name="K. Two",
                                    classic_role_seed="POR", is_goalkeeper=True)
        MatchAppearance.objects.create(match=self.match, player=gk2,
                                       team_season=self.home_ts, side="home",
                                       minutes_played=30, is_starter=False)
        MatchShot.objects.create(match=self.match, player=None, team_side="away",
                                 minute=75, shot_type="save", is_goal=False, xg=0.79,
                                 xgot=0.7, situation="penalty", provider="sofascore",
                                 zone_key="z_4_2")
        self.assertEqual(_penalties_saved_for_match(self.match.id),
                         {self.gk.id: 1, gk2.id: 1})
        # an off-target penalty is a miss, not a save -> no +3
        MatchShot.objects.create(match=self.match, player=None, team_side="away",
                                 minute=80, shot_type="miss", is_goal=False, xg=0.79,
                                 xgot=0.0, situation="penalty", provider="sofascore",
                                 zone_key="z_4_2")
        self.assertEqual(_penalties_saved_for_match(self.match.id),
                         {self.gk.id: 1, gk2.id: 1})

    def test_goals_conceded_charged_to_the_keeper_on_pitch(self):
        """The -1/goal keeper malus goes to whoever was in goal when each was scored,
        not the whole team's total to every keeper who appeared (Okoye gd16: subbed
        off before the goals, fanta charged him 0, we used to charge 5)."""
        from realdata.models import MatchShot
        from vfoot.services.classic_pagella import _goals_conceded_by_keeper
        Player.objects.filter(id=self.gk.id).update(is_goalkeeper=True)
        # home keeper self.gk plays 45', then a back-up comes on. Home concedes 2 (1-2):
        MatchAppearance.objects.filter(match=self.match,
                                       player=self.gk).update(minutes_played=45)
        gk2 = Player.objects.create(full_name="Keeper Two", short_name="K. Two",
                                    classic_role_seed="POR", is_goalkeeper=True)
        MatchAppearance.objects.create(match=self.match, player=gk2,
                                       team_season=self.home_ts, side="home",
                                       minutes_played=45, is_starter=False)
        # one goal before the change (35'), one after (70')
        MatchShot.objects.create(match=self.match, player=None, team_side="away",
                                 minute=35, shot_type="goal", is_goal=True, xg=0.3,
                                 xgot=0.7, provider="sofascore", zone_key="z_4_2")
        MatchShot.objects.create(match=self.match, player=None, team_side="away",
                                 minute=70, shot_type="goal", is_goal=True, xg=0.3,
                                 xgot=0.7, provider="sofascore", zone_key="z_4_2")
        conceded = _goals_conceded_by_keeper(self.match.id)
        self.assertEqual(conceded.get(self.gk.id), 1)   # only the 35' goal
        self.assertEqual(conceded.get(gk2.id), 1)       # only the 70' goal

    def test_own_goal_shot_is_not_counted_as_a_goal_scored(self):
        """SofaScore files an own goal as a 'goal' shot tagged with the OPPONENT's
        side; it must not inflate the own-scorer's shots_goal (a goals-scored proxy),
        while a real goal on the player's own side still counts."""
        from realdata.models import MatchShot
        from vfoot.services.classic_rating import _per_match_player_totals
        scorer = Player.objects.create(full_name="Real Scorer", short_name="R. Scorer",
                                       classic_role_seed="ATT")
        MatchAppearance.objects.create(match=self.match, player=scorer,
                                       team_season=self.home_ts, side="home",
                                       minutes_played=90, is_starter=True)
        # A match needs at least one zone row to be scoreable at all (see
        # test_a_match_without_zone_features_is_not_scored): without it the whole
        # match is skipped, which would make this test pass for the wrong reason.
        # Realistic too — a player who gets a shot off has touches.
        PlayerZoneFeature.objects.create(
            match=self.match, player=scorer, provider="sofascore",
            feature_key="touches", zone_key="z_4_2", value=30.0, team_side="home")
        # df is home (setUp): an own goal is tagged with the away side.
        MatchShot.objects.create(match=self.match, player=self.df, team_side="away",
                                 minute=50, shot_type="goal", is_goal=True,
                                 xg=0.0, xgot=0.9, provider="sofascore", zone_key="z_4_2")
        MatchShot.objects.create(match=self.match, player=scorer, team_side="home",
                                 minute=60, shot_type="goal", is_goal=True,
                                 xg=0.3, xgot=0.7, provider="sofascore", zone_key="z_4_2")
        tot = _per_match_player_totals([self.match.id])
        self.assertEqual(tot[(self.match.id, scorer.id)]["shots_goal"], 1.0)
        self.assertEqual(tot.get((self.match.id, self.df.id), {}).get("shots_goal", 0), 0)

    def test_a_match_without_zone_features_is_not_scored(self):
        """A database whose zone tables were emptied must produce NO votes.

        This is the slim copy from ``export_dev_db``, which keeps ``MatchShot`` and
        ``MatchAppearance.raw_stats`` while dropping the zone features the index is
        built from. The two merges read exactly those surviving tables, so before
        the coverage check they rebuilt a row per appearance carrying a couple of
        features out of forty — and a near-zero index sits BELOW every frozen
        per-role mean, so the season came out as a complete, ordered, entirely
        believable listone in which nobody could exceed 6. Refusing to score is
        what the export already promises; scoring on the leftovers is worse than
        an empty page because nothing says it happened.
        """
        from realdata.models import MatchShot
        from vfoot.services.classic_rating import _per_match_player_totals
        MatchShot.objects.create(match=self.match, player=self.df, team_side="home",
                                 minute=60, shot_type="goal", is_goal=True, xg=0.3,
                                 xgot=0.7, provider="sofascore", zone_key="z_4_2")
        self.assertFalse(PlayerZoneFeature.objects.filter(match=self.match).exists())
        self.assertEqual(_per_match_player_totals([self.match.id]), {})

        # One zone row is enough to make the match scoreable again: the check is
        # per MATCH, so a failed import degrades that matchday and not the season.
        PlayerZoneFeature.objects.create(
            match=self.match, player=self.df, provider="sofascore",
            feature_key="touches", zone_key="z_4_2", value=30.0, team_side="home")
        tot = _per_match_player_totals([self.match.id])
        self.assertEqual(tot[(self.match.id, self.df.id)]["shots_goal"], 1.0)

    def test_gk_without_data_is_senza_voto(self):
        # No features at all -> the keeper is s.v. like any other player (he no
        # longer gets an automatic 6.0 baseline).
        pag = pagella_for_match(self.match, self.reference)
        gk_line = next(l for l in pag["home"]["starters"]
                       if l["player_id"] == self.gk.id)
        self.assertTrue(gk_line["sv"])
        self.assertIsNone(gk_line["fantavoto"])

    def test_unknown_role_is_still_rated(self):
        """A hole in our squad data must never surface as 'senza voto'.

        Regression: players the Transfermarkt import failed to match had an empty
        classic_role_seed, the rating layer skipped them, and the pagella rendered that
        as s.v. — so a goalscorer who played an hour was shown as unrated, and
        three whole promoted sides were wiped out."""
        nameless = Player.objects.create(full_name="No Role", short_name="N. Role")
        MatchAppearance.objects.create(match=self.match, player=nameless,
                                       team_season=self.home_ts, side="home",
                                       minutes_played=61, is_starter=True, goals=1)
        PlayerZoneFeature.objects.create(
            match=self.match, player=nameless, provider="sofascore",
            feature_key="touches", zone_key="z0101", value=53.0, team_side="home")

        line = next(l for l in pagella_for_match(self.match, self.reference)["home"]
                    ["starters"] if l["player_id"] == nameless.id)
        self.assertFalse(line["sv"])
        self.assertIsNotNone(line["voto_puro"])
        self.assertEqual(line["bonus"], 3.0)  # his goal is counted
        # ...but the guessed role is reported as a guess, not as fact.
        self.assertFalse(line["role_known"])

    def test_unknown_role_keeper_recognised_from_his_own_features(self):
        """A keeper without a declared role must not be scored as a midfielder:
        that silently costs him the -1 per goal conceded."""
        nameless = Player.objects.create(full_name="No Role GK", short_name="N. GK")
        MatchAppearance.objects.create(match=self.match, player=nameless,
                                       team_season=self.away_ts, side="away",
                                       minutes_played=90, is_starter=True)
        for key, val in (("touches", 30.0), ("gk_saves", 4.0)):
            PlayerZoneFeature.objects.create(
                match=self.match, player=nameless, provider="sofascore",
                feature_key=key, zone_key="z0101", value=val, team_side="away")

        line = next(l for l in pagella_for_match(self.match, self.reference)["away"]
                    ["starters"] if l["player_id"] == nameless.id)
        self.assertEqual(line["role"], "POR")
        self.assertFalse(line["role_known"])
        self.assertEqual(line["malus"], 1.0)  # the one home goal he conceded

    def test_long_appearance_is_rated_regardless_of_touches(self):
        """The touch threshold judges whether a CAMEO was involved enough. Applied
        to a player who was on the pitch for most of the match it produced absurd
        s.v. — including four full 90' appearances in a single season."""
        quiet = Player.objects.create(full_name="Quiet One", short_name="Q. One",
                                      classic_role_seed="ATT")
        MatchAppearance.objects.create(match=self.match, player=quiet,
                                       team_season=self.home_ts, side="home",
                                       minutes_played=90, is_starter=True)
        PlayerZoneFeature.objects.create(
            match=self.match, player=quiet, provider="sofascore",
            feature_key="touches", zone_key="z0101", value=8.0, team_side="home")

        line = next(l for l in pagella_for_match(self.match, self.reference)["home"]
                    ["starters"] if l["player_id"] == quiet.id)
        self.assertFalse(line["sv"])

    def test_short_uninvolved_cameo_is_still_senza_voto(self):
        """The counterpart: the touch gate must keep working where it belongs —
        the 14-16' window, after the thresholds were set from fantacalcio's own
        s.v. set (see MIN_MINUTES_RATED). At 18' the minutes alone now decide,
        as they do for the pagelle we are agreeing with."""
        cameo = Player.objects.create(full_name="Cameo One", short_name="C. One",
                                      classic_role_seed="ATT")
        MatchAppearance.objects.create(match=self.match, player=cameo,
                                       team_season=self.home_ts, side="home",
                                       minutes_played=15, is_starter=False)
        PlayerZoneFeature.objects.create(
            match=self.match, player=cameo, provider="sofascore",
            feature_key="touches", zone_key="z0101", value=4.0, team_side="home")

        line = next(l for l in pagella_for_match(self.match, self.reference)["home"]
                    ["bench"] if l["player_id"] == cameo.id)
        self.assertTrue(line["sv"])
        self.assertEqual(line["sv_reason"], "impiego_insufficiente")

    def _booked_cameo(self, card_type):
        """A 10' substitute with 4 touches who picks up ``card_type`` at the 90th."""
        who = Player.objects.create(full_name=f"Carded {card_type}",
                                    short_name=f"C. {card_type[:3]}",
                                    classic_role_seed="CEN")
        MatchAppearance.objects.create(match=self.match, player=who,
                                       team_season=self.home_ts, side="home",
                                       minutes_played=10, is_starter=False)
        PlayerZoneFeature.objects.create(
            match=self.match, player=who, provider="sofascore",
            feature_key="touches", zone_key="z0101", value=4.0, team_side="home")
        MatchDisciplinaryEvent.objects.create(
            match=self.match, player=who, team_season=self.home_ts,
            team_side="home", card_type=card_type, minute=90, provider="sofascore",
            provider_event_id=f"card-{card_type}-{who.id}")
        return next(l for l in pagella_for_match(self.match, self.reference)["home"]
                    ["bench"] if l["player_id"] == who.id)

    def test_a_booking_does_not_earn_a_short_cameo_a_vote(self):
        """Measured against the pagelle, not assumed: of the sub-threshold cameos
        whose only event was a yellow, fantacalcio rates 7 of 39. Their convention
        is coherent — an s.v. player is replaced, so his booking never scores — and
        forcing a vote here would invent a performance reading purely to attach a
        -0.5 the pagella declined to attach."""
        line = self._booked_cameo(CARD_YELLOW)
        self.assertTrue(line["sv"])
        self.assertEqual(line["sv_reason"], "impiego_insufficiente")

    def test_a_sending_off_still_earns_a_vote_however_short_the_cameo(self):
        """The other side of the same measurement: 5 of 5 sent-off cameos are rated
        by the pagelle. A red card is an event, a yellow is a footnote."""
        line = self._booked_cameo(CARD_RED)
        self.assertFalse(line["sv"])
        self.assertIsNotNone(line["voto_puro"])

    def test_sv_distinguishes_missing_data_from_little_football(self):
        line = next(l for l in pagella_for_match(self.match, self.reference)["home"]
                    ["starters"] if l["player_id"] == self.df.id)
        self.assertTrue(line["sv"])
        self.assertEqual(line["sv_reason"], "dati_mancanti")

    def test_league_frozen_role_wins_over_the_live_seed(self):
        """A league fixes its roles when its listone opens; a later Transfermarkt
        re-import may move Player.classic_role_seed, but the league's pagella must keep
        agreeing with the league's own listone."""
        league, _ = self._league()
        LeaguePlayerRole.objects.create(league=league, player=self.df, role="ATT",
                                        source=LeaguePlayerRole.SOURCE_SEED)
        PlayerZoneFeature.objects.create(
            match=self.match, player=self.df, provider="sofascore",
            feature_key="touches", zone_key="z0101", value=40.0, team_side="home")

        without = next(l for l in pagella_for_match(self.match, self.reference)["home"]
                       ["starters"] if l["player_id"] == self.df.id)
        self.assertEqual(without["role"], "DIF")  # the live seed

        within = next(l for l in pagella_for_match(self.match, self.reference,
                                                   league=league)["home"]["starters"]
                      if l["player_id"] == self.df.id)
        self.assertEqual(within["role"], "ATT")   # the league's frozen listone
        self.assertTrue(within["role_known"])

    def _league(self):
        user = User.objects.create_user("mgr", password="x")
        league = FantasyLeague.objects.create(
            name="L", owner=user, mode="classic", reference_season=self.cs)
        LeagueMembership.objects.create(league=league, user=user,
                                        role=LeagueMembership.ROLE_ADMIN)
        return league, user

    def test_real_fixtures_view_groups_by_matchday(self):
        league, user = self._league()
        req = APIRequestFactory().get(f"/leagues/{league.id}/real-fixtures")
        force_authenticate(req, user=user)
        resp = LeagueRealFixturesView.as_view()(req, league_id=league.id)
        resp.render()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["season"]["name"], "Serie A 2026-2027")
        self.assertEqual(len(resp.data["matchdays"]), 1)
        fx = resp.data["matchdays"][0]["fixtures"][0]
        self.assertEqual(fx["home_team"], "Torino")
        self.assertTrue(fx["has_detail"])

    def test_real_match_detail_view_returns_classic_shape(self):
        league, user = self._league()
        req = APIRequestFactory().get(
            f"/leagues/{league.id}/real-matches/{self.match.id}")
        force_authenticate(req, user=user)
        resp = LeagueRealMatchDetailView.as_view()(
            req, league_id=league.id, match_id=self.match.id)
        resp.render()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["mode"], "classic")
        self.assertEqual(resp.data["result"], "away")  # 1-2
        self.assertEqual(resp.data["home_goals"], 1)

    def test_starter_role_order(self):
        # GK first, then defence (goalkeeper -> defence -> midfield -> attack).
        pag = pagella_for_match(self.match, self.reference)
        self.assertEqual([l["role"] for l in pag["home"]["starters"]], ["POR", "DIF"])

    def test_superseded_postponed_hidden(self):
        league, user = self._league()
        # a postponed placeholder for the SAME leg as the played match is hidden
        Match.objects.create(
            competition_season=self.cs, matchday=1, home_team=self.home_ts,
            away_team=self.away_ts, status=Match.STATUS_POSTPONED,
            external_source="sofascore", external_id="pp-super")
        req = APIRequestFactory().get(f"/leagues/{league.id}/real-fixtures?matchday=1")
        force_authenticate(req, user=user)
        resp = LeagueRealFixturesView.as_view()(req, league_id=league.id)
        resp.render()
        fx = resp.data["matchdays"][0]["fixtures"]
        self.assertEqual(len(fx), 1)
        self.assertEqual(fx[0]["status"], "finished")

    def test_unreplayed_postponed_stays_visible(self):
        league, user = self._league()
        h = Team.objects.create(name="Genoa")
        a = Team.objects.create(name="Pisa")
        hts = TeamSeason.objects.create(competition_season=self.cs, team=h)
        ats = TeamSeason.objects.create(competition_season=self.cs, team=a)
        Match.objects.create(
            competition_season=self.cs, matchday=1, home_team=hts, away_team=ats,
            status=Match.STATUS_POSTPONED, external_source="sofascore",
            external_id="pp-lonely")
        req = APIRequestFactory().get(f"/leagues/{league.id}/real-fixtures?matchday=1")
        force_authenticate(req, user=user)
        resp = LeagueRealFixturesView.as_view()(req, league_id=league.id)
        resp.render()
        statuses = {f["status"] for f in resp.data["matchdays"][0]["fixtures"]}
        self.assertIn("postponed", statuses)  # no played sibling -> still shown

    def test_a_match_in_progress_is_offered_for_reading(self):
        """The calendar used to hand out the link only at the final whistle, so the
        one round worth following while it happens was the one with no way in."""
        Match.objects.filter(id=self.match.id).update(
            status=Match.STATUS_LIVE, data_ready=False)
        league, user = self._league()
        req = APIRequestFactory().get(f"/leagues/{league.id}/real-fixtures?matchday=1")
        force_authenticate(req, user=user)
        resp = LeagueRealFixturesView.as_view()(req, league_id=league.id)
        resp.render()
        fx = next(f for f in resp.data["matchdays"][0]["fixtures"]
                  if f["id"] == self.match.id)
        self.assertEqual(fx["status"], "live")
        self.assertTrue(fx["has_detail"])

    def test_the_votes_of_a_live_match_are_marked_as_movable(self):
        """Shown, but never as a verdict: at the fiftieth minute every number on
        the page can still change."""
        Match.objects.filter(id=self.match.id).update(
            status=Match.STATUS_LIVE, data_ready=False)
        league, user = self._league()
        req = APIRequestFactory().get(
            f"/leagues/{league.id}/real-matches/{self.match.id}")
        force_authenticate(req, user=user)
        resp = LeagueRealMatchDetailView.as_view()(
            req, league_id=league.id, match_id=self.match.id)
        resp.render()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["live"])
        self.assertTrue(resp.data["provisional"])
        self.assertTrue(resp.data["home"]["provisional"])
        self.assertTrue(resp.data["away"]["provisional"])

    def test_a_finished_but_unconfirmed_match_is_provisional_without_being_live(self):
        """The two states are not one: at the final whistle the votes can still move
        by a tenth until the provider confirms, but nobody else is coming on — so
        the totals stay marked and the individual lines do not."""
        Match.objects.filter(id=self.match.id).update(
            status=Match.STATUS_FINISHED, data_ready=False)
        league, user = self._league()
        req = APIRequestFactory().get(
            f"/leagues/{league.id}/real-matches/{self.match.id}")
        force_authenticate(req, user=user)
        resp = LeagueRealMatchDetailView.as_view()(
            req, league_id=league.id, match_id=self.match.id)
        resp.render()
        self.assertFalse(resp.data["live"])
        self.assertTrue(resp.data["provisional"])
        self.assertIsNone(resp.data["minute"])
        lines = resp.data["home"]["starters"] + resp.data["home"]["bench"]
        self.assertFalse(any(l.get("provisional") for l in lines))

    def test_a_live_match_carries_its_clock_and_marks_every_line(self):
        Match.objects.filter(id=self.match.id).update(
            status=Match.STATUS_LIVE, data_ready=False)
        league, user = self._league()
        req = APIRequestFactory().get(
            f"/leagues/{league.id}/real-matches/{self.match.id}")
        force_authenticate(req, user=user)
        resp = LeagueRealMatchDetailView.as_view()(
            req, league_id=league.id, match_id=self.match.id)
        resp.render()
        # The clock is whoever has been on longest, read off the appearances.
        longest = max(a.minutes_played or 0 for a in
                      MatchAppearance.objects.filter(match=self.match))
        self.assertEqual(resp.data["minute"], longest)
        lines = resp.data["home"]["starters"] + resp.data["home"]["bench"]
        self.assertTrue(all(l.get("provisional") for l in lines))

    def test_a_settled_match_is_not_marked_provisional(self):
        Match.objects.filter(id=self.match.id).update(
            status=Match.STATUS_FINISHED, data_ready=True)
        league, user = self._league()
        req = APIRequestFactory().get(
            f"/leagues/{league.id}/real-matches/{self.match.id}")
        force_authenticate(req, user=user)
        resp = LeagueRealMatchDetailView.as_view()(
            req, league_id=league.id, match_id=self.match.id)
        resp.render()
        self.assertFalse(resp.data["live"])
        self.assertFalse(resp.data["provisional"])

    def test_detail_404_without_appearances(self):
        league, user = self._league()
        empty = Match.objects.create(
            competition_season=self.cs, matchday=2, home_team=self.home_ts,
            away_team=self.away_ts, status=Match.STATUS_SCHEDULED,
            external_source="sofascore", external_id="999999")
        req = APIRequestFactory().get(
            f"/leagues/{league.id}/real-matches/{empty.id}")
        force_authenticate(req, user=user)
        resp = LeagueRealMatchDetailView.as_view()(
            req, league_id=league.id, match_id=empty.id)
        self.assertEqual(resp.status_code, 404)


class LeagueRoleDoesNotRescoreTests(TestCase):
    """The vote is the same in every league; only the LABEL follows the league.

    Pinned deliberately, because the two roles part in silence and the arithmetic
    hides it: over a real season the gap averages 0.028 of a vote and only moves
    the shown half-point twice in thirty-six appearances. A test that let it drift
    would not be caught by looking at a page. See AGENTS.md "Classic Role
    Resolution" for why it was chosen this way, and what reversing it costs.
    """

    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027", external_source="sofascore",
            external_id="95836")
        home = TeamSeason.objects.create(
            competition_season=cs, team=Team.objects.create(name="Torino"))
        away = TeamSeason.objects.create(
            competition_season=cs, team=Team.objects.create(name="Sassuolo"))
        self.match = Match.objects.create(
            competition_season=cs, matchday=1, home_team=home, away_team=away,
            home_goals=1, away_goals=1, status=Match.STATUS_FINISHED,
            external_source="sofascore", external_id="16283046")

        self.p = Player.objects.create(full_name="Ala Contesa", short_name="A. Contesa",
                                       classic_role_seed="CEN")
        CurrentPlayerRole.objects.create(
            player=self.p, role_data="CEN", role_mitigated="CEN",
            method=CurrentPlayerRole.METHOD_CATEGORY, tm_position="right winger")
        MatchAppearance.objects.create(match=self.match, player=self.p,
                                       team_season=home, side="home",
                                       minutes_played=90, is_starter=True)
        PlayerZoneFeature.objects.create(
            match=self.match, player=self.p, provider="sofascore",
            feature_key="touches", zone_key="z0101", value=60.0, team_side="home")

        # The two role buckets are placed a whole sigma apart, so scoring him under
        # the wrong one could not be mistaken for rounding: it would be worth about
        # six tenths of a vote, not the hundredths the real reference produces.
        self.reference = {"CEN": {"mean": 0.0, "std": 1.0, "n": 100},
                          "ATT": {"mean": 1.0, "std": 1.0, "n": 100}}

        admin = User.objects.create_user("boss", password="x")
        self.league = FantasyLeague.objects.create(
            name="L", owner=admin, mode="classic", reference_season=cs)
        LeagueMembership.objects.create(league=self.league, user=admin,
                                        role=LeagueMembership.ROLE_ADMIN)
        LeaguePlayerRole.objects.create(
            league=self.league, player=self.p, role="ATT",
            source=LeaguePlayerRole.SOURCE_ADMIN)

    def _line(self, league=None):
        pag = pagella_for_match(self.match, self.reference, league=league)
        return next(l for l in pag["home"]["starters"] if l["player_id"] == self.p.id)

    def test_the_league_changes_the_label_and_not_the_vote(self):
        free, in_league = self._line(), self._line(league=self.league)
        self.assertEqual(free["role"], "CEN")
        self.assertEqual(in_league["role"], "ATT")   # the frozen role is the label
        self.assertEqual(in_league["voto_puro"], free["voto_puro"])

    def test_the_vote_is_scored_against_the_measured_role(self):
        """Not merely 'the same in both' — the same as the CEN one, by value.

        His index sits on the CEN mean, so that bucket puts him at exactly 6.0.
        The ATT bucket is a whole sigma above, which would drag the same index to
        6 + 0.8 * (90/115) * (0 - 1) / 1 = 5.37, shown as 5.5. Asserting the 6.0
        is therefore asserting WHICH mean was subtracted, not merely that two
        calls agree — two calls would agree just as well if both were wrong."""
        in_league = self._line(league=self.league)
        self.assertEqual(in_league["voto_puro"], 6.0)
        self.assertNotEqual(in_league["voto_puro"], 5.5)


class ChampionshipWithoutALeagueTests(TestCase):
    """Il campionato vero si legge anche senza una lega.

    Chi si è appena iscritto non ne ha nessuna, e fino a ieri le uniche pagine che
    poteva aprire dicevano «Seleziona una lega». Calendario, pagelle e listone di
    un campionato però non appartengono a nessuna lega: sono la stagione. Qui si
    verifica che le due strade — per lega e per stagione — passino dalla stessa
    funzione, e che la sola differenza sia quello che la lega aggiunge di suo.
    """

    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.open_cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        self.over_cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2025-2026"),
            name="Serie A 2025-2026")
        home = TeamSeason.objects.create(
            competition_season=self.open_cs, team=Team.objects.create(name="Torino"))
        away = TeamSeason.objects.create(
            competition_season=self.open_cs, team=Team.objects.create(name="Sassuolo"))
        self.match = Match.objects.create(
            competition_season=self.open_cs, matchday=1, home_team=home,
            away_team=away, home_goals=1, away_goals=2,
            status=Match.STATUS_FINISHED, external_id="m1")
        Match.objects.create(
            competition_season=self.open_cs, matchday=2, home_team=home,
            away_team=away, status=Match.STATUS_SCHEDULED, external_id="m2")
        self.player = Player.objects.create(full_name="Uno Due", short_name="U. Due",
                                            classic_role_seed="DIF")
        MatchAppearance.objects.create(match=self.match, player=self.player,
                                       team_season=home, side="home",
                                       minutes_played=90, is_starter=True)
        PlayerTeamStint.objects.create(player=self.player, team_season=home,
                                       start_date=date(2026, 7, 1))
        # La stagione conclusa: una sola partita, finita. Nessuna da giocare.
        over_home = TeamSeason.objects.create(
            competition_season=self.over_cs, team=Team.objects.create(name="Lecce"))
        over_away = TeamSeason.objects.create(
            competition_season=self.over_cs, team=Team.objects.create(name="Empoli"))
        Match.objects.create(
            competition_season=self.over_cs, matchday=38, home_team=over_home,
            away_team=over_away, home_goals=0, away_goals=0,
            status=Match.STATUS_FINISHED, external_id="old1")

        self.user = User.objects.create_user("nuovo", password="x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_the_calendar_is_readable_without_a_league(self):
        r = self.client.get(f"/api/v1/real-seasons/{self.open_cs.id}/fixtures")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["season"]["name"], "Serie A 2026-2027")
        self.assertEqual([g["matchday"] for g in body["matchdays"]], [1, 2])
        # e la giornata «corrente» è la prima non finita, come nella vista di lega
        self.assertEqual(body["current_matchday"], 2)

    def test_the_pagella_is_readable_without_a_league(self):
        r = self.client.get(
            f"/api/v1/real-seasons/{self.open_cs.id}/matches/{self.match.id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["result"], "away")

    def test_a_match_of_another_season_is_not_served_under_this_one(self):
        r = self.client.get(
            f"/api/v1/real-seasons/{self.over_cs.id}/matches/{self.match.id}")
        self.assertEqual(r.status_code, 404)

    def test_the_listone_without_a_league_has_no_owners(self):
        r = self.client.get(f"/api/v1/real-seasons/{self.open_cs.id}/players")
        self.assertEqual(r.status_code, 200)
        rows = r.json()["players"]
        self.assertEqual([p["name"] for p in rows], ["U. Due"])
        self.assertFalse(rows[0]["owned"])
        self.assertIsNone(rows[0]["owner"])
        # nessuna decisione di ruolo in sospeso: fuori da una lega non si compra
        self.assertFalse(rows[0]["role_undecided"])
        self.assertEqual(rows[0]["role"], "DIF")

    def test_only_the_open_seasons_are_offered(self):
        every = self.client.get("/api/v1/real-seasons").json()
        self.assertEqual({s["id"]: s["open"] for s in every},
                         {self.open_cs.id: True, self.over_cs.id: False})
        only_open = self.client.get("/api/v1/real-seasons?open=1").json()
        self.assertEqual([s["id"] for s in only_open], [self.open_cs.id])

    def test_a_season_without_a_calendar_yet_is_still_open(self):
        """L'edizione dell'anno prossimo esiste prima del suo calendario."""
        next_cs = CompetitionSeason.objects.create(
            competition=self.open_cs.competition,
            season=Season.objects.create(code="2027-2028"))
        self.assertIn(next_cs.id, matchday_state.open_season_ids())

    def test_a_postponed_leftover_does_not_keep_a_season_alive(self):
        Match.objects.create(
            competition_season=self.over_cs, matchday=38,
            home_team=TeamSeason.objects.filter(
                competition_season=self.over_cs).first(),
            away_team=TeamSeason.objects.filter(
                competition_season=self.over_cs).last(),
            status=Match.STATUS_POSTPONED, external_id="old-pp")
        self.assertNotIn(self.over_cs.id, matchday_state.open_season_ids())
