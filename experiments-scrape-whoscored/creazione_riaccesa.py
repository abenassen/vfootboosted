#!/usr/bin/env python
"""E se l'ottimizzatore potesse muovere ANCHE key_passes e big_chance_created?

    cd vfoot-backend/src
    ../.venv/bin/python manage.py shell < ../../experiments-scrape-whoscored/creazione_riaccesa.py

LA DOMANDA. Il modello cercato (04/09/2026) e' stato ottimizzato con questi due pesi
SPENTI A PRIORI: ``proietta`` tiene a zero ogni peso che parte da zero, quindi la
ricerca non li ha mai provati. Erano stati azzerati a mano — big_chance_created il
25/08 (il flag paga l'assist travestito), key_passes il 01/09 (e' la xA contata due
volte) — contro il modello di ALLORA, che aveva altri pesi e un'altra sigma.

Quindi la domanda non e' "erano giusti quei due zeri" ma: **all'ottimo di oggi,
lasciarli liberi paga?** Il caso che l'ha sollevata: Mora in Roma-Atalanta, occasione
nitida creata per Mancini (z = 3.06, il segnale piu' forte della sua partita) che nel
voto vale esattamente zero, perche' l'unico canale acceso e' la xA.

STADIO A (questo file): la sonda a griglia. Pesi tutti fermi tranne i due, per vedere
se c'e' segnale e in che direzione. Non risponde alla domanda vera — muovere un peso
da solo non e' l'ottimo — ma costa poco e dice se vale la pena del resto.

MISURE. La correlazione col giudice e' cieca allo scostamento CONDIZIONATO (v. la
nota in classic_rating sugli eventi rari), quindi accanto alla Pearson c'e' sempre
il sottogruppo che questo peso tocca: chi ha creato un'occasione nitida senza che
l'assist arrivasse. E' li' che si vede se stiamo pagando poco.
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
STAGIONE = 2                      # in LOCALE la 2 e' la 2025-2026
T_SAT = cr.VOTE_SATURATION_T


# ============================================================== il banco e i giudici
def prepara():
    t0 = time.time()
    b = vt.Bench(STAGIONE, verbose=True)
    b._popola_valutate()
    b.carica_calibrazione(verbose=True)
    # il banco vuole DUE popolazioni; qui ne serve una sola
    b.ber_key = b.cal_key; b.ber_role = b.cal_role; b.ber_z = b.cal_z
    b.ber_min = b.cal_min; b.ber_extra = b.cal_extra; b.ber_idx = b.cal_idx
    vt.carica_giudici(b, str(QUI / "join_2526.json"))
    # LA CURVA DEI MINUTI SI TARA SULLO STATISTICO, come il modello spedito
    # (v. la memoria "Il maestro della curva dei minuti").
    vt.carica_residui_esterni(b, str(QUI / "join_2526.json"), "Statistico")
    print("banco pronto in %.0f s" % (time.time() - t0))
    return b


def giudice_whoscored(b):
    """{(match, giocatore): rating} da ws_2526.jsonl, col matcher del progetto."""
    from realdata.services.identity import norm_name
    from vfoot.management.commands.compare_external_votes import Command as Ext, _club_key
    f = QUI / "ws_2526.jsonl"
    if not f.exists():
        return {}
    ws = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    ext = Ext()
    team_map = ext._our_team_index(STAGIONE)
    pidx = ext._our_player_index(STAGIONE)

    def chiave(nome: str) -> str:
        return " ".join(t for t in _club_key(nome).split() if not t.isdigit())

    nostre = {}
    for m in (cr.Match.objects.filter(competition_season_id=STAGIONE)
              .select_related("home_team__team", "away_team__team")):
        nostre[(m.home_team.team.name, m.away_team.team.name)] = m.id
    out = {}
    for p in ws:
        tc = team_map.get(chiave(p["casa"] or "")); tf = team_map.get(chiave(p["fuori"] or ""))
        if not tc or not tf:
            continue
        mid = nostre.get((tc, tf))
        if mid is None:
            continue
        for g in p["giocatori"]:
            sq = tc if g["squadra"] == p["casa"] else tf
            cog = norm_name(g["nome"]).split()[-1] if g["nome"] else ""
            c = pidx.get((sq, cog), [])
            if len(c) == 1:
                out[(mid, c[0])] = float(g["rating"])
    return out


def giudice_sofascore(b):
    from django.conf import settings
    from realdata.services.sofascore_adapter import real_sofascore_ids
    cache = Path(settings.VFOOT_DATA_DIR) / "historical-data/serie-a/sofascore/cache"
    inv = {str(v): k for k, v in real_sofascore_ids().items()}
    out = {}
    for m in cr.Match.objects.filter(competition_season_id=STAGIONE).only("id", "external_id"):
        if not m.external_id:
            continue
        try:
            d = json.loads((cache / f"api_v1_event_{m.external_id}_lineups.json").read_text())
        except (FileNotFoundError, ValueError):
            continue
        for lato in ("home", "away"):
            for pl in d.get(lato, {}).get("players", []):
                spid = (pl.get("player") or {}).get("id")
                st = pl.get("statistics") or {}
                if spid is None or not st.get("rating"):
                    continue
                ours = inv.get(str(spid))
                if ours is not None:
                    out[(m.id, ours)] = float(st["rating"])
    return out


def giudici_fogli(b):
    d = json.loads((QUI / "join_2526.json").read_text())
    gd_of = dict(cr.Match.objects.filter(competition_season_id=STAGIONE)
                 .values_list("id", "matchday"))
    fanta, stat = {}, {}
    mins = dict(zip(b.cal_key, b.cal_min))
    for k in b.cal_key:
        if mins.get(k, 0) < 60:          # stessa soglia di ``carica_giudici``
            continue
        e = (d["ext"] or {}).get(f"{gd_of.get(k[0])}:{k[1]}") or {}
        if e.get("Fantacalcio") is not None:
            fanta[k] = e["Fantacalcio"]
        if e.get("Statistico") is not None:
            stat[k] = e["Statistico"]
    return fanta, stat


# ============================================================== lo stadio finale
def con_saturazione(b, arr, idx_rif, ext_rif):
    """Il voto DOPO ``scale_saturation``, con le costanti RIFATTE per questi pesi.

    ROLE_SATURATION non e' una costante del mondo: ``centro_pre`` e' la media
    empirica del ruolo e il fattore riapre la dispersione fino a quella delle
    pagelle. Cambiare un peso muove entrambe, quindi riusare i tre numeri spediti
    misurerebbe il modello nuovo con la scala del vecchio.
    """
    ruo = b.cal_role
    sat = lambda d: T_SAT * np.log1p(d / T_SAT) if d > 0 else d
    a = arr[idx_rif]; r = ruo[idx_rif]
    cen = {x: float(a[r == x].mean()) for x in RUOLI}
    comp = a.copy()
    for x in RUOLI:
        m = r == x
        comp[m] = cen[x] + np.array([sat(v) for v in (a[m] - cen[x])])
    out = np.empty(len(arr))
    for x in RUOLI:
        mr = ruo == x
        mm = r == x
        mu, sd = float(comp[mm].mean()), float(comp[mm].std())
        c, s = float(ext_rif[mm].mean()), float(ext_rif[mm].std())
        v = arr[mr]
        vc = cen[x] + np.array([sat(t) for t in (v - cen[x])])
        out[mr] = c + (vc - mu) * (s / max(sd, 1e-9))
    return out



# ============================================================== la struttura algebrica
def struttura(b, W0, giudici, chiavi_extra):
    """C'e' un'informazione INDIPENDENTE in questi due, o sono gia' dentro gli altri?

    Alcuni pesi del modello sono a zero perche' l'autovalore piccolo della matrice
    di correlazione diceva dipendenza (esatta o approssimata) da altre voci: quello
    zero e' una constatazione algebrica. Questi due, invece, sono stati spenti a mano
    e a priori, contro il modello di un'altra taratura. Le due cose vanno distinte
    con un numero, non con la memoria di come ci si e' arrivati.

    TRE MISURE, in ordine di quanto contano:

      1. R^2 di ognuno sulle ALTRE colonne accese. Alto = la colonna e' gia' scritta
         negli altri e riaccenderla ridistribuisce credito invece di aggiungerlo.
      2. gli autovalori della matrice di correlazione, con e senza i due: se
         aggiungerli fa crollare il piu' piccolo, la base diventa mal condizionata e
         l'ottimo non e' piu' identificato (e' li' che nascono i cambi di segno).
      3. LA PROVA CHE DECIDE: la parte di ognuno ORTOGONALE a tutto il resto,
         correlata col RESIDUO del giudice. Se il giudice non vede nulla in quella
         parte, nessun peso puo' comprare accordo — qualunque cosa dicano le prime
         due. Se la vede, il segnale c'e' e il resto e' taratura.
    """
    K = list(b.keys)
    chiavi_extra = [k for k in chiavi_extra if k in b.idx_of]
    accese = [k for k in K if abs(W0["CEN"][b.idx_of[k]]) > 1e-12]
    Z = b.cal_z
    def col(k):
        return Z[:, b.idx_of[k]]

    print("\nSTRUTTURA ALGEBRICA DELLA BASE (%d colonne accese, %d presenze)"
          % (len(accese), len(Z)))
    A = np.column_stack([col(k) for k in accese])
    A = A - A.mean(axis=0)
    def autov(M):
        C = np.corrcoef(M, rowvar=False)
        return np.sort(np.linalg.eigvalsh(C))
    e0 = autov(A)
    print("   autovalori (base attuale): min %.5f  poi %.5f  %.5f   max %.3f"
          % (e0[0], e0[1], e0[2], e0[-1]))

    for k in chiavi_extra:
        x = col(k) - col(k).mean()
        beta, *_ = np.linalg.lstsq(A, x, rcond=None)
        res = x - A @ beta
        r2 = 1.0 - float(res.var() / x.var())
        e1 = autov(np.column_stack([A, x]))
        print("   %-20s R^2 sulle accese %.4f  (varianza sua %.1f%%)   "
              "autovalore minimo aggiungendola: %.5f"
              % (k, r2, 100 * (1 - r2), e1[0]))

    # --- la prova che decide: il residuo del giudice contro la parte ortogonale
    print("\n   LA PARTE ORTOGONALE, CONTRO IL RESIDUO DEL GIUDICE")
    ctx = vt.contesto(b, W0)
    arr = ctx["arr"]
    for nome in ("Statistico", "Redazione", "WhoScored"):
        G = giudici.get(nome) or {}
        idx = np.array([i for i, kk in enumerate(b.cal_key) if kk in G])
        if len(idx) < 100:
            continue
        e = np.array([G[b.cal_key[i]] for i in idx])
        # il residuo del giudice DOPO aver tolto il nostro voto (pendenza libera)
        v = arr[idx]
        p = np.polyfit(v, e, 1)
        resid = e - np.polyval(p, v)
        for k in chiavi_extra:
            x = col(k) - col(k).mean()
            beta, *_ = np.linalg.lstsq(A, x, rcond=None)
            orto = (x - A @ beta)[idx]
            if orto.std() < 1e-9:
                continue
            r = float(np.corrcoef(orto, resid)[0, 1])
            # in punti di voto: quanto vale una sd della parte ortogonale
            pend = float(np.polyfit(orto / orto.std(), resid, 1)[0])
            print("      %-11s vs %-20s r = %+.4f   pendenza %+.4f voti / sd"
                  % (nome, k, r, pend))


# ============================================================== la valutazione
def valuta(b, W, giudici, sotto):
    ctx = vt.contesto(b, W)
    arr = ctx["arr"]
    iS, xS = b.giud_righe["Statistico"]
    fin = con_saturazione(b, arr, iS, xS)
    out = {"cruscotto": ctx["cruscotto"], "sigma": ctx["ref"]["CEN"]["std"]}
    for nome, G in giudici.items():
        idx = np.array([i for i, k in enumerate(b.cal_key) if k in G])
        if not len(idx):
            continue
        e = np.array([G[b.cal_key[i]] for i in idx])
        out["r_" + nome] = float(np.corrcoef(arr[idx], e)[0, 1])
        out["rs_" + nome] = float(np.corrcoef(fin[idx], e)[0, 1])
        if nome in ("Statistico", "Redazione"):
            out["mae_" + nome] = float(np.abs(fin[idx] - e).mean())
    # I SOTTOGRUPPI: dove questi due pesi agiscono davvero.
    G = giudici["Statistico"]
    for nome, sel in sotto.items():
        idx = np.array([i for i, k in enumerate(b.cal_key) if k in G and sel[i]])
        if len(idx) < 20:
            continue
        e = np.array([G[b.cal_key[i]] for i in idx])
        out["bias_" + nome] = float((fin[idx] - e).mean())
        out["n_" + nome] = len(idx)
    return out


def riga(nome, m):
    print("%-26s %7.4f %7.4f %7.4f %7.4f | %6.4f | %+6.3f %+6.3f %+6.3f | %.4f" % (
        nome, m.get("r_Statistico", float("nan")), m.get("r_Redazione", float("nan")),
        m.get("r_SofaScore", float("nan")), m.get("r_WhoScored", float("nan")),
        m.get("mae_Statistico", float("nan")),
        m.get("bias_nitida_senza_assist", float("nan")),
        m.get("bias_nitida", float("nan")),
        m.get("bias_kp_alto_senza_nitida", float("nan")),
        m["sigma"]))


def main():
    b = prepara()
    fanta, stat = giudici_fogli(b)
    lunghi = {k for k, m in zip(b.cal_key, b.cal_min) if m >= 60}
    taglia = lambda G: {k: v for k, v in G.items() if k in lunghi}
    giudici = {"Statistico": stat, "Redazione": fanta,
               "SofaScore": taglia(giudice_sofascore(b)),
               "WhoScored": taglia(giudice_whoscored(b))}
    for n, g in giudici.items():
        print("   %-11s agganciati %d" % (n, len(g)))

    # --- i sottogruppi, dai totali veri
    mids = list(cr.Match.objects.filter(competition_season_id=STAGIONE)
                .values_list("id", flat=True))
    tot = cr._per_match_player_totals(mids)
    bcc = np.array([(tot.get(k) or {}).get("big_chance_created", 0.0) or 0.0
                    for k in b.cal_key])
    kp = np.array([(tot.get(k) or {}).get("key_passes", 0.0) or 0.0 for k in b.cal_key])
    ass = np.array([(tot.get(k) or {}).get("assists", 0.0) or 0.0 for k in b.cal_key])
    sotto = {"nitida": bcc >= 1,
             "nitida_senza_assist": (bcc >= 1) & (ass < 1),
             "kp_alto_senza_nitida": (kp >= 3) & (bcc < 1)}
    for n, s in sotto.items():
        print("   sottogruppo %-22s %d presenze" % (n, int(s.sum())))

    # --- fedelta': il banco riproduce il voto PRIMA dello stadio finale?
    W0 = {r: b.vettore_pesi(r) for r in RUOLI}
    from vfoot.services.classic_pagella import get_reference
    ref_vero = get_reference(STAGIONE)
    pre = {}
    for m in cr.Match.objects.filter(competition_season_id=STAGIONE):
        for row in cr.voto_puro_for_match(m, ref_vero):
            if row.get("rated") and row.get("role") in RUOLI:
                pre[(m.id, row["player_id"])] = row["voto_pre_scala"]
    ctx0 = vt.contesto(b, W0)
    d = np.array([ctx0["arr"][i] - pre[k] for i, k in enumerate(b.cal_key) if k in pre])
    print("\nFEDELTA' (banco vs voto_pre_scala della pipeline vera, %d presenze):" % len(d))
    print("   scarto medio %+.5f | massimo %.5f | oltre 0.01: %d"
          % (d.mean(), np.abs(d).max(), int((np.abs(d) > 0.01).sum())))

    struttura(b, W0, giudici, ("key_passes", "big_chance_created", "assists"))

    print("\n%-26s %7s %7s %7s %7s | %6s | %6s %6s %6s | %s" % (
        "modello", "Stat.", "Redaz.", "Sofa", "WhoSc.", "MAE", "b:nit-a", "b:nit",
        "b:kp", "sigma"))
    base = valuta(b, W0, giudici, sotto)
    riga("SPEDITO (kp=0, bcc=0)", base)

    def prova(nome, **kw):
        W = {r: W0[r].copy() for r in RUOLI}
        for k, v in kw.items():
            i = b.idx_of[k]
            for r in RUOLI:
                W[r][i] = v
        m = valuta(b, W, giudici, sotto)
        riga(nome, m)
        return m

    print("\n-- solo big_chance_created --")
    for v in (0.010, 0.020, 0.030, 0.045, 0.060, 0.080):
        prova("bcc=%.3f" % v, big_chance_created=v)
    print("\n-- solo key_passes --")
    for v in (0.010, 0.020, 0.030, 0.050, 0.070, 0.100):
        prova("kp=%.3f" % v, key_passes=v)
    print("\n-- tutti e due --")
    for a in (0.020, 0.030, 0.045):
        for c in (0.010, 0.020, 0.030):
            prova("bcc=%.3f kp=%.3f" % (a, c), big_chance_created=a, key_passes=c)
    print("\n-- e se la xA cedesse budget? (bcc acceso) --")
    for xa in (0.049, 0.040, 0.030, 0.020):
        for a in (0.020, 0.030, 0.045):
            prova("xA=%.3f bcc=%.3f" % (xa, a), expected_assists=xa, big_chance_created=a)


main()
