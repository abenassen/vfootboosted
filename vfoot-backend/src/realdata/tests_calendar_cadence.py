"""Quanto calendario rileggere, e ogni quanto.

Serie A non gioca più solo il sabato e la domenica: si va dal venerdì al lunedì
più i turni infrasettimanali, e l'unica cosa che sa quando si gioca è il
calendario stesso — cioè proprio ciò che stiamo aggiornando. Quindi non esiste un
insieme di "giorni di gara" da scrivere dentro un'unità systemd: un'unità del
genere sarebbe vera per una settimana e poi falsa in silenzio.

La forma è quindi la stessa del pianificatore delle partite: il timer scatta
sempre uguale e il comando risponde a "è dovuta adesso?". Qui si fissano le due
risposte — quali turni e ogni quanto — e i due casi che le rendono non ovvie:
la partita rinviata di un turno passato, e l'orario che si sposta PRIMA di
quello che sappiamo.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from django.test import TestCase, override_settings

from realdata.models import (
    Competition, CompetitionSeason, Match, Season, Team, TeamSeason,
)
from realdata.services.calendar_sync import (
    DENSE_BEFORE_KICKOFF, rounds_to_sync, sync_is_due,
)

UTC = timezone.utc


class _Base(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            external_source="sofascore", external_id="95836", num_rounds=38)
        self.home = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Torino"))
        self.away = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Inter"))
        self.now = datetime(2027, 1, 31, 12, 0, tzinfo=UTC)

    def _match(self, matchday, kickoff, status=Match.STATUS_SCHEDULED, ext=None):
        return Match.objects.create(
            external_source="sofascore",
            external_id=ext or f"m{matchday}-{Match.objects.count()}",
            competition_season=self.cs, home_team=self.home, away_team=self.away,
            matchday=matchday, kickoff=kickoff, status=status)


@override_settings(VFOOT_CALENDAR_ROUNDS_AHEAD=4)
class RoundsToSyncTests(_Base):
    def test_the_next_round_and_the_four_after_it(self):
        for md in range(20, 30):
            self._match(md, self.now + timedelta(days=md - 22))
        for md in range(20, 22):                      # già giocati
            Match.objects.filter(matchday=md).update(status=Match.STATUS_FINISHED)
        self.assertEqual(rounds_to_sync(self.cs, self.now), [22, 23, 24, 25, 26])

    def test_a_played_round_is_not_read_again(self):
        """Il grosso del risparmio: una giornata giocata non si muove più."""
        self._match(20, self.now - timedelta(days=7), status=Match.STATUS_FINISHED)
        self._match(21, self.now + timedelta(days=1))
        self.assertNotIn(20, rounds_to_sync(self.cs, self.now))

    def test_a_postponed_fixture_keeps_its_old_round_in(self):
        """Il caso che la finestra ovvia perde: un rinvio conserva il numero di
        turno e prende una data nuova, anche mesi dopo. Il turno 20 può ancora
        muoversi mentre si gioca il 31."""
        self._match(20, None, status=Match.STATUS_POSTPONED)
        for md in range(31, 34):
            self._match(md, self.now + timedelta(days=md - 31))
        self.assertIn(20, rounds_to_sync(self.cs, self.now))
        self.assertIn(31, rounds_to_sync(self.cs, self.now))

    def test_an_unplayed_fixture_left_behind_is_kept_in_too(self):
        """Non solo i rinvii formali: qualunque partita ancora dovuta di un turno
        già passato tiene dentro il suo turno."""
        self._match(20, self.now - timedelta(days=30))     # scheduled, mai giocata
        self._match(31, self.now + timedelta(days=1))
        self.assertIn(20, rounds_to_sync(self.cs, self.now))

    def test_the_window_stops_at_the_last_round(self):
        """Chiedere il turno 41 costa una richiesta per ricevere zero eventi."""
        self._match(36, self.now + timedelta(days=1))
        self.assertEqual(rounds_to_sync(self.cs, self.now), [36, 37, 38])

    def test_a_finished_season_asks_for_nothing(self):
        self._match(38, self.now - timedelta(days=1), status=Match.STATUS_FINISHED)
        self.assertEqual(rounds_to_sync(self.cs, self.now), [])

    def test_an_empty_list_must_not_be_read_as_everything(self):
        """La trappola del chiamante: [] significa "niente", e uno scaldamento che
        lo leggesse come "nessun filtro" scaricherebbe tutta la stagione proprio
        quando non serve niente. Il comando esce prima; qui si fissa il valore."""
        self.assertEqual(rounds_to_sync(self.cs, self.now), [])


@override_settings(VFOOT_CALENDAR_SYNC_MINUTES=360,
                   VFOOT_CALENDAR_MATCHDAY_MINUTES=60)
class SyncIsDueTests(_Base):
    def _synced(self, ago):
        self.cs.calendar_synced_at = self.now - ago
        return self.cs

    def test_never_synced_is_due(self):
        self.assertTrue(sync_is_due(self.cs, self.now)[0])

    def test_the_floor_fires_even_with_nothing_in_sight(self):
        """Ed è la rete: è quello che prende una partita comparsa in un giorno che
        il calendario che abbiamo dice vuoto."""
        self._synced(timedelta(hours=7))
        self.assertTrue(sync_is_due(self.cs, self.now)[0])

    def test_below_the_floor_and_nothing_in_sight_is_not_due(self):
        self._synced(timedelta(hours=2))
        self.assertFalse(sync_is_due(self.cs, self.now)[0])

    def test_a_kickoff_in_sight_makes_an_hour_enough(self):
        self._match(22, self.now + timedelta(hours=6))
        self._synced(timedelta(minutes=61))
        self.assertTrue(sync_is_due(self.cs, self.now)[0])

    def test_but_not_more_often_than_the_dense_interval(self):
        self._match(22, self.now + timedelta(hours=6))
        self._synced(timedelta(minutes=30))
        self.assertFalse(sync_is_due(self.cs, self.now)[0])

    def test_the_dense_window_covers_a_kickoff_moved_earlier_in_the_day(self):
        """La debolezza del decidere la densità dal calendario che stiamo
        aggiornando: se un orario si sposta PRIMA di quello che sappiamo, una
        finestra ancorata all'ora nota sarebbe fitta a cose fatte — e quella è la
        direzione pericolosa, perché il blocco delle formazioni legge Match.kickoff.
        Diciotto ore coprono qualunque spostamento dentro la giornata."""
        self._match(22, self.now + DENSE_BEFORE_KICKOFF - timedelta(minutes=5))
        self._synced(timedelta(minutes=61))
        self.assertTrue(sync_is_due(self.cs, self.now)[0])

    def test_a_kickoff_beyond_the_window_does_not_make_it_dense(self):
        self._match(22, self.now + DENSE_BEFORE_KICKOFF + timedelta(hours=2))
        self._synced(timedelta(minutes=61))
        self.assertFalse(sync_is_due(self.cs, self.now)[0])

    def test_a_match_under_way_is_not_a_reason_to_look(self):
        """È cominciata: il calendario ha detto la verità e il resto è del tick."""
        self._match(22, self.now - timedelta(hours=1), status=Match.STATUS_LIVE)
        self._synced(timedelta(minutes=61))
        self.assertFalse(sync_is_due(self.cs, self.now)[0])

    def test_a_match_that_should_have_started_and_did_not_IS(self):
        """Il caso del rinvio per maltempo, ed è quello che una regola che guarda
        solo avanti perde. Partita alle 20, rinviata alle 22 e annunciato alle
        20:05 — cioè subito dopo la passata delle 20. Alle 21 il calcio d'inizio
        che conosciamo è passato: guardando solo avanti si cade sul pavimento e le
        22 non si vedono più. Una partita che non è cominciata quando pensavamo è
        invece l'indizio più forte che il calendario sia sbagliato."""
        self._match(22, self.now - timedelta(hours=1))   # ancora 'scheduled'
        self._synced(timedelta(minutes=61))
        self.assertTrue(sync_is_due(self.cs, self.now)[0])

    def test_the_same_for_one_the_provider_has_flagged_postponed(self):
        self._match(22, self.now - timedelta(minutes=30),
                    status=Match.STATUS_POSTPONED)
        self._synced(timedelta(minutes=61))
        self.assertTrue(sync_is_due(self.cs, self.now)[0])

    def test_but_not_for_ever(self):
        """Una partita che il provider abbandona senza mai risolverla non deve
        tenerci fitti all'infinito: oltre la grazia se ne occupa il pavimento, che
        è la cadenza giusta per una cosa ormai lontana giorni."""
        self._match(22, self.now - timedelta(hours=12))
        self._synced(timedelta(minutes=61))
        self.assertFalse(sync_is_due(self.cs, self.now)[0])

    def test_and_a_match_already_played_is_not_one_of_these(self):
        self._match(22, self.now - timedelta(hours=2),
                    status=Match.STATUS_FINISHED)
        self._synced(timedelta(minutes=61))
        self.assertFalse(sync_is_due(self.cs, self.now)[0])

    def test_a_finished_match_is_not_a_kickoff_in_sight(self):
        self._match(22, self.now + timedelta(hours=2), status=Match.STATUS_FINISHED)
        self._synced(timedelta(minutes=61))
        self.assertFalse(sync_is_due(self.cs, self.now)[0])

    @override_settings(VFOOT_CALENDAR_MATCHDAY_MINUTES=15)
    def test_the_dense_interval_is_a_knob(self):
        self._match(22, self.now + timedelta(hours=6))
        self._synced(timedelta(minutes=20))
        self.assertTrue(sync_is_due(self.cs, self.now)[0])

    def test_the_reason_is_always_given(self):
        """Va nel journal: un job che decide da solo di non fare niente deve dire
        perché, o è indistinguibile da uno rotto."""
        self._synced(timedelta(hours=2))
        due, why = sync_is_due(self.cs, self.now)
        self.assertFalse(due)
        self.assertTrue(why)
