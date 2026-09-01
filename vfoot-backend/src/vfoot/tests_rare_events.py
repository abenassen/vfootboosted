"""Un evento raro vale quello che abbiamo deciso che valga, e non quello che la
sigma decide per lui.

PERCHE' ESISTE QUESTO FILE. Quasi tutti i pesi del modello sono "punti di indice
per 1 sd della feature", ed e' l'unita' giusta per una grandezza che varia con
continuita'. Per un evento che capita nell'1% delle presenze non lo e': la sd e'
un decimo di occorrenza, il numero per sd non si legge, e quei pesi sono stati
tarati a mano su QUANTO VALE UNA OCCORRENZA — in punti di voto.

Solo che il peso vive nell'indice, e il voto divide l'indice per la sigma del
ruolo. Quindi il valore in voti di un evento raro **cambia da solo ogni volta che
si ritara il modello**, senza che nessuno abbia toccato quel peso, e cambia in
silenzio: non c'e' una riga che diventi rossa.

E' successo il 01/09/2026. La ritaratura del voto (creazione, conclusioni, duelli)
ha portato la sigma dei ruoli di movimento da 0.4273 a 0.2811, e ha gonfiato ogni
evento raro di **x1.52**: il pallone tolto dalla linea e' passato da +0.355 a
+0.539 di voto, il rigore concesso da -0.850 a -1.292. Per dare la misura del
disastro silenzioso: un GOL vale fra +0.34 e +0.79 (v. goal_impact), quindi
concedere un rigore era diventato piu' costoso di quanto renda qualunque gol, e
togliere un pallone dalla linea valeva quanto segnare il gol che decide la
partita. Se ne e' accorto un utente guardando il pannello di un giocatore, che e'
il modo peggiore per accorgersene.

Questo test e' il modo giusto. Non verifica un peso — i pesi si possono e si
devono cambiare — verifica l'unica cosa che di quei pesi e' stata DECISA: quanto
vale una occorrenza. Se una ritaratura futura muove la sigma, questo diventa
rosso e chi la sta facendo sa che deve risolvere di nuovo quei numeri (l'ordine
e': taglia, ricalibra, POI risolvi gli eventi rari).
"""
from __future__ import annotations

from django.test import SimpleTestCase

from vfoot.services import classic_rating as cr
from vfoot.services.vote_reference import fixed_reference


# {feature: quanto vale UNA occorrenza, in punti di voto, per un giocatore di
#  movimento}. I valori vengono dalla prova esterna dove c'e' e dalla taratura
#  deliberata precedente dove non c'e':
#    - salvataggio sulla linea +0.30, misurato su 63 presenze della 25-26;
#    - rigore concesso -0.455, cioe' il 76,4% di ``errors_led_to_goal`` — tanti
#      sono i rigori segnati (81 su 106 nella 25-26, xG medio 0.788). Concedere un
#      rigore non e' subire un gol: un quarto delle volte il gol non arriva.
#
#  LA TOLLERANZA E' STRETTA APPOSTA. Un decimo di voto lascia passare mezza
#  deriva: il gonfiaggio del 01/09 era di 0.18 sul salvataggio e questo test,
#  con 0.10 di tolleranza, non se ne sarebbe accorto. Con 0.06 lo prende, e resta
#  abbastanza largo da non diventare rosso per l'ultimo bit di una ricalibrazione.
ATTESI = {
    "clearances_off_line": +0.300,
    "penalties_won": +0.510,
    "penalties_conceded": -0.455,
    "errors_led_to_goal": -0.596,
    "errors_led_to_shot": -0.170,
}
TOLLERANZA = 0.06


def valore_per_occorrenza(key: str, role: str = "DIF") -> float:
    """Quanto sposta il voto UNA occorrenza di questa feature, a 90 minuti.

    Una occorrenza vale ``1 / sigma_raw`` deviazioni della feature; il peso e' per
    una deviazione, quindi l'indice sale di ``peso / sigma_raw``; e il voto e'
    l'indice diviso la sigma del RUOLO, per la scala del voto di quel ruolo.
    """
    scales = cr.feature_scales(gk=False)
    sigma_raw = (scales.get(key) or {}).get("sigma_raw") or 0.0
    if not sigma_raw:
        return 0.0
    std = fixed_reference()[role]["std"]
    return cr.WEIGHTS.get(key, 0.0) / sigma_raw * cr.spread_k_for(role) / std


class RareEventValueTests(SimpleTestCase):
    def test_one_occurrence_is_worth_what_we_decided(self):
        fuori = []
        for key, atteso in ATTESI.items():
            v = valore_per_occorrenza(key)
            if abs(v - atteso) > TOLLERANZA:
                fuori.append(f"{key}: {v:+.3f} invece di {atteso:+.3f}")
        self.assertEqual(fuori, [], "\n".join([
            "Il valore in voti di uno o piu' eventi rari e' andato alla deriva.",
            "Quasi sempre vuol dire che una ritaratura ha mosso la sigma dei ruoli:",
            "i pesi non si toccano da soli, il divisore si'. Vanno RISOLTI di nuovo,",
            "dopo la ricalibrazione, sui valori qui sopra. Vedi la docstring.",
            *fuori,
        ]))

    def test_no_rare_event_outweighs_a_goal(self):
        """Il metro di sanita': un gol vale fra +0.34 e +0.79 di voto.

        Nessun evento raro deve valere piu' del massimo che vale un gol. Non e' una
        finezza: il 01/09/2026 il rigore concesso era arrivato a -1.29, cioe' piu'
        di quanto renda la rete che decide una partita, e nessuno se n'era accorto
        perche' il peso nel sorgente era rimasto quello di sempre."""
        from vfoot.services.goal_impact import fixed_band

        (_lo, hi), _p95 = fixed_band()
        for key in ATTESI:
            v = abs(valore_per_occorrenza(key))
            self.assertLessEqual(
                v, hi + 0.15,
                f"{key} vale {v:.3f} di voto, contro i {hi:.3f} del gol piu' pesante")

    def test_the_scale_is_read_from_the_frozen_calibration(self):
        """Guardia sulla guardia: se ``sigma_raw`` sparisse dalla calibrazione,
        ``valore_per_occorrenza`` tornerebbe 0.0 per tutti e i due test sopra
        passerebbero senza guardare niente — tranne il primo, che a zero vede una
        deriva. Questo lo dice esplicitamente, cosi' il motivo non si perde."""
        scales = cr.feature_scales(gk=False)
        for key in ATTESI:
            self.assertTrue(
                (scales.get(key) or {}).get("sigma_raw"),
                f"{key} non ha una sigma_raw nella calibrazione congelata: "
                "senza, il valore per occorrenza non si puo' calcolare")
