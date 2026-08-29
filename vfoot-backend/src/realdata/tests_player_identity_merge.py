"""Un giocatore, una riga — anche quando i due fornitori non concordano.

Il caso e' successo in produzione, in campionato: Giacomo Calo' entra dall'import
rose di Transfermarkt (5 febbraio 1997), esordisce col Frosinone, e SofaScore lo
conia una seconda volta perche' la sua data e' il 2 maggio 1997 — giorno e mese
scambiati. Da li' in poi la meta' comprata all'asta non ha piu' una presenza e
resta senza voto, mentre la meta' che gioca non e' nel listone e non e' di
nessuno. Nessun errore da nessuna parte.

Insieme a lui, la stessa cosa per altri nove: 'Manga Foe Ondoa' contro
'Foe Ondoa' (stessa data, nome diverso) e cinque con un giorno di scarto.
"""
from __future__ import annotations

import io
from datetime import date

from django.core.management import call_command
from django.test import TestCase

from realdata.models import (Competition, CompetitionSeason, Match,
                             MatchAppearance, Player, PlayerAlias,
                             PlayerTeamStint, Season, Team, TeamSeason)
from realdata.services import health, roster_integrity
from realdata.services.identity import synthetic_sofascore_id
from realdata.services.sofascore_adapter import _adopt_by_identity, _player


class AdozioneTests(TestCase):
    def setUp(self):
        comp = Competition.objects.create(name="Serie A", external_source="sofascore",
                                          external_id="23")
        season = Season.objects.create(code="2026-2027")
        cs = CompetitionSeason.objects.create(
            competition=comp, season=season, external_source="sofascore",
            external_id="76457", num_rounds=38)
        team = Team.objects.create(name="Frosinone", external_source="sofascore",
                                   external_id="1")
        self.ts = TeamSeason.objects.create(team=team, competition_season=cs)
        self.altra = TeamSeason.objects.create(
            team=Team.objects.create(name="Monza", external_source="sofascore",
                                     external_id="2"),
            competition_season=cs)

    def _in_rosa(self, ts, **kw):
        p = Player.objects.create(external_source="transfermarkt", **kw)
        PlayerTeamStint.objects.create(player=p, team_season=ts,
                                       start_date=date(2026, 7, 1))
        return p

    def test_data_diversa_ma_stessa_rosa_e_stesso_nome(self):
        calo = self._in_rosa(self.ts, full_name="Giacomo Calò", external_id="301235",
                             date_of_birth=date(1997, 2, 5))
        self.assertEqual(
            _adopt_by_identity("Giacomo Calò", date(1997, 5, 2), self.ts), calo)

    def test_nome_diverso_ma_stessa_rosa_e_stessa_data(self):
        foe = self._in_rosa(self.ts, full_name="Foe Ondoa", external_id="1",
                            date_of_birth=date(2005, 12, 12))
        self.assertEqual(
            _adopt_by_identity("Manga Foe Ondoa", date(2005, 12, 12), self.ts), foe)

    def test_un_altra_rosa_non_conta(self):
        self._in_rosa(self.altra, full_name="Giacomo Calò", external_id="301235",
                      date_of_birth=date(1997, 2, 5))
        self.assertIsNone(
            _adopt_by_identity("Giacomo Calò", date(1997, 5, 2), self.ts))

    def test_due_omonimi_nella_stessa_rosa_non_si_adotta_nessuno(self):
        # Fondere due persone e' irreversibile; un doppione si fonde dopo.
        self._in_rosa(self.ts, full_name="Giacomo Calò", external_id="1",
                      date_of_birth=date(1997, 2, 5))
        self._in_rosa(self.ts, full_name="Giacomo Calò", external_id="2",
                      date_of_birth=date(1999, 1, 3))
        self.assertIsNone(
            _adopt_by_identity("Giacomo Calò", date(1997, 5, 2), self.ts))

    def test_il_primo_gennaio_non_identifica(self):
        # Il segnaposto di SofaScore: farebbe combaciare fra loro tutti quelli di
        # cui non si sa la data.
        self._in_rosa(self.ts, full_name="Tizio Uno", external_id="1",
                      date_of_birth=date(2005, 1, 1))
        self.assertIsNone(
            _adopt_by_identity("Caio Due", date(2005, 1, 1), self.ts))

    def test_chi_ha_gia_un_id_sofascore_vero_non_e_adottabile(self):
        p = self._in_rosa(self.ts, full_name="Giacomo Calò", external_id="301235",
                          date_of_birth=date(1997, 2, 5))
        PlayerAlias.objects.create(player=p, source="sofascore", alias="111111")
        self.assertIsNone(
            _adopt_by_identity("Giacomo Calò", date(1997, 5, 2), self.ts))

    def test_l_alias_sintetico_non_blocca_l_adozione(self):
        # E' la regola che in produzione ha coniato i doppioni.
        p = self._in_rosa(self.ts, full_name="Giacomo Calò", external_id="301235",
                          date_of_birth=date(1997, 2, 5))
        PlayerAlias.objects.create(player=p, source="sofascore",
                                   alias=synthetic_sofascore_id(p.id))
        self.assertEqual(
            _adopt_by_identity("Giacomo Calò", date(1997, 5, 2), self.ts), p)

    def test_l_import_aggancia_invece_di_coniare(self):
        calo = self._in_rosa(self.ts, full_name="Giacomo Calò", external_id="301235",
                             date_of_birth=date(1997, 2, 5))
        prima = Player.objects.count()
        got = _player("839487", "Giacomo Calò", "G. Calò", {},
                      dob_ts=862531200, team_season=self.ts)
        self.assertEqual(got, calo)
        self.assertEqual(Player.objects.count(), prima)
        self.assertTrue(PlayerAlias.objects.filter(
            player=calo, source="sofascore", alias="839487").exists())

    def test_senza_squadra_resta_la_regola_stretta(self):
        self._in_rosa(self.ts, full_name="Giacomo Calò", external_id="301235",
                      date_of_birth=date(1997, 2, 5))
        self.assertIsNone(_adopt_by_identity("Giacomo Calò", date(1997, 5, 2)))


class FusioneTests(TestCase):
    def setUp(self):
        comp = Competition.objects.create(name="Serie A", external_source="sofascore",
                                          external_id="23")
        season = Season.objects.create(code="2026-2027")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=season, external_source="sofascore",
            external_id="76457", num_rounds=38)
        team = Team.objects.create(name="Frosinone", external_source="sofascore",
                                   external_id="1")
        self.ts = TeamSeason.objects.create(team=team, competition_season=self.cs)
        self.vincitore = Player.objects.create(
            full_name="Giacomo Calò", external_source="transfermarkt",
            external_id="301235", date_of_birth=date(1997, 2, 5))
        PlayerTeamStint.objects.create(player=self.vincitore, team_season=self.ts,
                                       start_date=date(2026, 7, 1))
        self.perdente = Player.objects.create(
            full_name="Giacomo Calò", short_name="G. Calò",
            external_source="sofascore", external_id="839487",
            date_of_birth=date(1997, 5, 2))
        self.match = Match.objects.create(
            competition_season=self.cs, home_team=self.ts, away_team=self.ts,
            matchday=1, external_source="sofascore", external_id="390")
        MatchAppearance.objects.create(match=self.match, player=self.perdente,
                                       team_season=self.ts, side="home",
                                       minutes_played=90, is_starter=True)

    def test_le_presenze_passano_al_vincitore(self):
        call_command("merge_duplicate_players", "--apply", stdout=io.StringIO())
        self.assertFalse(Player.objects.filter(pk=self.perdente.pk).exists())
        self.assertEqual(
            MatchAppearance.objects.filter(player=self.vincitore).count(), 1)

    def test_l_id_sofascore_diventa_un_alias_del_vincitore(self):
        call_command("merge_duplicate_players", "--apply", stdout=io.StringIO())
        self.assertTrue(PlayerAlias.objects.filter(
            player=self.vincitore, source="sofascore", alias="839487").exists())

    def test_il_nome_breve_del_fornitore_arriva_al_vincitore(self):
        call_command("merge_duplicate_players", "--apply", stdout=io.StringIO())
        self.vincitore.refresh_from_db()
        self.assertEqual(self.vincitore.short_name, "G. Calò")

    def test_senza_apply_non_scrive_niente(self):
        call_command("merge_duplicate_players", stdout=io.StringIO())
        self.assertTrue(Player.objects.filter(pk=self.perdente.pk).exists())

    def test_una_presenza_gia_del_vincitore_non_fa_saltare_la_fusione(self):
        # Stessa partita per entrambe le meta': la chiave (match, player) e' unica,
        # e la copia del perdente e' un doppione senza niente da salvare.
        MatchAppearance.objects.create(match=self.match, player=self.vincitore,
                                       team_season=self.ts, side="home",
                                       minutes_played=0, is_starter=False)
        call_command("merge_duplicate_players", "--apply", stdout=io.StringIO())
        self.assertEqual(
            MatchAppearance.objects.filter(player=self.vincitore).count(), 1)
        self.assertFalse(Player.objects.filter(pk=self.perdente.pk).exists())


class GuardianoTests(TestCase):
    """Il doppione non fallisce in modo rumoroso: qualcuno deve andarlo a cercare."""

    def setUp(self):
        comp = Competition.objects.create(name="Serie A", external_source="sofascore",
                                          external_id="23")
        season = Season.objects.create(code="2026-2027")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=season, external_source="sofascore",
            external_id="76457", num_rounds=38)
        self.ts = TeamSeason.objects.create(
            team=Team.objects.create(name="Frosinone", external_source="sofascore",
                                     external_id="1"),
            competition_season=self.cs)
        self.match = Match.objects.create(
            competition_season=self.cs, home_team=self.ts, away_team=self.ts,
            matchday=1, external_source="sofascore", external_id="390")

    def _spezzato(self, nome_tm, dob_tm, nome_ss, dob_ss):
        tm = Player.objects.create(full_name=nome_tm, external_source="transfermarkt",
                                   external_id="1", date_of_birth=dob_tm)
        PlayerTeamStint.objects.create(player=tm, team_season=self.ts,
                                       start_date=date(2026, 7, 1))
        ss = Player.objects.create(full_name=nome_ss, external_source="sofascore",
                                   external_id="9", date_of_birth=dob_ss)
        MatchAppearance.objects.create(match=self.match, player=ss,
                                       team_season=self.ts, side="home",
                                       minutes_played=90, is_starter=True)
        return tm, ss

    def test_lo_trova_col_nome(self):
        tm, ss = self._spezzato("Giacomo Calò", date(1997, 2, 5),
                                "Giacomo Calò", date(1997, 5, 2))
        [found] = roster_integrity.split_identities()
        self.assertEqual((found.keeper_id, found.stray_id), (tm.id, ss.id))
        self.assertEqual(found.appearances, 1)

    def test_lo_trova_con_la_data(self):
        tm, ss = self._spezzato("Foe Ondoa", date(2005, 12, 12),
                                "Manga Foe Ondoa", date(2005, 12, 12))
        [found] = roster_integrity.split_identities()
        self.assertEqual((found.keeper_id, found.stray_id), (tm.id, ss.id))

    def test_due_persone_diverse_non_sono_una_coppia(self):
        # Filipe Bordon e Ricardo Bordon, Lazio: cognome uguale, nient'altro.
        self._spezzato("Filipe Bordon", date(2005, 6, 24),
                       "Ricardo Bordon", date(2006, 11, 2))
        self.assertEqual(roster_integrity.split_identities(), [])

    def test_un_esordiente_che_non_e_in_nessuna_rosa_non_e_un_doppione(self):
        ss = Player.objects.create(full_name="Ragazzo Sconosciuto",
                                   external_source="sofascore", external_id="9",
                                   date_of_birth=date(2008, 3, 1))
        MatchAppearance.objects.create(match=self.match, player=ss,
                                       team_season=self.ts, side="home",
                                       minutes_played=5, is_starter=False)
        self.assertEqual(roster_integrity.split_identities(), [])

    def test_dopo_la_fusione_non_resta_niente_da_segnalare(self):
        self._spezzato("Giacomo Calò", date(1997, 2, 5),
                       "Giacomo Calò", date(1997, 5, 2))
        call_command("merge_duplicate_players", "--apply", stdout=io.StringIO())
        self.assertEqual(roster_integrity.split_identities(), [])

    def test_il_canarino_lo_riporta(self):
        self._spezzato("Giacomo Calò", date(1997, 2, 5),
                       "Giacomo Calò", date(1997, 5, 2))
        report = health.report(skip_shape=True)
        codes = {c.code: c for c in report.checks}
        self.assertIn("player:split-identity", codes)
        self.assertEqual(codes["player:split-identity"].level, "warn")
