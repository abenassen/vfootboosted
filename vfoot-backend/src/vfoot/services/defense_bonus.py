"""Classic-mode defence modifier (bonus difesa).

Rules (league-configurable):
  * Awarded only to a defence at least FOUR strong. Which defence has to be four
    is the league's ``defense_bonus_gate``:
      - ``starters``  — four defenders in the XI AS SENT (a back four reached via
        substitutions does NOT qualify). The historical behaviour and the default.
      - ``effective`` — four defenders WITH A VOTE in the XI as it ended, so a
        substitute defender does qualify, and a starting back four reduced to three
        by an s.v. nobody could cover does not.
        Under the ``player`` deadline the bench is read defenders-first
        (``Ruleset.defence_first``), so a defender covers a non-defender only when
        no non-defender on the bench has a vote — and the "substitute qualifies"
        half of this gate reduces to that case. The half that always bites is the
        other one: a back four that loses a man does not collect.
    The gate is the ONLY thing the setting moves: under both readings the value is
    computed from the effective XI, because a vote that counted towards the total
    is a vote that was played.
  * Value = average of the 3 highest defender votes (voto puro, EXCLUDING bonus/malus)
    plus the goalkeeper vote (voto puro, EXCLUDING bonus/malus), divided by 4.
  * Banded bonus: +1 from 6.00, then one more at every 0.25 step. Le bande sono
    CHIUSE A SINISTRA e aperte a destra — la soglia appartiene alla banda che
    apre, non a quella che chiude:
        avg < 6.00           -> +0
        6.00 <= avg < 6.25   -> +1
        6.25 <= avg < 6.50   -> +2
        6.50 <= avg < 6.75   -> +3
        6.75 <= avg < 7.00   -> +4
        7.00 <= avg < 7.25   -> +5
        ...                  -> ...
  * Applied either added to the team's own score or subtracted from the opponent's
    (a reward to defences) — chosen per league.
"""

from __future__ import annotations

import math

# Mirrors FantasyLeague.DEF_GATE_* — kept here as plain strings so the calculation
# stays importable without the models (it is pure arithmetic, and the seed and the
# tests use it that way).
GATE_STARTERS = "starters"
GATE_EFFECTIVE = "effective"


def defense_bonus_value(avg: float) -> float:
    """+1 dalla media 6.00, e uno in piu' a ogni scatto di 0.25. Lineare, senza
    tetto. La soglia STA NELLA BANDA CHE APRE: 6.00 -> +1, 6.25 -> +2, 6.50 -> +3.

    CORRETTO il 01/09/2026, e non e' un arrotondamento: era una lettura sbagliata
    del regolamento. Le bande erano chiuse a DESTRA (``ceil`` sulla distanza dal
    6.00, con 6.00 stesso a zero), quindi su ogni soglia esatta davamo un punto in
    meno — 6.00 valeva 0 invece di 1, 6.25 valeva 1 invece di 2, e cosi' via. In
    mezzo alle bande il valore era ed e' lo stesso.

    PERCHE' NON ERA UN CASO DI MARGINE. La media e' (3 difensori + portiere) / 4 e
    i voti stanno sulla griglia dei mezzi punti, quindi la media e' SEMPRE un
    multiplo di 0.125: le soglie (i multipli di 0.25) sono meta' esatta dei valori
    che la media puo' assumere. Meta' delle difese premiate prendeva un punto in
    meno del dovuto, e il 6.00 tondo — il valore piu' frequente di tutti — non
    prendeva niente.

    Il +1e-9 tiene la soglia esatta (6.25) NELLA banda che apre, che senza sarebbe
    a caso del float."""
    if avg < 6.0:
        return 0.0
    return float(math.floor((avg - 6.0) / 0.25 + 1e-9) + 1)


def compute_defense_bonus(
    starter_lineup_roles: list[str],
    defender_votes: list[float],
    gk_vote: float | None,
    gate: str = GATE_STARTERS,
) -> dict:
    """``starter_lineup_roles`` = the roles (GK/DEF/MID/ATT) of the XI AS SENT, which
    the ``starters`` gate counts. ``defender_votes`` = voto puro of the effective XI's
    defenders that have a vote, which is both what the ``effective`` gate counts and
    what the average is made of under either gate. ``gk_vote`` = the effective
    keeper's voto puro.

    Returns {eligible, reason, avg, bonus, gate}. ``reason`` names the gate that
    refused, so the tabellino can say which rule the team fell foul of instead of
    reciting whichever one the page was written around.
    """
    voted = sorted((v for v in defender_votes if v is not None), reverse=True)
    out = {"eligible": False, "reason": "", "avg": None, "bonus": 0.0, "gate": gate}

    if gate == GATE_EFFECTIVE:
        # No separate "at least 3 with a vote" check to make here: four voted
        # defenders is a stricter demand than three, and it is the same demand.
        if len(voted) < 4:
            return out | {"reason": "meno_di_4_difensori_con_voto"}
    else:
        if sum(1 for r in starter_lineup_roles if r == "DEF") < 4:
            return out | {"reason": "meno_di_4_difensori_titolari"}
    if gk_vote is None:
        return out | {"reason": "portiere_senza_voto"}
    if len(voted) < 3:
        return out | {"reason": "meno_di_3_difensori_con_voto"}
    avg = (sum(voted[:3]) + gk_vote) / 4.0
    return out | {"eligible": True, "avg": round(avg, 3), "bonus": defense_bonus_value(avg)}
