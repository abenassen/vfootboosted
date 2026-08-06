"""I rigori: che somiglino a dei rigori, e che li decida il merito.

Un motore di rigori si puo' sbagliare in due modi opposti e ugualmente brutti:
essere una monetina (e allora il merito non conta) o essere prevedibile (e allora
non sono rigori). Le prove qui sotto fissano i due estremi e la calibratura in
mezzo.
"""
from __future__ import annotations

from django.test import SimpleTestCase

from vfoot.services import penalties as P


def line(pid: int, voto, role="MID", name=None) -> dict:
    return {"player_id": pid, "name": name or f"P{pid}", "lineup_role": role,
            "voto_puro": voto, "fantavoto": voto}


def team(votes: list[float], gk_vote=6.0, base=1) -> list[dict]:
    """Un undici. ``base`` distingue i due schieramenti: senza, casa e trasferta
    condividerebbero i player_id e quindi anche i dadi."""
    xi = [line(base, gk_vote, "GK")]
    xi += [line(base + i + 1, v) for i, v in enumerate(votes)]
    return xi


class ChiTiraTests(SimpleTestCase):
    def test_tirano_i_cinque_col_voto_piu_alto(self):
        xi = team([5.0, 8.0, 6.0, 7.5, 4.5, 7.0, 6.5, 5.5, 6.0, 5.0])
        ordine = [k["voto_puro"] for k in P._kickers(xi)][:5]
        self.assertEqual(ordine, [8.0, 7.5, 7.0, 6.5, 6.0])

    def test_chi_non_ha_preso_il_voto_non_tira(self):
        """Non e' sceso in campo: non puo' tirare un rigore."""
        xi = team([8.0, None, 7.0, None, 6.0, 5.0, 5.0, 5.0, 5.0, 5.0])
        self.assertTrue(all(k["voto_puro"] is not None for k in P._kickers(xi)))

    def test_l_undici_effettivo_comprende_chi_e_entrato(self):
        """L'errore che avevo fatto misurando: il titolare senza voto viene
        rimpiazzato, e il panchinaro entrato il voto ce l'ha. Leggendo la sola
        distinta sembrava che un terzo dei giocatori fosse senza voto."""
        payload = {
            "starters": [line(1, 6.0, "GK"), {**line(2, None), "replaced_by": {"player_id": 3}}],
            "bench": [{**line(3, 7.0), "entered": True}, line(4, 9.0)],
        }
        xi = P.effective_xi(payload)
        self.assertEqual({l["player_id"] for l in xi}, {1, 3},
                         "il sostituito esce, chi e' entrato conta, chi e' rimasto fuori no")

    def test_a_parita_di_voto_l_ordine_e_sempre_lo_stesso(self):
        a = P._kickers([line(9, 7.0), line(3, 7.0), line(5, 7.0)])
        b = P._kickers([line(5, 7.0), line(9, 7.0), line(3, 7.0)])
        self.assertEqual([k["player_id"] for k in a], [k["player_id"] for k in b])


class QuantoValeUnRigoreTests(SimpleTestCase):
    def test_a_parita_di_voti_vale_la_conversione_reale(self):
        self.assertAlmostEqual(P.conversion(6.0, 6.0), 0.75)

    def test_il_merito_sposta_nella_direzione_giusta(self):
        self.assertGreater(P.conversion(8.0, 6.0), P.conversion(6.0, 6.0))
        self.assertLess(P.conversion(6.0, 8.0), P.conversion(6.0, 6.0))

    def test_nessuno_e_mai_certo_di_segnare_o_di_sbagliare(self):
        """Il senso dei rigori: anche il fenomeno contro il portiere in giornata
        no puo' sbagliare, e viceversa."""
        self.assertLessEqual(P.conversion(10.0, 0.0), P.CEILING)
        self.assertGreaterEqual(P.conversion(0.0, 10.0), P.FLOOR)
        self.assertGreater(P.FLOOR, 0.0)
        self.assertLess(P.CEILING, 1.0)

    def test_il_portiere_senza_voto_e_neutro_non_disastroso(self):
        """Capita al 3,5% delle squadre. Trattarlo come uno zero regalerebbe la
        serie all'avversario per un dato che manca."""
        senza_portiere = [line(2, 6.0)]
        self.assertEqual(P._keeper_vote(senza_portiere), P.NEUTRAL_VOTE)


class LaSerieTests(SimpleTestCase):
    def _dice(self, values: dict[int, int]) -> dict:
        """Dadi truccati: la cifra che voglio, per provare gli estremi.

        La prima cifra viene dai metri (decimo di metro), la seconda dai tocchi:
        (v/10, v) mette la stessa cifra in entrambe, quindi 0 -> 0.00 e 9 -> 0.99.
        """
        return {pid: (v / 10.0, v) for pid, v in values.items()}

    def test_e_deterministica(self):
        """Il requisito non negoziabile: la stessa sfida deve dare lo stesso
        risultato domani, o la coppa cambierebbe vincitore a ogni ricalcolo."""
        casa, fuori = team([7.0] * 10, base=1), team([6.0] * 10, base=100)
        uno = P.shootout(casa, fuori)
        due = P.shootout(casa, fuori)
        self.assertEqual(uno, due)

    def test_finisce_nei_cinque_quando_una_delle_due_sbaglia(self):
        """Cinque tiri per parte, e non uno di piu', se a meta' serie il conto
        non e' in parita'."""
        casa = team([7.0] * 10, base=1)
        fuori = team([7.0] * 10, base=100)
        # Chi gioca in casa segna sempre (dado 0), chi e' fuori sbaglia sempre (9).
        dadi = {**{p: 0 for p in range(1, 20)}, **{p: 9 for p in range(100, 120)}}
        r = P.shootout(casa, fuori, self._dice(dadi))
        self.assertEqual((r["home_goals"], r["away_goals"]), (5, 0))
        self.assertEqual(r["winner"], "home")
        self.assertLessEqual(len(r["home"]), 5)

    def test_va_a_oltranza_e_prima_o_poi_finisce(self):
        """Con due squadre identiche i primi cinque tiri pareggiano: si continua,
        ma non all'infinito."""
        r = P.shootout(team([6.0] * 10, base=1), team([6.0] * 10, base=1))
        self.assertLessEqual(len(r["home"]), P.MAX_ROUNDS)
        self.assertEqual(len(r["home"]), len(r["away"]),
                         "l'oltranza si decide a parita' di tiri battuti, non a meta' turno")

    def test_una_serie_ancora_pari_lascia_decidere_al_criterio_dopo(self):
        """Il motore non inventa un vincitore: dice che non c'e', e la catena
        scende al fattore campo."""
        r = P.shootout(team([6.0] * 10, base=1), team([6.0] * 10, base=1))
        if r["home_goals"] == r["away_goals"]:
            self.assertIsNone(r["winner"])
        else:
            self.assertIsNotNone(r["winner"])

    def test_il_tabellino_dice_perche_ogni_tiro_e_andato_come_e_andato(self):
        r = P.shootout(team([7.0] * 10, base=1), team([6.0] * 10, base=100))
        tiro = r["home"][0]
        self.assertEqual(set(tiro), {"player_id", "name", "voto_puro", "p", "roll", "scored"})
        self.assertEqual(tiro["scored"], tiro["roll"] < tiro["p"])

    def test_il_dado_a_due_cifre_non_falsa_la_conversione(self):
        """Con una cifra sola il dado ha dieci facce, e dieci facce trasformano
        una probabilita' di 0,75 in una conversione dell'80%: misurato, non
        temuto. Due cifre riportano l'errore all'1%."""
        conv = P.conversion(6.0, 6.0)
        segnati = sum(1 for d in range(100) if (d / 100.0) < conv)
        self.assertEqual(segnati, 75)
