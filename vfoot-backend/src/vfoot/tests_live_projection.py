"""«Se la giornata finisse adesso»: la seconda lettura di un turno in corso.

A giornata cominciata il motore non sostituisce un titolare la cui partita si sta
giocando, e deve continuare a non farlo: un cambio e' la risposta a «non ha
giocato», che di una partita al ventesimo minuto non si sa ancora. Ma
l'allenatore che guarda la sua sfida una domanda ce l'ha, ed e' un'altra: se
finisse tutto adesso, quanto farei? Per lui il titolare rimasto in panchina al
ventesimo E' gia' un senza voto, e la sua riserva sarebbe gia' entrata.

Le due domande convivono perche' la previsione cambia UNA cosa sola, e queste
prove la circoscrivono:

* il titolare con zero minuti in una partita in corso — la previsione lo tratta
  come un senza voto qualunque: entra la panchina, e il voto d'ufficio tappa il
  buco che resta;
* CHI E' IN CAMPO NO. Nei primi minuti chi gioca non ha ancora un voto, e
  sostituirlo sarebbe il vecchio bug servito come funzione;
* la partita che non e' ancora cominciata resta fuori da entrambe: prevederla
  vorrebbe dire inventarne il risultato;
* e la previsione non lascia traccia — non si salva e non tocca il punteggio
  vero, che e' quello che la pagina mostra quando l'interruttore e' spento.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from realdata.models import (
    Competition, CompetitionSeason, Match, MatchAppearance, Player,
    PlayerTeamStint, PlayerZoneFeature, Season, Team, TeamSeason,
)
from vfoot.models import (
    FantasyCompetition, FantasyFixture, FantasyFixtureDetail, FantasyLeague,
    FantasyMatchday, FantasyTeam, LeagueMembership, SavedLineupSnapshot,
)
from vfoot.services.classic_matchday_scoring import _engine_in_progress

SAT = timezone.now() - timedelta(hours=1)
# Il cronometro della partita in corso, letto dalle presenze: chi ha questi minuti
# e' in campo adesso, chi ne ha meno e' gia' uscito (v. classic_pagella).
ELAPSED = 20


class EngineInProgressTests(TestCase):
    """La regola, nuda. Chi resta intoccabile quando si chiede la previsione."""

    INDEX = {
        1: {"sv_reason": "in_campo"},        # sta giocando, non ha ancora un voto
        2: {"sv_reason": "non_entrato"},     # zero minuti a partita cominciata
        3: {"sv_reason": None},              # ha un voto
    }

    def test_without_the_question_every_match_on_the_pitch_freezes_its_players(self):
        self.assertEqual(
            _engine_in_progress({1, 2, 3}, self.INDEX, False), {1, 2, 3})

    def test_the_projection_keeps_only_who_is_actually_on_the_pitch(self):
        self.assertEqual(_engine_in_progress({1, 2, 3}, self.INDEX, True), {1})

    def test_a_player_with_no_line_at_all_is_not_on_the_pitch(self):
        """Nemmeno nominato fra i convocati: non c'e' niente da aspettare."""
        self.assertEqual(_engine_in_progress({9}, self.INDEX, True), set())


class LiveProjectionTests(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        self.user = User.objects.create_user("mario", "m@x.it", "pw")
        self.league = FantasyLeague.objects.create(
            name="Lega", owner=self.user, mode=FantasyLeague.MODE_CLASSIC,
            reference_season=self.cs)
        membership = LeagueMembership.objects.create(
            league=self.league, user=self.user, role=LeagueMembership.ROLE_ADMIN)
        other = User.objects.create_user("luigi", "l@x.it", "pw")
        other_m = LeagueMembership.objects.create(league=self.league, user=other)
        self.mine = FantasyTeam.objects.create(
            league=self.league, manager=membership, name="I Miei")
        self.theirs = FantasyTeam.objects.create(
            league=self.league, manager=other_m, name="I Loro")

        self.home = self._club("Napoli")
        self.away = self._club("Inter")
        self.match = Match.objects.create(
            competition_season=self.cs, matchday=22, kickoff=SAT,
            kickoff_provisional=False, home_team=self.home, away_team=self.away,
            status=Match.STATUS_LIVE, data_ready=False, home_goals=0, away_goals=0,
            external_source="sofascore", external_id="900")

        self.md = FantasyMatchday.objects.create(
            league=self.league, real_competition_season=self.cs, real_matchday=22)
        competition = FantasyCompetition.objects.create(
            league=self.league, name="Campionato")
        self.fixture = FantasyFixture.objects.create(
            competition=competition, fantasy_matchday=self.md, round_no=22,
            home_team=self.mine, away_team=self.theirs)

        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.user).key}")

    # -- fixtures ----------------------------------------------------------- #
    def _club(self, name: str) -> TeamSeason:
        return TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name=name))

    def _player(self, name: str, role: str, *, minutes: int = ELAPSED,
                starter: bool = True, rated: bool = True) -> Player:
        """Un giocatore della partita in corso.

        ``minutes=ELAPSED`` = e' in campo adesso; meno = e' gia' uscito; zero e
        ``starter=False`` = non e' ancora entrato. ``rated=False`` gli toglie le
        zone, cioe' il caso dei primi minuti: in campo e senza un voto ancora.
        """
        p = Player.objects.create(full_name=name, short_name=name,
                                  classic_role_seed=role)
        PlayerTeamStint.objects.create(player=p, team_season=self.home)
        MatchAppearance.objects.create(
            match=self.match, player=p, team_season=self.home, side="home",
            minutes_played=minutes, is_starter=starter)
        if rated:
            PlayerZoneFeature.objects.create(
                match=self.match, player=p, provider="sofascore",
                feature_key="touches", zone_key="Z_2_2", value=12.0,
                team_side="home")
        return p

    def _field(self, gk, starters, bench):
        """La formazione mandata. Riscrivibile: piu' di una prova parte dall'XI
        base e ne cambia un posto solo."""
        SavedLineupSnapshot.objects.filter(
            league_id=str(self.league.id), lineup_id=f"team{self.mine.id}").delete()
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="22",
            lineup_id=f"team{self.mine.id}",
            gk_player_id=str(gk.id),
            starter_player_ids=[p.id for p in starters],
            bench_player_ids=[p.id for p in bench])

    def _squad(self):
        """Un XI legale (1-4-4-2) in cui due titolari non hanno un voto, per due
        ragioni diverse, e in panchina c'e' un solo rimpiazzo utilizzabile.

        L'ordine conta: IL DIFENSORE IN CAMPO VIENE PRIMA del centrocampista non
        entrato. La panchina si legge in ordine e il rimpiazzo e' uno solo, quindi
        se la previsione sbagliasse a scongelare chi sta giocando se lo prenderebbe
        LUI, e il non entrato resterebbe scoperto — cioe' esattamente il contrario
        di quel che deve succedere, invece di una differenza che non si vede.
        """
        self.gk = self._player("Portiere", "POR")
        # Il difensore dei primi minuti: in campo, ancora senza voto.
        self.on_pitch = self._player("In Campo", "DIF", rated=False)
        self.defs = [self.on_pitch] + [self._player(f"Dif{i}", "DIF") for i in range(3)]
        # Il titolare che il suo allenatore non ha schierato: zero minuti a partita
        # cominciata. E' lui che la previsione sostituisce.
        self.not_entered = self._player("Non Entrato", "CEN", minutes=0, starter=False,
                                        rated=False)
        self.mids = [self._player(f"Cen{i}", "CEN") for i in range(3)] + [self.not_entered]
        self.atts = [self._player(f"Att{i}", "ATT") for i in range(2)]
        # In panchina un centrocampista che sta giocando e ha gia' un voto: l'unico
        # che puo' entrare.
        self.reserve = self._player("Riserva", "CEN")
        self.starters = self.defs + self.mids + self.atts
        self._field(self.gk, self.starters, [self.reserve])

    def _detail(self, projection: bool = False):
        qs = "?projection=1" if projection else ""
        res = self.client.get(f"/api/v1/fixtures/{self.fixture.id}{qs}")
        self.assertEqual(res.status_code, 200)
        return res.data

    def _line(self, payload, player) -> dict:
        team = payload["home"]
        return next(l for l in team["starters"] + team["bench"]
                    if l["player_id"] == player.id)

    # -- le due letture ------------------------------------------------------ #
    def test_live_the_bench_covers_nobody_while_the_ball_is_rolling(self):
        """Il punteggio vero, quello di sempre: nessuno dei due buchi e' un buco
        finche' la partita che li ha fatti non e' finita."""
        self._squad()
        d = self._detail()
        self.assertFalse(d["projected"])
        self.assertTrue(d["in_progress"])
        self.assertEqual(d["home"]["substitutions"], [])
        self.assertIsNone(self._line(d, self.not_entered)["replaced_by"])
        self.assertFalse(self._line(d, self.reserve).get("entered"))

    def test_the_projection_brings_the_bench_on_for_who_never_came_on(self):
        """La domanda dell'utente, e la sua risposta."""
        self._squad()
        d = self._detail(projection=True)
        self.assertTrue(d["projected"])
        self.assertEqual(len(d["home"]["substitutions"]), 1)
        sub = d["home"]["substitutions"][0]
        self.assertEqual(sub["out"]["player_id"], self.not_entered.id)
        self.assertEqual(sub["in"]["player_id"], self.reserve.id)
        self.assertTrue(self._line(d, self.reserve)["entered"])

    def test_the_projection_never_substitutes_a_player_on_the_pitch(self):
        """Il confine della funzione. Al ventesimo minuto chi gioca puo' benissimo
        non avere ancora un voto, e sostituirlo sarebbe il vecchio errore — la
        panchina che copre un titolare regolarmente in campo — stavolta offerto
        come funzione invece che subito come bug."""
        self._squad()
        d = self._detail(projection=True)
        self.assertIsNone(self._line(d, self.on_pitch)["replaced_by"])
        self.assertNotIn(self.on_pitch.id,
                         [s["out"]["player_id"] for s in d["home"]["substitutions"]])

    def test_the_projection_still_says_those_matches_are_in_progress(self):
        """La previsione non fa finta che la giornata sia finita: la partita e' in
        corso davvero, ed e' il motivo per cui questo numero puo' cambiare fra dieci
        minuti. La pagina deve poterlo scrivere anche qui."""
        self._squad()
        d = self._detail(projection=True)
        self.assertTrue(d["in_progress"])
        self.assertTrue(d["provisional"])
        self.assertTrue(self._line(d, self.on_pitch)["in_progress"])

    def test_the_hole_the_bench_cannot_cover_gets_the_leagues_office_vote(self):
        """La panchina e' finita, la lega ha un voto d'ufficio: nella previsione il
        buco vale quel voto, perche' a fine partita varrebbe quello."""
        self.league.sv_office_vote = 4.0
        self.league.save(update_fields=["sv_office_vote"])
        self._squad()
        # Un SECONDO titolare mai entrato, al posto di un centrocampista qualunque:
        # i buchi diventano due e la panchina ne copre uno solo.
        second = self._player("Altro Assente", "CEN", minutes=0, starter=False,
                              rated=False)
        self.mids[0] = second
        self._field(self.gk, self.defs + self.mids + self.atts, [self.reserve])

        # Senza previsione nessuno dei due e' ancora un buco: la partita e' in corso.
        live = self._detail()
        self.assertFalse(self._line(live, second).get("office"))

        d = self._detail(projection=True)
        covered = {s["out"]["player_id"] for s in d["home"]["substitutions"]}
        uncovered = next(p for p in (self.not_entered.id, second.id)
                         if p not in covered)
        line = next(l for l in d["home"]["starters"] if l["player_id"] == uncovered)
        self.assertTrue(line["office"])
        self.assertEqual(line["fantavoto"], 4.0)

    # -- quel che la previsione NON e' --------------------------------------- #
    def test_a_match_that_has_not_kicked_off_stays_out_of_the_projection(self):
        """«Se finisse adesso» non ha niente da dire su una partita che non e'
        cominciata: li' la panchina non entra nemmeno nella previsione, perche'
        l'unica risposta possibile sarebbe inventata."""
        self._squad()
        tonight = self._club("Lazio")
        Match.objects.create(
            competition_season=self.cs, matchday=22,
            kickoff=timezone.now() + timedelta(hours=5), kickoff_provisional=False,
            home_team=tonight, away_team=self._club("Roma"),
            status=Match.STATUS_SCHEDULED, data_ready=False,
            external_source="sofascore", external_id="901")
        late = Player.objects.create(full_name="Jolly Stasera", short_name="Stasera",
                                     classic_role_seed="ATT")
        PlayerTeamStint.objects.create(player=late, team_season=tonight)
        # Un attaccante che stasera deve ancora scendere in campo, al posto di uno
        # dei due che stanno giocando.
        self.atts[0] = late
        self._field(self.gk, self.defs + self.mids + self.atts, [self.reserve])

        d = self._detail(projection=True)
        line = self._line(d, late)
        self.assertTrue(line["pending"])
        self.assertIsNone(line["replaced_by"])
        self.assertNotIn(late.id,
                         [s["out"]["player_id"] for s in d["home"]["substitutions"]])

    def test_the_projection_persists_nothing_and_leaves_the_real_score_alone(self):
        """La garanzia che rende il tasto innocuo: e' una LETTURA. Chiederla non
        scrive un referto e non cambia quel che si legge un istante dopo."""
        self._squad()
        before = self._detail()["home_total"]
        projected = self._detail(projection=True)
        after = self._detail()["home_total"]
        self.assertEqual(before, after)
        self.assertNotEqual(projected["home_total"], before,
                            "in questo scenario la previsione DEVE dire un numero "
                            "diverso, o la prova non sta misurando niente")
        self.assertFalse(FantasyFixtureDetail.objects.filter(
            fixture=self.fixture).exists())

    def test_the_projection_carries_the_real_score_alongside(self):
        """«84,5» da solo non dice niente: serve sapere che adesso sono 78,5. Le due
        risposte viaggiano insieme, cosi' la pagina non deve tenersi la vecchia ne'
        fare una seconda chiamata per confrontarle."""
        self._squad()
        live = self._detail()
        d = self._detail(projection=True)
        self.assertEqual(d["actual"]["home_total"], live["home_total"])
        self.assertEqual(d["actual"]["home_goals"], live["home_goals"])
        self.assertNotEqual(d["home_total"], d["actual"]["home_total"])

    def test_without_the_projection_there_is_no_second_score_to_carry(self):
        """Il punteggio vero non si porta dietro una copia di se stesso."""
        self._squad()
        self.assertNotIn("actual", self._detail())

    def test_on_a_concluded_tabellino_the_flag_is_ignored(self):
        """A giornata conclusa non c'e' piu' niente da prevedere: il referto
        congelato risponde com'e', e non si dichiara previsione."""
        FantasyFixtureDetail.objects.create(
            fixture=self.fixture, vfoot_home=1.0, vfoot_away=2.0,
            payload={"mode": "classic", "frozen": True})
        res = self.client.get(f"/api/v1/fixtures/{self.fixture.id}?projection=1")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["frozen"])
        self.assertNotIn("projected", res.data)
