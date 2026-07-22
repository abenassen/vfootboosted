"""Say, in words, why a voto puro came out where it did.

A number a player cannot interrogate is a number he will not trust — especially
one produced by a weighted index of fifteen-odd measures. The vote itself is
already explainable in principle: it is a sum of weighted terms, z-scored within
the role. This turns that structure into a handful of sentences.

Two choices make the output honest rather than merely plausible:

* contributions are expressed in VOTE POINTS, not in index units. "Duels: +0.35"
  means those duels moved his vote by a third of a point. Index units would be
  unfalsifiable — nobody can tell whether 0.42 of an index is a lot.
* every term is measured AGAINST THE AVERAGE PLAYER IN HIS ROLE, not against
  zero. A defender who made the usual number of clearances did nothing
  remarkable, and saying "clearances +0.4" would be flattery. What explains a
  6.5 rather than a 6 is only where he departed from his peers.

Bonus and malus (goals, assists, cards) are deliberately absent: they are added
after the voto puro, in the open, and the user can already see them.
"""
from __future__ import annotations

from vfoot.services.classic_rating import (
    DEF_EXPOSURE_WEIGHT, EXTRAP_FLOOR_MINUTES, GK_PER90_WEIGHTS, GK_TOTAL_WEIGHTS,
    PER90_WEIGHTS, SHRINKAGE_MINUTES, SIGNED_FEATURES, TOTAL_WEIGHTS, VOTE_SPREAD_K,
    _compress, _compress_signed,
)
from realdata.models import Player

# What each feature is called when we have to say it out loud, and how to say it.
#
# "count" features are continuous and only mean something COMPARED to the role
# average, so they are announced as molti/pochi. Getting this wrong produces
# sentences that are arithmetically right and read as nonsense — the first draft
# said "Bene: duelli persi" for a defender who had lost FEWER duels than his
# peers, and "Male: duelli vinti" for one who had won fewer.
#
# "event" features are rare and discrete. Nobody wants to hear that a player
# conceded fewer penalties than average; those are reported only when they
# actually happened.
COUNT, EVENT = "count", "event"
# Quantifier pairs, because Italian will not let a single "molti/pochi" serve:
# "molti respinte" and "pochi occasioni" are the kind of thing that makes an
# explanation feel machine-made even when its arithmetic is right.
QUANTIFIERS = {"mp": ("molti", "pochi"), "fp": ("molte", "poche"),
               "ms": ("molto", "poco"), "fs": ("molta", "poca")}
LABELS = {
    "expected_assists": ("occasioni create per i compagni", COUNT, "fp"),
    "xg_on_target": ("conclusioni di qualita'", COUNT, "fp"),
    "xg_shots": ("posizioni di tiro conquistate", COUNT, "fp"),
    "big_chance_created": ("un'occasione nitida creata", EVENT, None),
    "key_passes": ("passaggi chiave", COUNT, "mp"),
    "shots_on_target": ("tiri nello specchio", COUNT, "mp"),
    "shots": ("tiri tentati", COUNT, "mp"),
    "errors_led_to_goal": ("un errore che ha portato a un gol", EVENT, None),
    "errors_led_to_shot": ("un errore che ha concesso un tiro", EVENT, None),
    "big_chance_missed": ("un'occasione nitida sprecata", EVENT, None),
    "penalties_conceded": ("un rigore concesso", EVENT, None),
    "penalties_won": ("un rigore conquistato", EVENT, None),
    "clearances_off_line": ("un salvataggio sulla linea", EVENT, None),
    "last_man_tackle": ("un intervento da ultimo uomo", EVENT, None),
    "dribbles_won": ("dribbling riusciti", COUNT, "mp"),
    "duels_won": ("duelli vinti", COUNT, "mp"),
    "duels_lost": ("duelli persi", COUNT, "mp"),
    "aerials_won": ("duelli aerei vinti", COUNT, "mp"),
    "aerials_lost": ("duelli aerei persi", COUNT, "mp"),
    "dribbled_past": ("dribbling subiti", COUNT, "mp"),
    "tackles_won": ("contrasti vinti", COUNT, "mp"),
    "interceptions": ("intercetti", COUNT, "mp"),
    "ball_recoveries": ("palloni recuperati", COUNT, "mp"),
    "blocks": ("conclusioni murate", COUNT, "fp"),
    "clearances": ("respinte", COUNT, "fp"),
    "touches_in_box": ("palloni toccati in area", COUNT, "mp"),
    "passes_opp_half": ("gioco nella meta' campo avversaria", COUNT, "ms"),
    "long_balls_completed": ("lanci lunghi riusciti", COUNT, "mp"),
    "passes_completed": ("passaggi riusciti", COUNT, "mp"),
    "was_fouled": ("falli subiti", COUNT, "mp"),
    "touches": ("palloni giocati", COUNT, "mp"),
    "errors_bad_passes": ("passaggi sbagliati", COUNT, "mp"),
    "errors_dispossessed": ("palloni persi in conduzione", COUNT, "mp"),
    "errors_miscontrols": ("controlli sbagliati", COUNT, "mp"),
    "errors_fouls_committed": ("falli commessi", COUNT, "mp"),
    "gk_goals_prevented": ("gol evitati rispetto ai tiri affrontati", COUNT, "mp"),
    "gk_saves": ("parate", COUNT, "fp"),
    "gk_saves_inside_box": ("parate su tiri ravvicinati", COUNT, "fp"),
    "gk_penalty_saves": ("un rigore parato", EVENT, None),
    "gk_high_claims": ("uscite alte", COUNT, "fp"),
    "gk_punches": ("respinte di pugno", COUNT, "fp"),
    "gk_sweeper": ("uscite fuori area", COUNT, "fp"),
    "gk_crosses_not_claimed": ("cross non trattenuti", COUNT, "mp"),
    "_exposure": ("pericolo concesso nella sua zona", COUNT, "ms"),
}


def _weight_of(role: str, key: str) -> float:
    if key == "_exposure":
        return -DEF_EXPOSURE_WEIGHT
    is_gk = role == Player.ROLE_GK
    tables = ((GK_TOTAL_WEIGHTS, GK_PER90_WEIGHTS) if is_gk
              else (TOTAL_WEIGHTS, PER90_WEIGHTS))
    for table in tables:
        if key in table:
            return table[key]
    return 0.0


def _phrase(role: str, key: str, term_delta: float, raw_value: float) -> str | None:
    """How to name this deviation, or None when it is not worth saying."""
    entry = LABELS.get(key)
    if entry is None:
        return None
    label, kind, quant = entry
    if kind == EVENT:
        # Only when it actually happened; "fewer penalties conceded than average"
        # is not a thing anyone wants read back to them.
        return label if raw_value > 0 else None
    # A negative-weighted feature improves the index by being SMALLER, so the
    # direction of the raw deviation is the sign of the term deviation flipped by
    # the weight's own sign.
    more = (term_delta > 0) == (_weight_of(role, key) > 0)
    high, low = QUANTIFIERS.get(quant, QUANTIFIERS["mp"])
    return f"{high if more else low} {label}"


def _terms(role: str, totals: dict, minutes: int, exposure: float = 0.0) -> dict:
    """Each feature's raw contribution to the index, before comparison."""
    if minutes <= 0:
        return {}
    is_gk = role == Player.ROLE_GK
    total_w = GK_TOTAL_WEIGHTS if is_gk else TOTAL_WEIGHTS
    per90_w = GK_PER90_WEIGHTS if is_gk else PER90_WEIGHTS
    out = {}
    for key, w in total_w.items():
        raw = totals.get(key, 0.0)
        squashed = _compress_signed(raw) if key in SIGNED_FEATURES else _compress(raw)
        if squashed:
            out[key] = w * squashed
    scale = 90.0 / max(minutes, EXTRAP_FLOOR_MINUTES)
    for key, w in per90_w.items():
        squashed = _compress(totals.get(key, 0.0) * scale)
        if squashed:
            out[key] = w * squashed
    if role == Player.ROLE_DEF and exposure > 0:
        out["_exposure"] = -DEF_EXPOSURE_WEIGHT * _compress(exposure)
    return out


def role_average_terms(rows) -> dict:
    """{role: {feature: mean contribution}} — the yardstick every explanation is
    read against. ``rows`` is an iterable of (role, totals, minutes, exposure)."""
    sums: dict[str, dict[str, float]] = {}
    counts: dict[str, int] = {}
    for role, totals, minutes, exposure in rows:
        terms = _terms(role, totals, minutes, exposure)
        if not terms:
            continue
        bucket = sums.setdefault(role, {})
        for key, value in terms.items():
            bucket[key] = bucket.get(key, 0.0) + value
        counts[role] = counts.get(role, 0) + 1
    return {role: {k: v / counts[role] for k, v in bucket.items()}
            for role, bucket in sums.items()}


def explain(role: str, totals: dict, minutes: int, reference: dict,
            averages: dict, exposure: float = 0.0, *, top: int = 3) -> dict:
    """Why this vote, in vote points against the average player in the role.

    Returns {"positives": [...], "negatives": [...], "note": str}, each entry
    {"key", "label", "points"}. Empty when the player has no measured terms.
    """
    terms = _terms(role, totals, minutes, exposure)
    if not terms:
        return {"positives": [], "negatives": [], "note": ""}

    ref = reference.get(role)
    mean_terms = averages.get(role, {})
    # Index units -> vote points, the same transformation the vote itself uses:
    # a 1-unit move of the index is VOTE_SPREAD_K / std of a vote, shrunk for a
    # short appearance exactly as the vote is shrunk.
    weight = minutes / (minutes + SHRINKAGE_MINUTES) if minutes > 0 else 0.0
    per_unit = (VOTE_SPREAD_K * weight / ref["std"]) if ref and ref.get("std") else 0.0

    scored = []
    for key in set(terms) | set(mean_terms):
        delta = terms.get(key, 0.0) - mean_terms.get(key, 0.0)
        points = delta * per_unit
        if abs(points) < 0.05:      # below the vote's own resolution: noise
            continue
        phrase = _phrase(role, key, delta, totals.get(key, 0.0)
                         if key != "_exposure" else exposure)
        if not phrase:
            continue
        scored.append({"key": key, "label": phrase, "points": round(points, 2)})

    scored.sort(key=lambda e: e["points"], reverse=True)
    positives = [e for e in scored if e["points"] > 0][:top]
    negatives = [e for e in scored if e["points"] < 0][-top:][::-1]
    note = ""
    if minutes < SHRINKAGE_MINUTES * 2:
        note = ("Ha giocato poco: il voto e' stato avvicinato al 6 perche' "
                "l'evidenza e' scarsa.")
    return {"positives": positives, "negatives": negatives, "note": note}


def to_sentence(explanation: dict) -> str:
    """One readable line, for places with no room for a breakdown."""
    def names(entries):
        return ", ".join(e["label"] for e in entries)
    pos, neg = explanation.get("positives", []), explanation.get("negatives", [])
    if pos and neg:
        return f"Bene: {names(pos)}. Male: {names(neg)}."
    if pos:
        return f"Bene: {names(pos)}."
    if neg:
        return f"Male: {names(neg)}."
    return "Prestazione in linea con la media del suo ruolo."
