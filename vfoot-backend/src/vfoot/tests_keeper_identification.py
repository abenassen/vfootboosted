"""Chi è un portiere, quando il cartellino non lo dice.

``Player.is_goalkeeper`` viene dal cartellino Transfermarkt e c'è solo per chi sta
in una rosa importata. In produzione, l'11/08/2026, sette portieri della 2025-26
avevano il tag a False — nel 2026-27 non sono in nessuna rosa — e il modello li ha
trattati da giocatori di movimento: raggruppati per stile ne uscivano CEN, quindi
valutati sul canale sbagliato, e nell'esposizione difensiva si prendevano una fetta
del pericolo concesso che spetta ai difensori davanti a loro (218 presenze di
compagni spostate di mezzo voto).

La distinta dice chi era in porta senza inferire niente. Questi test fissano che
sia LEI a decidere quando il tag manca — nel clustering, nell'esposizione e nel
credito per l'autogol — perché la stessa asimmetria fra due installazioni tornerà
ogni volta che una ha le rose di una stagione e l'altra no.
"""
from __future__ import annotations

from django.test import TestCase

from realdata.models import (
    Competition, CompetitionSeason, Match, MatchAppearance, MatchShot, Player,
    PlayerZoneFeature, Season, Team, TeamSeason,
)
from vfoot.services.classic_rating import (
    OWN_GOAL_KEEPER_XGOT_DEFAULT, _per_match_player_totals, defensive_exposure,
    match_lineup_keepers, _minutes_map,
)
from vfoot.services.role_inference import player_profiles


class KeeperFromLineupTests(TestCase):
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

    def _player(self, name, *, position, zones, minutes=90, tagged=False, extra=None):
        """Un giocatore con la sua casella in distinta e la sua mappa di tocchi.
        ``tagged`` è il cartellino Transfermarkt, che qui lasciamo di norma a False:
        è esattamente lo stato della produzione."""
        p = Player.objects.create(full_name=name, short_name=name,
                                  is_goalkeeper=tagged)
        MatchAppearance.objects.create(
            match=self.match, player=p, side="home", team_season=self.home,
            minutes_played=minutes, is_starter=True,
            raw_stats={"position": position, **(extra or {})})
        for (col, row), touches in zones.items():
            PlayerZoneFeature.objects.create(
                match=self.match, player=p, provider="sofascore",
                feature_key="touches", zone_key=f"Z_{col}_{row}", value=touches,
                team_side="home")
        return p

    def _keeper(self, name="portiere", **kw):
        # il portiere vive nella zona davanti alla propria porta
        return self._player(name, position="G", zones={(0, 1): 40.0}, **kw)

    def _defender(self, name, col=1, row=1, **kw):
        return self._player(name, position="D", zones={(col, row): 50.0}, **kw)

    def _shot_conceded(self, minute=30, *, goal=True, xgot=0.5):
        """Un tiro dell'avversario, nel suo sistema di riferimento offensivo."""
        return MatchShot.objects.create(
            match=self.match, team_side="away", minute=minute, zone_key="Z_4_2",
            xg=0.3, xgot=xgot, is_goal=goal, shot_type="goal" if goal else "save",
            provider="sofascore", external_id=f"s{minute}")

    # -- la distinta, come terza prova --------------------------------------
    def test_the_lineup_says_who_was_in_goal(self):
        gk = self._keeper()
        self._defender("difensore")
        self.assertEqual(match_lineup_keepers([self.match.id]),
                         {self.match.id: {gk.id}})

    def test_an_untagged_keeper_is_not_clustered_as_an_outfielder(self):
        """Il difetto all'origine: senza il tag finiva nella popolazione del
        raggruppamento per stile e ne usciva centrocampista."""
        gk = self._keeper()
        self._defender("difensore")
        ids, _rows = player_profiles(self.cs.id, min_minutes=1)
        self.assertNotIn(gk.id, ids)

    def test_a_tagged_keeper_stays_out_too(self):
        gk = self._keeper(tagged=True)
        ids, _rows = player_profiles(self.cs.id, min_minutes=1)
        self.assertNotIn(gk.id, ids)

    def test_an_outfielder_is_still_clustered(self):
        d = self._defender("difensore")
        ids, _rows = player_profiles(self.cs.id, min_minutes=1)
        self.assertIn(d.id, ids)

    # -- l'esposizione: la fetta di pericolo non va al portiere -------------
    # NB sulla geometria: il tiro avversario è registrato nel SUO sistema offensivo
    # (Z_4_2) e l'esposizione lo specchia in quello di chi difende, dove diventa la
    # zona (0, 1) — cioè l'area davanti alla propria porta. È lì che devono stare i
    # difensori che se lo prendono, ed è la stessa zona del portiere: il motivo per
    # cui escluderlo dalla spartizione conta tanto.
    def test_an_untagged_keeper_takes_no_share_of_the_danger(self):
        gk = self._keeper()
        d = self._defender("difensore", col=0, row=1)   # dove arriva il tiro, specchiato
        self._shot_conceded()
        minutes = _minutes_map([self.match.id])
        exp = defensive_exposure([self.match.id], minutes)
        self.assertNotIn((self.match.id, gk.id), exp)
        self.assertGreater(exp.get((self.match.id, d.id), 0.0), 0.0)

    def test_the_defender_carries_the_whole_charge_when_alone(self):
        """La controprova che spiega le 218 presenze spostate: se il portiere
        entrasse nella spartizione, al difensore arriverebbe meno."""
        self._keeper()
        d = self._defender("difensore", col=0, row=1)
        self._shot_conceded()
        minutes = _minutes_map([self.match.id])
        solo = defensive_exposure([self.match.id], minutes)[(self.match.id, d.id)]
        # un secondo difensore nella stessa zona dimezza la sua quota: è la prova
        # che la spartizione è fra i giocatori di movimento presenti. NB i minuti
        # vanno riletti, o il nuovo arrivato risulta mai entrato in campo e la
        # spartizione non lo vede.
        self._defender("secondo", col=0, row=1)
        minutes = _minutes_map([self.match.id])
        in_due = defensive_exposure([self.match.id], minutes)[(self.match.id, d.id)]
        self.assertLess(in_due, solo)

    # -- il credito per l'autogol arriva anche a lui ------------------------
    def test_an_untagged_keeper_still_gets_the_own_goal_relief(self):
        gk = self._keeper(extra={"gk_goals_prevented": None})
        scorer = self._defender("autore")
        PlayerZoneFeature.objects.create(
            match=self.match, player=gk, provider="sofascore",
            feature_key="gk_goals_prevented", zone_key="Z_0_1", value=-0.5,
            team_side="home")
        MatchShot.objects.create(          # autogol: la riga sta sul lato avversario
            match=self.match, player=scorer, team_side="away", minute=47,
            zone_key="Z_4_2", xg=0.0, xgot=0.0, is_goal=True, shot_type="goal",
            provider="sofascore", external_id="og")
        totals = _per_match_player_totals([self.match.id])
        self.assertAlmostEqual(
            totals[(self.match.id, gk.id)]["gk_goals_prevented"],
            -0.5 + OWN_GOAL_KEEPER_XGOT_DEFAULT, places=6)
