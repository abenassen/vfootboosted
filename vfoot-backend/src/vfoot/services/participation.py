"""La PARTECIPAZIONE di un giocatore alla partita, per l'adeguamento al risultato.

Nasce dal caso Modric (Milan-Inter 3-1, 31/10/2026): 88 tocchi, regia per tutta la
partita, 6,0 — lo stesso voto di Goncalo Ramos, 32 tocchi e nessuna azione. Il voto
di merito di Modric era esattamente nella media del ruolo, e la spinta della
vittoria (che fino al rilascio 1.21 alzava SOLO chi stava sotto il centro) non gli
dava niente, mentre portava Ramos da 5,5 a 6,0. Scelta di prodotto di Andrea
(02/11/2026): chi ha partecipato di piu' alla vittoria deve risentirne di piu'.

Che cosa vuol dire partecipare, misurato:

    p = max( percentile dei TOCCHI , percentile delle AZIONI )
    AZIONI = passaggi chiave + tiri + dribbling riusciti

entrambi per 90 minuti, contro i giocatori dello STESSO ruolo con almeno 80' della
stagione di riferimento (25-26, tabella congelata in ``data/participation_reference
.json``). Il MASSIMO e non una somma, ed e' la misura a deciderlo: chi tocca pochi
palloni ma entra in qualche azione pericolosa partecipa quanto chi gira il gioco, e
una somma pesata (tocchi + k*azioni) diluiva i tocchi senza ridargli la spinta. Sulla
25-26 (3.903 presenze 80'+, le due pagelle): solo tocchi costava +0,0009/+0,0032 di
errore medio contro Statistico/Redazione; il massimo GUADAGNA 0,0035/0,0012. Sulle
prime cinque giornate della 26-27 la differenza e' nel rumore (una ventina di voti).

Le voci difensive (contrasti, intercetti) NON ci sono di proposito: rendono uguale, e
con loro un attaccante che non ha giocato il pallone sale di percentile per due
intercetti. I tiri vengono dalla mappa dei tiri (autogol esclusi, rigori inclusi).

Per chi non ha giocato tutta la partita il percentile del RITMO (per 90') viene
tirato verso 0,5 in proporzione ai minuti non giocati: dieci tocchi in dieci minuti
non sono la partita di Modric, e a partita in corso la partecipazione cresce con lei.
"""
from __future__ import annotations

import hashlib
import json
from bisect import bisect_left, bisect_right
from collections import Counter
from pathlib import Path

from django.conf import settings

DATA_PATH = Path(settings.BASE_DIR) / "vfoot" / "data" / "participation_reference.json"

ACTION_KEYS = ("key_passes", "shots", "dribbles_won")
ROLES = ("DIF", "CEN", "ATT")
# La popolazione: presenze da almeno tanti minuti. E' quella su cui la regola e'
# stata misurata; gli spezzoni ne restano fuori perche' il loro ritmo per 90' e'
# rumore (un tocco in un minuto e' «90 tocchi»).
POPULATION_MIN_MINUTES = 80
# Valore neutro: a chi non ha ruolo di movimento, o non ha minuti.
NEUTRAL = 0.5

_cache: dict | None = None


def actions(feats: dict) -> float:
    return sum(float(feats.get(k, 0.0) or 0.0) for k in ACTION_KEYS)


def touches(feats: dict) -> float:
    return float(feats.get("touches", 0.0) or 0.0)


def _per90(value: float, minutes: int) -> float:
    return value * 90.0 / max(1, minutes)


def build(rows) -> dict:
    """La tabella da righe ``(ruolo, minuti, feats)``: per ruolo, i valori per 90'
    (arrotondati al decimo) ordinati con la loro frequenza. Chiavi portabili: nessun
    id di giocatore o di partita, solo distribuzioni."""
    pops = {r: {"touches": Counter(), "actions": Counter()} for r in ROLES}
    for role, minutes, feats in rows:
        if role not in pops or minutes < POPULATION_MIN_MINUTES:
            continue
        pops[role]["touches"][round(_per90(touches(feats), minutes), 1)] += 1
        pops[role]["actions"][round(_per90(actions(feats), minutes), 1)] += 1
    return {
        "action_keys": list(ACTION_KEYS),
        "population_min_minutes": POPULATION_MIN_MINUTES,
        "roles": {r: {k: sorted([v, n] for v, n in c.items()) for k, c in d.items()}
                  for r, d in pops.items()},
    }


def save(table: dict, season_id: int) -> None:
    DATA_PATH.write_text(json.dumps({"season_id": season_id, **table},
                                    indent=1, sort_keys=True))
    clear_cache()


def _load() -> dict | None:
    global _cache
    if _cache is None:
        if not DATA_PATH.exists():
            return None
        raw = json.loads(DATA_PATH.read_text())
        # expanded into sorted value lists once: percentile = two bisections
        roles = {}
        for role, d in raw.get("roles", {}).items():
            roles[role] = {}
            for key, pairs in d.items():
                vals = []
                for v, n in pairs:
                    vals.extend([float(v)] * int(n))
                roles[role][key] = vals
        _cache = {"raw": raw, "roles": roles}
    return _cache


def clear_cache() -> None:
    global _cache
    _cache = None


def sha() -> str | None:
    """L'impronta della tabella, per ``scoring_fingerprint``: ricostruirla sposta voti."""
    if not DATA_PATH.exists():
        return None
    return hashlib.sha256(DATA_PATH.read_bytes()).hexdigest()[:16]


def _percentile(vals: list[float], x: float) -> float:
    """Rango medio: P(X < x) + P(X = x)/2. Con molti pari merito (le azioni sono
    spesso zero) e' l'unica lettura che non regala ne' toglie a chi sta nel mucchio."""
    if not vals:
        return NEUTRAL
    lo, hi = bisect_left(vals, x), bisect_right(vals, x)
    return (lo + 0.5 * (hi - lo)) / len(vals)


def participation(role: str, feats: dict, minutes: int) -> float:
    """p in [0, 1]. ``NEUTRAL`` se il ruolo non e' di movimento o manca la tabella."""
    data = _load()
    if not data or role not in data["roles"] or minutes <= 0:
        return NEUTRAL
    pops = data["roles"][role]
    pt = _percentile(pops["touches"], round(_per90(touches(feats), minutes), 1))
    pa = _percentile(pops["actions"], round(_per90(actions(feats), minutes), 1))
    p = max(pt, pa)
    # gli spezzoni verso il neutro, in proporzione ai minuti non giocati
    lam = min(1.0, minutes / 90.0)
    return NEUTRAL + lam * (p - NEUTRAL)
