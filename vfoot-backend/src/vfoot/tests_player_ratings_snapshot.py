"""Invarianti del FILE spedito, non del codice che lo legge.

``player_ratings_snapshot.json` viaggia col sorgente: finisce sul portatile di chi
collabora e sul server, e li' vale come listone dove le zone non ci sono. E' un dato
di produzione tenuto in un file di testo, quindi le sue proprieta' vanno controllate
come si controlla un dato di produzione — qui, offline, senza database.

Cosa NON si puo' controllare qui: che i numeri siano quelli giusti. Ricalcolarli
vuole le zone feature, che nel database di test non esistono; per quello c'e'
``manage.py build_player_ratings_snapshot --check`` su una macchina che le ha.
Quello che si controlla e' tutto il resto, ed e' la parte che si e' rotta davvero:
la FORMA delle chiavi e la loro corrispondenza col modello di adesso.
"""
from __future__ import annotations

import json

from django.test import SimpleTestCase

from vfoot.services.player_ratings import SNAPSHOT_FORMAT, SNAPSHOT_PATH
from vfoot.services.vote_reference import scoring_fingerprint


class ShippedSnapshotTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.snapshot = json.loads(SNAPSHOT_PATH.read_text())

    def test_the_file_declares_the_format_the_reader_expects(self):
        self.assertEqual(self.snapshot.get("format"), SNAPSHOT_FORMAT)

    def test_it_was_built_by_the_model_that_is_in_the_repository_now(self):
        """Il 13/08/2026 non lo era: il file portava ``7c6ea371e3784e8a`` e il codice
        calcolava ``854ab017abbc67e5``. Nessuno se ne accorgeva, perche' il lettore si
        limitava a scriverlo nel log — e un log in produzione lo legge chi lo va a
        cercare. Se questo test fallisce: ``manage.py build_player_ratings_snapshot``
        su un database con le zone, e ricommittare il file."""
        self.assertEqual(self.snapshot.get("scoring_fingerprint"),
                         scoring_fingerprint(),
                         "snapshot costruito da un modello diverso da quello nel "
                         "repository: rilancia build_player_ratings_snapshot")

    def test_seasons_are_addressed_by_provider_and_not_by_primary_key(self):
        """La chiave che ha causato il guasto: ``"2"`` e' la 25-26 qui e la 26-27 in
        produzione. ``"sofascore:76457"`` e' la stessa stagione ovunque."""
        for key in self.snapshot["seasons"]:
            source, sep, external_id = key.partition(":")
            self.assertTrue(sep and source and external_id,
                            f"chiave stagione non portabile: {key!r}")
            self.assertFalse(key.isdigit())

    def test_players_are_addressed_by_provider_and_not_by_primary_key(self):
        for key, season in self.snapshot["seasons"].items():
            for player_key in season["ratings"]:
                source, sep, external_id = player_key.partition(":")
                self.assertTrue(sep and source and external_id,
                                f"chiave giocatore non portabile in {key}: "
                                f"{player_key!r}")

    def test_every_season_says_how_many_matches_it_was_built_on(self):
        """E' il numero su cui il lettore rifiuta: senza, non c'e' modo di dire che
        una stagione non giocata qui non e' la stagione descritta li'."""
        for key, season in self.snapshot["seasons"].items():
            played = season["data_version"].split(":")[0]
            self.assertTrue(played.isdigit() and int(played) > 0,
                            f"{key}: data_version senza partite giocate "
                            f"({season['data_version']!r})")

    def test_the_ratings_are_votes_and_appearances(self):
        for key, season in self.snapshot["seasons"].items():
            played = int(season["data_version"].split(":")[0])
            for player_key, value in season["ratings"].items():
                avg, n = value
                self.assertTrue(3.0 <= avg <= 9.5, f"{key}/{player_key}: voto {avg}")
                self.assertTrue(1 <= n <= played,
                                f"{key}/{player_key}: {n} presenze su {played} "
                                f"partite di stagione")
