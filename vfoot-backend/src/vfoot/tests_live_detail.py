"""The tabellino of a league fixture while its matchday is still being played.

Two claims worth pinning down, because both are easy to break by accident:

* the round in progress ANSWERS — with votes, computed on the spot — instead of the
  404 it used to give until the admin concluded;
* it answers WITHOUT PERSISTING. The frozen payload is born at the conclusion and
  only there; a provisional one written into ``FantasyFixtureDetail`` would destroy
  the property that reopening a closed matchday is pure reading.

And the distinction the live view exists for: a player whose club has not kicked off
is NOT the same as one whose club is playing. The first has nothing to show and the
bench must not cover him; the second has a vote that is simply going to move.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from realdata.models import (
    Competition, CompetitionSeason, Match, Player, PlayerTeamStint, Season, Team,
    TeamSeason,
)
from vfoot.models import (
    FantasyCompetition, FantasyFixture, FantasyFixtureDetail, FantasyLeague,
    FantasyMatchday, FantasyTeam, LeagueMembership, SavedLineupSnapshot, UserProfile,
)
from vfoot.services.classic_matchday_scoring import _live_states, _mark_unstable

# Relative to the real clock, not a fixed date: half of what is under test keys on
# whether the round HAS KICKED OFF, and a 2027 fixture is in the future for a suite
# run in 2026 — the calendar would answer "not begun" and prove nothing.
SAT = timezone.now() - timedelta(hours=1)


class LiveDetailTests(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        self.user = User.objects.create_user("mario", "m@x.it", "pw")
        self.league = FantasyLeague.objects.create(
            name="Lega", owner=self.user, mode=FantasyLeague.MODE_CLASSIC,
            reference_season=self.cs)
        self.membership = LeagueMembership.objects.create(
            league=self.league, user=self.user, role=LeagueMembership.ROLE_ADMIN)
        other = User.objects.create_user("luigi", "l@x.it", "pw")
        other_m = LeagueMembership.objects.create(league=self.league, user=other)
        self.mine = FantasyTeam.objects.create(
            league=self.league, manager=self.membership, name="I Miei")
        self.theirs = FantasyTeam.objects.create(
            league=self.league, manager=other_m, name="I Loro")

        # Two real clubs: one playing right now, one kicking off tonight.
        self.playing = self._club("Napoli"), self._club("Inter")
        self.later = self._club("Lazio"), self._club("Roma")
        self.live_match = Match.objects.create(
            competition_season=self.cs, matchday=22, kickoff=SAT,
            kickoff_provisional=False, home_team=self.playing[0],
            away_team=self.playing[1], status=Match.STATUS_LIVE, data_ready=False,
            home_goals=1, away_goals=0,
            external_source="sofascore", external_id="900")
        self.later_match = Match.objects.create(
            competition_season=self.cs, matchday=22, kickoff=SAT + timedelta(hours=6),
            kickoff_provisional=False, home_team=self.later[0],
            away_team=self.later[1], status=Match.STATUS_SCHEDULED, data_ready=False,
            external_source="sofascore", external_id="901")

        self.md = FantasyMatchday.objects.create(
            league=self.league, real_competition_season=self.cs, real_matchday=22)
        self.competition = FantasyCompetition.objects.create(
            league=self.league, name="Campionato")
        self.fixture = FantasyFixture.objects.create(
            competition=self.competition, fantasy_matchday=self.md, round_no=22,
            home_team=self.mine, away_team=self.theirs)

        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.user).key}")

    def _club(self, name: str) -> TeamSeason:
        return TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name=name))

    def _player(self, name: str, club: TeamSeason) -> Player:
        p = Player.objects.create(full_name=name)
        PlayerTeamStint.objects.create(player=p, team_season=club)
        return p

    # -- the two ways a vote can fail to be final --------------------------- #
    def test_a_club_in_the_field_is_unstable_and_one_still_to_play_is_not_started(self):
        on_pitch = self._player("In Campo", self.playing[0])
        tonight = self._player("Stasera", self.later[0])
        not_started, unstable, in_progress = _live_states(
            self.cs.id, 22, [on_pitch.id, tonight.id])
        self.assertEqual(unstable, {on_pitch.id})
        self.assertEqual(in_progress, {on_pitch.id})
        self.assertEqual(not_started, {tonight.id})

    def test_a_settled_match_is_neither(self):
        p = self._player("Ieri", self.playing[0])
        Match.objects.filter(id=self.live_match.id).update(
            status=Match.STATUS_FINISHED, data_ready=True)
        not_started, unstable, in_progress = _live_states(self.cs.id, 22, [p.id])
        self.assertEqual((not_started, unstable, in_progress), (set(), set(), set()))

    def test_full_time_is_still_unstable_until_the_data_settles(self):
        """data_ready, not the status, is the marker — the provider goes on
        correcting a match for an hour after the whistle.

        Ma NON e' piu' «in corso»: il fischio e' suonato. I due insiemi si separano
        esattamente qui, ed e' l'ora in cui la pagina scriveva «live» su una partita
        finita e il motore rimandava il voto d'ufficio."""
        p = self._player("Finito", self.playing[0])
        Match.objects.filter(id=self.live_match.id).update(
            status=Match.STATUS_FINISHED, data_ready=False)
        _not_started, unstable, in_progress = _live_states(self.cs.id, 22, [p.id])
        self.assertEqual(unstable, {p.id})
        self.assertEqual(in_progress, set())

    def test_one_unstable_line_makes_the_whole_team_total_provisional(self):
        team = {"starters": [{"player_id": 1}, {"player_id": 2}], "bench": []}
        self.assertTrue(_mark_unstable(team, {2}))
        self.assertTrue(team["provisional"])
        self.assertNotIn("provisional", team["starters"][0])
        self.assertTrue(team["starters"][1]["provisional"])

    def test_only_a_match_on_the_pitch_is_marked_in_progress(self):
        """Provvisorio e in corso sono due marchi diversi: il primo dice che il
        numero puo' muoversi, il secondo che la palla sta ancora rotolando — e solo
        il secondo ferma la sostituzione."""
        team = {"starters": [{"player_id": 1}, {"player_id": 2}], "bench": []}
        self.assertTrue(_mark_unstable(team, {1, 2}, {2}))
        self.assertTrue(team["starters"][0]["provisional"])
        self.assertNotIn("in_progress", team["starters"][0])
        self.assertTrue(team["starters"][1]["in_progress"])
        self.assertTrue(team["in_progress"])

    def test_an_imposed_vote_is_never_marked_provisional(self):
        """The league has ruled; nothing the provider does afterwards moves it."""
        team = {"starters": [{"player_id": 1, "office": True}], "bench": []}
        self.assertFalse(_mark_unstable(team, {1}))
        self.assertFalse(team["provisional"])

    # -- the endpoint -------------------------------------------------------- #
    def test_a_round_in_progress_answers_and_persists_nothing(self):
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="22",
            lineup_id=f"team{self.mine.id}",
            gk_player_id=str(self._player("Portiere", self.playing[0]).id),
            starter_player_ids=[self._player("Attaccante", self.playing[1]).id],
            bench_player_ids=[])
        res = self.client.get(f"/api/v1/fixtures/{self.fixture.id}")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["live"])
        self.assertEqual(res.data["real_matchday"], 22)
        # The one thing it must NOT do.
        self.assertFalse(FantasyFixtureDetail.objects.filter(
            fixture=self.fixture).exists())

    def test_a_concluded_matchday_without_a_payload_is_still_a_404(self):
        self.md.status = FantasyMatchday.STATUS_CONCLUDED
        self.md.save(update_fields=["status"])
        res = self.client.get(f"/api/v1/fixtures/{self.fixture.id}")
        self.assertEqual(res.status_code, 404)

    # -- the calendar ------------------------------------------------------- #
    def test_the_calendar_carries_the_partial_score_of_a_round_that_has_begun(self):
        """It used to say "vs" over a match two thirds played, while the tabellino
        one tap away said 66-72 — two answers to one question."""
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="22",
            lineup_id=f"team{self.mine.id}",
            gk_player_id=str(self._player("Portiere", self.playing[0]).id),
            starter_player_ids=[self._player("Attaccante", self.playing[1]).id],
            bench_player_ids=[])
        res = self.client.get(f"/api/v1/leagues/{self.league.id}/fixtures")
        self.assertEqual(res.status_code, 200)
        row = next(r for r in res.data if r["fixture_id"] == self.fixture.id)
        self.assertIsNotNone(row["score"])
        self.assertTrue(row["score_provisional"])
        self.assertTrue(row["score_in_progress"])
        self.assertTrue(row["has_detail"])

    def test_after_the_last_whistle_the_calendar_stops_saying_live(self):
        """L'ora fra il fischio finale e la conferma del fornitore. Il punteggio si
        muove ancora — di poco — ma non si sta piu' giocando, e dirlo con la stessa
        parola faceva pulsare «live» su un turno finito, allo stesso utente a cui
        era appena arrivata la notifica di fine partita."""
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="22",
            lineup_id=f"team{self.mine.id}",
            gk_player_id=str(self._player("Portiere", self.playing[0]).id),
            starter_player_ids=[self._player("Attaccante", self.playing[1]).id],
            bench_player_ids=[])
        Match.objects.filter(competition_season=self.cs).update(
            status=Match.STATUS_FINISHED, data_ready=False)
        res = self.client.get(f"/api/v1/leagues/{self.league.id}/fixtures")
        row = next(r for r in res.data if r["fixture_id"] == self.fixture.id)
        self.assertTrue(row["score_provisional"])
        self.assertFalse(row["score_in_progress"])

    def test_a_round_that_has_not_kicked_off_has_no_score_at_all(self):
        """Zero-zero because it has not started and zero-zero at the twentieth
        minute are the same two numbers; only one of them may be shown."""
        Match.objects.filter(competition_season=self.cs).update(
            kickoff=timezone.now() + timedelta(days=3))
        res = self.client.get(f"/api/v1/leagues/{self.league.id}/fixtures")
        row = next(r for r in res.data if r["fixture_id"] == self.fixture.id)
        self.assertIsNone(row["score"])
        self.assertFalse(row["score_provisional"])
        # Aprirla si', pero': in classic le formazioni sono pubbliche anche prima
        # del via. Non c'e' un punteggio da mostrare, ci sono le formazioni — sono
        # due cose diverse e solo una delle due manca.
        self.assertTrue(row["has_detail"])

    # -- il voto d'ufficio aspetta l'ultimo fischio -------------------------- #
    #
    # Al sabato sera nessun panchinaro ha ancora un voto, quindi nessuno e'
    # utilizzabile e OGNI titolare senza voto risulta un buco che la panchina non
    # copre. Tapparlo subito col voto d'ufficio significava scrivere per due giorni
    # «questo non verra' sostituito» proprio mentre il sostituto doveva ancora
    # scendere in campo — e alla domenica sera il cambio si faceva lo stesso.
    def _played_on_saturday(self) -> TeamSeason:
        """La partita del sabato pomeriggio: finita e confermata, con tutte le
        altre del turno ancora da giocare."""
        home, away = self._club("Milan"), self._club("Venezia")
        Match.objects.create(
            competition_season=self.cs, matchday=22, kickoff=SAT - timedelta(hours=3),
            kickoff_provisional=False, home_team=home, away_team=away,
            status=Match.STATUS_FINISHED, data_ready=True, home_goals=2, away_goals=0,
            external_source="sofascore", external_id="902")
        return home

    def _field_a_hole(self):
        """Un titolare della partita gia' finita che non e' sceso in campo — nessuna
        riga in pagella, cioe' un buco — e in panchina l'unico che potrebbe coprirlo,
        che gioca stasera."""
        self.league.sv_office_vote = 4.0
        self.league.save(update_fields=["sv_office_vote"])
        hole = self._player("Mai Sceso", self._played_on_saturday())
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="22",
            lineup_id=f"team{self.mine.id}",
            gk_player_id=str(hole.id), starter_player_ids=[],
            bench_player_ids=[self._player("Stasera", self.later[0]).id])
        return hole

    def _hole_line(self, hole):
        d = self.client.get(f"/api/v1/fixtures/{self.fixture.id}").data
        return d, next(l for l in d["home"]["starters"] if l["player_id"] == hole.id)

    def test_the_office_vote_waits_while_the_round_is_still_being_played(self):
        hole = self._field_a_hole()
        d, line = self._hole_line(hole)
        self.assertFalse(line.get("office"))
        self.assertIsNone(line["fantavoto"])
        self.assertEqual(d["home"]["sv_filled"], [])
        # Il posto e' scoperto adesso, e il referto continua a dirlo: quel che
        # aspetta e' il conto, non la constatazione.
        self.assertEqual(d["home"]["unresolved_sv"], [hole.id])
        self.assertTrue(d["office_deferred"])

    def test_and_it_arrives_when_the_last_match_of_the_round_is_over(self):
        """Stesso buco, ultimo fischio del turno: adesso la frase e' vera e il voto
        d'ufficio la paga."""
        hole = self._field_a_hole()
        Match.objects.filter(competition_season=self.cs).update(
            status=Match.STATUS_FINISHED)
        d, line = self._hole_line(hole)
        self.assertTrue(line["office"])
        self.assertEqual(line["fantavoto"], 4.0)
        self.assertEqual(d["home"]["sv_filled"], [hole.id])
        self.assertFalse(d["office_deferred"])

    def test_a_postponement_does_not_hold_the_whole_round_hostage(self):
        """Il rinvio non e' «una partita ancora da giocare in giornata»: e' un caso
        che la lega risolve a parte, e tenere sospesi i buchi di tutti per sei
        settimane sarebbe peggio del problema."""
        hole = self._field_a_hole()
        Match.objects.filter(competition_season=self.cs).update(
            status=Match.STATUS_FINISHED)
        Match.objects.filter(id=self.later_match.id).update(
            status=Match.STATUS_POSTPONED)
        d, line = self._hole_line(hole)
        self.assertTrue(line["office"])
        self.assertFalse(d["office_deferred"])

    def test_the_frozen_payload_wins_when_there_is_one(self):
        FantasyFixtureDetail.objects.create(
            fixture=self.fixture, vfoot_home=1.0, vfoot_away=2.0,
            payload={"mode": "classic", "frozen": True})
        res = self.client.get(f"/api/v1/fixtures/{self.fixture.id}")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["frozen"])

    # -- prima del calcio d'inizio ------------------------------------------- #
    #
    # Il blocco delle formazioni E' il primo calcio d'inizio del turno, quindi
    # «prima che la giornata cominci» e «prima della scadenza» sono lo stesso
    # momento. Fin qui li' non c'era niente da aprire, in nessuna delle due
    # modalita'. Dal 20/08/2026 in CLASSIC si', perche' la formazione altrui non e'
    # un vantaggio: la migliore e' la tua migliore qualunque cosa faccia l'altro.
    # In AURA no — il punteggio nasce da un duello per zone e sapere dove si mette
    # l'avversario e' esattamente cio' che permette di contro-schierarsi.
    def _kickoffs_in_three_days(self):
        Match.objects.filter(competition_season=self.cs).update(
            kickoff=timezone.now() + timedelta(days=3))

    def _field(self, team):
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="22",
            lineup_id=f"team{team.id}",
            gk_player_id=str(self._player("Portiere", self.playing[0]).id),
            starter_player_ids=[self._player("Attaccante", self.playing[1]).id],
            bench_player_ids=[])

    def _calendar_row(self):
        res = self.client.get(f"/api/v1/leagues/{self.league.id}/fixtures")
        return next(r for r in res.data if r["fixture_id"] == self.fixture.id)

    def test_in_classic_the_other_managers_lineup_is_visible_before_kickoff(self):
        """E' tutto il punto: la formazione che si vede e' quella DELL'ALTRO."""
        self._kickoffs_in_three_days()
        self._field(self.theirs)
        self.assertTrue(self._calendar_row()["has_detail"])

        res = self.client.get(f"/api/v1/fixtures/{self.fixture.id}")
        self.assertEqual(res.status_code, 200)
        # Non e' un tabellino, e' un'anteprima: il client ci disegna una pagina
        # diversa invece di presentare uno 0-0 come un risultato.
        self.assertFalse(res.data["lineups_locked"])
        self.assertIsNotNone(res.data["lock_at"])
        self.assertEqual(res.data["lineup_source"]["away"], "lineup")
        self.assertTrue(res.data["away"]["starters"])

    def test_the_preview_says_when_each_side_locks_in_its_leagues_words(self):
        """La frase in fondo dipende dalla modalita': in ``own`` ogni squadra si
        chiude alla prima partita di un proprio giocatore, e il payload lo dice
        per lato, con la partita che la chiude. Nessuna rosa qui, quindi la
        scadenza di ciascuna ricade sul primo calcio d'inizio del turno."""
        self._kickoffs_in_three_days()
        self.league.lineup_lock_mode = FantasyLeague.LOCK_OWN
        self.league.save(update_fields=["lineup_lock_mode"])
        res = self.client.get(f"/api/v1/fixtures/{self.fixture.id}")
        lk = res.data["lineup_lock"]
        self.assertEqual(lk["mode"], "own")
        self.assertEqual(lk["home"]["at"], res.data["lock_at"])
        self.assertIn("-", lk["home"]["with"])
        self.assertIsNotNone(lk["last_at"])
        self.league.lineup_lock_mode = FantasyLeague.LOCK_MATCHDAY
        self.league.save(update_fields=["lineup_lock_mode"])
        lk = self.client.get(f"/api/v1/fixtures/{self.fixture.id}").data["lineup_lock"]
        self.assertEqual((lk["mode"], lk["home"]), ("matchday", None))

    def test_and_it_opens_even_with_nobody_fielded_yet(self):
        """Perche' la regola e' della LEGA, non della singola partita.

        Aprire solo dove qualcuno avesse gia' schierato sembrava un riguardo — un
        collegamento a un tabellino vuoto non serve a nessuno — ed e' finito col
        rendere cliccabili certe righe si' e certe no senza niente che lo
        spiegasse. Per giunta la riga morta era spesso proprio la propria, cioe'
        l'unica in cui non aver ancora schierato e' una cosa su cui si puo' agire.
        """
        self._kickoffs_in_three_days()
        self.assertTrue(self._calendar_row()["has_detail"])
        res = self.client.get(f"/api/v1/fixtures/{self.fixture.id}")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["lineups_locked"])
        # E la pagina lo dice, invece di far finta che una formazione ci sia.
        self.assertEqual(res.data["lineup_source"]["home"], "forfait")
        self.assertEqual(res.data["home"]["starters"], [])

    def test_an_aura_league_keeps_the_lineups_covered_until_the_deadline(self):
        """E non basta che il calendario non ci porti: l'indirizzo si digita.

        Finche' l'unico cancello e' stato il collegamento mancante, chiunque
        conoscesse l'id della partita si leggeva la formazione dell'avversario di
        una giornata ancora aperta."""
        FantasyLeague.objects.filter(id=self.league.id).update(
            mode=FantasyLeague.MODE_AURA)
        self._kickoffs_in_three_days()
        self._field(self.theirs)
        self.assertFalse(self._calendar_row()["has_detail"])
        self.assertEqual(
            self.client.get(f"/api/v1/fixtures/{self.fixture.id}").status_code, 404)

    def test_once_the_round_has_kicked_off_aura_opens_like_everyone_else(self):
        """La copertura e' fino alla scadenza, non per sempre."""
        FantasyLeague.objects.filter(id=self.league.id).update(
            mode=FantasyLeague.MODE_AURA)
        self._field(self.theirs)
        self.assertTrue(self._calendar_row()["has_detail"])
        res = self.client.get(f"/api/v1/fixtures/{self.fixture.id}")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["lineups_locked"])

    # -- i due fantallenatori ------------------------------------------------ #
    def test_the_tabellino_names_both_managers_live(self):
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="22",
            lineup_id=f"team{self.mine.id}",
            gk_player_id=str(self._player("Portiere", self.playing[0]).id),
            starter_player_ids=[self._player("Attaccante", self.playing[1]).id],
            bench_player_ids=[])
        res = self.client.get(f"/api/v1/fixtures/{self.fixture.id}")
        self.assertEqual(res.data["home_manager"]["username"], "mario")
        self.assertEqual(res.data["away_manager"]["username"], "luigi")
        self.assertEqual(res.data["home_manager"]["team_id"], self.mine.id)
        # Nessun profilo = nessun avatar scelto, che è uno stato normale: il client
        # ne disegna uno seminato sul nome, e la stringa vuota è come glielo dice.
        self.assertEqual(res.data["away_manager"]["avatar"], "")

    def test_a_frozen_tabellino_shows_the_avatar_of_today(self):
        """Il referto è congelato, la faccia no.

        Congelare l'avatar dentro il payload avrebbe voluto dire che chi se la
        cambia oggi resta con la vecchia su tutte le partite già giocate — e la
        striscia in fondo al tabellino esiste proprio per farla vedere."""
        FantasyFixtureDetail.objects.create(
            fixture=self.fixture, vfoot_home=1.0, vfoot_away=2.0,
            payload={"mode": "classic", "frozen": True})
        UserProfile.objects.create(user=self.user, avatar='{"top":"hat"}')
        res = self.client.get(f"/api/v1/fixtures/{self.fixture.id}")
        self.assertEqual(res.data["home_manager"]["avatar"], '{"top":"hat"}')
        self.assertEqual(res.data["home_manager"]["user_id"], self.user.id)
