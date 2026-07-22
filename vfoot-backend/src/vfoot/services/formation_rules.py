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

# Per-role bounds for a legal classic XI. `max_strict` encodes "strictly fewer than
# 6 in any role" (confirmed rule) as an inclusive max of 5; ATT is further capped at
# 3 and DEF floored at 3; exactly one GK.
CLASSIC_CONSTRAINTS = {
    "starters": XI,
    "per_role": {
        "GK": {"min": 1, "max": 1},
        "DEF": {"min": 3, "max": 5},
        "MID": {"min": 0, "max": 5},
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
    for role in ("DEF", "MID"):
        if counts[role] > bounds[role]["max"]:
            errors.append(
                f"Meno di 6 {ROLE_LABEL[role]} ({bounds[role]['max']} max, ne hai {counts[role]})."
            )
    return errors


def is_legal_classic(starter_roles: list[str]) -> bool:
    return not validate_classic_lineup(starter_roles)
