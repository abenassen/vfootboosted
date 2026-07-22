"""Tests for the real reference-championship pagella service + views."""
from __future__ import annotations

from io import StringIO

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from realdata.models import (
    CARD_YELLOW,
    Competition,
    CompetitionSeason,
    Match,
    MatchAppearance,
    MatchDisciplinaryEvent,
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
from vfoot.models import FantasyLeague, LeagueMembership
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
                                        classic_role="POR")
        self.df = Player.objects.create(full_name="Def One", short_name="D. One",
                                        classic_role="DIF")

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
        classic_role, the rating layer skipped them, and the pagella rendered that
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
                                      classic_role="ATT")
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
        """The counterpart: the touch gate must keep working where it belongs."""
        cameo = Player.objects.create(full_name="Cameo One", short_name="C. One",
                                      classic_role="ATT")
        MatchAppearance.objects.create(match=self.match, player=cameo,
                                       team_season=self.home_ts, side="home",
                                       minutes_played=18, is_starter=False)
        PlayerZoneFeature.objects.create(
            match=self.match, player=cameo, provider="sofascore",
            feature_key="touches", zone_key="z0101", value=4.0, team_side="home")

        line = next(l for l in pagella_for_match(self.match, self.reference)["home"]
                    ["bench"] if l["player_id"] == cameo.id)
        self.assertTrue(line["sv"])
        self.assertEqual(line["sv_reason"], "impiego_insufficiente")

    def test_sv_distinguishes_missing_data_from_little_football(self):
        line = next(l for l in pagella_for_match(self.match, self.reference)["home"]
                    ["starters"] if l["player_id"] == self.df.id)
        self.assertTrue(line["sv"])
        self.assertEqual(line["sv_reason"], "dati_mancanti")

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
