"""L'indice di giornata sta in cache, e la chiave si muove con i dati.

Il conto piu' caro che l'applicazione faccia in risposta a un clic sono le dieci
pagelle di un turno: voto puro, esposizione difensiva e spiegazione per
quattrocentosessanta giocatori. Il calendario le rifaceva TUTTE per stampare due
numeri per partita — a ogni apertura della home e a ogni colpo del socket live —
e il tabellino live le rifaceva un'altra volta per conto suo. Un secondo e mezzo
di attesa per un dato che, fra un giro di importazione e l'altro, non cambia.

Quello che questi test inchiodano non e' la velocita' ma la CORRETTEZZA della
cosa che la produce: la chiave. Una cache che serve dati stantii e' molto peggio
di una lenta, perche' non lo dice a nessuno — e' gia' successo col listone, che
ha servito per settimane voti calcolati prima di una ritaratura del modello.
Quindi: stesse risposte, e chiave diversa appena si muove qualcosa che conta —
il punteggio, i tabellini, i ruoli congelati della lega, i pesi del modello.
"""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings

from realdata.models import (
    Competition, CompetitionSeason, Match, MatchAppearance, Player,
    PlayerZoneFeature, Season, Team, TeamSeason,
)
from vfoot.models import (
    FantasyLeague, LeagueMembership, LeaguePlayerRole,
)
from vfoot.services import classic_matchday_scoring as cms
from vfoot.services.classic_pagella import matchday_data_version


# La suite gira su una cache finta, perche' un contatore di throttle che
# sopravvive fra un test e l'altro fa fallire il test dopo (vedi settings.py).
# Qui la cache e' l'oggetto in esame, quindi ce ne vuole una vera.
@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                        "LOCATION": "matchday-index-tests"}},
)
class MatchdayIndexCacheTests(TestCase):
    def setUp(self):
        cache.clear()
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        self.user = User.objects.create_user("mario", "m@x.it", "pw")
        self.league = FantasyLeague.objects.create(
            name="Lega", owner=self.user, mode=FantasyLeague.MODE_CLASSIC,
            reference_season=self.cs)
        LeagueMembership.objects.create(
            league=self.league, user=self.user, role=LeagueMembership.ROLE_ADMIN)
        self.match = Match.objects.create(
            competition_season=self.cs, matchday=22,
            home_team=self._club("Napoli"), away_team=self._club("Inter"),
            status=Match.STATUS_LIVE, data_ready=False,
            home_goals=1, away_goals=0)
        self.player = self._appearance("Tizio", minutes=70)

    def _club(self, name: str) -> TeamSeason:
        return TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name=name))

    def _appearance(self, name: str, *, minutes: int) -> Player:
        p = Player.objects.create(full_name=name, short_name=name,
                                  classic_role_seed="CEN")
        MatchAppearance.objects.create(
            match=self.match, player=p, team_season=self.match.home_team,
            side="home", minutes_played=minutes, is_starter=True)
        PlayerZoneFeature.objects.create(
            match=self.match, player=p, provider="sofascore",
            feature_key="touches", zone_key="Z_2_2", value=30.0, team_side="home")
        return p

    def _index(self):
        return cms.build_matchday_index(self.cs.id, 22, self.league)

    def _key(self):
        return cms._index_cache_key(self.cs.id, 22, self.league)

    # -- la cache serve la stessa cosa -------------------------------------
    def test_the_second_read_is_the_first_one(self):
        first = self._index()
        second = self._index()
        self.assertEqual(first, second)
        self.assertIn(self.player.id, first)

    def test_the_second_read_does_not_recompute(self):
        self._index()
        with patch.object(cms, "pagella_for_match") as never:
            self._index()
        never.assert_not_called()

    def test_a_cold_cache_computes(self):
        """Il contrappeso del test sopra: senza voce in cache la pagella si fa."""
        with patch.object(cms, "pagella_for_match",
                          return_value={"home": {"starters": [], "bench": []},
                                        "away": {"starters": [], "bench": []}}) as once:
            self._index()
        once.assert_called_once()

    # -- ...e cambia chiave quando cambiano i dati -------------------------
    def test_a_goal_moves_the_key(self):
        before = self._key()
        self.match.home_goals = 2
        self.match.save(update_fields=["home_goals"])
        self.assertNotEqual(before, self._key())

    def test_a_live_round_moves_the_key(self):
        """Il timbro che il tick scrive dopo ogni importazione live."""
        before = self._key()
        self.match.data_checked_at = self.match.created_at
        self.match.save(update_fields=["data_checked_at"])
        self.assertNotEqual(before, self._key())

    def test_the_final_confirmation_moves_the_key(self):
        before = self._key()
        self.match.data_ready = True
        self.match.save(update_fields=["data_ready"])
        self.assertNotEqual(before, self._key())

    def test_a_reimported_scoresheet_moves_the_key(self):
        """Nessuna riga di presenza porta una data di modifica, e un reimport a
        mano dei tabellini non tocca la partita: senza le somme sulle presenze
        questo passerebbe inosservato."""
        before = self._key()
        MatchAppearance.objects.filter(match=self.match, player=self.player).update(
            minutes_played=90, goals=1)
        self.assertNotEqual(before, self._key())

    def test_a_new_frozen_role_moves_the_key(self):
        """L'import di Transfermarkt puo' congelare un ruolo a lega in corso, e il
        ruolo decide il malus della riga."""
        before = self._key()
        LeaguePlayerRole.objects.create(
            league=self.league, player=self.player, role="DIF")
        self.assertNotEqual(before, self._key())

    def test_retuning_the_model_moves_the_key(self):
        """Ritoccare i pesi cambia ogni voto senza toccare una riga di database:
        se la chiave non se ne accorge, la cache serve il modello vecchio."""
        before = self._key()
        with patch.object(cms, "scoring_fingerprint", return_value="ritarato"):
            self.assertNotEqual(before, self._key())

    def test_only_the_latest_index_stays_in_the_cache(self):
        """Un turno in diretta ne genererebbe una nuova ogni due minuti.

        La cache su file tiene cinquecento voci e, arrivata al tetto, ne butta un
        terzo A CASO — fra cui la taratura del voto, che costa molto piu' di quel
        che queste hanno risparmiato. La precedente e' spazzatura appena i dati si
        muovono, quindi se ne va subito.
        """
        self._index()
        old = self._key()
        self.assertIsNotNone(cache.get(old))

        self.match.home_goals = 2
        self.match.save(update_fields=["home_goals"])
        self._index()

        self.assertIsNone(cache.get(old), "la voce del giro precedente e' andata")
        self.assertIsNotNone(cache.get(self._key()))

    def test_another_league_gets_its_own_entry(self):
        """I ruoli congelati sono per lega, quindi lo e' anche la pagella."""
        other_user = User.objects.create_user("luigi", "l@x.it", "pw")
        other = FantasyLeague.objects.create(
            name="Altra", owner=other_user, mode=FantasyLeague.MODE_CLASSIC,
            reference_season=self.cs)
        self.assertNotEqual(self._key(),
                            cms._index_cache_key(self.cs.id, 22, other))

    # -- l'impronta dei dati, per conto suo --------------------------------
    def test_an_untouched_matchday_keeps_its_version(self):
        self.assertEqual(matchday_data_version(self.cs.id, 22),
                         matchday_data_version(self.cs.id, 22))

    def test_matchdays_do_not_share_a_version(self):
        self.assertNotEqual(matchday_data_version(self.cs.id, 22),
                            matchday_data_version(self.cs.id, 23))
