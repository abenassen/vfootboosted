"""L'id di fornitore che ci siamo coniati noi non deve uscire di qui.

Il caso che questi test chiudono e' successo: un ponte
fantacalcio -> Player -> SofaScore che leggeva ``PlayerAlias`` ha agganciato al
76% invece che al 95%, e a picco sulle neopromosse — perche' quelle sono piene di
giocatori arrivati da Transfermarkt, cioe' proprio quelli a cui il simulatore
conia un id. Nessun errore da nessuna parte: un id simulato ha la forma di uno
vero e si aggancia a nulla.
"""
from __future__ import annotations

from django.test import SimpleTestCase, TestCase

from realdata.models import Player, PlayerAlias
from realdata.services.identity import (
    is_synthetic_sofascore_id, synthetic_sofascore_id,
)
from realdata.services.sofascore_adapter import (
    real_sofascore_id, real_sofascore_ids,
)


class SyntheticIdShapeTests(SimpleTestCase):
    def test_conio_e_riconoscimento_sono_la_stessa_cosa(self):
        # L'invariante che per un anno non e' stata scritta da nessuna parte.
        for pid in (1, 42, 1614, 99_999_999):
            self.assertTrue(is_synthetic_sofascore_id(synthetic_sofascore_id(pid)))

    def test_gli_id_veri_di_sofascore_passano(self):
        # Maignan, Bella-Kotchap, Fini: 6 e 7 cifre, misurati sull'API.
        for real in ("191210", "976025", "1164381", 798002):
            self.assertFalse(is_synthetic_sofascore_id(real))

    def test_niente_di_ambiguo(self):
        for x in (None, "", "  ", "abc", "9000016141", "90000161"):
            self.assertFalse(is_synthetic_sofascore_id(x))


class RealSofascoreIdsTests(TestCase):
    def setUp(self):
        self.vero = Player.objects.create(
            full_name="Mike Maignan", external_source="sofascore",
            external_id="191210")
        self.da_tm = Player.objects.create(
            full_name="Filip Stankovic", external_source="transfermarkt",
            external_id="552223")
        self.riconosciuto = Player.objects.create(
            full_name="Toma Basic", external_source="transfermarkt",
            external_id="500000")
        PlayerAlias.objects.create(player=self.da_tm, source="sofascore",
                                   alias=synthetic_sofascore_id(self.da_tm.id))
        PlayerAlias.objects.create(player=self.riconosciuto, source="sofascore",
                                   alias="798002")

    def test_id_proprio(self):
        self.assertEqual(real_sofascore_id(self.vero), "191210")

    def test_alias_vero(self):
        self.assertEqual(real_sofascore_id(self.riconosciuto), "798002")

    def test_alias_simulato_non_esce(self):
        # Il cuore della cosa: c'e' una riga in PlayerAlias, e cionondimeno la
        # risposta onesta e' "non ne abbiamo uno".
        self.assertIsNone(real_sofascore_id(self.da_tm))

    def test_in_blocco(self):
        got = real_sofascore_ids([self.vero.id, self.da_tm.id, self.riconosciuto.id])
        self.assertEqual(got, {self.vero.id: "191210",
                               self.riconosciuto.id: "798002"})

    def test_lo_proprio_id_vince_sullalias(self):
        # Un giocatore importato da SofaScore che porta anche un alias diverso:
        # l'id con cui e' stato importato e' quello buono.
        PlayerAlias.objects.create(player=self.vero, source="sofascore",
                                   alias="111111")
        self.assertEqual(real_sofascore_id(self.vero), "191210")
