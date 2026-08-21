"""Classic-mode formation rules and lineup validation.

Classic fantacalcio fixes the shape of a legal XI by role. The roster page (and the
save endpoint) must enforce it, and the substitution algorithm must keep it legal
when it swaps a benched player in. This module is the single source of truth for
those rules, shared by the API (server-side validation + frontend-facing constants)
and the substitution service.

Roles use the frontend taxonomy GK/DEF/MID/ATT (the lineup endpoint maps the frozen
LeaguePlayerRole POR/DIF/CEN/ATT onto these). Constants are mirrored to the client
verbatim so the page and the server validate identically.
"""

from __future__ import annotations

ROLES = ("GK", "DEF", "MID", "ATT")
ROLE_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "ATT": 3}  # P, D, C, A
ROLE_LABEL = {"GK": "POR", "DEF": "DIF", "MID": "CEN", "ATT": "ATT"}

XI = 11

# Bounds per reparto di un XI classic legale. Il tetto NON e' lo stesso ovunque, ed
# e' deliberato: in difesa si resta sotto i sei (max 5, quindi niente 6-3-1), mentre
# a centrocampo il sesto uomo e' legale e il 3-6-1 e' un modulo come gli altri.
# Nessun reparto puo' restare vuoto: a farlo rispettare sono i minimi di DEF (3) e
# ATT (1) — il centrocampo ha min 0 perche' l'aritmetica lo tiene comunque a 2 o
# piu' (dieci di movimento, al massimo 5 dietro e 3 davanti). Un solo portiere.
CLASSIC_CONSTRAINTS = {
    "starters": XI,
    "per_role": {
        "GK": {"min": 1, "max": 1},
        "DEF": {"min": 3, "max": 5},
        "MID": {"min": 0, "max": 6},
        "ATT": {"min": 1, "max": 3},
    },
}


def role_counts(roles: list[str]) -> dict[str, int]:
    return {r: sum(1 for x in roles if x == r) for r in ROLES}


def validate_classic_lineup(starter_roles: list[str]) -> list[str]:
    """Return a list of human-readable (Italian) violations for a classic XI given
    the roles of the 11 chosen starters. Empty list == legal."""
    errors: list[str] = []
    n = len(starter_roles)
    if n != XI:
        errors.append(f"Servono esattamente {XI} titolari (ne hai {n}).")
    counts = role_counts(starter_roles)
    bounds = CLASSIC_CONSTRAINTS["per_role"]
    if counts["GK"] != 1:
        errors.append(
            "Manca il portiere." if counts["GK"] == 0 else "Un solo portiere fra i titolari."
        )
    if counts["DEF"] < bounds["DEF"]["min"]:
        errors.append(f"Almeno {bounds['DEF']['min']} difensori (ne hai {counts['DEF']}).")
    if counts["ATT"] < bounds["ATT"]["min"]:
        errors.append(f"Almeno {bounds['ATT']['min']} attaccante (ne hai {counts['ATT']}).")
    if counts["ATT"] > bounds["ATT"]["max"]:
        errors.append(f"Al massimo {bounds['ATT']['max']} attaccanti (ne hai {counts['ATT']}).")
    # Il messaggio legge il tetto dal dizionario invece di dire "meno di 6": i due
    # reparti hanno massimi diversi, e una frase che ne nomina uno solo mentirebbe
    # sull'altro alla prima volta che uno dei due cambia.
    for role in ("DEF", "MID"):
        if counts[role] > bounds[role]["max"]:
            errors.append(
                f"Al massimo {bounds[role]['max']} {ROLE_LABEL[role]} (ne hai {counts[role]})."
            )
    return errors


def is_legal_classic(starter_roles: list[str]) -> bool:
    return not validate_classic_lineup(starter_roles)
