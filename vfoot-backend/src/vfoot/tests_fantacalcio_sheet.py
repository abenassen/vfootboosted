"""Il foglio dei voti di fantacalcio.it: la riga di squadra si riconosce dalla forma."""
from django.test import SimpleTestCase

from vfoot.management.commands.compare_external_votes import _is_team_row


class TeamRowTests(SimpleTestCase):
    def test_a_promoted_club_not_in_the_list_is_still_a_team_row(self):
        """Monza, Venezia e Frosinone non stavano nell'elenco della 25-26: i loro
        giocatori finivano sotto la squadra precedente del foglio."""
        for name in ("Monza", "Venezia", "Frosinone", "Atalanta", "Hellas Verona"):
            self.assertTrue(_is_team_row((name,) + (None,) * 12), name)

    def test_banner_and_data_rows_are_not_teams(self):
        self.assertFalse(_is_team_row(("Voti Statistici 2ª giornata di campionato",) + (None,) * 12))
        self.assertFalse(_is_team_row(("QUESTO FILE NON PUO' ESSERE RIPRODOTTO NE' PUBBLICATO SU ALTRI SITI INTERNET",) + (None,) * 12))
        self.assertFalse(_is_team_row(("Cod.", "R", "Nome", "Voto") + (None,) * 9))
        self.assertFalse(_is_team_row((2170, "P", "Thiam", 4.5) + (None,) * 9))
        self.assertFalse(_is_team_row((None,) * 13))
