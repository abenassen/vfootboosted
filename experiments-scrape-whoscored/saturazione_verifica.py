#!/usr/bin/env python
"""Quale terna di ROLE_SATURATION porta davvero il ruolo sulle pagelle?

    cd vfoot-backend/src
    VFOOT_SCRATCH=... ../.venv/bin/python manage.py shell < .../saturazione_verifica.py

IL DUBBIO. Ri-derivando le costanti dello stadio finale sulla pipeline vera, con la
reference vecchia e la creazione a zero, non tornano quelle spedite: il fattore
esce +0.6% piu' alto (DIF 1.5584 contro 1.5486, ATT 1.6863 contro 1.6765). O ho
sbagliato la formula, o quelle costanti erano state derivate sul BANCO — che
riproduce il voto a 0.002 ma non e' la pipeline — e portano quel piccolo scarto da
allora.

NON SI DECIDE GUARDANDO I NUMERI, si decide guardando A COSA SERVONO: quelle tre
costanti esistono per portare media e dispersione del ruolo su quelle della
pagella. Quindi si applicano entrambe le terne e si misura chi ci arriva. E' il
test diretto della cosa che le costanti promettono.

TRE CONFIGURAZIONI:
  1. reference VECCHIA + creazione a zero + terna SPEDITA — il controllo. Se qui la
     terna spedita centra media e dispersione, la sua derivazione era giusta sulla
     pipeline e l'errore e' mio.
  2. reference NUOVA + creazione accesa + terna SPEDITA — cosa succede a non
     ritoccarle.
  3. reference NUOVA + creazione accesa + terna NUOVA.
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
SCRATCH = Path(os.environ.get("VFOOT_SCRATCH", "/tmp/vfoot-taratura"))
RUOLI = ("DIF", "CEN", "ATT")
ATTR = {"DIF": "ROLE_DEF", "CEN": "ROLE_MID", "ATT": "ROLE_FWD"}
STAGIONE = 2

SPEDITA = {"DIF": (5.955666852686118, 6.061230791524389, 1.5485834273858712),
           "CEN": (6.052875763317001, 6.1238237595148695, 1.596370972734363),
           "ATT": (6.097521915325461, 6.155905316629372, 1.676461101184294)}


def statistico():
    d = json.loads((QUI / "join_2526.json").read_text())
    gd_of = dict(Match.objects.filter(competition_season_id=STAGIONE)
                 .values_list("id", "matchday"))
    return {k: v["Statistico"] for k, v in (d["ext"] or {}).items()
            if v.get("Statistico") is not None}, gd_of


def passata(ext, gd_of):
    from vfoot.services.classic_pagella import get_reference
    ref = get_reference(STAGIONE)
    righe = []
    for m in Match.objects.filter(competition_season_id=STAGIONE):
        for r in cr.voto_puro_for_match(m, ref):
            if not r.get("rated") or r.get("role") not in RUOLI:
                continue
            if (r.get("minutes") or 0) < 60:
                continue
            v = ext.get("%s:%s" % (gd_of.get(m.id), r["player_id"]))
            if v is not None:
                righe.append((r["role"], r["voto_pre_scala"], v))
    return righe


def applica(righe, terna):
    sat = lambda d: math.log1p(d) if d > 0 else d
    out = {}
    for r in RUOLI:
        v = np.array([x[1] for x in righe if x[0] == r])
        e = np.array([x[2] for x in righe if x[0] == r])
        pre, dopo, a = terna[r]
        f = np.array([dopo + a * sat(x - pre) for x in v])
        out[r] = (float(f.mean()), float(f.std()), float(e.mean()), float(e.std()),
                  len(v), float(np.abs(np.array([cr._round_half(x) for x in f]) - e).mean()))
    return out


def mostra(nome, m):
    print("\n%s" % nome)
    print("   %-4s %8s %8s | %8s %8s | %8s %8s | %6s %6s" % (
        "", "media", "disp.", "pagella", "disp.", "d.media", "d.disp.", "n", "MAE"))
    for r in RUOLI:
        mu, sd, c, s, n, mae = m[r]
        print("   %-4s %8.4f %8.4f | %8.4f %8.4f | %+8.4f %+8.4f | %6d %6.4f"
              % (r, mu, sd, c, s, mu - c, sd - s, n, mae))
    print("   scarto assoluto totale: media %.4f  dispersione %.4f" % (
        sum(abs(m[r][0] - m[r][2]) for r in RUOLI),
        sum(abs(m[r][1] - m[r][3]) for r in RUOLI)))


def usa(percorso):
    shutil.copy(percorso, vr.REFERENCE_PATH)
    vr.clear_cache(); cr.clear_scales_cache()


def main():
    ext, gd_of = statistico()
    nuova = {r: tuple(v) for r, v in
             json.loads((SCRATCH / "role_saturation_nuovo.json").read_text()).items()}

    print("=" * 78)
    print("1. CONTROLLO — reference vecchia, creazione a zero, terna SPEDITA")
    usa(SCRATCH / "ref_vecchia.json")
    for k in ("key_passes", "big_chance_created"):
        cr.TOTAL_WEIGHTS[k] = 0.0; cr.WEIGHTS[k] = 0.0
    for r in RUOLI:
        cr.ROLE_SATURATION[getattr(cr.Player, ATTR[r])] = SPEDITA[r]
    righe_v = passata(ext, gd_of)
    mostra("terna SPEDITA sulla configurazione VECCHIA", applica(righe_v, SPEDITA))

    print("\n" + "=" * 78)
    print("2/3. reference NUOVA, creazione a 0.020")
    usa(SCRATCH / "ref_nuova.json")
    for k in ("key_passes", "big_chance_created"):
        cr.TOTAL_WEIGHTS[k] = 0.020; cr.WEIGHTS[k] = 0.020
    for r in RUOLI:
        cr.ROLE_SATURATION[getattr(cr.Player, ATTR[r])] = nuova[r]
    righe_n = passata(ext, gd_of)
    mostra("terna SPEDITA (non ritoccata)", applica(righe_n, SPEDITA))
    mostra("terna NUOVA (ri-derivata)", applica(righe_n, nuova))


main()
