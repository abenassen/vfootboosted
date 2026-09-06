#!/usr/bin/env python
"""STADIO F: gli ERRORI GRAVI (|noi - Statistico| >= 1.5), non la correlazione.

    cd vfoot-backend/src
    ../.venv/bin/python manage.py shell < ../../experiments-scrape-whoscored/creazione_coda.py

PERCHE'. Lo stadio E ha detto che fra 0.005 e 0.040 la correlazione collo Statistico
e' piatta: il bersaglio non sa dire dove mettere i due pesi. Ma la Pearson e' una
misura di ORDINAMENTO su diecimila righe, e per costruzione non vede la coda —
spostare venti presenze di un punto e mezzo la muove di millesimi. L'errore grave e'
proprio quello che l'utente vede, ed e' gia' il criterio con cui questo progetto
giudica gli eventi rari (v. tests_rare_events e la memoria sul rosso).

DUE PARTI, e la prima e' quella che risponde alla domanda:

  1. LA SPAZZOLATA A PESI FERMI. Si muovono solo i due, tutto il resto sta dov'e'.
     Nessuna ri-ottimizzazione, quindi la differenza fra due righe e' attribuibile
     al peso e a nient'altro. E' la curva "errori gravi contro peso".
  2. I CINQUE MODELLI gia' trovati (spedito, i due bracci dello stadio C, i quattro
     semi dello stadio E), confrontati A COPPIE: quante presenze diventano gravi e
     quante smettono di esserlo. Un conteggio netto di -3 su 5000 e' rumore; sapere
     che 18 sono uscite e 15 entrate lo dice, un totale no.

LA SCALA CONTA, ed e' il pezzo che si puo' sbagliare in silenzio. Un conteggio di
code non ha senso sul voto grezzo del banco, che non e' sulla scala delle pagelle:
va applicato lo stadio finale (saturazione + media/dispersione di ruolo). Le
costanti di quello stadio si RIFANNO per ogni modello — cambiare un peso muove sia
il baricentro sia la dispersione — e si tarano SULLA META' DISPARI, poi si applicano
alla meta' pari. Tararle su tutto e poi contare su tutto sarebbe misurare la coda
di una scala cucita addosso a quella stessa coda.

E SI CONTA SUL VOTO ARROTONDATO, quello che sta accanto al nome: la griglia dei
mezzi punti fa parte del voto, non del rumore.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

import vfoot.services.classic_rating as cr
from vfoot.services import vote_tuning as vt

QUI = Path("/home/andrea/Nextcloud/vfootboosted/experiments-scrape-whoscored")
DATI = QUI / "dati_modello"
RUOLI = ("DIF", "CEN", "ATT")
STAGIONE = 2
SOGLIA = 1.5
T_SAT = cr.VOTE_SATURATION_T


def prepara():
    t0 = time.time()
    b = vt.Bench(STAGIONE, verbose=True)
    b._popola_valutate()
    b.carica_calibrazione(verbose=True)
    b.ber_key = b.cal_key; b.ber_role = b.cal_role; b.ber_z = b.cal_z
    b.ber_min = b.cal_min; b.ber_extra = b.cal_extra; b.ber_idx = b.cal_idx
    vt.carica_giudici(b, str(QUI / "join_2526.json"))
    vt.carica_residui_esterni(b, str(QUI / "join_2526.json"), "Statistico")
    print("banco pronto in %.0f s" % (time.time() - t0))
    return b


def main():
    b = prepara()
    d = json.loads((QUI / "join_2526.json").read_text())
    gd_of = dict(cr.Match.objects.filter(competition_season_id=STAGIONE)
                 .values_list("id", "matchday"))
    lunghi = np.array([m >= 60 for m in b.cal_min])
    gd = np.array([gd_of.get(k[0]) or 0 for k in b.cal_key])
    disp = (gd % 2) == 1

    st = np.full(len(b.cal_key), np.nan)
    for i, k in enumerate(b.cal_key):
        v = ((d["ext"] or {}).get(f"{gd_of.get(k[0])}:{k[1]}") or {}).get("Statistico")
        if v is not None and lunghi[i]:
            st[i] = v
    ha = ~np.isnan(st)
    tara = ha & disp
    prova = ha & ~disp
    ruo = b.cal_role
    print("   Statistico: %d presenze (tara %d, prova %d)"
          % (ha.sum(), tara.sum(), prova.sum()))

    mids = list(cr.Match.objects.filter(competition_season_id=STAGIONE)
                .values_list("id", flat=True))
    tot = cr._per_match_player_totals(mids)
    bcc_v = np.array([(tot.get(k) or {}).get("big_chance_created", 0.0) or 0.0
                      for k in b.cal_key])

    n = len(b.keys)
    ruolo_i = [b.idx_of[k] for k in vt.CHIAVI_RUOLO if k in b.idx_of]

    def da_vettore(theta):
        W = {r: np.array(theta[:n], dtype=float) for r in RUOLI}
        p = n
        for i in ruolo_i:
            for j, r in enumerate(RUOLI):
                W[r][i] = theta[p + j]
            p += 3
        return W

    sat = lambda x: T_SAT * np.log1p(x / T_SAT) if x > 0 else x

    def voti_finali(W):
        """Il voto sulla scala delle pagelle: stadio finale TARATO SULLA META' DISPARI."""
        arr = vt.contesto(b, W)["arr"]
        out = np.full(len(arr), np.nan)
        for r in RUOLI:
            mr = ruo == r
            mt = mr & tara
            if mt.sum() < 30:
                continue
            centro = float(arr[mt].mean())
            comp_t = centro + np.array([sat(x) for x in (arr[mt] - centro)])
            mu, sd = float(comp_t.mean()), float(comp_t.std())
            c, s = float(st[mt].mean()), float(st[mt].std())
            comp = centro + np.array([sat(x) for x in (arr[mr] - centro)])
            out[mr] = c + (comp - mu) * (s / max(sd, 1e-9))
        return out

    def misure(v, sel):
        """Coda, errore e accordo su un sottoinsieme, sul voto ARROTONDATO."""
        m = sel & ~np.isnan(v)
        x = np.array([cr._round_half(t) for t in v[m]])
        e = st[m]
        dd = x - e
        return {"n": int(m.sum()),
                "gravi": int((np.abs(dd) >= SOGLIA).sum()),
                "gravi_su": int((dd >= SOGLIA).sum()),
                "gravi_giu": int((dd <= -SOGLIA).sum()),
                "oltre1": int((np.abs(dd) >= 1.0).sum()),
                "oltre2": int((np.abs(dd) >= 2.0).sum()),
                "mae": float(np.abs(dd).mean()),
                "r": float(np.corrcoef(x, e)[0, 1]),
                "chi": np.nonzero(m)[0][np.abs(dd) >= SOGLIA]}

    W0 = {r: b.vettore_pesi(r) for r in RUOLI}
    th0 = np.array(list(W0["DIF"]) + [W0[r][i] for i in ruolo_i for r in RUOLI])

    def con(**kw):
        t = th0.copy()
        for k, v in kw.items():
            t[b.idx_of[k]] = v
        return t

    # ------------------------------------------------ 1. la spazzolata a pesi fermi
    print("\n" + "=" * 100)
    print("1. ERRORI GRAVI (|noi - Statistico| >= %.1f), muovendo SOLO i due pesi\n" % SOGLIA)
    print("%-28s | %s | %s" % ("", "  META' PARI (mai vista)", "     TUTTE"))
    print("%-28s | %5s %5s %5s %6s %7s | %5s %5s %6s %7s" % (
        "modello", "gravi", "su", "giu", "MAE", "r", "gravi", ">=2", "MAE", "r"))

    def riga(nome, theta, tieni=None):
        v = voti_finali(da_vettore(theta))
        a = misure(v, prova); t = misure(v, ha)
        print("%-28s | %5d %5d %5d %6.4f %7.5f | %5d %5d %6.4f %7.5f" % (
            nome, a["gravi"], a["gravi_su"], a["gravi_giu"], a["mae"], a["r"],
            t["gravi"], t["oltre2"], t["mae"], t["r"]))
        if tieni is not None:
            tieni[nome] = (v, a, t)
        return v, a, t

    base = {}
    riga("SPEDITO (0 / 0)", th0, base)
    print("   -- solo big_chance_created --")
    for x in (0.010, 0.015, 0.020, 0.030, 0.040, 0.060):
        riga("bcc %.3f" % x, con(big_chance_created=x))
    print("   -- solo key_passes --")
    for x in (0.010, 0.015, 0.020, 0.030, 0.040, 0.060):
        riga("kp  %.3f" % x, con(key_passes=x))
    print("   -- tutti e due --")
    for x in (0.010, 0.015, 0.020, 0.030, 0.040):
        riga("bcc=kp %.3f" % x, con(big_chance_created=x, key_passes=x), base)

    # ------------------------------------------------ 2. i modelli gia' trovati
    print("\n" + "=" * 100)
    print("2. I MODELLI OTTIMIZZATI, e il confronto A COPPIE col modello spedito\n")
    modelli = {}
    p = DATI / "creazione_fuori_campione.json"
    if p.exists():
        j = json.loads(p.read_text())
        modelli["C: due a zero"] = np.array(j["A"])
        modelli["C: due liberi"] = np.array(j["B"])
    p = DATI / "creazione_semi.json"
    if p.exists():
        for r in json.loads(p.read_text()):
            modelli["E: seme %.3f" % r["seme"]] = np.array(r["theta"])
    print("%-28s | %5s %5s %5s %6s %7s | %5s %5s %6s %7s" % (
        "modello", "gravi", "su", "giu", "MAE", "r", "gravi", ">=2", "MAE", "r"))
    tenuti = {}
    for nome, th in modelli.items():
        if len(th) != len(th0):
            print("   %-25s (vettore di un'altra base: %d invece di %d)"
                  % (nome, len(th), len(th0)))
            continue
        riga(nome, th, tenuti)

    print("\n   CONFRONTO A COPPIE con lo SPEDITO, sulla meta' mai vista")
    print("   (una presenza puo' USCIRE dalla coda o ENTRARCI: il netto da solo mente)")
    v0, a0, _t0 = base["SPEDITO (0 / 0)"]
    g0 = set(a0["chi"].tolist())
    for nome in list(tenuti) + [k for k in base if k != "SPEDITO (0 / 0)"]:
        v, a, _t = (tenuti.get(nome) or base.get(nome))
        g = set(a["chi"].tolist())
        usc, ent = len(g0 - g), len(g - g0)
        # segno-test su chi cambia stato: se il modello non fa differenza, uscite
        # ed entrate sono una moneta equa
        k, N = usc, usc + ent
        pval = float("nan")
        if N:
            from math import comb
            pval = 2 * sum(comb(N, i) for i in range(min(k, N - k) + 1)) / 2 ** N
            pval = min(1.0, pval)
        print("   %-28s uscite %3d  entrate %3d  netto %+4d   p=%.3f"
              % (nome, usc, ent, len(g) - len(g0), pval))

    # ------------------------------------------------ 3. chi sono i gravi
    print("\n" + "=" * 100)
    print("3. GLI ERRORI GRAVI SUI CREATORI (presenze con >=1 occasione nitida creata)\n")
    print("%-28s | %6s %7s %7s" % ("modello", "n", "gravi", "quota"))
    for nome in ["SPEDITO (0 / 0)"] + [k for k in base if k != "SPEDITO (0 / 0)"]:
        v, _a, _t = base[nome]
        sel = ha & (bcc_v >= 1)
        m = misure(v, sel)
        print("%-28s | %6d %7d %6.2f%%" % (nome, m["n"], m["gravi"],
                                           100 * m["gravi"] / max(m["n"], 1)))


main()
