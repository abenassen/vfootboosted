#!/usr/bin/env python
"""STADIO C: il guadagno regge FUORI CAMPIONE e DENTRO I VINCOLI?

    cd vfoot-backend/src
    ../.venv/bin/python manage.py shell < ../../experiments-scrape-whoscored/creazione_fuori_campione.py

Lo stadio B ha detto che liberare key_passes e big_chance_created vale +0.0018 di
correlazione collo Statistico rispetto alla stessa ricerca coi due inchiodati. Due
ragioni per non crederci ancora:

  1. E' IN CAMPIONE. Due parametri liberi in piu' alzano sempre un po' l'accordo
     sulle stesse presenze su cui li si e' tarati. Qui la stagione si taglia a meta'
     per GIORNATA (dispari = si tara, pari = si misura) e il numero che conta e'
     quello sulla meta' mai vista.
  2. ERA SENZA VINCOLI, e infatti il vettore che ne usciva pagava un rigore concesso
     -1.12 contro il -0.455 di taratura: un ottimo che migliora ogni media
     peggiorando il calcio, cioe' esattamente il difetto del 01/09/2026 che il
     cruscotto esiste per intercettare. Qui gli invarianti sono nell'obiettivo.

IL CONFRONTO RESTA CONTROLLATO: due bracci, stesso punto di partenza, stesso
obiettivo, stessi passi, e l'unica differenza e' la maschera dei pesi mobili.

LA REFERENCE NON SI TAGLIA. Media, sigma e curve restano su tutta la stagione,
com'e' in produzione (la calibrazione e' congelata su una stagione chiusa intera):
il taglio serve a chiedere «questi pesi sono tarati sul rumore di QUESTE pagelle?»,
non a simulare una stagione dimezzata.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

import vfoot.services.classic_rating as cr
from vfoot.services import vote_tuning as vt
from vfoot.data.vote_constraints import INVARIANTI

QUI = Path("/home/andrea/Nextcloud/vfootboosted/experiments-scrape-whoscored")
RUOLI = ("DIF", "CEN", "ATT")
STAGIONE = 2
LIBERI = ("key_passes", "big_chance_created")
SEME = 0.015
PASSI = 60


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


def giudici_tutti(b):
    """{nome: (indici, voti)} per i tre giudici esterni, tutti a >=60'."""
    from realdata.services.identity import norm_name
    from vfoot.management.commands.compare_external_votes import Command as Ext, _club_key
    lunghi = {k for k, m in zip(b.cal_key, b.cal_min) if m >= 60}
    G = {}
    d = json.loads((QUI / "join_2526.json").read_text())
    gd_of = dict(cr.Match.objects.filter(competition_season_id=STAGIONE)
                 .values_list("id", "matchday"))
    for nome, foglio in (("Statistico", "Statistico"), ("Redazione", "Fantacalcio")):
        G[nome] = {k: (d["ext"] or {}).get(f"{gd_of.get(k[0])}:{k[1]}", {}).get(foglio)
                   for k in b.cal_key if k in lunghi}
        G[nome] = {k: v for k, v in G[nome].items() if v is not None}
    f = QUI / "ws_2526.jsonl"
    if f.exists():
        ext = Ext(); tm = ext._our_team_index(STAGIONE); pidx = ext._our_player_index(STAGIONE)
        kk = lambda n: " ".join(t for t in _club_key(n).split() if not t.isdigit())
        nostre = {(m.home_team.team.name, m.away_team.team.name): m.id
                  for m in cr.Match.objects.filter(competition_season_id=STAGIONE)
                  .select_related("home_team__team", "away_team__team")}
        W = {}
        for p in (json.loads(l) for l in f.read_text().splitlines() if l.strip()):
            tc = tm.get(kk(p["casa"] or "")); tf = tm.get(kk(p["fuori"] or ""))
            mid = nostre.get((tc, tf)) if tc and tf else None
            if mid is None:
                continue
            for g in p["giocatori"]:
                sq = tc if g["squadra"] == p["casa"] else tf
                c = pidx.get((sq, norm_name(g["nome"]).split()[-1] if g["nome"] else ""), [])
                if len(c) == 1 and (mid, c[0]) in lunghi:
                    W[(mid, c[0])] = float(g["rating"])
        G["WhoScored"] = W
    return G


def main():
    b = prepara()
    G = giudici_tutti(b)
    gd_of = dict(cr.Match.objects.filter(competition_season_id=STAGIONE)
                 .values_list("id", "matchday"))
    gd = np.array([gd_of.get(k[0]) or 0 for k in b.cal_key])
    # LA META' SU CUI SI TARA e quella su cui si misura. Per GIORNATA e non a caso:
    # due presenze della stessa partita si somigliano (stesso risultato, stessa
    # mitigazione), e spezzarle fra le due meta' farebbe filtrare informazione.
    disp = (gd % 2) == 1

    idx = {}
    for nome, d in G.items():
        i = np.array([j for j, k in enumerate(b.cal_key) if k in d])
        e = np.array([d[b.cal_key[j]] for j in i], dtype=float)
        idx[nome] = {"tara": (i[disp[i]], e[disp[i]]), "prova": (i[~disp[i]], e[~disp[i]])}
        print("   %-11s tara %d  prova %d" % (nome, len(idx[nome]["tara"][0]),
                                              len(idx[nome]["prova"][0])))

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

    def theta_da(W):
        th = list(W["DIF"])
        for i in ruolo_i:
            th += [W[r][i] for r in RUOLI]
        return np.array(th, dtype=float)

    def cor(arr, quale, parte):
        i, e = idx[quale][parte]
        return float(np.corrcoef(arr[i], e)[0, 1])

    def penale(ctx):
        """Quanto i vincoli sono violati: invarianti + pavimento sugli altri due."""
        p = 0.0
        for q, atteso, toll in INVARIANTI:
            v = ctx["cruscotto"].get(q)
            if v is None:
                continue
            s = toll - abs(v - atteso)
            if s < 0:
                p += s * s
        return p

    PAVIMENTO = {}

    def obiettivo(theta, completo=False):
        ctx = vt.contesto(b, da_vettore(theta))
        arr = ctx["arr"]
        r = cor(arr, "Statistico", "tara")
        pen = 500.0 * penale(ctx)
        for nome, minimo in PAVIMENTO.items():
            s = cor(arr, nome, "tara") - minimo
            if s < 0:
                pen += 50.0 * s * s
        if completo:
            return r - pen, ctx, arr
        return r - pen

    W0 = {r: b.vettore_pesi(r) for r in RUOLI}
    th0 = theta_da(W0)
    _v, ctx0, arr0 = obiettivo(th0, completo=True)
    # il pavimento: gli altri due giudici non devono scendere sotto il modello spedito
    for nome in ("Redazione", "WhoScored"):
        if nome in idx:
            PAVIMENTO[nome] = cor(arr0, nome, "tara")
    print("\nSPEDITO  tara %.5f  prova %.5f | pen %.5f" % (
        cor(arr0, "Statistico", "tara"), cor(arr0, "Statistico", "prova"), penale(ctx0)))
    print("   cruscotto spedito: " + "  ".join(
        "%s %+.3f" % (q.replace("1 ", ""), ctx0["cruscotto"][q])
        for q, _a, _t in INVARIANTI if q in ctx0["cruscotto"]))

    def cerca(theta0, mobili, etichetta):
        th = theta0.copy(); segno = np.sign(theta0)
        f = obiettivo(th)
        passo = 0.25
        for it in range(PASSI):
            g = np.zeros(len(th))
            for j in np.nonzero(mobili)[0]:
                h = max(abs(th[j]), 1e-3) * 0.05
                su = th.copy(); su[j] += h
                giu = th.copy(); giu[j] -= h
                g[j] = (obiettivo(su) - obiettivo(giu)) / (2 * h)
            nrm = np.linalg.norm(g)
            if nrm < 1e-12:
                break
            taglia = np.where(np.abs(theta0) > 1e-9, np.abs(theta0), 1e-2)
            d = g / nrm * taglia
            avanti = False
            for alfa in (passo, passo / 2, passo / 4, passo / 8, passo / 16):
                c = th + alfa * d
                for j in range(len(c)):
                    if not mobili[j]:
                        c[j] = theta0[j]
                    elif segno[j] > 0:
                        c[j] = max(0.0, c[j])
                    elif segno[j] < 0:
                        c[j] = min(0.0, c[j])
                fc = obiettivo(c)
                if fc > f:
                    th, f, avanti = c, fc, True
                    break
            if not avanti:
                passo /= 2
                if passo < 0.005:
                    break
            if (it + 1) % 10 == 0:
                print("   %s passo %2d  obiettivo %.5f" % (etichetta, it + 1, f))
        return th

    mob_A = np.abs(th0) > 1e-12
    th0_B = th0.copy()
    for k in LIBERI:
        th0_B[b.idx_of[k]] = SEME
    mob_B = np.abs(th0_B) > 1e-12

    ris = {}
    for et, start, mob in (("A", th0, mob_A), ("B", th0_B, mob_B)):
        print("\nBRACCIO %s — %d pesi mobili" % (et, int(mob.sum())))
        t0 = time.time()
        th = cerca(start, mob, et)
        _v, ctx, arr = obiettivo(th, completo=True)
        ris[et] = (th, ctx, arr)
        print("   fatto in %.0f s" % (time.time() - t0))

    print("\n" + "=" * 92)
    print("%-12s %9s %9s | %9s %9s | %9s %9s | %s" % (
        "", "Stat.tara", "Stat.PROVA", "Red.tara", "Red.PROVA",
        "WS.tara", "WS.PROVA", "vincoli"))
    for et, (th, ctx, arr) in [("SPEDITO", (th0, ctx0, arr0))] + list(ris.items()):
        print("%-12s %9.5f %9.5f | %9.5f %9.5f | %9.5f %9.5f | pen %.5f" % (
            et, cor(arr, "Statistico", "tara"), cor(arr, "Statistico", "prova"),
            cor(arr, "Redazione", "tara"), cor(arr, "Redazione", "prova"),
            cor(arr, "WhoScored", "tara"), cor(arr, "WhoScored", "prova"),
            penale(ctx)))
    thA, _cA, arrA = ris["A"]; thB, ctxB, arrB = ris["B"]
    print("\nLIBERARLI VALE, FUORI CAMPIONE: %+.5f collo Statistico  "
          "(%+.5f Redazione, %+.5f WhoScored)" % (
              cor(arrB, "Statistico", "prova") - cor(arrA, "Statistico", "prova"),
              cor(arrB, "Redazione", "prova") - cor(arrA, "Redazione", "prova"),
              cor(arrB, "WhoScored", "prova") - cor(arrA, "WhoScored", "prova")))
    print("\ni due pesi trovati:  " + "  ".join(
        "%s %.4f" % (k, thB[b.idx_of[k]]) for k in LIBERI))
    print("cruscotto B: " + "  ".join(
        "%s %+.3f" % (q.replace("1 ", ""), ctxB["cruscotto"][q])
        for q, _a, _t in INVARIANTI if q in ctxB["cruscotto"]))
    K = list(b.keys)
    print("\nI PESI CHE SI SONO MOSSI DI PIU' (B contro A, cioe' cosa ha pagato i due):")
    d = sorted(((K[j], thA[j], thB[j]) for j in range(n)), key=lambda x: -abs(x[2] - x[1]))
    for k, a, c in d[:12]:
        print("   %-24s A %+.4f -> B %+.4f   (%+.4f)" % (k, a, c, c - a))
    json.dump({"chiavi": K, "spedito": th0.tolist(), "A": thA.tolist(), "B": thB.tolist()},
              open(QUI / "dati_modello" / "creazione_fuori_campione.json", "w"), indent=1)


main()
