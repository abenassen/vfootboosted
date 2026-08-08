"""L'IMPIEGO: quanto ci si può aspettare di vedere un giocatore in campo.

È l'etichetta che un fantallenatore legge per decidere se schierare qualcuno, e
la sua unica virtù è essere aggiornata: guarda le ultime giornate e non la
stagione (v. player_profiles.MINUTES_WINDOW). Questi test tengono ferme le due
cose che quel cambio ha reso possibili — un titolare che si ferma smette di
leggersi «titolare abituale», e un rincalzo che comincia a giocare lo diventa —
più il caso che la prima versione sbagliava: chi non gioca da sei giornate.
"""
from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from realdata.models import (
    Competition, CompetitionSeason, Match, MatchAppearance, Player, Season, Team, TeamSeason,
)
from vfoot.services.player_profiles import MINUTES_WINDOW, minutes_label, player_minutes


class MinutesLabelRuleTests(TestCase):
    """La regola, presa da sola."""

    def test_serve_esserci_e_restarci(self):
        """Le due misure insieme, perché ognuna da sola inganna."""
        # C'è sempre ma entra al 90°: non è un titolare.
        self.assertEqual(minutes_label(8.0, 6, 6), "low")
        # Ha giocato una partita intera e poi più niente: nemmeno.
        self.assertEqual(minutes_label(90.0, 1, 6), "low")
        # Sempre in campo e per quasi tutta la partita: lo è.
        self.assertEqual(minutes_label(85.0, 6, 6), "high")

    def test_chi_non_gioca_piu_e_poco_impiegato_non_uno_sconosciuto(self):
        """Il caso che la prima versione sbagliava.

        Zero presenze nella finestra non è mancanza di informazione se il
        giocatore in stagione ha giocato: è l'infortunato, ed è proprio quello che
        non si vuole schierare. Restava senza etichetta, che a schermo si legge
        come «nessun problema».
        """
        self.assertEqual(minutes_label(0.0, 0, 6, has_history=True), "low")
        self.assertEqual(minutes_label(0.0, 0, 6, has_history=False), "unknown")

    def test_senza_campionato_giocato_non_si_giudica(self):
        """A campionato fermo tacere è l'unica risposta onesta."""
        self.assertEqual(minutes_label(0.0, 0, 0), "unknown")
        self.assertEqual(minutes_label(90.0, 3, 0), "unknown")


class MinutesWindowTests(TestCase):
    """La finestra, sui dati veri: chi cambia abitudini cambia etichetta."""

    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        self.home = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(external_id="t1", name="Alfa"))
        self.away = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(external_id="t2", name="Beta"))
        base = timezone.now() - timedelta(days=200)
        self.matches = [
            Match.objects.create(competition_season=self.cs, external_id=f"m{md}", matchday=md,
                                 home_team=self.home, away_team=self.away,
                                 kickoff=base + timedelta(days=7 * md),
                                 status=Match.STATUS_FINISHED, data_ready=True)
            for md in range(1, 21)
        ]

    def _player(self, name: str) -> Player:
        return Player.objects.create(full_name=name, external_source="sofascore",
                                     external_id=name.lower())

    def _played(self, player: Player, matchdays, minutes: int, starter: bool = True):
        for md in matchdays:
            MatchAppearance.objects.create(
                match=self.matches[md - 1], player=player, side="home",
                team_season=self.home,
                minutes_played=minutes, is_starter=starter)

    def test_il_titolare_che_si_ferma_smette_di_essere_titolare(self):
        """Quattordici partite intere, poi sei giornate fuori: l'etichetta segue
        le ultime, che è tutto il punto del cambio."""
        p = self._player("Fermato")
        self._played(p, range(1, 15), 90)          # fino alla 14ª, poi più niente

        mins = player_minutes([p.id], competition_season_id=self.cs.id)[p.id]
        self.assertEqual(mins["appearances"], 14, "la stagione resta quella che è")
        self.assertEqual(mins["recent_appearances"], 0)
        self.assertEqual(mins["recent_window"], MINUTES_WINDOW)
        self.assertEqual(
            minutes_label(mins["recent_avg_minutes"], mins["recent_appearances"],
                          mins["recent_window"], has_history=mins["appearances"] > 0),
            "low")

    def test_il_rincalzo_che_comincia_a_giocare_lo_diventa(self):
        """Il verso opposto: dieci panchine e poi sei partite intere. Sulla
        stagione resterebbe un rincalzo; sulle ultime giornate è un titolare."""
        p = self._player("Esploso")
        self._played(p, range(1, 11), 5, starter=False)
        self._played(p, range(15, 21), 90)

        mins = player_minutes([p.id], competition_season_id=self.cs.id)[p.id]
        self.assertEqual(mins["recent_appearances"], 6)
        self.assertEqual(mins["recent_avg_minutes"], 90.0)
        self.assertEqual(
            minutes_label(mins["recent_avg_minutes"], mins["recent_appearances"],
                          mins["recent_window"], has_history=True),
            "high")
        # E la media di stagione, che è un'altra domanda, resta bassa.
        self.assertLess(mins["avg_minutes"], 60)

    def test_la_panchina_non_e_una_presenza(self):
        """Convocato sempre, mai entrato: nella finestra vale zero.

        Fuori di qui ``appearances`` conta le convocazioni — è la definizione del
        dato — ma alla domanda «quante volte è sceso in campo» la panchina
        risponde zero, e contarla produceva la frase impossibile «in campo 6
        volte, 0′ di media».
        """
        p = self._player("Panchinaro")
        self._played(p, range(15, 21), 0, starter=False)

        mins = player_minutes([p.id], competition_season_id=self.cs.id)[p.id]
        self.assertEqual(mins["appearances"], 6, "convocato sei volte, questo resta")
        self.assertEqual(mins["recent_appearances"], 0, "ma in campo mai")
        self.assertEqual(
            minutes_label(mins["recent_avg_minutes"], mins["recent_appearances"],
                          mins["recent_window"], has_history=True),
            "low")

    def test_la_finestra_non_guarda_oltre_la_giornata_richiesta(self):
        """Con ``as_of_matchday`` si sta decidendo una formazione: quello che è
        successo dopo non esiste ancora."""
        p = self._player("Costante")
        self._played(p, range(1, 21), 90)

        mins = player_minutes([p.id], as_of_matchday=10,
                              competition_season_id=self.cs.id)[p.id]
        self.assertEqual(mins["appearances"], 9, "le giornate 1-9, non venti")
        self.assertEqual(mins["recent_appearances"], MINUTES_WINDOW)
        self.assertEqual(mins["recent_window"], MINUTES_WINDOW)
