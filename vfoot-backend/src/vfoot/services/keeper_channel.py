"""Il canale del portiere: tiro per tiro, a valore atteso zero per costruzione.

Fino all'08/10/2026 il portiere era un INDICE come un giocatore di movimento:
dieci feature del fornitore (gol evitati, parate, parate in area, uscite, errori,
passaggi) standardizzate, pesate, z-scorate contro la popolazione dei portieri.
Funzionava in media e sbagliava nei casi: strapagava la fascia di parate 0,3-0,7
(+0,07/+0,19 a parata contro i giudici), contava le parate DUE volte (nell'xGOT e
nel conteggio), e un gol regalato costava −0,60 sia quando era una papera sia
quando era un tiro deviato in una selva di gambe. La revisione della sosta
(``experiments-revisione-sosta/portieri/ANALISI_PORTIERI.md``, 19 parti) ha
misurato la funzione di valore implicita dei giudici tiro per tiro e ha
congelato questa forma, provata fuori campione sulla 26-27.

OGNI TIRO AFFRONTATO vale, prima della scala:

    parata        + A * p^G                       p = xGOT (calibrato: parte 3)
    gol subito    - B(dist) * (1 - p)^D           B da 0,45 (vicino) a 1,0 (lontano), logistica a 18 m
    rigore        K * (p - gol)                   escursione amplificata, nessun premio fisso

Le tre proprieta' che contano:

* la non linearita' SULLE PARATE (G > 1) sopprime con continuita' le parate di
  routine — un tiro a xGOT 0,05 vale +0,02, a 0,30 +0,20, a 0,90 +0,82 — senza
  scalini e senza franchigia: e' la forma che i giudici usano (parte 1), ed e'
  quella che toglie il portiere «fenomeno» che ha respinto dieci palloni fattibili;
* il costo del GOL si concentra sull'xGOT basso (D = 2) ed e' modulato dalla
  DISTANZA: da lontano un gol a xGOT basso e' il portiere scavalcato o bucato, da
  vicino e' quasi sempre mischia. E' l'unico modulatore su cui i due giudici
  concordano, e senza di lui la stessa escursione fa esplodere la coda (87/17
  contro 61/7 di scarti ≥1,0/≥1,5: parte 10);
* la PAPERA RICONOSCIUTA dal fornitore (``errors_led_to_goal``) non e' un addendo:
  il gol che nella partita costa gia' di piu' costa IN TUTTO ``ERROR_GOAL_TOTAL``.
  Era −1,77 sommando le due voci, i giudici dicono −1,35/−1,20 (parte 17).

Poi la RIBATTUTA (parte 9): una parata seguita entro ``REBOUND_SECONDS`` da un
gol della stessa squadra non si paga, e costa in piu' meta' di quel che il primo
tiro avrebbe costato da gol — la respinta corta che regala il tap-in si vede dai
secondi della mappa dei tiri e coincide con «ParriedDanger» di Opta in 45 casi
su 58. Le USCITE restano un canale a se' (crediti piccoli, costi veri): i giudici
non le premiano, ma lo scopo della revisione e' un voto PIU' espressivo e non
meno (decisione del 21/09/2026). Il MOMENTO della parata (quanto sarebbe costato
un gol in quell'istante) pesa ``MOMENT_LAMBDA`` sulle sole parate: oltre 0,5
peggiora, sui gol peggiora sempre (26/09/2026).

I MINUTI: voto(m) = base + somma dei tiri visti + (1 - t) * valore medio di una
partita intera. Niente pavimento a 55', niente attenuazione, niente curva per
minuto: la forma e' una somma e i tiri hanno il minuto, quindi a orologio fermato
il voto di partenza resta fermo a due centesimi e il ritorno verso la media
EMERGE (parte 3 di ANALISI_MINUTAGGIO).

LA SCALA e' riportata alla dispersione dello Statistico, l'intercetta e l'errore
che porta a un tiro sono stimati sulla stagione di taratura e CONGELATI qui
(``CALIBRATION``, scritta da ``experiments-revisione-sosta/portieri/build_keeper_calibration.py``).
Il portiere non passa dallo stadio finale della scala (lo stadio e' del
movimento) ne' dalla mitigazione del risultato: la sua correzione e' lineare.

Cio' che il canale NON vede, dichiarato: la papera non segnalata su tiro facile,
la respinta maldestra senza ribattuta entro cinque secondi, il rinvio sbagliato
senza tiro, la deviazione (nessun fornitore la riporta). Sono le 8-12 divergenze
gravi a stagione che nessuna forma toglie (parte 16: la forma cambia QUALI casi
si sbagliano, non quanti).
"""
from __future__ import annotations

import math
from collections import defaultdict

from realdata.models import MatchAppearance, MatchShot, Player
from vfoot.services import goal_impact

# --- la forma -----------------------------------------------------------------
SAVE_A = 0.8
SAVE_G = 1.3
GOAL_B_NEAR = 0.45
GOAL_B_FAR = 1.0
GOAL_B_MID_M = 18.0
GOAL_B_WIDTH_M = 3.0
GOAL_D = 2.0
PENALTY_K = 1.25
ERROR_GOAL_TOTAL = 1.2
REBOUND_SECONDS = 5
REBOUND_BETA = 0.5
EXIT_GOOD = 0.05        # uscita alta riuscita, uscita da libero riuscita
EXIT_PUNCH = 0.025      # respinta di pugno
EXIT_BAD = -0.20        # cross non trattenuto, uscita da libero fallita
MOMENT_LAMBDA = 0.5     # sulle sole parate
# Un tiro senza coordinate (riga importata prima del campo, cache incompleta) si
# tratta come un tiro dalla distanza mediana dei tiri nello specchio della 25-26.
DEFAULT_DISTANCE_M = 16.0

# --- la calibrazione, CONGELATA sulla 25-26 (v. build_keeper_calibration.py) ----
# centre:    il voto del portiere medio (media dei giudici sulle presenze intere)
# scale:     punti di voto per punto di valore (dispersione dello Statistico)
# mean_full: il valore medio di una partita intera (tiri + uscite + errori)
# err_shot:  il costo, in valore, di un errore che porta a un tiro
# intercept: il voto (pre-scala) di chi non ha affrontato niente in 90 minuti,
#            scritto per intero perche' lo si legga: centre - scale * mean_full
CALIBRATION = {
    "centre": 6.1777,
    "scale": 1.1596,
    "mean_full": 0.0995,
    "err_shot": -0.1717,
}


def goal_cost_factor(distance_m: float | None) -> float:
    """B(dist): da vicino il gol a xGOT basso e' mischia, da lontano e' il
    portiere; la logistica passa da ``GOAL_B_NEAR`` a ``GOAL_B_FAR`` attorno ai
    18 metri, larga 3."""
    d = DEFAULT_DISTANCE_M if distance_m is None else float(distance_m)
    return GOAL_B_NEAR + (GOAL_B_FAR - GOAL_B_NEAR) / (
        1.0 + math.exp(-(d - GOAL_B_MID_M) / GOAL_B_WIDTH_M))


def shot_value(xgot: float, is_goal: bool, distance_m: float | None = None,
               is_penalty: bool = False) -> float:
    """Quanto vale UN tiro affrontato, prima della scala e prima delle regole di
    partita (ribattuta, tetto sull'errore). Equo: su un tiro a xGOT p, il valore
    atteso di parata e gol e' circa zero."""
    p = min(max(float(xgot or 0.0), 0.0), 1.0)
    if is_penalty:
        return PENALTY_K * (p - (1.0 if is_goal else 0.0))
    if is_goal:
        return -goal_cost_factor(distance_m) * (1.0 - p) ** GOAL_D
    return SAVE_A * p ** SAVE_G


def match_value(shots: list[dict], errors_to_goal: int, exits: dict,
                errors_to_shot: float = 0.0) -> dict:
    """Il valore di una partita, con le regole che legano i tiri fra loro.

    ``shots``: [{minute, seconds, xgot, is_goal, is_penalty, distance_m, weight}],
    ``weight`` il peso del momento (media 1). Restituisce le righe, una per tiro,
    con ``points`` gia' comprensivi di ribattuta e tetto sull'errore, e i
    totali; tutto PRIMA della scala."""
    rows = []
    for s in shots:
        v = shot_value(s["xgot"], s["is_goal"], s.get("distance_m"), s.get("is_penalty", False))
        if not s["is_goal"] and not s.get("is_penalty"):
            v *= 1.0 + MOMENT_LAMBDA * (float(s.get("weight", 1.0)) - 1.0)
        rows.append({**s, "points": v, "kind": (
            "penalty" if s.get("is_penalty") else "goal" if s["is_goal"] else "save")})
    # LA RIBATTUTA: la parata non si paga, e costa meta' del gol che il primo tiro
    # sarebbe stato. Si riconosce dai secondi; senza secondi non si vede.
    for i, s in enumerate(rows):
        if s["is_goal"] or s.get("is_penalty") or s.get("seconds") is None:
            continue
        after = [t for t in rows if t.get("seconds") is not None
                 and 0 < t["seconds"] - s["seconds"] <= REBOUND_SECONDS]
        if after and min(after, key=lambda t: t["seconds"])["is_goal"]:
            s["points"] = -REBOUND_BETA * goal_cost_factor(s.get("distance_m")) * (
                1.0 - min(max(float(s["xgot"] or 0.0), 0.0), 1.0)) ** GOAL_D
            s["kind"] = "rebound"
    # IL TETTO SULL'ERRORE SEGNALATO: il fornitore dice QUANTI errori hanno
    # portato a un gol, non quali; il gol che gia' costa di piu' e' quello (batte
    # perfino l'aggancio vero agli eventi Opta: parte 17). Se e' GIA' piu' caro,
    # resta com'e'; un errore senza un gol da addebitare (autogol, gol fuori dalla
    # mappa) costa il tetto da solo.
    goals = sorted([i for i, s in enumerate(rows) if s["is_goal"] and not s.get("is_penalty")],
                   key=lambda i: rows[i]["points"])
    n_err = int(errors_to_goal or 0)
    for i in goals[:n_err]:
        if -rows[i]["points"] < ERROR_GOAL_TOTAL:
            rows[i]["points"] = -ERROR_GOAL_TOTAL
        rows[i]["flagged_error"] = True
    orphan_errors = max(0, n_err - len(goals))
    exits_value = (EXIT_GOOD * (float(exits.get("good", 0.0)))
                   + EXIT_PUNCH * float(exits.get("punch", 0.0))
                   + EXIT_BAD * float(exits.get("bad", 0.0)))
    shots_value = sum(r["points"] for r in rows)
    err_shot_value = CALIBRATION["err_shot"] * float(errors_to_shot or 0.0)
    orphan_value = -ERROR_GOAL_TOTAL * orphan_errors
    return {
        "shots": rows,
        "shots_value": shots_value,
        "exits": dict(exits),
        "exits_value": exits_value,
        "orphan_errors": orphan_errors,
        "orphan_value": orphan_value,
        "errors_to_shot": float(errors_to_shot or 0.0),
        "err_shot_value": err_shot_value,
        "value": shots_value + exits_value + orphan_value + err_shot_value,
    }


def completion_value(minutes: int) -> float:
    """Il valore dei minuti NON visti: la media di una partita intera, in
    proporzione. Zero a partita intera."""
    t = min(max(int(minutes or 0), 0), 90) / 90.0
    return (1.0 - t) * CALIBRATION["mean_full"]


def vote_from_value(value: float, minutes: int) -> float:
    """Il voto pre-arrotondamento: centro + scala * (valore completato - media)."""
    c = CALIBRATION
    return c["centre"] + c["scale"] * (value + completion_value(minutes) - c["mean_full"])


def base_vote(minutes: int) -> float:
    """Il voto di PARTENZA della spiegazione: chi non ha affrontato niente nei
    minuti visti e ha fatto la media nel resto."""
    return vote_from_value(0.0, minutes)


def points_per_value() -> float:
    """Punti di voto per punto di valore: la scala, per righe e tabelle."""
    return CALIBRATION["scale"]


# --- i dati di una partita ------------------------------------------------------
def _exits_of(raw: dict | None, feats: dict) -> dict:
    """Le uscite: le riuscite dai totali del fornitore (che le abbiamo gia' come
    feature), le fallite dalla statistica grezza, dove sola si trova l'uscita da
    libero tentata e non riuscita."""
    raw = raw or {}

    def g(key):
        try:
            return float(raw.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    good = float(feats.get("gk_high_claims", 0.0) or 0.0) + float(feats.get("gk_sweeper", 0.0) or 0.0)
    punch = float(feats.get("gk_punches", 0.0) or 0.0)
    failed_sweeper = max(0.0, g("totalKeeperSweeper") - g("accurateKeeperSweeper"))
    bad = float(feats.get("gk_crosses_not_claimed", 0.0) or 0.0) + failed_sweeper
    return {"good": good, "punch": punch, "bad": bad}


def details_for_matches(match_ids, minutes: dict, totals: dict,
                        keepers: set | None = None) -> dict:
    """{(match_id, player_id): dettaglio} per ogni portiere in campo.

    I tiri sono quelli NELLO SPECCHIO affrontati mentre lui era fra i pali: parati
    (un xGOT c'e') o entrati; il tiro «parato» senza xGOT e' il salvataggio sulla
    linea di un compagno, non suo. L'autogol di un compagno resta fuori (la sua
    difficolta' e' gia' restituita altrove, v. ``_merge_own_goal_relief``), il
    rigore entra con la sua regola. Il MOMENTO e' letto dal lato che subisce, come
    per il gol subito (v. ``goal_impact.conceded_by_side``)."""
    from vfoot.services.classic_rating import (
        is_own_goal, match_lineup_keepers, on_pitch_windows,
    )
    ids = list(match_ids)
    if not ids:
        return {}
    if keepers is None:
        keepers = set(Player.objects.filter(is_goalkeeper=True).values_list("id", flat=True))
    lineup_keepers = match_lineup_keepers(ids)
    apps = {(a["match_id"], a["player_id"]): a
            for a in MatchAppearance.objects.filter(match_id__in=ids)
            .values("match_id", "player_id", "side", "is_starter", "raw_stats")}
    windows = on_pitch_windows(ids, minutes, {k: (a["side"], a["is_starter"])
                                              for k, a in apps.items()})
    xp = goal_impact.fixed_xp_table()
    _band, p95 = goal_impact.fixed_band()
    by_match: dict[int, list] = defaultdict(list)
    for s in (MatchShot.objects.filter(match_id__in=ids)
              .values("match_id", "player_id", "minute", "elapsed_seconds", "team_side",
                      "shot_type", "xgot", "is_goal", "situation", "distance_m")):
        if s["minute"] is not None:
            by_match[s["match_id"]].append(s)
    out = {}
    for (mid, pid), a in apps.items():
        if pid not in keepers and pid not in lineup_keepers.get(mid, ()):
            continue
        if minutes.get((mid, pid), 0) <= 0:
            continue
        side = a["side"]
        lo, hi = windows.get((mid, pid), (0.0, 0.0))
        shots = sorted(by_match.get(mid, []), key=lambda s: (s["minute"], s["elapsed_seconds"] or 0))
        goals = [s for s in shots if s["is_goal"]]
        side_of = {k[1]: v["side"] for k, v in apps.items() if k[0] == mid}
        faced = []
        for s in shots:
            if s["team_side"] == side or not (lo <= s["minute"] <= hi):
                continue
            if s["shot_type"] not in ("save", "goal"):
                continue
            if is_own_goal(s["shot_type"], s["team_side"], side_of.get(s["player_id"])):
                continue
            xgot = float(s["xgot"] or 0.0)
            if not s["is_goal"] and xgot <= 0.0:
                continue                 # salvato sulla linea da un compagno
            subiti = sum(1 for g in goals if g["team_side"] != side and g["minute"] < s["minute"])
            fatti = sum(1 for g in goals if g["team_side"] == side and g["minute"] < s["minute"])
            weight = goal_impact.conceded_weight(
                goal_impact.importance(xp, s["minute"], subiti - fatti - 1), p95)
            faced.append({
                "minute": s["minute"], "seconds": s["elapsed_seconds"], "xgot": xgot,
                "is_goal": bool(s["is_goal"]), "is_penalty": s["situation"] == "penalty",
                "distance_m": s["distance_m"], "situation": s["situation"] or "",
                "weight": weight,
            })
        feats = totals.get((mid, pid), {}) or {}
        detail = match_value(faced, int(round(float(feats.get("errors_led_to_goal", 0.0) or 0.0))),
                             _exits_of(a.get("raw_stats"), feats),
                             float(feats.get("errors_led_to_shot", 0.0) or 0.0))
        detail["minutes"] = minutes.get((mid, pid), 0)
        detail["completion"] = completion_value(detail["minutes"])
        out[(mid, pid)] = detail
    return out


def vote_for(detail: dict) -> float:
    return vote_from_value(detail["value"], detail["minutes"])
