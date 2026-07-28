"""Classic-mode defence modifier (bonus difesa).

Rules (league-configurable):
  * Awarded only if AT LEAST 4 defenders START the match (a back line reached via
    substitutions does NOT qualify).
  * Value = average of the 3 highest defender votes (voto puro, EXCLUDING bonus/malus)
    plus the goalkeeper vote (voto puro, EXCLUDING bonus/malus), divided by 4.
  * Banded bonus: +1 every 0.25 above 6.00, linear and uncapped (inclusive upper
    bound):
        avg <= 6.00        -> +0
        6.00 < avg <= 6.25 -> +1
        6.25 < avg <= 6.50 -> +2
        6.50 < avg <= 6.75 -> +3
        6.75 < avg <= 7.00 -> +4
        7.00 < avg <= 7.25 -> +5
        ...                -> ...
  * Applied either added to the team's own score or subtracted from the opponent's
    (a reward to defences) — chosen per league.
"""

from __future__ import annotations

import math


def defense_bonus_value(avg: float) -> float:
    """+1 for every 0.25 above 6.00, banded on the inclusive upper bound
    (avg 6.25 -> +1, 6.50 -> +2, …). Linear, no cap. The −1e-9 keeps exact band
    boundaries (e.g. 6.25) in the LOWER band despite float rounding."""
    if avg <= 6.0:
        return 0.0
    return float(math.ceil((avg - 6.0) / 0.25 - 1e-9))


def compute_defense_bonus(
    starter_lineup_roles: list[str],
    defender_votes: list[float],
    gk_vote: float | None,
) -> dict:
    """``starter_lineup_roles`` = the STARTING XI's roles (GK/DEF/MID/ATT) to check the
    >=4-defenders-at-kickoff gate. ``defender_votes`` = voto puro of the defenders that
    have a vote (the effective lineup's defenders). ``gk_vote`` = the keeper's voto puro.

    Returns {eligible, reason, avg, bonus}."""
    starting_def = sum(1 for r in starter_lineup_roles if r == "DEF")
    if starting_def < 4:
        return {"eligible": False, "reason": "meno_di_4_difensori_titolari",
                "avg": None, "bonus": 0.0}
    if gk_vote is None:
        return {"eligible": False, "reason": "portiere_senza_voto", "avg": None, "bonus": 0.0}
    top3 = sorted((v for v in defender_votes if v is not None), reverse=True)[:3]
    if len(top3) < 3:
        return {"eligible": False, "reason": "meno_di_3_difensori_con_voto",
                "avg": None, "bonus": 0.0}
    avg = (sum(top3) + gk_vote) / 4.0
    return {"eligible": True, "reason": "", "avg": round(avg, 3),
            "bonus": defense_bonus_value(avg)}
