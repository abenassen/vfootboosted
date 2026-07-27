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

# What each feature is called out loud, and how to quantify it. THREE kinds, chosen
# by how much the number "1" already means for that feature:
#
# COUNT (kind, label, quant): VOLUME stats where 1 is nothing and only the amount
# vs the role average matters — duels, clearances, passes, touches. Announced with
# absolute quantifiers ("tanti/pochi {label}") read against the role average as the
# yardstick; ``quant`` carries the gender/number agreement so we never say "tanti
# respinte".
#
# SIGNAL (kind, positive, negative): the small, high-value continuous quantities
# where even one is notable but there is no clean integer to count — xA and the
# merged shooting/dribbling nets. Announced NEUTRALLY as "una o più ...", the noun
# carrying the sense: net-positive -> "una o più conclusioni pericolose",
# net-negative -> "una o più occasioni fallite". This sidesteps both "molte" (false
# for one big pass) and a dangling "più". ``negative`` may be None — nothing worth
# saying on the low side (below-average creation is a non-event).
#
# EVENT (kind, singular, plural): rare discrete facts we count EXACTLY — reported
# only when they happened, with the real number: "3 interventi da ultimo uomo".
COUNT, SIGNAL, EVENT = "count", "signal", "event"

# Absolute quantifier pairs (many / few) with gender-number agreement.
QUANTIFIERS = {"mp": ("tanti", "pochi"), "fp": ("tante", "poche"),
               "ms": ("tanto", "poco"), "fs": ("tanta", "poca")}

# The narrative is one-sided at the extremes, symmetrically around 6. A clearly
# poor game's "positives" are only its least-bad deviations (faint praise), and a
# clearly good game's "negatives" are trivialities on a fine display — neither is
# worth reading back. In the middle band [5.5, 6.5] (mixed games) both sides show.
# Suppressed items fold into "altre voci", so the breakdown still reconciles.
POSITIVES_MIN_VOTE = 5.5   # below this: only what went wrong
NEGATIVES_MAX_VOTE = 6.5   # above this: only what went well

LABELS = {
    # SIGNAL — small high-value continuous; "una o più ...", (positive, negative)
    "expected_assists": (SIGNAL, "una o più occasioni create per i compagni", None),
    # EVENT — counted exactly, (singular, plural)
    "shots_goal": (EVENT, "un gol", "gol"),
    "big_chance_created": (EVENT, "un'occasione nitida creata", "occasioni nitide create"),
    "big_chance_missed": (EVENT, "un'occasione nitida sprecata", "occasioni nitide sprecate"),
    "shots_post": (EVENT, "un tiro sul palo", "tiri sul palo"),
    "errors_led_to_goal": (EVENT, "un errore che ha portato a un gol",
                           "errori che hanno portato a un gol"),
    "errors_led_to_shot": (EVENT, "un errore che ha concesso un tiro",
                           "errori che hanno concesso un tiro"),
    "penalties_conceded": (EVENT, "un rigore concesso", "rigori concessi"),
    "penalties_won": (EVENT, "un rigore conquistato", "rigori conquistati"),
    "clearances_off_line": (EVENT, "un salvataggio sulla linea", "salvataggi sulla linea"),
    "last_man_tackle": (EVENT, "un intervento da ultimo uomo", "interventi da ultimo uomo"),
    "gk_penalty_saves": (EVENT, "un rigore parato", "rigori parati"),
    # COUNT — volume, "tanti/pochi ...", (label, quant)
    "key_passes": (COUNT, "passaggi chiave", "mp"),
    "duels_won": (COUNT, "duelli vinti", "mp"),
    "duels_lost": (COUNT, "duelli persi", "mp"),
    "aerials_won": (COUNT, "duelli aerei vinti", "mp"),
    "aerials_lost": (COUNT, "duelli aerei persi", "mp"),
    "dribbled_past": (COUNT, "dribbling concessi all'avversario", "mp"),
    "tackles_won": (COUNT, "contrasti vinti", "mp"),
    "interceptions": (COUNT, "intercetti", "mp"),
    "ball_recoveries": (COUNT, "palloni recuperati", "mp"),
    "blocks": (COUNT, "conclusioni murate", "fp"),
    "clearances": (COUNT, "respinte", "fp"),
    "touches_in_box": (COUNT, "palloni toccati in area", "mp"),
    "passes_opp_half": (COUNT, "gioco nella meta' campo avversaria", "ms"),
    "long_balls_completed": (COUNT, "lanci lunghi riusciti", "mp"),
    "crosses_completed": (COUNT, "cross riusciti", "mp"),
    "passes_completed": (COUNT, "passaggi riusciti", "mp"),
    "was_fouled": (COUNT, "falli subiti", "mp"),
    "touches": (COUNT, "palloni giocati", "mp"),
    "errors_bad_passes": (COUNT, "passaggi sbagliati", "mp"),
    "errors_dispossessed": (COUNT, "palloni persi in conduzione", "mp"),
    "errors_miscontrols": (COUNT, "controlli sbagliati", "mp"),
    "errors_fouls_committed": (COUNT, "falli commessi", "mp"),
    "gk_goals_prevented": (COUNT, "gol evitati rispetto ai tiri affrontati", "mp"),
    "gk_saves": (COUNT, "parate", "fp"),
    "gk_saves_inside_box": (COUNT, "parate su tiri ravvicinati", "fp"),
    "gk_high_claims": (COUNT, "uscite alte", "fp"),
    "gk_punches": (COUNT, "respinte di pugno", "fp"),
    "gk_sweeper": (COUNT, "uscite fuori area", "fp"),
    "gk_crosses_not_claimed": (COUNT, "cross non trattenuti", "mp"),
    "_exposure": (COUNT, "pericolo concesso nella sua zona", "ms"),
    # Merged into SIGNAL lines below — labels kept for coverage, never phrased alone.
    "xg_on_target": (COUNT, "qualita' nelle conclusioni", "fp"),
    "xg_shots": (COUNT, "posizioni di tiro conquistate", "fp"),
    "shots_on_target": (COUNT, "tiri nello specchio", "mp"),
    "shots": (COUNT, "tiri tentati", "mp"),
    "shots_blocked": (COUNT, "conclusioni respinte dalla difesa", "fp"),
    "dribbles_won": (COUNT, "dribbling riusciti", "mp"),
    "dribbles_attempted": (COUNT, "dribbling tentati", "mp"),
}

# Feature families that describe ONE thing through several overlapping terms (a
# "good minus volume" net) and read as nonsense split apart ("Bene: tanti dribbling
# riusciti. Male: tanti dribbling tentati"; "Male: tante posizioni di tiro
# conquistate", because xg_shots is subtracted by design). Merged into a single
# SIGNAL line, phrased "una o più ..." by the sign of the net. Scoring untouched.
# (group_keys, phrase when net-positive, phrase when net-negative.)
MERGES = [
    (("xg_on_target", "xg_shots", "shots_on_target", "shots", "shots_blocked",
      "shots_off"),
     "una o più conclusioni pericolose", "una o più occasioni fallite"),
    (("dribbles_won", "dribbles_attempted"),
     "uno o più dribbling riusciti", "uno o più dribbling falliti"),
]


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
    kind = entry[0]
    if kind == EVENT:
        # Only when it happened, with the real count: three last-man tackles are
        # "3 interventi da ultimo uomo", not "un intervento".
        n = int(round(raw_value))
        if n <= 0:
            return None
        return entry[1] if n == 1 else f"{n} {entry[2]}"
    # ``more`` is whether the raw value is ABOVE the role average — a negative-weighted
    # feature improves the index by being SMALLER, so the raw direction is the
    # term-delta sign flipped by the weight's own sign.
    more = (term_delta > 0) == (_weight_of(role, key) > 0)
    if kind == SIGNAL:
        # "una o più ..." — the noun carries the sense; the negative side may be
        # None (nothing worth saying, e.g. below-average creation).
        return entry[1] if more else entry[2]
    # COUNT: absolute quantifier vs the role average (the implicit yardstick).
    label, quant = entry[1], entry[2]
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
        # v2 selective-√: outfield totals are LINEAR; the GK channel keeps √
        # (its weights were fit against a √-compressed total block).
        if is_gk:
            val = _compress_signed(raw) if key in SIGNED_FEATURES else _compress(raw)
        else:
            val = raw
        if val:
            out[key] = w * val
    scale = 90.0 / max(minutes, EXTRAP_FLOOR_MINUTES)
    for key, w in per90_w.items():
        squashed = _compress(totals.get(key, 0.0) * scale)
        if squashed:
            out[key] = w * squashed
    if role == Player.ROLE_DEF and exposure > 0:
        out["_exposure"] = -DEF_EXPOSURE_WEIGHT * exposure  # LINEAR (v2)
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
            averages: dict, exposure: float = 0.0, *, top: int = 3,
            result_nudge: float = 0.0, red_adjustment: float = 0.0,
            own_goal_adjustment: float = 0.0) -> dict:
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

    points_by_key = {key: (terms.get(key, 0.0) - mean_terms.get(key, 0.0)) * per_unit
                     for key in set(terms) | set(mean_terms)}

    scored = []
    # Collapse the overlapping feature families (see MERGES) into one net line each.
    for group, label_pos, label_neg in MERGES:
        net = sum(points_by_key.pop(k, 0.0) for k in group)
        if abs(net) >= 1e-9:
            scored.append((net, group[0], label_pos if net > 0 else label_neg))
    for key, pts in points_by_key.items():
        phrase = _phrase(role, key, pts,
                         (totals.get(key, 0.0) if key != "_exposure" else exposure))
        scored.append((pts, key, phrase))

    # The subtotal is the vote's OWN raw value, computed exactly as the scorer
    # computes it (index z-scored against the reference mean), not re-derived from
    # the sum of slices — otherwise float drift near a rounding boundary would let
    # the explanation show a different vote than the one on the row. The "other"
    # line then absorbs whatever the shown slices don't account for, so the visible
    # numbers still reconcile to this subtotal.
    index = sum(terms.values())
    z = (index - ref["mean"]) / ref["std"]
    raw = max(VOTE_MIN, min(VOTE_MAX, VOTE_CENTER + VOTE_SPREAD_K * weight * z))
    # Same order as the scorer: clamp the merit vote, add the (divergence-only)
    # result nudge, the red-card drop and the own-goal drop, then clamp back.
    subtotal = max(VOTE_MIN, min(VOTE_MAX,
                   raw + result_nudge + red_adjustment + own_goal_adjustment))
    voto = round(subtotal * 2) / 2

    named = [(pts, ph) for pts, _, ph in scored if ph and abs(pts) >= 0.05]
    named.sort(key=lambda x: x[0], reverse=True)
    # One-sided at the extremes (see POSITIVES_MIN_VOTE / NEGATIVES_MAX_VOTE): a bad
    # game's "positives" are faint praise, a fine game's "negatives" are nitpicks.
    # Suppressed items fold into "altre voci", so the breakdown still reconciles.
    positives = ([] if voto < POSITIVES_MIN_VOTE
                 else [x for x in named[:top] if x[0] > 0])
    negatives = ([] if voto > NEGATIVES_MAX_VOTE
                 else [x for x in (named[-top:][::-1]) if x[0] < 0])
    shown = positives + negatives

    def entry(pts, label):
        return {"label": label, "points": round(pts, 2)}

    contributions = [entry(pts, ph) for pts, ph in shown]
    # The result adjustment is a vote-level term, not a feature, so it rides on top
    # of the feature contributions and is named explicitly.
    if abs(result_nudge) >= 0.005:
        contributions.append(entry(result_nudge,
                                   "adeguamento al risultato di squadra"))
    if abs(red_adjustment) >= 0.005:
        contributions.append(entry(red_adjustment, "espulsione"))
    if abs(own_goal_adjustment) >= 0.005:
        contributions.append(entry(own_goal_adjustment, "autogol"))
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
        core = f"Bene: {names(pos)}. Male: {names(neg)}."
    elif pos:
        core = f"Bene: {names(pos)}."
    elif neg:
        core = f"Male: {names(neg)}."
    else:
        core = "Prestazione in linea con la media del suo ruolo."
    # The sending-off is a vote-level fact, not a feature, so it is not in
    # positives/negatives — call it out explicitly.
    labels = {c["label"] for c in explanation.get("contributions", [])}
    if "espulsione" in labels:
        core += " Espulso."
    if "autogol" in labels:
        core += " Autogol."
    return core
