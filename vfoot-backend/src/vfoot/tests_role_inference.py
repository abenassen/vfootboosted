"""Tests for the data-driven classic role inference."""
from __future__ import annotations

import numpy as np
from django.contrib.auth.models import User
from django.test import TestCase

from realdata.models import (
    Competition, CompetitionSeason, Match, MatchAppearance, Player,
    PlayerTeamStint, PlayerZoneFeature, Season, Team, TeamSeason,
)
from vfoot.models import CurrentPlayerRole, FantasyLeague, LeaguePlayerRole
from vfoot.services.role_inference import (
    ROLE_MARGIN_REVIEW, TM_AMBIGUOUS, TM_DEFAULT, TM_DETERMINISTIC, infer_roles,
    player_profiles, refresh_current_roles, role_margins, tm_positions,
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

    def test_attacking_midfield_is_ambiguous_and_measured_style_wins(self):
        """A trequartista is no longer overridden to CEN merely by TM's label."""
        self._population()
        trequartista = self._player("Trequartista", "attacking midfield", col=4,
                                    box=40.0, shots=30.0)
        rep = infer_roles(self.cur.id, self.prev.id, runs=6, n_categories=3)
        r = next(x for x in rep.results if x.player_id == trequartista.id)
        self.assertEqual(r.method, "category")
        self.assertEqual(r.role_data, Player.ROLE_FWD)
        self.assertEqual(r.role_mitigated, Player.ROLE_FWD)

    def test_unmeasured_attacking_midfield_is_provisional_and_reviewable(self):
        self._population()
        newcomer = self._player("Trequartista nuovo", "attacking midfield", col=3,
                                seasons=("cur",))
        rep = infer_roles(self.cur.id, self.prev.id, runs=6, n_categories=3)
        r = next(x for x in rep.results if x.player_id == newcomer.id)
        self.assertEqual(r.method, "default")
        self.assertEqual(r.role_data, Player.ROLE_MID)
        self.assertEqual(r.role_mitigated, Player.ROLE_MID)
        self.assertTrue(r.needs_decision)

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


class RoleMarginTests(TestCase):
    """The margin is read against the role we ASSIGN, not between the top two.

    Four players, two categories: 0 and 3 are 'centrocampista offensivo' (CEN),
    1 and 2 are 'ala offensiva' (ATT). The matrix is the co-association the runs
    would have produced.
    """

    BY_LABEL = {0: "centrocampista offensivo", 1: "ala offensiva"}
    LABELS = np.array([0, 1, 1, 0])

    def _margins(self, M):
        return role_margins(np.array(M), self.LABELS, self.BY_LABEL)

    def test_a_contradicted_assignment_is_negative_not_confident(self):
        """Guðmundsson's case: assigned CEN while the runs put him with the
        attackers three times out of four. Read as top-minus-runner-up that was a
        margin of +0.56 — "settled" — about a role we are not giving him."""
        m = self._margins([[0.30, 0.70, 0.70, 0.10],    # CEN by label, ATT by mass
                           [0.70, 1.00, 0.80, 0.10],
                           [0.70, 0.80, 1.00, 0.10],
                           [0.10, 0.10, 0.10, 1.00]])
        self.assertAlmostEqual(m[0], -0.556, places=3)
        self.assertLess(m[0], ROLE_MARGIN_REVIEW)       # hence: ask a human

    def test_an_uncontradicted_assignment_is_the_old_number(self):
        """The whole population save a handful is in this case, and it must not
        move: when the assigned role already wins the mass, its lead over the
        runner-up IS top-minus-second."""
        M = [[0.30, 0.70, 0.70, 0.10],
             [0.70, 1.00, 0.80, 0.10],
             [0.70, 0.80, 1.00, 0.10],
             [0.10, 0.10, 0.10, 1.00]]
        m = self._margins(M)
        # riga 1: massa CEN = 0.70 + 0.10 (colonne 0 e 3), ATT = 1.00 + 0.80
        share = np.array([0.80 / 2.60, 1.80 / 2.60])    # CEN, ATT
        self.assertAlmostEqual(m[1], abs(share[1] - share[0]), places=3)
        self.assertGreater(m[1], 0)

    def test_a_player_alone_with_his_own_role_is_fully_determined(self):
        """Player 3 co-associates with nobody but himself: all the mass is on his
        own role, no rival at all."""
        m = self._margins([[1.0, 0.0, 0.0, 0.0],
                           [0.0, 1.0, 0.8, 0.0],
                           [0.0, 0.8, 1.0, 0.0],
                           [0.0, 0.0, 0.0, 1.0]])
        self.assertAlmostEqual(m[3], 1.0, places=6)


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
