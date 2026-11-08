"""Il tiro che provoca un autogol prende meta' del credito del gol.

Deciso il 07/11/2026 sul caso Simeone (Torino-Lecce): gol in campo, autogol per la
Lega a posteriori. Il confine fra i due e' una decisione formale, e senza questa
regola il tiratore perdeva tutto il credito del gol — mezzo voto e piu' — per un
verdetto a tavolino. Il legame tiro -> autogol e' lo STESSO che gradua il malus del
difensore (``own_goal_links``): questi test tengono insieme le due letture.
"""
from __future__ import annotations

from django.test import TestCase

from realdata.models import (
    Competition, CompetitionSeason, Match, MatchAppearance, MatchShot, Player,
    Season, Team, TeamSeason,
)
from vfoot.services import goal_impact
from vfoot.services.classic_rating import (
    INDUCED_OWN_GOAL_SHARE_MAX, INDUCED_OWN_GOAL_SHARE_MIN,
    INDUCED_OWN_GOAL_XG_FULL, OWN_GOAL_DEFLECTION_WINDOW_S, induced_own_goal_share,
    own_goal_details, own_goal_links,
)


class _Fixture(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        self.home = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Torino"))
        self.away = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Lecce"))
        self.match = Match.objects.create(
            competition_season=self.cs, matchday=11, home_team=self.home,
            away_team=self.away, home_goals=1, away_goals=0,
            status=Match.STATUS_FINISHED)
        self.striker = self._player("Attaccante", "home")
        self.mate = self._player("Compagno", "home")
        self.defender = self._player("Difensore", "away")
        self._n = 0

    def _player(self, name, side):
        p = Player.objects.create(full_name=name, short_name=name)
        MatchAppearance.objects.create(
            match=self.match, player=p, side=side, minutes_played=90,
            is_starter=True,
            team_season=self.home if side == "home" else self.away)
        return p

    def _shot(self, player, side, *, minute, seconds, shot_type="miss", goal=False):
        self._n += 1
        return MatchShot.objects.create(
            match=self.match, player=player, team_side=side, minute=minute,
            elapsed_seconds=seconds, zone_key="Z_4_1", xg=0.03, xgot=0.0,
            is_goal=goal, shot_type=shot_type, situation="assisted",
            provider="sofascore", external_id=f"s{self._n}")

    def _own_goal(self, *, minute=60, seconds=3556):
        # La riga dell'autogol sta sul lato che ne BENEFICIA (casa), il difensore no.
        return self._shot(self.defender, "home", minute=minute, seconds=seconds,
                          shot_type="goal", goal=True)



class InducedOwnGoalTests(_Fixture):
    # -- il legame -----------------------------------------------------------
    def test_links_the_shot_just_before_the_own_goal(self):
        self._shot(self.striker, "home", minute=60, seconds=3554)
        self._own_goal()
        [link] = own_goal_links(self.match.id)
        self.assertEqual(link["og_player_id"], self.defender.id)
        self.assertEqual(link["provoker_id"], self.striker.id)
        self.assertEqual(link["provoker_seconds"], 3554)

    def test_picks_the_closest_shot_when_two_are_in_the_window(self):
        self._shot(self.mate, "home", minute=60, seconds=3553)
        self._shot(self.striker, "home", minute=60, seconds=3555)
        self._own_goal()
        self.assertEqual(own_goal_links(self.match.id)[0]["provoker_id"],
                         self.striker.id)

    def test_no_link_outside_the_window_or_without_seconds(self):
        self._shot(self.striker, "home", minute=60,
                   seconds=3556 - OWN_GOAL_DEFLECTION_WINDOW_S - 1)
        self._own_goal()
        self.assertIsNone(own_goal_links(self.match.id)[0]["provoker_id"])
        MatchShot.objects.filter(player=self.defender).update(elapsed_seconds=None)
        self.assertIsNone(own_goal_links(self.match.id)[0]["provoker_id"])

    def test_defender_grading_reads_the_same_link(self):
        """Il malus del difensore e il credito del tiratore non possono dire due
        cose diverse dello stesso pallone."""
        self._own_goal()
        self.assertEqual(own_goal_details(self.match.id)[self.defender.id]["kind"], "solo")
        self._shot(self.striker, "home", minute=60, seconds=3555)
        self.assertEqual(own_goal_details(self.match.id)[self.defender.id]["kind"],
                         "deflection")

    # -- il credito ----------------------------------------------------------
    def test_shooter_gets_a_share_of_the_goal_credit(self):
        if not goal_impact.fixed_xp_table():
            self.skipTest("vote_reference.json senza tabella xP")
        self._shot(self.striker, "home", minute=60, seconds=3554)
        self._own_goal()
        recs = goal_impact.induced_own_goals_by_player(self.match)
        [rec] = recs[self.striker.id]
        self.assertTrue(rec["induced_own_goal"])
        self.assertEqual((rec["own_after"], rec["opp_after"]), (1, 0))
        # Il difensore non prende niente, e il compagno nemmeno.
        self.assertNotIn(self.defender.id, recs)
        self.assertNotIn(self.mate.id, recs)
        band, p95 = goal_impact.fixed_band()
        fact = goal_impact.goal_credit([rec["importance"]], band, p95)
        self.assertAlmostEqual(rec["xg"], 0.03)
        self.assertAlmostEqual(goal_impact.goal_credit_for([rec], band, p95),
                               induced_own_goal_share(0.03) * fact)
        self.assertEqual(goal_impact.goal_phrase([rec]),
                         "un tiro che provoca l'autogol dell'1-0, al 60'")

    def test_share_grows_with_the_xg_of_the_original_shot(self):
        """Il pallone che in porta non ci andava e' colpa del difensore; l'intervento
        disperato su un'occasione vera lascia il gol a chi l'ha creato."""
        self.assertAlmostEqual(induced_own_goal_share(0.0), INDUCED_OWN_GOAL_SHARE_MIN)
        self.assertAlmostEqual(induced_own_goal_share(None), INDUCED_OWN_GOAL_SHARE_MIN)
        self.assertAlmostEqual(induced_own_goal_share(INDUCED_OWN_GOAL_XG_FULL),
                               INDUCED_OWN_GOAL_SHARE_MAX)
        self.assertAlmostEqual(induced_own_goal_share(0.9), INDUCED_OWN_GOAL_SHARE_MAX)
        self.assertLess(induced_own_goal_share(0.05), induced_own_goal_share(0.2))

    def test_phrase_with_a_real_goal_too(self):
        goal = {"minute": 20, "own_after": 1, "opp_after": 0, "importance": 0.9}
        induced = {"minute": 60, "own_after": 2, "opp_after": 0, "importance": 0.5,
                   "induced_own_goal": True}
        self.assertEqual(goal_impact.goal_phrase([goal, induced]),
                         "un gol e un autogol provocato")
        self.assertEqual(goal_impact.goal_phrase([goal, dict(goal)]), "2 gol")


class RewrittenGoalTests(_Fixture):
    """Torino-Lecce, 08/11/2026: la rilettura della Lega non affianca una riga
    d'autogol al tiro, RISCRIVE la riga del gol (stesso secondo, niente xG). Il
    tiratore sopravvive solo se il reimport se lo ricorda."""

    def _reimport(self, rows, *, was_finished=True):
        from realdata.services.sofascore_adapter import carry_own_goal_shooters
        carry_own_goal_shooters(self.match, rows, was_finished=was_finished)
        MatchShot.objects.filter(match=self.match).delete()
        MatchShot.objects.bulk_create(rows)

    def _row(self, player, *, xg):
        self._n += 1
        return MatchShot(match=self.match, player=player, team_side="home",
                         minute=60, elapsed_seconds=3554, zone_key="Z_4_1", xg=xg,
                         xgot=0.067, is_goal=True, shot_type="goal",
                         situation="assisted", provider="sofascore",
                         external_id=f"r{self._n}")

    def test_the_shooter_survives_the_rewrite(self):
        self._shot(self.striker, "home", minute=60, seconds=3554, shot_type="goal",
                   goal=True)
        MatchShot.objects.filter(player=self.striker).update(xg=0.026)
        self._reimport([self._row(self.defender, xg=0.0)])
        og = MatchShot.objects.get(match=self.match)
        self.assertEqual(og.own_goal_shooter_id, self.striker.id)
        self.assertAlmostEqual(og.own_goal_shooter_xg, 0.026)
        [link] = own_goal_links(self.match.id)
        self.assertEqual(link["provoker_id"], self.striker.id)
        self.assertIsNone(link["provoker_seconds"])
        self.assertAlmostEqual(link["provoker_xg"], 0.026)
        # Il difensore ha deviato un tiro: non e' un errore suo.
        self.assertEqual(own_goal_details(self.match.id)[self.defender.id]["kind"],
                         "deflection")
        # E il reimport successivo, tale e quale, non lo dimentica.
        self._reimport([self._row(self.defender, xg=0.0)])
        self.assertEqual(MatchShot.objects.get(match=self.match).own_goal_shooter_id,
                         self.striker.id)

    def test_a_scorer_fixed_during_the_match_is_not_a_provoker(self):
        """Il gol dato per sbaglio all'attaccante e restituito al difensore a partita
        in corso e' un errore di battitura del fornitore, non un tiro deviato."""
        self._shot(self.striker, "home", minute=60, seconds=3554, shot_type="goal",
                   goal=True)
        self._reimport([self._row(self.defender, xg=0.0)], was_finished=False)
        self.assertIsNone(MatchShot.objects.get(match=self.match).own_goal_shooter_id)
        self.assertIsNone(own_goal_links(self.match.id)[0]["provoker_id"])

    def test_a_goal_that_stays_a_goal_carries_nothing(self):
        self._shot(self.striker, "home", minute=60, seconds=3554, shot_type="goal",
                   goal=True)
        self._reimport([self._row(self.mate, xg=0.2)])   # gol dato a un compagno
        self.assertIsNone(MatchShot.objects.get(match=self.match).own_goal_shooter_id)


class CanaryOwnGoalTests(TestCase):
    def test_own_goal_rows_are_not_missing_xg(self):
        import json, tempfile
        from pathlib import Path
        from realdata.services import shape_canary
        rows = [{"id": i, "isHome": True, "player": {}, "playerCoordinates": {},
                 "shotType": "miss", "situation": "assisted", "time": 10, "xg": 0.1}
                for i in range(15)]
        rows += [{"id": 99 + i, "isHome": True, "player": {}, "playerCoordinates": {},
                  "shotType": "goal", "goalType": "own", "situation": "assisted",
                  "time": 60} for i in range(2)]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "api_v1_event_1_shotmap.json"
            p.write_text(json.dumps({"shotmap": rows}))
            report = shape_canary.CanaryReport()
            shape_canary._check_rows(report, p, "shotmap", shape_canary.SHOT_FIELDS,
                                     "shots", "tiri")
            self.assertTrue(report.ok)
            self.assertTrue(report.ok)
            rows[0].pop("xg"); rows[1].pop("xg")
            p.write_text(json.dumps({"shotmap": rows}))
            shape_canary._check_rows(report, p, "shotmap", shape_canary.SHOT_FIELDS,
                                     "shots", "tiri")
            # Mancare l'xG su righe che dovrebbero averlo resta un allarme.
            self.assertFalse(report.ok)
