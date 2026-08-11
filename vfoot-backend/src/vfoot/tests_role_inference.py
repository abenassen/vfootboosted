"""Tests for the data-driven classic role inference."""
from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase

from realdata.models import (
    Competition, CompetitionSeason, Match, MatchAppearance, Player,
    PlayerTeamStint, PlayerZoneFeature, Season, Team, TeamSeason,
)
from vfoot.models import CurrentPlayerRole, FantasyLeague, LeaguePlayerRole
from vfoot.services.role_inference import (
    TM_AMBIGUOUS, TM_DEFAULT, TM_DETERMINISTIC, infer_roles, player_profiles,
    refresh_current_roles, tm_positions,
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

    def test_the_matrix_order_is_canonical_and_portable(self):
        """La popolazione va presentata al k-means SEMPRE nello stesso ordine, e in
        un ordine che non dipenda dall'installazione: i centroidi iniziali si
        pescano per indice di riga, quindi un ordine diverso sposta i casi di
        confine. Fra il portatile (SQLite) e la produzione (PostgreSQL) l'ordine
        della query senza ORDER BY era diverso e J. Harrison usciva ATT su una e CEN
        sull'altra, a dati identici. La chiave e' (fonte, id del provider) e non la
        chiave primaria, che e' autoincrementale e quindi diversa in ogni database."""
        self._population()
        ids, _ = player_profiles(self.prev.id, min_minutes=1)
        chiavi = dict(Player.objects.filter(id__in=ids)
                      .values_list("id", "external_id"))
        fonti = dict(Player.objects.filter(id__in=ids)
                     .values_list("id", "external_source"))
        atteso = sorted(ids, key=lambda p: (fonti.get(p) or "", chiavi.get(p) or "",
                                            str(p)))
        self.assertEqual(list(ids), atteso)

    def test_positions_are_read_from_the_season_being_listed(self):
        p = self._player("Uno", "right winger", col=3, seasons=("cur",))
        self.assertEqual(tm_positions(self.cur.id)[p.id], "right winger")
        self.assertNotIn(p.id, tm_positions(self.prev.id))

    def test_ambiguous_set_and_deterministic_set_do_not_overlap(self):
        self.assertFalse(TM_AMBIGUOUS & set(TM_DETERMINISTIC))
        self.assertEqual(set(TM_DEFAULT), TM_AMBIGUOUS)


class CurrentRoleRefreshTests(RoleInferenceTests):
    """The unattended half: what the Transfermarkt import runs after every scrape.

    Destructive on the GLOBAL table by design — the estimate may improve whenever
    new football has been played — and the guard that keeps it from destroying
    anything of value when the data season turns out to be empty.
    """

    def test_a_newcomer_gets_a_row_so_each_league_can_resolve_him_its_own_way(self):
        """The point of the whole exercise. Without a CurrentPlayerRole row a new
        signing falls through to Player.classic_role_seed — one provider value for
        every league — and the league's role_mode stops applying to him."""
        self._population()
        newcomer = self._player("Arrivato a gennaio", "left winger", col=4,
                                seasons=("cur",))
        out = refresh_current_roles(self.cur, data_cs=self.prev)
        self.assertTrue(out["written"])

        row = CurrentPlayerRole.objects.get(player_id=newcomer.id)
        # Both variants present is what lets two leagues on the same season answer
        # differently; a single seed value could not.
        self.assertTrue(row.role_data)
        self.assertTrue(row.role_mitigated)
        self.assertEqual(row.tm_position, "left winger")

    def test_the_refresh_never_touches_a_role_already_frozen_in_a_league(self):
        """Destructive globally, additive per league — the invariant the whole
        design rests on: a squad must not find itself holding a player who had a
        different role when he was paid for."""
        self._population()
        p = Player.objects.get(full_name="MID0")
        user = User.objects.create_user("owner", password="x")
        league = FantasyLeague.objects.create(
            name="L", owner=user, mode=FantasyLeague.MODE_CLASSIC,
            reference_season=self.cur)
        LeaguePlayerRole.objects.create(league=league, player=p, role="ATT",
                                        source=LeaguePlayerRole.SOURCE_ADMIN)

        refresh_current_roles(self.cur, data_cs=self.prev)

        frozen = LeaguePlayerRole.objects.get(league=league, player=p)
        self.assertEqual(frozen.role, "ATT")
        self.assertEqual(frozen.source, LeaguePlayerRole.SOURCE_ADMIN)

    def test_an_empty_data_season_does_not_wipe_measured_roles(self):
        """A data season with no zone features is the ordinary way to get here (it
        was never imported, or was pruned). ``infer_roles`` degrades gracefully to
        provider positions, which is right for one player and catastrophic for a
        table: it would trade every measured role for a default and report success.
        So it changes nothing and says so."""
        self._population()
        self.assertTrue(refresh_current_roles(self.cur, data_cs=self.prev)["written"])
        measured_before = CurrentPlayerRole.objects.filter(
            method=CurrentPlayerRole.METHOD_CATEGORY).count()
        self.assertGreater(measured_before, 0)

        PlayerZoneFeature.objects.all().delete()
        out = refresh_current_roles(self.cur, data_cs=self.prev)

        self.assertFalse(out["written"])
        self.assertEqual(out["reason"], "no_measurement")
        self.assertEqual(
            CurrentPlayerRole.objects.filter(
                method=CurrentPlayerRole.METHOD_CATEGORY).count(),
            measured_before)

    def test_no_previous_season_is_reported_not_guessed(self):
        out = refresh_current_roles(self.prev)   # nothing before it
        self.assertFalse(out["written"])
        self.assertEqual(out["reason"], "no_data_season")
