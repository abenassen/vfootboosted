#!/usr/bin/env python
"""La verifica di fine catena: il modello VECCHIO e il NUOVO, dalla pipeline vera.

    cd vfoot-backend/src
    VFOOT_SCRATCH=... ../.venv/bin/python manage.py shell < .../verifica_finale.py

Le misure che hanno deciso l'accensione (stadio F) venivano dal BANCO dei pesi, con
lo stadio finale rifatto a mano sopra. Il banco e' fedele a 0.002 ma non e' la
pipeline, e fra quelle misure e il rilascio sono passati altri tre cambi: la
ricalibrazione, le terne dello stadio finale ri-derivate e i cinque eventi rari
ri-risolti. Questo file rifa' il confronto DA CAPO, con ``voto_puro_for_match``, cioe'
col codice che scrive il voto accanto al nome.

Le due configurazioni girano nello STESSO processo, scambiando la reference e i
pesi: cosi' la differenza non puo' venire da un ambiente diverso.
"""
from __future__ import annotations

import json, os, shutil
from pathlib import Path

import numpy as np

import vfoot.services.classic_rating as cr
from vfoot.services import vote_reference as vr
from vfoot.services.classic_pagella import get_reference
from realdata.models import Match

QUI = Path("/home/andrea/Nextcloud/vfootboosted/experiments-scrape-whoscored")
SCRATCH = Path(os.environ.get("VFOOT_SCRATCH", "/tmp/vfoot-taratura"))
RUOLI = ("DIF", "CEN", "ATT"); ATTR = {"DIF":"ROLE_DEF","CEN":"ROLE_MID","ATT":"ROLE_FWD"}
SOGLIA = 1.5

VECCHIA_SAT = {"DIF": (5.955666852686118, 6.061230791524389, 1.5485834273858712),
               "CEN": (6.052875763317001, 6.1238237595148695, 1.596370972734363),
               "ATT": (6.097521915325461, 6.155905316629372, 1.676461101184294)}
VECCHI_PESI = {"key_passes": 0.0, "big_chance_created": 0.0,
               "clearances_off_line": 0.0037, "penalties_won": 0.0241,
               "penalties_conceded": -0.0341, "errors_led_to_goal": -0.0181,
               "errors_led_to_shot": -0.0057}
NUOVI_PESI = {k: cr.WEIGHTS[k] for k in VECCHI_PESI}
NUOVA_SAT = {r: tuple(cr.ROLE_SATURATION[getattr(cr.Player, ATTR[r])]) for r in RUOLI}


def giudici():
    d = json.loads((QUI / "join_2526.json").read_text())
    gd_of = dict(Match.objects.filter(competition_season_id=2).values_list("id","matchday"))
    # CHIAVI A TUPLA, come quelle dei voti: il file le porta come "giornata:id" e
    # confrontare una stringa con una tupla non solleva, restituisce un insieme
    # vuoto — cioe' un confronto fra zero presenze che si annuncia solo con un
    # avviso di numpy su una media vuota.
    st, red = {}, {}
    for k, v in (d["ext"] or {}).items():
        gd, _, pid = k.partition(":")
        kk = (int(gd), int(pid))
        if v.get("Statistico") is not None:
            st[kk] = v["Statistico"]
        if v.get("Fantacalcio") is not None:
            red[kk] = v["Fantacalcio"]
    return st, red, gd_of


def voti(st, gd_of):
    ref = get_reference(2); out = {}
    for m in Match.objects.filter(competition_season_id=2):
        for r in cr.voto_puro_for_match(m, ref):
            if not r.get("rated") or r.get("role") not in RUOLI or (r.get("minutes") or 0) < 60:
                continue
            out[(gd_of.get(m.id), r["player_id"])] = (r["role"], r["voto_puro"])
    return out


def usa(percorso, pesi, sat):
    shutil.copy(percorso, vr.REFERENCE_PATH)
    vr.clear_cache(); cr.clear_scales_cache()
    for k, v in pesi.items():
        cr.WEIGHTS[k] = v
        (cr.TOTAL_WEIGHTS if k in cr.TOTAL_WEIGHTS else cr.PER90_WEIGHTS)[k] = v
    for r in RUOLI:
        cr.ROLE_SATURATION[getattr(cr.Player, ATTR[r])] = sat[r]


def misura(v, st, red, bcc):
    ch = [k for k in v if k in st]
    if not ch:
        raise SystemExit("nessuna presenza agganciata: le chiavi non combaciano")
    x = np.array([v[k][1] for k in ch]); e = np.array([st[k] for k in ch])
    ruo = np.array([v[k][0] for k in ch])
    d = x - e
    gravi = np.abs(d) >= SOGLIA
    m = {"n": len(ch), "gravi": int(gravi.sum()), "mae": float(np.abs(d).mean()),
         "r": float(np.corrcoef(x, e)[0,1]),
         "chi": {ch[i] for i in np.nonzero(gravi)[0]}}
    chr_ = [k for k in v if k in red]
    xr = np.array([v[k][1] for k in chr_]); er = np.array([red[k] for k in chr_])
    m["r_red"] = float(np.corrcoef(xr, er)[0,1])
    m["mae_red"] = float(np.abs(xr - er).mean())
    sel = np.array([bcc.get(k, 0.0) >= 1 for k in ch], dtype=bool)
    m["creatori_n"] = int(sel.sum()); m["creatori_gravi"] = int((gravi & sel).sum())
    m["bias_creatori"] = float(d[sel].mean()) if sel.any() else float("nan")
    for r in RUOLI:
        mr = ruo == r
        m["media_" + r] = float(x[mr].mean() - e[mr].mean())
    return m


def main():
    st, red, gd_of = giudici()
    mids = list(Match.objects.filter(competition_season_id=2).values_list("id", flat=True))
    tot = cr._per_match_player_totals(mids)
    bcc = {(gd_of.get(mid), pid): (f.get("big_chance_created") or 0.0)
           for (mid, pid), f in tot.items()}

    usa(SCRATCH / "ref_vecchia.json", VECCHI_PESI, VECCHIA_SAT)
    vecchio = misura(voti(st, gd_of), st, red, bcc)
    usa(SCRATCH / "ref_nuova_finale.json", NUOVI_PESI, NUOVA_SAT)
    nuovo = misura(voti(st, gd_of), st, red, bcc)

    print("\n%-26s %10s %10s %10s" % ("", "PRIMA", "DOPO", "differenza"))
    for et, k, f in (("presenze confrontate", "n", "%d"),
                     ("errori gravi (>=1.5)", "gravi", "%d"),
                     ("MAE Statistico", "mae", "%.4f"),
                     ("correlazione Statistico", "r", "%.5f"),
                     ("MAE Redazione", "mae_red", "%.4f"),
                     ("correlazione Redazione", "r_red", "%.5f"),
                     ("creatori: presenze", "creatori_n", "%d"),
                     ("creatori: errori gravi", "creatori_gravi", "%d"),
                     ("creatori: scarto medio", "bias_creatori", "%+.4f"),
                     ("scarto medio DIF", "media_DIF", "%+.4f"),
                     ("scarto medio CEN", "media_CEN", "%+.4f"),
                     ("scarto medio ATT", "media_ATT", "%+.4f")):
        a, b = vecchio[k], nuovo[k]
        diff = ("%+.4f" % (b - a)) if isinstance(a, float) else ("%+d" % (b - a))
        print("%-26s %10s %10s %10s" % (et, f % a, f % b, diff))
    usc, ent = vecchio["chi"] - nuovo["chi"], nuovo["chi"] - vecchio["chi"]
    print("\ncoda: %d presenze ESCONO dagli errori gravi, %d ci ENTRANO"
          % (len(usc), len(ent)))


main()
