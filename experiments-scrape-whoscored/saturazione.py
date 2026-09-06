#!/usr/bin/env python
"""Ri-deriva ROLE_SATURATION: i tre numeri dello stadio finale, per questi pesi.

    cd vfoot-backend/src
    ../.venv/bin/python manage.py shell < ../../experiments-scrape-whoscored/saturazione.py

PERCHE' SERVE UNO SCRIPT. ``calibrate_vote_reference`` rifa' scale, reference,
medie di ruolo, curve dei minuti e impatto dei gol. NON rifa' ROLE_SATURATION, che
pero' dipende dai pesi quanto tutto il resto: ``centro_pre`` e' la media empirica
del voto del ruolo PRIMA dello stadio, e il fattore riapre la dispersione fino a
quella delle pagelle. Cambiare un peso muove entrambi. Fino al 06/09/2026 quei tre
numeri per ruolo erano cuciti a mano dalla sessione che aveva cercato il modello, e
un cambio di pesi li avrebbe lasciati a comprimere attorno al baricentro sbagliato.

LA FORMA. ``scale_saturation`` fa  out = dopo + a * sat(v - pre), con
sat(d) = T*log1p(d/T) per d>0 e d altrimenti. Si vuole che il ruolo finisca sulla
media e sulla dispersione del giudice, quindi, detta ``comp`` la trasformata:

    a    = sd(pagella) / sd(comp)
    dopo = media(pagella) + (pre - media(comp)) * a

SI ITERA, e non e' pedanteria: il voto pre-stadio contiene rosso, autogol e rigore
sbagliato gia' DIVISI per il fattore vecchio (v. ``voto_puro_for_match``), quindi il
punto di partenza dipende dal risultato. Tre giri bastano ampiamente — lo
spostamento fra il secondo e il terzo si legge sulla quinta cifra.

PROVA DI RIPRODUZIONE: con la reference VECCHIA e i due pesi della creazione a zero
questa derivazione deve restituire i tre numeri spediti. Se non li restituisce, la
formula non e' quella che li ha prodotti e non ci si puo' costruire sopra.
"""
from __future__ import annotations

import json
import math
import os
import shutil
from pathlib import Path

import numpy as np

import vfoot.services.classic_rating as cr
from vfoot.services import vote_reference as vr
from realdata.models import Match

QUI = Path("/home/andrea/Nextcloud/vfootboosted/experiments-scrape-whoscored")
# NON da sys.argv: sotto ``manage.py shell`` argv[1] e' "shell", e la copia
# fallisce su un percorso inventato. Sta in una variabile d'ambiente o qui.
SCRATCH = Path(os.environ.get("VFOOT_SCRATCH", "/tmp/vfoot-taratura"))
RUOLI = ("DIF", "CEN", "ATT")
STAGIONE = 2


def statistico():
    d = json.loads((QUI / "join_2526.json").read_text())
    gd_of = dict(Match.objects.filter(competition_season_id=STAGIONE)
                 .values_list("id", "matchday"))
    out = {}
    for k, v in (d["ext"] or {}).items():
        if v.get("Statistico") is not None:
            out[k] = v["Statistico"]
    return out, gd_of


def pre_stadio(ext, gd_of):
    """{(mid,pid): (ruolo, voto_pre_scala, voto_statistico)} sulle presenze >=60'."""
    from vfoot.services.classic_pagella import get_reference
    ref = get_reference(STAGIONE)
    righe = []
    for m in Match.objects.filter(competition_season_id=STAGIONE):
        for r in cr.voto_puro_for_match(m, ref):
            if not r.get("rated") or r.get("role") not in RUOLI:
                continue
            v = ext.get("%s:%s" % (gd_of.get(m.id), r["player_id"]))
            if v is None:
                continue
            righe.append((r["role"], r["voto_pre_scala"], v, r.get("minutes", 0)))
    return righe


def deriva(righe, minuti_min=60):
    sat = lambda d: math.log1p(d) if d > 0 else d      # T = 1.0
    fuori = {}
    for r in RUOLI:
        v = np.array([x[1] for x in righe if x[0] == r and x[3] >= minuti_min])
        e = np.array([x[2] for x in righe if x[0] == r and x[3] >= minuti_min])
        if len(v) < 50:
            continue
        pre = float(v.mean())
        comp = pre + np.array([sat(x) for x in (v - pre)])
        a = float(e.std() / comp.std())
        dopo = float(e.mean() + (pre - comp.mean()) * a)
        fuori[r] = (pre, dopo, a)
    return fuori


def giro(ext, gd_of, giri=3, etichetta=""):
    for i in range(giri):
        righe = pre_stadio(ext, gd_of)
        nuovo = deriva(righe)
        for r, t in nuovo.items():
            cr.ROLE_SATURATION[getattr(cr.Player, {"DIF": "ROLE_DEF", "CEN": "ROLE_MID",
                                                   "ATT": "ROLE_FWD"}[r])] = t
        print("   %s giro %d:  %s" % (etichetta, i + 1, "  ".join(
            "%s (%.6f, %.6f, %.6f)" % (r, *nuovo[r]) for r in RUOLI)))
    return nuovo


def usa(percorso):
    shutil.copy(percorso, vr.REFERENCE_PATH)
    vr.clear_cache(); cr.clear_scales_cache()


def main():
    ext, gd_of = statistico()
    print("Statistico: %d presenze agganciate" % len(ext))
    partenza = {r: tuple(cr.ROLE_SATURATION[getattr(
        cr.Player, {"DIF": "ROLE_DEF", "CEN": "ROLE_MID", "ATT": "ROLE_FWD"}[r])])
        for r in RUOLI}
    print("\nSPEDITO (dal sorgente):")
    for r in RUOLI:
        print("   %s (%.6f, %.6f, %.6f)" % (r, *partenza[r]))

    # --- prova di riproduzione: reference vecchia, creazione a zero
    print("\nPROVA DI RIPRODUZIONE (reference vecchia, kp=bcc=0):")
    usa(SCRATCH / "ref_vecchia.json")
    for k in ("key_passes", "big_chance_created"):
        cr.TOTAL_WEIGHTS[k] = 0.0; cr.WEIGHTS[k] = 0.0
    rip = giro(ext, gd_of, 3, "rip")
    scarto = max(abs(rip[r][i] - partenza[r][i]) for r in RUOLI for i in range(3))
    print("   scarto massimo dai valori spediti: %.6f  ->  %s"
          % (scarto, "RIPRODOTTI" if scarto < 0.01 else "NON RIPRODOTTI"))

    # --- i valori nuovi: reference nuova, creazione accesa
    print("\nVALORI NUOVI (reference nuova, kp=bcc=0.020):")
    for k in ("key_passes", "big_chance_created"):
        cr.TOTAL_WEIGHTS[k] = 0.020; cr.WEIGHTS[k] = 0.020
    for r in RUOLI:
        cr.ROLE_SATURATION[getattr(cr.Player, {"DIF": "ROLE_DEF", "CEN": "ROLE_MID",
                                               "ATT": "ROLE_FWD"}[r])] = partenza[r]
    usa(SCRATCH / "ref_nuova.json")
    nuovo = giro(ext, gd_of, 3, "new")
    json.dump({r: list(nuovo[r]) for r in RUOLI},
              open(SCRATCH / "role_saturation_nuovo.json", "w"), indent=1)
    print("\nDA SCRIVERE IN classic_rating.ROLE_SATURATION:")
    for r, attr in (("DIF", "ROLE_DEF"), ("CEN", "ROLE_MID"), ("ATT", "ROLE_FWD")):
        print("    Player.%s: (%r, %r, %r)," % (attr, *nuovo[r]))


main()
