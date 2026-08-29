"""L'xGOT che il fornitore non manda: si tappa d'ufficio, e lo si dice.

``sga_post`` = xGOT − xG sottrae due grandezze che vengono da posti diversi:
``xg_shots`` è la somma esatta dei tiri (``shotmap_exact``), ``xg_on_target`` è
l'aggregato ``expectedGoalsOnTarget`` del fornitore spalmato sulla heatmap
(``heatmap_interpolated``). Quando l'aggregato non arriva, la sua assenza si legge
come uno zero e il modello racconta una partita di conclusioni buttate via.

Il caso vero: Moro in Torino-Bologna g25 aveva ``shots_goal`` 1 e ``xg_on_target``
0 nella stessa riga — un pallone entrato senza valore dopo il tiro. Non è un
giudizio severo, è una contraddizione, e valeva un punto pieno di voto (6.0 invece
di 7.0) con la frase «una o più occasioni fallite» su chi aveva segnato.

Il confine che questi test difendono è quello fra un BUCO e uno ZERO MISURATO:
2929 righe della 25-26 hanno tiri, nessuno nello specchio e xGOT zero, e quella è
la lettura giusta. Riparare anche loro vorrebbe dire regalare merito a chi ha
sbagliato tutto.
"""
from __future__ import annotations

from django.test import TestCase

from realdata.models import (
    Competition, CompetitionSeason, Match, MatchAppearance, MatchShot, Player,
    PlayerZoneFeature, Season, Team, TeamSeason,
)
from vfoot.services.classic_rating import (
    _per_match_player_totals, derived_features, missing_xgot_rows,
)


class MissingXgotTests(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2025-2026"),
            name="Serie A 2025-2026")
        self.home = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Bologna"))
        self.away = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Torino"))
        self.match = Match.objects.create(
            competition_season=self.cs, matchday=25, home_team=self.home,
            away_team=self.away, home_goals=1, away_goals=0,
            status=Match.STATUS_FINISHED)
        self.player = self._player("Nikola Moro")

    def _player(self, name):
        p = Player.objects.create(full_name=name, short_name=name,
                                  classic_role_seed="CEN")
        MatchAppearance.objects.create(
            match=self.match, player=p, side="home", minutes_played=90,
            is_starter=True, team_season=self.home)
        PlayerZoneFeature.objects.create(
            match=self.match, player=p, provider="sofascore", feature_key="touches",
            zone_key="Z_0_1", value=50.0, team_side="home")
        return p

    def _zone(self, key, value, zone="Z_4_1"):
        PlayerZoneFeature.objects.create(
            match=self.match, player=self.player, provider="sofascore",
            feature_key=key, zone_key=zone, value=value, team_side="home")

    def _shot(self, minute, kind, xg, xgot, *, own=False):
        app = MatchAppearance.objects.get(match=self.match, player=self.player)
        side = ("away" if app.side == "home" else "home") if own else app.side
        return MatchShot.objects.create(
            match=self.match, player=self.player, team_side=side, minute=minute,
            zone_key="Z_4_1", xg=xg, xgot=xgot, is_goal=kind == "goal",
            shot_type=kind, situation="regular", provider="sofascore",
            external_id=f"s{minute}")

    def _totals(self):
        return _per_match_player_totals([self.match.id])[(self.match.id,
                                                          self.player.id)]

    def _moro(self):
        """La sua partita vera: un tiro fuori e un gol, e nessuna riga di xGOT."""
        self._zone("shots", 2.0)
        self._zone("xg_shots", 0.14136)
        self._zone("xg_shots", 0.7386, zone="Z_4_2")
        self._zone("shots_on_target", 1.0)
        self._shot(5, "miss", 0.14136, 0.0)
        self._shot(49, "goal", 0.7386, 0.9945)

    # -- il rilevatore -----------------------------------------------------
    def test_it_finds_the_row_whose_field_never_arrived(self):
        self._moro()
        self.assertEqual(missing_xgot_rows([self.match.id]),
                         {(self.match.id, self.player.id): 0.9945})

    def test_a_measured_zero_is_not_a_hole(self):
        """Il campo c'è e vale zero: è il dato, non la sua assenza. Non si tocca —
        sono le 204 righe in cui le due fonti non concordano, e sceglierne una
        sarebbe una taratura travestita da riparazione."""
        self._moro()
        self._zone("xg_on_target", 0.0)
        self.assertEqual(missing_xgot_rows([self.match.id]), {})

    def test_shooting_badly_is_not_a_hole(self):
        """2929 righe della 25-26: ha tirato, tutto fuori, xGOT zero. Giusto così."""
        self._zone("shots", 2.0)
        self._zone("xg_shots", 0.25)
        self._shot(10, "miss", 0.15, 0.0)
        self._shot(60, "miss", 0.10, 0.0)
        self.assertEqual(missing_xgot_rows([self.match.id]), {})

    def test_an_own_goal_brings_no_xgot_of_its_own(self):
        """L'autogol ha un xGOT nella mappa (0.92 su Edmundsson) e non è merito
        suo: se entrasse nella riparazione, il buco si tapperebbe col regalo."""
        self._zone("shots", 1.0)
        self._shot(47, "goal", 0.0, 0.915, own=True)
        self.assertEqual(missing_xgot_rows([self.match.id]), {})

    # -- la riparazione ----------------------------------------------------
    def test_the_totals_are_repaired_from_the_shot_map(self):
        self._moro()
        totals = self._totals()
        self.assertAlmostEqual(totals["xg_on_target"], 0.9945, places=4)
        # e il merito dell'esecuzione cambia di segno: era −0.880
        self.assertGreater(derived_features(totals)["sga_post"], 0.0)

    def test_the_repair_leaves_a_genuine_zero_alone(self):
        self._moro()
        self._zone("xg_on_target", 0.0)
        self.assertEqual(self._totals().get("xg_on_target"), 0.0)
        self.assertLess(derived_features(self._totals())["sga_post"], 0.0)

    def test_the_repaired_value_is_read_not_invented(self):
        """Non è una stima: è lo stesso evento letto dall'altro archivio, che è già
        la fonte dell'altra metà della sottrazione."""
        self._moro()
        self._shot(70, "save", 0.20, 0.31)
        self._zone("shots", 1.0, zone="Z_3_1")     # il fornitore ne conta 3 in tutto
        self.assertAlmostEqual(self._totals()["xg_on_target"], 0.9945 + 0.31,
                               places=4)
