"""L'autogol non è una conclusione tentata, e nel pannello non si chiama «gol».

Il difetto che questi test fissano era vecchio quanto la correzione che sembrava
averlo chiuso. ``_merge_shot_detail`` teneva l'autogol fuori da ``shots_goal`` —
giusto — ma ``shots`` non passa di lì: arriva dalle zone del fornitore, che
l'autogol lo conta come un tiro qualunque. E siccome il volume di tiro è
creditato, ogni autogol regalava al suo autore un pezzetto di voto: 22 casi su 22
sulla 25-26, +0.048 in media, mai una penalità. Poi la mappa dei tiri, aggiunta il
29/08/2026, leggeva ``MatchShot`` grezzo e lo mostrava come «gol» — con un valore
fabbricato fino a +0.95, perché il contro-fattuale sottraeva dai totali un xGOT
che quei totali non avevano mai contenuto.

Tre letture dello stesso evento, una sola corretta. La ragione per cui le altre
due non lo erano è che ognuna si riconosceva l'autogol per conto proprio: adesso
la domanda si fa in un posto, ``is_own_goal``, e questi test tengono insieme i
quattro posti che la pongono.
"""
from __future__ import annotations

from django.test import TestCase

from realdata.models import (
    Competition, CompetitionSeason, Match, MatchAppearance, MatchShot, Player,
    PlayerZoneFeature, Season, Team, TeamSeason,
)
from vfoot.services.classic_pagella import shot_detail
from vfoot.services.classic_rating import (
    _per_match_player_totals, is_own_goal, own_goal_details, own_goal_shots,
)


class OwnGoalIsNotAShotTests(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2025-2026"),
            name="Serie A 2025-2026")
        self.home = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Verona"))
        self.away = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Inter"))
        self.match = Match.objects.create(
            competition_season=self.cs, matchday=1, home_team=self.home,
            away_team=self.away, home_goals=0, away_goals=1,
            status=Match.STATUS_FINISHED)
        self.player = self._player("Difensore Sfortunato", "home")

    def _player(self, name, side, minutes=90):
        p = Player.objects.create(full_name=name, short_name=name,
                                  classic_role_seed="DIF")
        MatchAppearance.objects.create(
            match=self.match, player=p, side=side, minutes_played=minutes,
            is_starter=True,
            team_season=self.home if side == "home" else self.away)
        # Una riga di zona qualunque: senza, la partita non è calcolabile e i
        # totali non esistono affatto (v. _per_match_player_totals).
        PlayerZoneFeature.objects.create(
            match=self.match, player=p, provider="sofascore",
            feature_key="touches", zone_key="Z_0_1", value=30.0, team_side=side)
        return p

    def _zone_shots(self, player, n, xg=0.0, xgot=0.0, on_target=0.0):
        """Il conteggio dei tiri COME LO MANDA IL FORNITORE: l'autogol è dentro.

        Coerente con i ``MatchShot`` che il test crea, e non è un dettaglio: i due
        archivi discordano davvero nel 3.9% delle righe vere, e una fixture che li
        fa discordare misura quel difetto invece del comportamento voluto."""
        for feature_key, value in (("shots", float(n)), ("xg_shots", xg),
                                   ("xg_on_target", xgot),
                                   ("shots_on_target", on_target)):
            if value:
                PlayerZoneFeature.objects.create(
                    match=self.match, player=player, provider="sofascore",
                    feature_key=feature_key, zone_key="Z_4_2", value=value,
                    team_side="home")

    def _own_goal(self, player, *, minute=47, xgot=0.0):
        """La riga sta sul lato che ne BENEFICIA; il giocatore no. È la firma."""
        app = MatchAppearance.objects.get(match=self.match, player=player)
        other = "away" if app.side == "home" else "home"
        return MatchShot.objects.create(
            match=self.match, player=player, team_side=other, minute=minute,
            zone_key="Z_4_2", xg=0.0, xgot=xgot, is_goal=True, shot_type="goal",
            situation="corner", provider="sofascore", external_id=f"og{minute}")

    def _real_shot(self, player, *, minute, shot_type="miss", xg=0.1, xgot=0.0):
        app = MatchAppearance.objects.get(match=self.match, player=player)
        return MatchShot.objects.create(
            match=self.match, player=player, team_side=app.side, minute=minute,
            zone_key="Z_4_1", xg=xg, xgot=xgot, is_goal=shot_type == "goal",
            shot_type=shot_type, situation="regular", provider="sofascore",
            external_id=f"s{minute}")

    def _totals(self):
        return _per_match_player_totals([self.match.id])[(self.match.id,
                                                          self.player.id)]

    # -- il predicato -----------------------------------------------------
    def test_predicate_reads_the_side_the_goal_counts_for(self):
        self.assertTrue(is_own_goal("goal", "away", "home"))
        self.assertFalse(is_own_goal("goal", "home", "home"))
        # Non è un gol: qualunque altro tiro sul lato avversario resta un tiro.
        self.assertFalse(is_own_goal("save", "away", "home"))
        # Senza la presenza a referto non si afferma niente, in nessuno dei versi.
        self.assertFalse(is_own_goal("goal", "away", None))

    # -- i totali dell'indice ---------------------------------------------
    def test_own_goal_is_not_counted_among_the_shots(self):
        """Il regalo. Il fornitore conta 1 tiro, e quel tiro è l'autogol."""
        self._zone_shots(self.player, 1)
        self._own_goal(self.player)
        totals = self._totals()
        self.assertEqual(totals.get("shots"), 0.0)
        self.assertEqual(totals.get("shots_goal"), None)

    def test_real_shots_survive_alongside_an_own_goal(self):
        """Solo l'autogol esce: chi ha anche tirato davvero non perde quei tiri."""
        self._zone_shots(self.player, 3, xg=0.25, xgot=0.8, on_target=1)
        self._own_goal(self.player)
        self._real_shot(self.player, minute=20, xg=0.1)
        self._real_shot(self.player, minute=70, shot_type="goal", xg=0.15, xgot=0.8)
        totals = self._totals()
        self.assertEqual(totals.get("shots"), 2.0)
        # e il gol VERO continua a contare come gol
        self.assertEqual(totals.get("shots_goal"), 1.0)
        self.assertAlmostEqual(totals.get("xg_shots"), 0.25, places=6)

    def test_the_shot_count_never_goes_negative(self):
        """Se il fornitore un giorno smettesse di contarlo, si sbaglia per difetto."""
        self._zone_shots(self.player, 0)
        self._own_goal(self.player)
        self.assertEqual(self._totals().get("shots"), 0.0)

    def test_on_target_channel_is_left_alone(self):
        """Lo specchio l'autogol non lo conta MAI (misurato: 0 su 22), nemmeno
        quando il fornitore gli allega un xGOT. Sottrarre lì sfonderebbe lo zero."""
        self._zone_shots(self.player, 1)
        PlayerZoneFeature.objects.create(
            match=self.match, player=self.player, provider="sofascore",
            feature_key="shots_on_target", zone_key="Z_4_2", value=0.0,
            team_side="home")
        self._own_goal(self.player, xgot=0.915)
        totals = self._totals()
        self.assertEqual(totals.get("shots"), 0.0)
        self.assertEqual(totals.get("shots_on_target"), 0.0)
        self.assertIn(totals.get("xg_on_target"), (None, 0.0))

    # -- la mappa dei tiri -------------------------------------------------
    def test_shot_map_names_it_and_prices_it_at_zero(self):
        self._zone_shots(self.player, 1)
        self._own_goal(self.player, xgot=0.915)
        rows = shot_detail(self.match, self.player.id)["shots"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "autogol")
        self.assertEqual(rows[0]["points"], 0.0)
        # l'xGOT si mostra lo stesso: la palla era battuta bene, in porta sbagliata
        self.assertAlmostEqual(rows[0]["xgot"], 0.915, places=3)

    def test_shot_map_still_calls_a_real_goal_a_goal(self):
        """La discriminante vera: stessa partita, stesso giocatore, due 'gol'."""
        self._zone_shots(self.player, 2, xg=0.15, xgot=0.9, on_target=1)
        self._own_goal(self.player, minute=17)
        self._real_shot(self.player, minute=26, shot_type="goal", xg=0.15, xgot=0.9)
        rows = {r["minute"]: r
                for r in shot_detail(self.match, self.player.id)["shots"]}
        self.assertEqual(rows[17]["outcome"], "autogol")
        self.assertEqual(rows[17]["points"], 0.0)
        self.assertEqual(rows[26]["outcome"], "gol")
        self.assertGreater(rows[26]["points"], 0.0)

    # -- gli altri due lettori dello stesso evento -------------------------
    def test_the_malus_is_untouched(self):
        """Togliergli il TIRO non è assolverlo: il malus è una voce a sé."""
        self._zone_shots(self.player, 1)
        self._own_goal(self.player)
        detail = own_goal_details(self.match.id)[self.player.id]
        self.assertEqual(detail["count"], 1)
        self.assertLess(detail["penalty"], 0.0)     # è un calo, quindi negativo

    def test_the_keeper_relief_still_sees_it(self):
        """Il quarto lettore: il credito al portiere della squadra che l'ha subito."""
        self._zone_shots(self.player, 1)
        self._own_goal(self.player, xgot=0.5)
        self.assertEqual(own_goal_shots([self.match.id])[(self.match.id, "home")],
                         [(47, 0.5)])
