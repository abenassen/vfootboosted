"""Un giocatore ha un club per volta — e cosa facciamo quando i dati dicono di no.

Il fatto da cui parte tutto: la squadra di un giocatore non e' una colonna, e'
``PlayerTeamStint``, una relazione valida su un intervallo di date. Il modello
puo' quindi scrivere una cosa che nella realta' non esiste, e nessun vincolo di
banca dati lo impedisce (non e' esprimibile: la stagione si raggiunge solo
attraversando ``team_season``).

Qui si fissano le tre decisioni che ne discendono, e soprattutto i loro confini:

* **la presenza batte l'assenza.** Vedere un giocatore nella rosa del Milan
  chiude il suo tesseramento all'Inter ANCHE SE l'Inter non l'abbiamo letta: e'
  una prova positiva e non chiede nessuna garanzia di completezza. L'assenza da
  una rosa, al contrario, e' una prova solo se quella rosa l'abbiamo letta —
  altrimenti e' un artefatto nostro;
* **la guardia sulle partenze e' per club, non globale.** Un timeout su venti
  club non deve costare al giro intero il trattamento delle uscite. Prima
  costava tutto;
* **la sovrapposizione si riferisce, non si corregge.** Se Transfermarkt elenca
  un giocatore in due rose siamo davanti a un errore suo, che di norma ripara da
  solo. Indovinare quale valga sarebbe peggio del problema; un vincolo di banca
  dati farebbe saltare l'intera importazione dentro la sua unica transazione.
"""
from __future__ import annotations

from datetime import date

from django.test import TestCase

from realdata.models import (
    Competition, CompetitionSeason, Player, PlayerTeamStint, Season, Team,
    TeamSeason,
)
from realdata.services import roster_integrity


def _season(name="Serie A 2026-2027"):
    comp = Competition.objects.create(name="Serie A")
    seas = Season.objects.create(code="2026-2027")
    return CompetitionSeason.objects.create(competition=comp, season=seas,
                                            name=name)


def _team(cs, name):
    return TeamSeason.objects.create(competition_season=cs,
                                     team=Team.objects.create(name=name))


class Sovrapposizioni(TestCase):
    """Cosa conta come «due club nello stesso momento» e cosa no."""

    def setUp(self):
        self.cs = _season()
        self.inter = _team(self.cs, "Inter")
        self.milan = _team(self.cs, "Milan")
        self.p = Player.objects.create(full_name="Marco Rossi")

    def _stint(self, ts, start, end=None):
        return PlayerTeamStint.objects.create(player=self.p, team_season=ts,
                                              start_date=start, end_date=end)

    def test_due_tesseramenti_aperti_sono_una_sovrapposizione(self):
        self._stint(self.inter, date(2026, 8, 1))
        self._stint(self.milan, date(2026, 8, 10))
        found = roster_integrity.overlapping_stints(self.cs.id)
        self.assertEqual(len(found), 1)
        self.assertIn("Marco Rossi", found[0].describe())

    def test_il_subentro_dello_stesso_giorno_non_e_una_sovrapposizione(self):
        """L'intervallo e' semiaperto, e non e' un dettaglio.

        L'import chiude il vecchio tesseramento e apre il nuovo con la STESSA
        data. Se il confronto fosse chiuso a destra, ogni singolo trasferimento
        regolare farebbe gridare il controllo — che e' il modo piu' rapido per
        farlo spegnere entro una settimana.
        """
        self._stint(self.inter, date(2026, 8, 1), end=date(2026, 8, 10))
        self._stint(self.milan, date(2026, 8, 10))
        self.assertEqual(roster_integrity.overlapping_stints(self.cs.id), [])

    def test_un_giorno_di_accavallamento_basta(self):
        self._stint(self.inter, date(2026, 8, 1), end=date(2026, 8, 11))
        self._stint(self.milan, date(2026, 8, 10))
        self.assertEqual(len(roster_integrity.overlapping_stints(self.cs.id)), 1)

    def test_le_date_nulle_sono_estremi_aperti(self):
        """``start`` nullo = da sempre, ``end`` nullo = tuttora."""
        self._stint(self.inter, None, None)
        self._stint(self.milan, date(2026, 8, 10))
        self.assertEqual(len(roster_integrity.overlapping_stints(self.cs.id)), 1)

    def test_due_righe_per_lo_stesso_club_non_contano(self):
        """Un rientro dal prestito non e' un doppio tesseramento."""
        self._stint(self.inter, date(2026, 8, 1), end=date(2027, 1, 10))
        self._stint(self.inter, date(2027, 1, 5))
        self.assertEqual(roster_integrity.overlapping_stints(self.cs.id), [])

    def test_stagioni_diverse_non_si_confrontano(self):
        """Il controllo risponde a una domanda sola, dentro una sola edizione."""
        altra = CompetitionSeason.objects.create(
            competition=self.cs.competition,
            season=Season.objects.create(code="2025-2026"), name="Serie A 25-26")
        vecchia = _team(altra, "Inter")
        PlayerTeamStint.objects.create(player=self.p, team_season=vecchia,
                                       start_date=date(2025, 8, 1))
        self._stint(self.milan, date(2026, 8, 10))
        self.assertEqual(roster_integrity.overlapping_stints(self.cs.id), [])

    def test_il_caso_normale_non_trova_niente(self):
        self._stint(self.milan, date(2026, 8, 10))
        self.assertEqual(roster_integrity.overlapping_stints(self.cs.id), [])


class SoloQuelloInCorso(TestCase):
    """``active_on``: i controlli automatici guardano il presente, non l'archivio.

    Il caso e' vero, non inventato. Al 12/08/2026 la produzione conteneva una sola
    sovrapposizione — Benjamín Domínguez fra Bologna e Sassuolo, lunga un giorno e
    gia' chiusa da se': l'artefatto dello scrape parziale dell'11 agosto, cioe'
    proprio il guasto che nel frattempo abbiamo riparato. Un avviso quotidiano su
    un fatto concluso e irreparabile e' la ricetta per farsi ignorare il giorno in
    cui l'avviso e' vero.

    Senza ``active_on`` la funzione risponde su tutta la storia: serve quando la
    domanda e' «e' mai successo?».
    """

    def setUp(self):
        self.cs = _season()
        self.bologna = _team(self.cs, "Bologna")
        self.sassuolo = _team(self.cs, "Sassuolo")
        self.p = Player.objects.create(full_name="Benjamin Dominguez")
        PlayerTeamStint.objects.create(
            player=self.p, team_season=self.bologna,
            start_date=date(2026, 8, 11), end_date=date(2026, 8, 12))
        PlayerTeamStint.objects.create(
            player=self.p, team_season=self.sassuolo,
            start_date=date(2026, 8, 11), end_date=None)

    def test_il_giorno_in_cui_accadeva_la_vede(self):
        found = roster_integrity.overlapping_stints(
            self.cs.id, active_on=date(2026, 8, 11))
        self.assertEqual(len(found), 1)

    def test_il_giorno_dopo_tace(self):
        self.assertEqual(roster_integrity.overlapping_stints(
            self.cs.id, active_on=date(2026, 8, 12)), [])

    def test_senza_data_resta_visibile_a_chi_la_cerca(self):
        self.assertEqual(len(roster_integrity.overlapping_stints(self.cs.id)), 1)
