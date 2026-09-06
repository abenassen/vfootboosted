#!/usr/bin/env python
"""STADIO D: la RICERCA DEL PROGETTO, con i due pesi liberati.

    cd vfoot-backend/src
    ../.venv/bin/python manage.py shell < ../../experiments-scrape-whoscored/creazione_ricerca_vera.py

Gli stadi A-C usavano un ottimizzatore MIO (salita del gradiente sulla correlazione
collo Statistico). Rispondevano a «c'e' segnale li' dentro?», non a «il vostro
ottimizzatore, potendo, ce li metterebbe?». Questo usa la macchina vera:
``vt.margini`` + ``vt.passo`` + ``vt.obiettivo``, i vincoli di
``vfoot/data/vote_constraints.py``, i bersagli di campo della 26-27.

LA PROVA DI RIPRODUZIONE viene prima di tutto. Se la ricerca, partendo dai pesi
SPEDITI e coi due inchiodati a zero, se ne va da qualche altra parte, allora non e'
la ricerca che ha prodotto quei pesi e il confronto non vale niente. Si stampa
quanto si muove: e' il controllo dell'esperimento, non un dettaglio.

--- UNA COSA TROVATA STRADA FACENDO, e va detta prima dei numeri ----------------
``vote_constraints.INVARIANTI`` e ``tests_rare_events.ATTESI`` sono LE STESSE
CINQUE DECISIONI su due scale diverse — il test misura DOPO lo stadio finale
(x~1.60), i vincoli PRIMA — e non dicono la stessa cosa:

    evento                  INVARIANTI   ATTESI/1.60   modello spedito
    salvataggio sulla linea    +0.300       +0.131         +0.131
    rigore conquistato         +0.510       +0.877         +0.877
    rigore concesso            -0.455       -0.999         -0.999
    errore -> gol              -0.596       -0.530         -0.530
    errore -> tiro             -0.170       -0.089         -0.089

Il modello spedito soddisfa ATTESI (il test e' verde) e VIOLA INVARIANTI tutti e
cinque. La spiegazione sta nella docstring del test: il 03/09/2026 quei cinque
numeri sono stati RISOLTI contro il giudice invece che decisi a priori, e il file
dei vincoli non e' stato aggiornato con loro. Chi rilanciasse la ricerca oggi
verrebbe tirato via dalla taratura spedita da un vincolo scaduto. Qui si usano i
valori del TEST, riportati sulla scala pre-stadio, perche' sono quelli che il
modello in produzione rispetta.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

import vfoot.services.classic_rating as cr
from vfoot.services import vote_tuning as vt
from vfoot.data import vote_constraints as vc
from vfoot.tests_rare_events import ATTESI, TOLLERANZA, _fattore_stadio

QUI = Path("/home/andrea/Nextcloud/vfootboosted/experiments-scrape-whoscored")
RUOLI = ("DIF", "CEN", "ATT")
STAGIONE = 2
LIBERI = ("key_passes", "big_chance_created")
SEME = 0.015
GIRI = 18


def prepara():
    t0 = time.time()
    b = vt.Bench(STAGIONE, verbose=True)
    b._popola_valutate()
    b.carica_calibrazione(verbose=True)
    b.carica_bersagli_da_file(str(QUI / "dati_modello" / "ber_2627.json"), verbose=True)
    vt.carica_giudici(b, str(QUI / "join_2526.json"))
    vt.carica_residui_esterni(b, str(QUI / "join_2526.json"), "Statistico")
    vt.carica_bande(b, str(QUI / "bande_2526.json"),
                    str(QUI / "dati_modello" / "bande_2627.json"))
    print("banco pronto in %.0f s" % (time.time() - t0))
    return b


def costruisci_vincoli(b, ctx0):
    """I vincoli del progetto, con gli invarianti riportati sulla scala giusta."""
    f = _fattore_stadio()
    v = []
    for nome, sotto, sopra, marg in vc.ORDINI:
        v.append(vt.Ordine(nome, b.aggancia(*sotto), b.aggancia(*sopra), marg))
    for nome, gd, fr, verso, val, marg in vc.SOGLIE:
        v.append(vt.Soglia(nome, b.aggancia(fr, gd), verso, val, marg))
    for k, atteso in ATTESI.items():
        v.append(vt.Invariante("1 " + k, "1 " + k, atteso / f, TOLLERANZA / f))
    for nome in ("Statistico", "Redazione", "SofaScore"):
        if nome in ctx0["giudici"]:
            v.append(vt.Giudice("pavimento " + nome, nome, ctx0["giudici"][nome]))
    return v


def stato(b, theta, vincoli, etichetta, theta0=None):
    m, ctx = vt.margini(b, theta, vincoli)
    dentro = int((m >= 0).sum())
    print("   %-22s vincoli dentro %d/%d   Stat %.5f  Red %.5f  Sofa %.5f  MAE %.4f"
          % (etichetta, dentro, len(m), ctx["giudici"].get("Statistico", float("nan")),
             ctx["giudici"].get("Redazione", float("nan")),
             ctx["giudici"].get("SofaScore", float("nan")),
             vt.errore_medio(b, ctx["arr"]).get("Statistico", float("nan"))))
    fuori = [(v.nome, s) for v, s in zip(vincoli, m) if s < 0]
    if fuori:
        print("      fuori: " + ", ".join("%s %.3f" % x for x in fuori[:8])
              + (" ..." if len(fuori) > 8 else ""))
    return m, ctx


def cerca(b, theta0_pin, theta_start, vincoli, base, etichetta):
    """Il ciclo del progetto: jacobiano dei margini, passo piu' corto, proiezione."""
    th = theta_start.copy()
    scala = np.where(np.abs(theta_start) > 1e-9, np.abs(theta_start), 1e-2)
    mobili = np.abs(theta0_pin) > 1e-12
    L, _ctx = vt.obiettivo(b, th, vincoli, theta_start, base)
    print("   %s partenza L = %.5f" % (etichetta, L))
    raggio = 0.25
    for giro in range(GIRI):
        m, _ = vt.margini(b, th, vincoli)
        J = np.zeros((len(m), len(th)))
        for j in np.nonzero(mobili)[0]:
            h = max(abs(th[j]), 1e-3) * 0.05
            su = th.copy(); su[j] += h
            giu = th.copy(); giu[j] -= h
            J[:, j] = (vt.margini(b, su, vincoli)[0]
                       - vt.margini(b, giu, vincoli)[0]) / (2 * h)
        d = vt.passo(J, m, scala, dentro=0.01, raggio=raggio)
        avanti = False
        for alfa in (1.0, 0.5, 0.25, 0.125):
            cand = vt.proietta(b, th + alfa * d, theta0_pin)
            Lc, _ = vt.obiettivo(b, cand, vincoli, theta_start, base)
            if Lc < L:
                th, L, avanti = cand, Lc, True
                break
        if not avanti:
            raggio /= 2
            if raggio < 0.01:
                break
        if (giro + 1) % 3 == 0:
            print("   %s giro %2d  L = %.5f" % (etichetta, giro + 1, L))
    return th, L


def main():
    b = prepara()
    W0 = {r: b.vettore_pesi(r) for r in RUOLI}
    th0 = vt.parametri(b, W0)
    print("theta: %d parametri (%d pesi + %d per-ruolo + 4 banda)"
          % (len(th0), len(b.keys), 3 * len(vt.CHIAVI_RUOLO)))
    ctx0 = vt.contesto(b, W0)
    vincoli = costruisci_vincoli(b, ctx0)
    print("\nvincoli: %d (%d ordini, %d soglie, %d invarianti, %d pavimenti)" % (
        len(vincoli), len(vc.ORDINI), len(vc.SOGLIE), len(ATTESI),
        len(vincoli) - len(vc.ORDINI) - len(vc.SOGLIE) - len(ATTESI)))
    print("\nCONFRONTO DELLE DUE TABELLE DI INVARIANTI (scala pre-stadio, x%.4f):"
          % _fattore_stadio())
    f = _fattore_stadio()
    vecchi = dict((q.replace("1 ", ""), a) for q, a, _t in vc.INVARIANTI)
    for k, a in ATTESI.items():
        print("   %-22s vincoli %+.3f   test/%0.2f %+.3f   spedito %+.3f"
              % (k, vecchi.get(k, float("nan")), f, a / f,
                 ctx0["cruscotto"].get("1 " + k, float("nan"))))

    base = vt.errore_medio(b, ctx0["arr"])
    print("\nSTATO DI PARTENZA")
    m0, _ = stato(b, th0, vincoli, "SPEDITO", th0)

    # --- BRACCIO A: la prova di riproduzione (i due restano a zero)
    print("\nBRACCIO A — i due inchiodati a zero (PROVA DI RIPRODUZIONE)")
    thA, LA = cerca(b, th0, th0, vincoli, base, "A")
    mA, ctxA = stato(b, thA, vincoli, "arrivo A")
    sp = np.abs(thA - th0) / np.where(np.abs(th0) > 1e-9, np.abs(th0), 1e-2)
    print("   spostamento dai pesi spediti: mediano %.1f%%  massimo %.1f%% (%s)"
          % (100 * np.median(sp), 100 * sp.max(),
             (list(b.keys) + ["ruolo"] * 9 + ["banda"] * 4)[int(sp.argmax())]))

    # --- BRACCIO B: gli stessi vincoli, i due liberi
    th0_B = th0.copy()
    for k in LIBERI:
        th0_B[b.idx_of[k]] = SEME
    print("\nBRACCIO B — key_passes e big_chance_created LIBERI")
    thB, LB = cerca(b, th0_B, th0_B, vincoli, base, "B")
    mB, ctxB = stato(b, thB, vincoli, "arrivo B")

    print("\n" + "=" * 86)
    print("%-10s %8s | %7s %7s %7s | %8s | %s" % (
        "", "L", "Stat.", "Redaz.", "Sofa", "MAE Stat", "vincoli dentro"))
    for et, th, mm in (("SPEDITO", th0, m0), ("A", thA, mA), ("B", thB, mB)):
        _mm, c = vt.margini(b, th, vincoli)
        L, _ = vt.obiettivo(b, th, vincoli, th0, base)
        print("%-10s %8.5f | %7.5f %7.5f %7.5f | %8.4f | %d/%d" % (
            et, L, c["giudici"].get("Statistico", 0), c["giudici"].get("Redazione", 0),
            c["giudici"].get("SofaScore", 0),
            vt.errore_medio(b, c["arr"]).get("Statistico", 0),
            int((_mm >= 0).sum()), len(_mm)))
    print("\ni due pesi che la ricerca ha scelto:  " + "   ".join(
        "%s %.4f" % (k, thB[b.idx_of[k]]) for k in LIBERI))
    K = list(b.keys)
    print("\nCosa e' cambiato fra B e A:")
    d = sorted(((K[j], thA[j], thB[j]) for j in range(len(K))),
               key=lambda x: -abs(x[2] - x[1]))
    for k, a, c in d[:12]:
        print("   %-24s A %+.4f -> B %+.4f   (%+.4f)" % (k, a, c, c - a))
    json.dump({"chiavi": K, "spedito": th0.tolist(), "A": thA.tolist(),
               "B": thB.tolist(), "L": {"A": LA, "B": LB}},
              open(QUI / "dati_modello" / "creazione_ricerca_vera.json", "w"), indent=1)
    print("\nsalvato in dati_modello/creazione_ricerca_vera.json")


main()
