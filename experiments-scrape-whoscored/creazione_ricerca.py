#!/usr/bin/env python
"""STADIO B: la ricerca, con key_passes e big_chance_created LIBERATI.

    cd vfoot-backend/src
    ../.venv/bin/python manage.py shell < ../../experiments-scrape-whoscored/creazione_ricerca.py

PERCHE' LO STADIO A NON BASTA. Accendere un peso da solo aggiunge la colonna
INTERA, e la parte di quella colonna che gli altri pesi gia' pagano viene contata
due volte — che e' esattamente l'argomento con cui key_passes era stato azzerato il
01/09. La domanda vera e' un'altra: se gli ALTRI pesi possono restituire cio' che
duplicano, il nuovo ottimo e' piu' alto del vecchio?

L'ESPERIMENTO E' CONTROLLATO, ed e' l'unica forma in cui la risposta significa
qualcosa. Due bracci, stesso punto di partenza (i pesi spediti), stesso obiettivo,
stesso numero di passi:

   BRACCIO A — i due inchiodati a zero, come oggi. E' il CONTROLLO: dice quanto si
               guadagna semplicemente ri-ottimizzando, cioe' quanta parte del
               risultato non c'entra niente coi due pesi.
   BRACCIO B — i due liberi.

La differenza fra i due e' l'effetto di averli liberati. Confrontare il braccio B
col modello SPEDITO invece che col braccio A attribuirebbe ai due pesi anche il
guadagno che viene dall'aver ottimizzato con un obiettivo diverso da quello che ha
prodotto il modello spedito.

L'OBIETTIVO E' LO STATISTICO, perche' e' il bersaglio dichiarato del modello (v. la
memoria "La percezione umana e' il bersaglio"). WhoScored e la Redazione si
GUARDANO, non si inseguono: servono a dire se un guadagno e' vero o e' adattamento
alle convenzioni di chi ci da' i dati.

QUELLO CHE QUESTA RICERCA NON HA. I vincoli di campo della 26-27 vivono in
produzione e qui non ci sono, quindi il vettore che esce NON e' spedibile com'e':
e' la risposta a "c'e' del guadagno li' dentro", non un candidato al rilascio. Il
cruscotto degli eventi rari viene stampato lo stesso, perche' un ottimo che sposta
quelli e' gia' da buttare (v. la nota in vote_tuning).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

import vfoot.services.classic_rating as cr
from vfoot.services import vote_tuning as vt

QUI = Path("/home/andrea/Nextcloud/vfootboosted/experiments-scrape-whoscored")
RUOLI = ("DIF", "CEN", "ATT")
STAGIONE = 2
LIBERI = ("key_passes", "big_chance_created")
SEME = {"key_passes": 0.015, "big_chance_created": 0.015}


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


def giudici_extra(b):
    """Redazione, SofaScore e WhoScored come indici gia' pronti, a >=60'."""
    import sys
    sys.path.insert(0, str(QUI))
    from realdata.services.identity import norm_name
    from vfoot.management.commands.compare_external_votes import Command as Ext, _club_key
    from django.conf import settings

    lunghi = {k for k, m in zip(b.cal_key, b.cal_min) if m >= 60}
    out = {}

    # --- WhoScored
    f = QUI / "ws_2526.jsonl"
    if f.exists():
        ext = Ext(); team_map = ext._our_team_index(STAGIONE); pidx = ext._our_player_index(STAGIONE)
        kk = lambda n: " ".join(t for t in _club_key(n).split() if not t.isdigit())
        nostre = {(m.home_team.team.name, m.away_team.team.name): m.id
                  for m in cr.Match.objects.filter(competition_season_id=STAGIONE)
                  .select_related("home_team__team", "away_team__team")}
        G = {}
        for p in (json.loads(l) for l in f.read_text().splitlines() if l.strip()):
            tc = team_map.get(kk(p["casa"] or "")); tf = team_map.get(kk(p["fuori"] or ""))
            mid = nostre.get((tc, tf)) if tc and tf else None
            if mid is None:
                continue
            for g in p["giocatori"]:
                sq = tc if g["squadra"] == p["casa"] else tf
                c = pidx.get((sq, norm_name(g["nome"]).split()[-1] if g["nome"] else ""), [])
                if len(c) == 1 and (mid, c[0]) in lunghi:
                    G[(mid, c[0])] = float(g["rating"])
        out["WhoScored"] = G

    # --- Redazione dal join
    d = json.loads((QUI / "join_2526.json").read_text())
    gd_of = dict(cr.Match.objects.filter(competition_season_id=STAGIONE)
                 .values_list("id", "matchday"))
    G = {}
    for k in b.cal_key:
        if k not in lunghi:
            continue
        e = (d["ext"] or {}).get(f"{gd_of.get(k[0])}:{k[1]}") or {}
        if e.get("Fantacalcio") is not None:
            G[k] = e["Fantacalcio"]
    out["Redazione"] = G

    idx = {}
    for nome, G in out.items():
        i = np.array([j for j, k in enumerate(b.cal_key) if k in G])
        idx[nome] = (i, np.array([G[b.cal_key[j]] for j in i], dtype=float))
    return idx


# ============================================================== l'obiettivo
def fabbrica(b, W0):
    """(valuta, da_vettore) — la correlazione collo Statistico per un vettore.

    Il vettore che l'ottimizzatore muove e' quello CONDIVISO fra i tre ruoli piu'
    le tre chiavi per-ruolo, come ``vt.parametri``: sciogliere i ruoli qui vorrebbe
    dire far decidere all'ottimizzatore un pezzo di modello che abbiamo deciso noi.
    """
    n = len(b.keys)
    ruolo_i = [b.idx_of[k] for k in vt.CHIAVI_RUOLO if k in b.idx_of]
    iS, xS = b.giud_righe["Statistico"]

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

    def valuta(theta, extra=None):
        W = da_vettore(theta)
        ctx = vt.contesto(b, W)
        arr = ctx["arr"]
        r = float(np.corrcoef(arr[iS], xS)[0, 1])
        if extra is None:
            return r
        fuori = {nome: float(np.corrcoef(arr[i], e)[0, 1])
                 for nome, (i, e) in extra.items()}
        return r, fuori, ctx

    return valuta, da_vettore, theta_da


def cerca(b, theta0, valuta, mobili, passi=25, verbose=True):
    """Salita del gradiente proiettata, a differenze finite.

    NIENTE CAMBI DI SEGNO e gli zeri di ``mobili=False`` restano zero: e' la stessa
    proiezione di ``vt.proietta``, applicata a una maschera che decidiamo noi invece
    che al vettore di partenza. E' l'unica differenza fra i due bracci.
    """
    th = theta0.copy()
    segno = np.sign(theta0)
    r = valuta(th)
    if verbose:
        print("   partenza r = %.5f" % r)
    passo0 = 0.25          # frazione della taglia del peso
    for it in range(passi):
        g = np.zeros(len(th))
        for j in np.nonzero(mobili)[0]:
            h = max(abs(th[j]), 1e-3) * 0.05
            su = th.copy(); su[j] += h
            giu = th.copy(); giu[j] -= h
            g[j] = (valuta(su) - valuta(giu)) / (2 * h)
        norma = np.linalg.norm(g)
        if norma < 1e-9:
            break
        taglia = np.where(np.abs(theta0) > 1e-9, np.abs(theta0), 1e-2)
        d = g / norma * taglia
        migliore, r_mig = None, r
        for alfa in (passo0, passo0 / 2, passo0 / 4, passo0 / 8):
            cand = th + alfa * d
            for j in range(len(cand)):
                if not mobili[j]:
                    cand[j] = theta0[j]
                elif segno[j] > 0:
                    cand[j] = max(0.0, cand[j])
                elif segno[j] < 0:
                    cand[j] = min(0.0, cand[j])
            rc = valuta(cand)
            if rc > r_mig:
                migliore, r_mig = cand, rc
                break
        if migliore is None:
            passo0 /= 2
            if passo0 < 0.01:
                break
            continue
        th, r = migliore, r_mig
        if verbose:
            print("   passo %2d  r = %.5f" % (it + 1, r))
    return th, r


def main():
    b = prepara()
    extra = giudici_extra(b)
    for n, (i, _e) in extra.items():
        print("   %-11s agganciati %d" % (n, len(i)))
    valuta, da_vettore, theta_da = fabbrica(b, None)

    W0 = {r: b.vettore_pesi(r) for r in RUOLI}
    th0 = theta_da(W0)
    n = len(b.keys)
    t0 = time.time(); valuta(th0); dt = time.time() - t0
    print("   una valutazione: %.2f s  ->  un gradiente da %d pesi: %.0f s"
          % (dt, int((np.abs(th0) > 1e-12).sum()), dt * 2 * (np.abs(th0) > 1e-12).sum()))

    mob_A = np.abs(th0) > 1e-12                     # come oggi: gli zeri restano zero
    th0_B = th0.copy()
    for k, v in SEME.items():
        th0_B[b.idx_of[k]] = v
    mob_B = np.abs(th0_B) > 1e-12                   # i due liberati

    ris = {}
    for nome, t_start, mob in (("A  (kp=0, bcc=0)", th0, mob_A),
                               ("B  (kp, bcc liberi)", th0_B, mob_B)):
        print("\nBRACCIO %s — %d pesi mobili" % (nome, int(mob.sum())))
        th, r = cerca(b, t_start, valuta, mob)
        rS, fuori, ctx = valuta(th, extra)
        ris[nome] = (th, rS, fuori, ctx)
        print("   ARRIVO  Statistico %.5f | %s" % (
            rS, " | ".join("%s %.5f" % (k, v) for k, v in fuori.items())))
        for k in LIBERI:
            print("      %-20s %.4f" % (k, th[b.idx_of[k]]))

    print("\n" + "=" * 78)
    rS0, fuori0, ctx0 = valuta(th0, extra)[0], *valuta(th0, extra)[1:]
    print("SPEDITO              Statistico %.5f | %s" % (
        rS0, " | ".join("%s %.5f" % (k, v) for k, v in fuori0.items())))
    for nome, (th, rS, fuori, ctx) in ris.items():
        print("BRACCIO %-20s %.5f | %s" % (
            nome, rS, " | ".join("%s %.5f" % (k, v) for k, v in fuori.items())))
    (thA, rA, _fA, _cA) = ris["A  (kp=0, bcc=0)"]
    (thB, rB, _fB, ctxB) = ris["B  (kp, bcc liberi)"]
    print("\nLIBERARLI VALE: %+.5f di correlazione collo Statistico "
          "(braccio B meno braccio A)" % (rB - rA))

    print("\nCRUSCOTTO del braccio B (gli eventi rari, in punti di voto):")
    for k, v in ctxB["cruscotto"].items():
        print("   %-24s %s" % (k, v if not isinstance(v, float) else "%+.3f" % v))

    print("\nI PESI CHE SI SONO MOSSI DI PIU' (braccio B contro spedito):")
    K = list(b.keys)
    d = [(K[j], th0[j], thB[j]) for j in range(n)]
    d.sort(key=lambda x: -abs(x[2] - x[1]))
    for k, a, c in d[:14]:
        print("   %-24s %+.4f -> %+.4f   (%+.4f)" % (k, a, c, c - a))
    json.dump({"spedito": th0.tolist(), "braccio_A": thA.tolist(),
               "braccio_B": thB.tolist(), "chiavi": K,
               "r": {"spedito": rS0, "A": rA, "B": rB}},
              open(QUI / "dati_modello" / "creazione_ricerca.json", "w"), indent=1)
    print("\nsalvato in dati_modello/creazione_ricerca.json")


main()
