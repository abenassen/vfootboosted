"""L'autogol di un compagno, letto dal punto di vista del portiere.

Il campo ``goalsPrevented`` del provider è "xGOT dei tiri affrontati meno i gol
subiti", e conta gli autogol fra i gol subiti: un pallone che il portiere non ha
mai visto arrivare come tiro gli costava un'unità intera nella misura che pesa il
60% del suo canale. La correzione gli restituisce la DIFFICOLTÀ di quell'autogol —
il suo xGOT quando c'è, OWN_GOAL_KEEPER_XGOT_DEFAULT quando manca — e questi test
fissano i quattro comportamenti che la rendono una lettura e non uno sconto:

* dove l'xGOT c'è, si usa quello (un autogol imparabile assolve, uno facile no);
* dove manca, si usa il default e non 1.0 (al portiere resta un residuo);
* il credito è gated sui minuti in campo: chi entra dopo non lo prende;
* un gol vero dell'avversario non c'entra niente, e il credito non tocca nessuno
  che non sia il portiere della squadra che l'autogol lo ha subito.
"""
from __future__ import annotations

from django.test import TestCase

from realdata.models import (
    Competition, CompetitionSeason, Match, MatchAppearance, MatchShot, Player,
    PlayerOnPitchInterval, PlayerZoneFeature, Season, Team, TeamSeason,
    INTERVAL_SUBSTITUTION_OFF, INTERVAL_SUBSTITUTION_ON,
)
from vfoot.services import goal_impact
from vfoot.services.classic_rating import (
    KEEPER_MOMENT_LAMBDA, KEEPER_SAVE_DEDUCTIBLE,
    OWN_GOAL_KEEPER_XGOT_DEFAULT, _per_match_player_totals, own_goal_shots,
)


class OwnGoalKeeperReliefTests(TestCase):
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

    # -- fixtures ---------------------------------------------------------
    def _player(self, name, side, *, keeper=False, minutes=90, starter=True,
                goals_prevented=None, zone_touches=30.0):
        p = Player.objects.create(full_name=name, short_name=name,
                                  is_goalkeeper=keeper,
                                  classic_role_seed="POR" if keeper else "DIF")
        MatchAppearance.objects.create(
            match=self.match, player=p, side=side, minutes_played=minutes,
            is_starter=starter,
            team_season=self.home if side == "home" else self.away,
            raw_stats={"ownGoals": 1} if name.startswith("autogol") else {})
        # Almeno una riga di zona: senza, la partita non è calcolabile e il credito
        # non deve inventare un giocatore (v. _per_match_player_totals).
        PlayerZoneFeature.objects.create(
            match=self.match, player=p, provider="sofascore", feature_key="touches",
            zone_key="Z_0_1", value=zone_touches, team_side=side)
        if goals_prevented is not None:
            PlayerZoneFeature.objects.create(
                match=self.match, player=p, provider="sofascore",
                feature_key="gk_goals_prevented", zone_key="Z_0_1",
                value=goals_prevented, team_side=side)
        return p

    def _own_goal(self, scorer, *, minute=47, xgot=0.0):
        """Un autogol: la riga sta sul lato che ne BENEFICIA, il giocatore no."""
        app = MatchAppearance.objects.get(match=self.match, player=scorer)
        other = "away" if app.side == "home" else "home"
        return MatchShot.objects.create(
            match=self.match, player=scorer, team_side=other, minute=minute,
            zone_key="Z_4_2", xg=0.0, xgot=xgot, is_goal=True, shot_type="goal",
            situation="corner", provider="sofascore", external_id=f"og{minute}")

    def _gp(self, player):
        totals = _per_match_player_totals([self.match.id])
        return totals[(self.match.id, player.id)].get("gk_goals_prevented")

    # -- l'xGOT vero, quando c'è ------------------------------------------
    def test_unsaveable_own_goal_gives_back_almost_all_of_it(self):
        """0.915 di xGOT: il pallone non si prendeva, e il portiere quasi non paga."""
        gk = self._player("portiere", "home", keeper=True, goals_prevented=-0.358)
        self._own_goal(self._player("autogol difensore", "home"), xgot=0.915)
        self.assertAlmostEqual(self._gp(gk), -0.358 + 0.915, places=6)

    def test_easy_own_goal_leaves_the_charge_standing(self):
        """0.15 di xGOT: era un pallone da prendere, e il conto resta negativo."""
        gk = self._player("portiere", "home", keeper=True, goals_prevented=-0.60)
        self._own_goal(self._player("autogol difensore", "home"), xgot=0.15)
        self.assertAlmostEqual(self._gp(gk), -0.45, places=6)

    # -- il default, quando l'xGOT manca ---------------------------------
    def test_missing_xgot_uses_the_default_and_not_a_full_pardon(self):
        gk = self._player("portiere", "home", keeper=True, goals_prevented=-1.0)
        self._own_goal(self._player("autogol difensore", "home"), xgot=0.0)
        self.assertAlmostEqual(self._gp(gk), -1.0 + OWN_GOAL_KEEPER_XGOT_DEFAULT,
                               places=6)
        # il residuo è la differenza fra il default e il gol intero: se questo
        # diventasse zero, l'autogol sarebbe diventato un'assoluzione d'ufficio
        self.assertGreater(1.0 - OWN_GOAL_KEEPER_XGOT_DEFAULT, 0.0)

    # -- il cancello sui minuti ------------------------------------------
    def test_a_keeper_who_came_on_later_gets_no_credit(self):
        """L'autogol era già dentro: non è un gol su cui lui poteva niente, è un
        gol che non ha nemmeno visto."""
        first = self._player("portiere primo", "home", keeper=True, minutes=45,
                             goals_prevented=-1.0)
        second = self._player("portiere secondo", "home", keeper=True, minutes=45,
                              starter=False, goals_prevented=0.0)
        for p, kind, minute in ((first, INTERVAL_SUBSTITUTION_OFF, 45),
                                (second, INTERVAL_SUBSTITUTION_ON, 45)):
            PlayerOnPitchInterval.objects.create(
                match=self.match, player=p, team_season=self.home, team_side="home",
                start_minute=0 if p is first else 45,
                end_minute=45 if p is first else 90,
                start_reason="", end_reason=kind)
        self._own_goal(self._player("autogol difensore", "home"), minute=20)
        self.assertAlmostEqual(self._gp(first), -1.0 + OWN_GOAL_KEEPER_XGOT_DEFAULT,
                               places=6)
        self.assertAlmostEqual(self._gp(second), 0.0, places=6)

    # -- a chi NON tocca --------------------------------------------------
    def test_a_real_goal_by_the_opponent_is_not_an_own_goal(self):
        gk = self._player("portiere", "home", keeper=True, goals_prevented=-0.50)
        striker = self._player("attaccante", "away")
        MatchShot.objects.create(
            match=self.match, player=striker, team_side="away", minute=30,
            zone_key="Z_4_2", xg=0.3, xgot=0.5, is_goal=True, shot_type="goal",
            provider="sofascore", external_id="vero")
        self.assertEqual(own_goal_shots([self.match.id]), {})
        # NON prende il credito dell'autogol. Gli scostamenti ammessi sono i due di
        # ``_merge_keeper_shot_credit``: la FRANCHIGIA, che toglie min(xGOT, c) da
        # ogni tiro affrontato, e il MOMENTO, che pesa la quantita' con segno gia'
        # detratta. Si ricalcolano dalle stesse costanti pubbliche invece di
        # scrivere un numero, cosi' il test resta una verita' sull'autogol e non
        # un'impronta della taratura.
        imp = goal_impact.importance(goal_impact.fixed_xp_table(), 30, -1)
        peso = goal_impact.conceded_weight(imp)
        detrazione = min(0.5, KEEPER_SAVE_DEDUCTIBLE)
        atteso = (-0.50 - detrazione
                  + KEEPER_MOMENT_LAMBDA * (peso - 1.0) * (0.5 - detrazione - 1.0))
        self.assertAlmostEqual(self._gp(gk), atteso, places=6)

    def test_the_other_keeper_and_the_outfielders_are_untouched(self):
        gk_home = self._player("portiere casa", "home", keeper=True,
                               goals_prevented=-0.358)
        gk_away = self._player("portiere ospite", "away", keeper=True,
                              goals_prevented=-0.20)
        scorer = self._player("autogol difensore", "home")
        self._own_goal(scorer, xgot=0.915)
        self.assertAlmostEqual(self._gp(gk_home), -0.358 + 0.915, places=6)
        self.assertAlmostEqual(self._gp(gk_away), -0.20, places=6)
        totals = _per_match_player_totals([self.match.id])
        self.assertNotIn("gk_goals_prevented", totals[(self.match.id, scorer.id)])
