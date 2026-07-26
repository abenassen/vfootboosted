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
# Two kinds, phrased very differently on purpose:
#
# COUNT (kind, label): everything measured only RELATIVE to the role average — true
# counts (clearances, duels) and continuous xG-type quantities (xA, xG) alike. These
# are announced COMPARATIVELY: "più/meno {label}", never with an absolute quantifier.
# "molte occasioni create" read as "many chances" even when a single dangerous pass
# drove a high xA; "più occasioni create [del solito]" is what the number actually
# says — he did MORE than his usual, whatever the absolute amount. The comparative
# also fixes the low-mean trap (one box touch against a ~0 role mean is not "molti").
#
# EVENT (kind, singular, plural): rare, discrete, and COUNTED — reported only when it
# happened, and with the real number, so three last-man tackles read as "3 interventi
# da ultimo uomo", not "un intervento". Nobody wants to hear about FEWER penalties
# conceded than average, so events never surface on the low side.
COUNT, EVENT = "count", "event"
LABELS = {
    "expected_assists": (COUNT, "occasioni create per i compagni"),
    "xg_on_target": (COUNT, "qualita' nelle conclusioni"),
    "xg_shots": (COUNT, "posizioni di tiro conquistate"),
    "big_chance_created": (EVENT, "un'occasione nitida creata", "occasioni nitide create"),
    "key_passes": (COUNT, "passaggi chiave"),
    "shots_on_target": (COUNT, "tiri nello specchio"),
    "shots": (COUNT, "tiri tentati"),
    "shots_post": (EVENT, "un tiro sul palo", "tiri sul palo"),
    "shots_blocked": (COUNT, "conclusioni respinte dalla difesa"),
    "errors_led_to_goal": (EVENT, "un errore che ha portato a un gol",
                           "errori che hanno portato a un gol"),
    "errors_led_to_shot": (EVENT, "un errore che ha concesso un tiro",
                           "errori che hanno concesso un tiro"),
    "big_chance_missed": (EVENT, "un'occasione nitida sprecata",
                          "occasioni nitide sprecate"),
    "penalties_conceded": (EVENT, "un rigore concesso", "rigori concessi"),
    "penalties_won": (EVENT, "un rigore conquistato", "rigori conquistati"),
    "clearances_off_line": (EVENT, "un salvataggio sulla linea",
                            "salvataggi sulla linea"),
    "last_man_tackle": (EVENT, "un intervento da ultimo uomo",
                        "interventi da ultimo uomo"),
    "dribbles_won": (COUNT, "dribbling riusciti"),
    "duels_won": (COUNT, "duelli vinti"),
    "duels_lost": (COUNT, "duelli persi"),
    "aerials_won": (COUNT, "duelli aerei vinti"),
    "aerials_lost": (COUNT, "duelli aerei persi"),
    "dribbled_past": (COUNT, "dribbling subiti"),
    "tackles_won": (COUNT, "contrasti vinti"),
    "interceptions": (COUNT, "intercetti"),
    "ball_recoveries": (COUNT, "palloni recuperati"),
    "blocks": (COUNT, "conclusioni murate"),
    "clearances": (COUNT, "respinte"),
    "touches_in_box": (COUNT, "palloni toccati in area"),
    "passes_opp_half": (COUNT, "gioco nella meta' campo avversaria"),
    "long_balls_completed": (COUNT, "lanci lunghi riusciti"),
    "crosses_completed": (COUNT, "cross riusciti"),
    "dribbles_attempted": (COUNT, "dribbling tentati"),
    "passes_completed": (COUNT, "passaggi riusciti"),
    "was_fouled": (COUNT, "falli subiti"),
    "touches": (COUNT, "palloni giocati"),
    "errors_bad_passes": (COUNT, "passaggi sbagliati"),
    "errors_dispossessed": (COUNT, "palloni persi in conduzione"),
    "errors_miscontrols": (COUNT, "controlli sbagliati"),
    "errors_fouls_committed": (COUNT, "falli commessi"),
    "gk_goals_prevented": (COUNT, "gol evitati rispetto ai tiri affrontati"),
    "gk_saves": (COUNT, "parate"),
    "gk_saves_inside_box": (COUNT, "parate su tiri ravvicinati"),
    "gk_penalty_saves": (EVENT, "un rigore parato", "rigori parati"),
    "gk_high_claims": (COUNT, "uscite alte"),
    "gk_punches": (COUNT, "respinte di pugno"),
    "gk_sweeper": (COUNT, "uscite fuori area"),
    "gk_crosses_not_claimed": (COUNT, "cross non trattenuti"),
    "_exposure": (COUNT, "pericolo concesso nella sua zona"),
}

# Feature families that describe ONE thing through several overlapping terms — a
# "good minus volume" structure where the parts point opposite ways and read as
# nonsense on their own ("Bene: più dribbling riusciti. Male: più dribbling
# tentati"; "Male: più posizioni di tiro conquistate", because xg_shots is
# subtracted by design). They are summed into a single net line for display; the
# scoring is untouched. (group_keys, label when net-positive, label when negative.)
MERGES = [
    (("xg_on_target", "xg_shots", "shots_on_target", "shots", "shots_blocked"),
     "più incisività nelle conclusioni", "meno incisività nelle conclusioni"),
    (("dribbles_won", "dribbles_attempted"),
     "più efficacia nel dribbling", "meno efficacia nel dribbling"),
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
    if entry[0] == EVENT:
        # Only when it actually happened, and with the real count: three last-man
        # tackles are "3 interventi da ultimo uomo", not "un intervento".
        n = int(round(raw_value))
        if n <= 0:
            return None
        singular, plural = entry[1], entry[2]
        return singular if n == 1 else f"{n} {plural}"
    # COUNT: comparative, never absolute. ``more`` is whether the raw value is ABOVE
    # the role average — a negative-weighted feature improves the index by being
    # SMALLER, so the raw direction is the term-delta sign flipped by the weight's.
    label = entry[1]
    more = (term_delta > 0) == (_weight_of(role, key) > 0)
    return f"più {label}" if more else f"meno {label}"


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
            result_nudge: float = 0.0, red_adjustment: float = 0.0) -> dict:
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
    # result nudge and the red-card drop, then clamp back to the pagella range.
    subtotal = max(VOTE_MIN, min(VOTE_MAX, raw + result_nudge + red_adjustment))
    voto = round(subtotal * 2) / 2

    named = [(pts, ph) for pts, _, ph in scored if ph and abs(pts) >= 0.05]
    named.sort(key=lambda x: x[0], reverse=True)
    positives = [x for x in named[:top] if x[0] > 0]
    negatives = [x for x in (named[-top:][::-1]) if x[0] < 0]
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
    if any(c["label"] == "espulsione"
           for c in explanation.get("contributions", [])):
        core += " Espulso."
    return core
