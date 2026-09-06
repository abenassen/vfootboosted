#!/usr/bin/env python
"""STADIO E: 0.015 e' un fatto dei dati o l'inerzia del seme?

    cd vfoot-backend/src
    ../.venv/bin/python manage.py shell < ../../experiments-scrape-whoscored/creazione_semi.py

IL DIFETTO CHE QUESTO FILE RIPARA. Negli stadi C e D key_passes e big_chance_created
sono stati SEMINATI a 0.015 e sono atterrati a 0.015. Presentarlo come "tre ricerche
convergono sullo stesso punto" era leggere l'inerzia del punto di partenza come un
risultato: in D il termine di minimo cambiamento e' ancorato proprio al seme, quindi
non poteva finire altrove; e in C la ricerca si muove poco perche' il guadagno e'
piatto in quella direzione. L'unico che si e' mosso davvero — B, senza vincoli e
senza ancoraggio — e' finito al DOPPIO su key_passes.

LA PROVA. Stesso obiettivo, stessi vincoli, nessun ancoraggio al punto di partenza,
QUATTRO SEMI diversi (0.005, 0.015, 0.040, 0.080). Se atterrano vicini, il valore e'
una proprieta' dei dati; se ognuno resta dov'e' partito, l'obiettivo e' piatto e il
numero non e' identificato — che sarebbe comunque una risposta, e piu' onesta di un
numero preciso letto in una superficie senza pendenza.

Gli invarianti sono quelli del TEST riportati sulla scala pre-stadio, non quelli
scaduti di ``vote_constraints`` (v. la nota nello stadio D).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

import vfoot.services.classic_rating as cr
from vfoot.services import vote_tuning as vt
from vfoot.tests_rare_events import ATTESI, TOLLERANZA, _fattore_stadio

QUI = Path("/home/andrea/Nextcloud/vfootboosted/experiments-scrape-whoscored")
RUOLI = ("DIF", "CEN", "ATT")
STAGIONE = 2
LIBERI = ("key_passes", "big_chance_created")
SEMI = (0.005, 0.015, 0.040, 0.080)
PASSI = 70


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


def giudici(b):
    from realdata.services.identity import norm_name
    from vfoot.management.commands.compare_external_votes import Command as Ext, _club_key
    lunghi = {k for k, m in zip(b.cal_key, b.cal_min) if m >= 60}
    G, d = {}, json.loads((QUI / "join_2526.json").read_text())
    gd_of = dict(cr.Match.objects.filter(competition_season_id=STAGIONE)
                 .values_list("id", "matchday"))
    for nome, foglio in (("Statistico", "Statistico"), ("Redazione", "Fantacalcio")):
        G[nome] = {k: v for k, v in
                   ((k, ((d["ext"] or {}).get(f"{gd_of.get(k[0])}:{k[1]}") or {}).get(foglio))
                    for k in b.cal_key if k in lunghi) if v is not None}
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
    G = giudici(b)
    gd_of = dict(cr.Match.objects.filter(competition_season_id=STAGIONE)
                 .values_list("id", "matchday"))
    gd = np.array([gd_of.get(k[0]) or 0 for k in b.cal_key])
    disp = (gd % 2) == 1
    idx = {}
    for nome, d in G.items():
        i = np.array([j for j, k in enumerate(b.cal_key) if k in d])
        e = np.array([d[b.cal_key[j]] for j in i], dtype=float)
        idx[nome] = {"tara": (i[disp[i]], e[disp[i]]), "prova": (i[~disp[i]], e[~disp[i]])}

    n = len(b.keys)
    ruolo_i = [b.idx_of[k] for k in vt.CHIAVI_RUOLO if k in b.idx_of]
    fatt = _fattore_stadio()

    def da_vettore(theta):
        W = {r: np.array(theta[:n], dtype=float) for r in RUOLI}
        p = n
        for i in ruolo_i:
            for j, r in enumerate(RUOLI):
                W[r][i] = theta[p + j]
            p += 3
        return W

    def cor(arr, quale, parte):
        i, e = idx[quale][parte]
        return float(np.corrcoef(arr[i], e)[0, 1])

    PAV = {}

    def obiettivo(theta, completo=False):
        ctx = vt.contesto(b, da_vettore(theta))
        arr = ctx["arr"]
        r = cor(arr, "Statistico", "tara")
        pen = 0.0
        for k, atteso in ATTESI.items():
            v = ctx["cruscotto"].get("1 " + k)
            if v is None:
                continue
            s = TOLLERANZA / fatt - abs(v - atteso / fatt)
            if s < 0:
                pen += 500.0 * s * s
        for nome, minimo in PAV.items():
            s = cor(arr, nome, "tara") - minimo
            if s < 0:
                pen += 50.0 * s * s
        return (r - pen, ctx, arr) if completo else r - pen

    W0 = {r: b.vettore_pesi(r) for r in RUOLI}
    th0 = np.array(list(W0["DIF"]) + [W0[r][i] for i in ruolo_i for r in RUOLI])
    _v, ctx0, arr0 = obiettivo(th0, completo=True)
    for nome in ("Redazione", "WhoScored"):
        if nome in idx:
            PAV[nome] = cor(arr0, nome, "tara")
    print("SPEDITO  tara %.5f  prova %.5f" % (cor(arr0, "Statistico", "tara"),
                                              cor(arr0, "Statistico", "prova")))

    def cerca(theta0, etichetta):
        """NESSUN ANCORAGGIO al punto di partenza: solo l'obiettivo e i vincoli."""
        th = theta0.copy(); segno = np.sign(theta0)
        mob = np.abs(theta0) > 1e-12
        f = obiettivo(th); passo = 0.30
        for it in range(PASSI):
            g = np.zeros(len(th))
            for j in np.nonzero(mob)[0]:
                h = max(abs(th[j]), 1e-3) * 0.05
                su = th.copy(); su[j] += h
                giu = th.copy(); giu[j] -= h
                g[j] = (obiettivo(su) - obiettivo(giu)) / (2 * h)
            nrm = np.linalg.norm(g)
            if nrm < 1e-12:
                break
            # LA TAGLIA DEL PASSO NON VIENE DAL PUNTO DI PARTENZA. Usarla (come
            # negli stadi B/C) rende il passo dei due pesi proporzionale al SEME:
            # un seme piccolo si muove piano e sembra "restare dov'e'". Qui la
            # taglia e' quella dei pesi SPEDITI, uguale per tutti i semi.
            taglia = np.where(np.abs(th0) > 1e-9, np.abs(th0), 2e-2)
            d = g / nrm * taglia
            avanti = False
            for alfa in (passo, passo / 2, passo / 4, passo / 8, passo / 16):
                c = th + alfa * d
                for j in range(len(c)):
                    if not mob[j]:
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
        return th, f

    print("\n%-8s | %-9s %-9s | %9s %9s | %9s | %s" % (
        "seme", "kp arrivo", "bcc arr.", "Stat.tara", "Stat.PROVA", "WS.PROVA", "spostamento"))
    ris = []
    for seme in SEMI:
        t0 = time.time()
        ts = th0.copy()
        for k in LIBERI:
            ts[b.idx_of[k]] = seme
        th, f = cerca(ts, "seme %.3f" % seme)
        _v, ctx, arr = obiettivo(th, completo=True)
        kp, bcc = th[b.idx_of["key_passes"]], th[b.idx_of["big_chance_created"]]
        print("%-8.3f | %-9.4f %-9.4f | %9.5f %9.5f | %9.5f | kp %+.4f  bcc %+.4f   (%.0f s)"
              % (seme, kp, bcc, cor(arr, "Statistico", "tara"),
                 cor(arr, "Statistico", "prova"), cor(arr, "WhoScored", "prova"),
                 kp - seme, bcc - seme, time.time() - t0))
        ris.append({"seme": seme, "kp": kp, "bcc": bcc,
                    "stat_tara": cor(arr, "Statistico", "tara"),
                    "stat_prova": cor(arr, "Statistico", "prova"),
                    "ws_prova": cor(arr, "WhoScored", "prova"),
                    "theta": th.tolist()})
    kps = [r["kp"] for r in ris]; bccs = [r["bcc"] for r in ris]
    print("\nkey_passes:         da %.4f a %.4f   (i semi andavano da %.3f a %.3f)"
          % (min(kps), max(kps), min(SEMI), max(SEMI)))
    print("big_chance_created: da %.4f a %.4f" % (min(bccs), max(bccs)))
    print("\nVERDETTO: %s" % (
        "il punto d'arrivo NON dipende dal seme -> il valore e' dei dati"
        if (max(kps) - min(kps) < 0.010 and max(bccs) - min(bccs) < 0.010)
        else "ogni seme resta vicino a dov'e' partito -> l'obiettivo e' piatto "
             "in questa direzione e il valore NON e' identificato"))
    json.dump(ris, open(QUI / "dati_modello" / "creazione_semi.json", "w"), indent=1)


main()
