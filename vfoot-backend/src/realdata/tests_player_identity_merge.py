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
from datetime import date, timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

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

    def test_il_cognome_nel_solo_nome_breve_basta_ad_adottare(self):
        # Rahim Alhassane, Bologna: SofaScore manda il campo lungo troncato
        # ('Abdel Rahim') e il cognome sopravvive solo nel nome breve. Il 1
        # gennaio da entrambe le parti spegne anche la prova della data.
        alhassane = self._in_rosa(self.ts, full_name="Rahim Alhassane",
                                  external_id="929899",
                                  date_of_birth=date(2002, 1, 1))
        self.assertEqual(
            _adopt_by_identity("Abdel Rahim", date(2002, 1, 1), self.ts,
                               short_name="A. R. Alhassane"),
            alhassane)

    def test_lo_stesso_cognome_con_un_altro_nome_non_adotta(self):
        # Filipe Bordon e Ricardo Bordon, Lazio: due persone diverse. Il cognome
        # da solo li appaiava; l'iniziale e la data lo impediscono.
        self._in_rosa(self.ts, full_name="Filipe Bordon", external_id="1",
                      date_of_birth=date(2005, 6, 24))
        self.assertIsNone(
            _adopt_by_identity("Ricardo Bordon", date(2006, 11, 2), self.ts,
                               short_name="R. Bordon"))

    def test_col_cognome_la_data_diversa_basta_a_fermare_l_adozione(self):
        # Stessa iniziale: a rifiutare resta solo la data, ed e' abbastanza.
        self._in_rosa(self.ts, full_name="Roberto Bordon", external_id="1",
                      date_of_birth=date(2005, 6, 24))
        self.assertIsNone(
            _adopt_by_identity("Ricardo Bordon", date(2006, 11, 2), self.ts,
                               short_name="R. Bordon"))

    def test_col_cognome_l_iniziale_diversa_basta_a_fermare_l_adozione(self):
        # Due date segnaposto non contraddicono niente: a rifiutare resta solo
        # l'iniziale, ed e' abbastanza.
        self._in_rosa(self.ts, full_name="Filipe Bordon", external_id="1",
                      date_of_birth=date(2005, 1, 1))
        self.assertIsNone(
            _adopt_by_identity("Ricardo Bordon", date(2006, 1, 1), self.ts,
                               short_name="R. Bordon"))

    def test_la_particella_del_cognome_non_e_un_nome_di_battesimo(self):
        # 'De Rossi' contro 'De Rossi': la 'D' della particella regalerebbe
        # un'iniziale in comune a due persone che non ne hanno nessuna.
        self._in_rosa(self.ts, full_name="Daniele De Rossi", external_id="1",
                      date_of_birth=date(1983, 1, 1))
        self.assertIsNone(
            _adopt_by_identity("Marco De Rossi", date(2006, 1, 1), self.ts,
                               short_name="M. De Rossi"))

    def test_due_cognomi_uguali_nella_rosa_non_adottano_nessuno(self):
        self._in_rosa(self.ts, full_name="Rahim Alhassane", external_id="1",
                      date_of_birth=date(2002, 1, 1))
        self._in_rosa(self.ts, full_name="Rachid Alhassane", external_id="2",
                      date_of_birth=date(2004, 1, 1))
        self.assertIsNone(
            _adopt_by_identity("Abdel Rahim", date(2002, 1, 1), self.ts,
                               short_name="A. R. Alhassane"))

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

    def _spezzato(self, nome_tm, dob_tm, nome_ss, dob_ss, breve_ss=""):
        tm = Player.objects.create(full_name=nome_tm, external_source="transfermarkt",
                                   external_id="1", date_of_birth=dob_tm)
        PlayerTeamStint.objects.create(player=tm, team_season=self.ts,
                                       start_date=date(2026, 7, 1))
        ss = Player.objects.create(full_name=nome_ss, short_name=breve_ss,
                                   external_source="sofascore",
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

    def test_lo_trova_col_cognome_quando_il_nome_lungo_e_troncato(self):
        # Ne' il nome intero ne' la data reggono: 'Abdel Rahim' contro 'Rahim
        # Alhassane', 1 gennaio da entrambe le parti. Senza la prova del cognome
        # questo giocatore restava spezzato e il canarino taceva.
        tm, ss = self._spezzato("Rahim Alhassane", date(2002, 1, 1),
                                "Abdel Rahim", date(2002, 1, 1),
                                breve_ss="A. R. Alhassane")
        [found] = roster_integrity.split_identities()
        self.assertEqual((found.keeper_id, found.stray_id), (tm.id, ss.id))

    def test_due_persone_diverse_non_sono_una_coppia(self):
        # Filipe Bordon e Ricardo Bordon, Lazio: cognome uguale, nient'altro.
        self._spezzato("Filipe Bordon", date(2005, 6, 24),
                       "Ricardo Bordon", date(2006, 11, 2), breve_ss="R. Bordon")
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
class OrfaniTests(TestCase):
    """Ha giocato, e non e' in nessuna rosa.

    Il guardiano che regge quando l'euristica dell'adozione cade: Alhassane ha
    giocato novanta minuti da titolare col Bologna mentre l'elenco degli spezzati
    era vuoto, e a vederlo e' stato un utente.
    """

    def setUp(self):
        comp = Competition.objects.create(name="Serie A", external_source="sofascore",
                                          external_id="23")
        season = Season.objects.create(code="2026-2027")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=season, external_source="sofascore",
            external_id="76457", num_rounds=38)
        self.ts = TeamSeason.objects.create(
            team=Team.objects.create(name="Bologna", external_source="sofascore",
                                     external_id="1"),
            competition_season=self.cs)
        self.now = timezone.now()

    def _match(self, giorni_fa, ext="390"):
        return Match.objects.create(
            competition_season=self.cs, home_team=self.ts, away_team=self.ts,
            matchday=1, external_source="sofascore", external_id=ext,
            kickoff=self.now - timedelta(days=giorni_fa))

    def _in_rosa(self, **kw):
        p = Player.objects.create(external_source="transfermarkt", **kw)
        PlayerTeamStint.objects.create(player=p, team_season=self.ts,
                                       start_date=date(2026, 7, 1))
        return p

    def _rosa_regolare(self, match, quanti=19):
        """Tesserati che giocano davvero: e' cio' che tiene alta la copertura.

        Senza di loro ogni prova qui dentro descriverebbe un'edizione le cui rose
        non coprono nessuno, e il controllo tacerebbe per il motivo sbagliato.
        """
        for i in range(quanti):
            p = self._in_rosa(full_name=f"Regolare {i}", external_id=f"r{i}")
            MatchAppearance.objects.create(match=match, player=p,
                                           team_season=self.ts, side="home",
                                           minutes_played=90, is_starter=True)

    def _gioca(self, match, *, minuti, titolare, ext="9", nome="Chi E'"):
        p = Player.objects.create(full_name=nome, external_source="sofascore",
                                  external_id=ext)
        MatchAppearance.objects.create(match=match, player=p, team_season=self.ts,
                                       side="home", minutes_played=minuti,
                                       is_starter=titolare)
        return p

    def _orfani(self, giorni=10):
        return roster_integrity.unrostered_players(
            since=self.now - timedelta(days=giorni))

    def test_chi_gioca_senza_rosa_e_un_orfano(self):
        m = self._match(1)
        self._rosa_regolare(m)
        ss = self._gioca(m, minuti=90, titolare=True, nome="Rahim Alhassane")
        [found] = self._orfani()
        self.assertEqual(found.player_id, ss.id)
        self.assertEqual((found.minutes, found.started, found.appearances),
                         (90, True, 1))
        self.assertTrue(found.played)

    def test_chi_e_in_rosa_non_e_un_orfano(self):
        self._rosa_regolare(self._match(1))
        self.assertEqual(self._orfani(), [])

    def test_un_edizione_senza_rose_non_si_guarda(self):
        # In produzione la Serie A 25-26 da' 772 orfani su 772: l'assenza di
        # tesseramenti non dice niente sul giocatore, dice che mancano le rose.
        self._gioca(self._match(1), minuti=90, titolare=True)
        self.assertEqual(self._orfani(), [])

    def test_una_rosa_parziale_non_si_guarda(self):
        # L'errore che questo controllo ha fatto per primo: chiedere che UN
        # tesseramento esista. Nel database di sviluppo la 25-26 ne ha 536 su 772
        # e il controllo tirava dentro Guendouzi con 1430 minuti giocati.
        m = self._match(1)
        self._rosa_regolare(m, quanti=1)
        for i in range(9):
            self._gioca(m, minuti=90, titolare=True, ext=f"9{i}",
                        nome=f"Fuori Rosa {i}")
        self.assertEqual(self._orfani(), [])          # copertura 10%, si tace

    def test_fuori_finestra_si_spegne_da_se(self):
        vecchia = self._match(30)
        self._rosa_regolare(vecchia)
        self._gioca(vecchia, minuti=90, titolare=True)
        self.assertEqual(self._orfani(), [])

    def test_la_panchina_non_alza_il_verdetto(self):
        # Quattordici su sedici, alla misura del 31/08/2026: chi non entra non
        # prende voto, e un giallo da agosto a maggio non lo legge nessuno.
        m = self._match(1)
        self._rosa_regolare(m)
        self._gioca(m, minuti=0, titolare=False, nome="Ragazzo")
        [found] = self._orfani()
        self.assertFalse(found.played)
        codes = {c.code: c for c in health.report(skip_shape=True).checks}
        self.assertEqual(codes["player:unrostered"].level, "info")

    def test_chi_ha_calpestato_il_campo_alza_il_verdetto(self):
        m = self._match(1)
        self._rosa_regolare(m)
        self._gioca(m, minuti=0, titolare=False, ext="9", nome="Ragazzo")
        self._gioca(m, minuti=90, titolare=True, ext="10", nome="Rahim Alhassane")
        codes = {c.code: c for c in health.report(skip_shape=True).checks}
        self.assertEqual(codes["player:unrostered"].level, "warn")
        # La prima riga e' sempre quella che conta.
        self.assertIn("Rahim Alhassane", codes["player:unrostered"].message)

    def test_lo_spezzato_compare_in_tutte_e_due_le_righe(self):
        # La sovrapposizione e' voluta: una volta col rimedio pronto, una volta
        # in mezzo ai suoi simili.
        m = self._match(1)
        self._rosa_regolare(m)
        self._in_rosa(full_name="Giacomo Calò", external_id="calo",
                      date_of_birth=date(1997, 2, 5))
        self._gioca(m, minuti=90, titolare=True, nome="Giacomo Calò")
        codes = {c.code: c for c in health.report(skip_shape=True).checks}
        self.assertIn("player:split-identity", codes)
        self.assertIn("player:unrostered", codes)
