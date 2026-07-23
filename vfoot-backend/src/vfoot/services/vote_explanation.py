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
    PER90_WEIGHTS, SHRINKAGE_MINUTES, SIGNED_FEATURES, TOTAL_WEIGHTS, VOTE_CENTER,
    VOTE_MAX, VOTE_MIN, VOTE_SPREAD_K, _compress, _compress_signed,
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
    """Why this vote, decomposed so it ADDS UP to the vote.

    The vote is 6 + spread * shrink * (index - role_mean) / std. Every feature is
    a slice of that (index - role_mean), so once converted to vote points the
    slices sum to (vote - 6) exactly — as long as the yardstick the explanation
    subtracts is the SAME role mean the vote uses. It was not: the vote's mean
    came from build_reference (players over the minutes threshold), the
    explanation's from every appearance, and the two disagreed, so the numbers
    could never reconcile. get_role_averages now filters to match.

    Returns an additive breakdown: ``base`` (6), the largest ``contributions`` in
    vote points, an ``other`` bucket folding the long tail of small ones, and the
    resulting ``voto`` — so 6 + contributions + other rounds to the vote. A short
    appearance shrinks every slice toward zero (little evidence), which is why a
    cameo's terms are all small: that is the honest reason, not a rounding quirk.
    """
    terms = _terms(role, totals, minutes, exposure)
    ref = reference.get(role)
    if not terms or not ref or not ref.get("std"):
        return {"positives": [], "negatives": [], "contributions": [],
                "base": VOTE_CENTER, "other_points": 0.0, "other_count": 0,
                "minutes": minutes, "low_minutes": False, "note": ""}

    mean_terms = averages.get(role, {})
    weight = minutes / (minutes + SHRINKAGE_MINUTES) if minutes > 0 else 0.0
    per_unit = VOTE_SPREAD_K * weight / ref["std"]

    scored = []
    for key in set(terms) | set(mean_terms):
        delta = terms.get(key, 0.0) - mean_terms.get(key, 0.0)
        phrase = _phrase(role, key, delta,
                         (totals.get(key, 0.0) if key != "_exposure" else exposure))
        scored.append((delta * per_unit, key, phrase))

    # The subtotal is the vote's OWN raw value, computed exactly as the scorer
    # computes it (index z-scored against the reference mean), not re-derived from
    # the sum of slices — otherwise float drift near a rounding boundary would let
    # the explanation show a different vote than the one on the row. The "other"
    # line then absorbs whatever the shown slices don't account for, so the visible
    # numbers still reconcile to this subtotal.
    index = sum(terms.values())
    z = (index - ref["mean"]) / ref["std"]
    subtotal = max(VOTE_MIN, min(VOTE_MAX, VOTE_CENTER + VOTE_SPREAD_K * weight * z))
    voto = round(subtotal * 2) / 2

    named = [(pts, ph) for pts, _, ph in scored if ph and abs(pts) >= 0.05]
    named.sort(key=lambda x: x[0], reverse=True)
    positives = [x for x in named[:top] if x[0] > 0]
    negatives = [x for x in (named[-top:][::-1]) if x[0] < 0]
    shown = positives + negatives

    def entry(pts, label):
        return {"label": label, "points": round(pts, 2)}

    contributions = [entry(pts, ph) for pts, ph in shown]
    shown_rounded = sum(c["points"] for c in contributions)
    other_points = round(subtotal - VOTE_CENTER - shown_rounded, 2)
    low = minutes < SHRINKAGE_MINUTES * 2
    note = ("Con pochi minuti giocati ogni voce pesa meno: il voto resta piu' "
            "vicino al 6.") if low else ""
    return {
        "positives": [entry(p, ph) for p, ph in positives],
        "negatives": [entry(p, ph) for p, ph in negatives],
        "contributions": contributions,
        "base": VOTE_CENTER,
        "other_points": other_points,
        "other_count": max(0, len(scored) - len(shown)),
        "subtotal": round(subtotal, 2),
        "voto": voto,
        "minutes": minutes,
        "low_minutes": low,
        "note": note,
    }


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
