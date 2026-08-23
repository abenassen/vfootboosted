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
    DERIVED_FEATURES, EXPOSURE_KEY, EXPOSURE_WEIGHT, GK_PER90_WEIGHTS,
    GK_TOTAL_WEIGHTS, GK_WEIGHTS, PER90_WEIGHTS, SHRINKAGE_MINUTES, TOTAL_WEIGHTS,
    VOTE_CENTER, VOTE_MAX, VOTE_MIN, VOTE_SPREAD_K, WEIGHTS,
    _feature_z, exposure_z, feature_scales, raw_feature_values,
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

# An assist is paid as a BONUS (+1 on the fantavoto) and almost nothing in the base
# vote, which reads the PASS and not its outcome. When the pass carried little
# expected value the two readings part company, and that is worth saying out loud —
# it is the single most common reason our base vote sits below a pagella's on a
# player who "did something". Threshold from the distribution of the 581
# assist-carrying appearances of 2025-26: median xA 0.14, first quartile 0.044, and
# 29% of them combine xA < 0.15 with no clear chance created at all.
ASSIST_LOW_XA = 0.15

# How a sending-off's reason reads in Italian. The severity that scales the drop is
# RED_CARD_SEVERITY on the same keys; naming the reason is how a reader can tell why
# one sending-off cost 0.6 and another 1.5.
RED_REASON_IT = {
    "Professional foul last man": "fallo tattico da ultimo uomo",
    "Foul": "fallo",
    "Foul Committed": "fallo",
    "Violent conduct": "condotta violenta",
    "Bad Behaviour": "comportamento antisportivo",
    "Argument": "protesta",
}

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
    "sga_post": (COUNT, "qualita' nelle conclusioni", "fp"),
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
# (group_keys, phrase when net-positive, phrase when net-negative, family name.)
#
# The family NAME exists so the merge can be SEEN. Someone reading the full
# per-feature ledger who finds "una o più conclusioni pericolose +0.58" in the
# summary and no such row in the table below is entitled to suspect one of the two
# is wrong; the rows carrying this name are the ones that add up to it.
MERGES = [
    (("sga_post", "xg_shots", "shots_on_target", "shots", "shots_blocked",
      "shots_off"),
     "una o più conclusioni pericolose", "una o più occasioni fallite",
     "conclusioni"),
    (("dribbles_won", "dribbles_attempted"),
     "uno o più dribbling riusciti", "uno o più dribbling falliti", "dribbling"),
]
# {feature: family name} — the same table read the other way round.
MERGE_FAMILY = {k: name for keys, _pos, _neg, name in MERGES for k in keys}


# Come si chiamano, nel REGISTRO ESTESO, le voci che la frase parlata non nomina
# mai. Non sono le stesse di TABLE_ONLY_LABELS: quelle descrivono la feature a chi
# legge la tabella tecnica del tuner ("proxy sintetico"), queste vanno sotto gli
# occhi di chi ha appena aperto il dettaglio di un voto.
#
# ``defensive_value`` e' il caso che ha motivato tutto questo: puo' essere la voce
# PIU' GRANDE del voto di un difensore (0.28 su 1.37, il 20%, in Rrahmani di
# Genoa-Napoli) e finiva sempre e solo dentro "altre voci", perche' senza una riga
# in LABELS ``_phrase`` non ha niente da dire. Nel registro deve avere un nome, e
# il nome deve ammettere che cos'e': un indice di chi ci fornisce i dati, non una
# cosa che contiamo noi.
LEDGER_LABELS = {
    "defensive_value": "valore difensivo (indice del fornitore)",
    # Il lato negativo del SIGNAL e' None per scelta (creare poco non e' una
    # notizia da dire ad alta voce): nel registro la riga c'e' lo stesso, quindi
    # serve il sostantivo neutro, che col numero negativo accanto si legge bene.
    "expected_assists": "occasioni create per i compagni",
    "shots_off": "tiri fuori",
}


def _weight_of(role: str, key: str) -> float:
    if key == EXPOSURE_KEY:
        return -EXPOSURE_WEIGHT
    return (GK_WEIGHTS if role == Player.ROLE_GK else WEIGHTS).get(key, 0.0)


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


def _never_happened(entry) -> str:
    """"nessun gol", "nessun'occasione nitida creata" — un EVENT che NON e'
    successo. Nella frase parlata questi non si dicono (``_phrase`` restituisce
    None: elencare cio' che uno non ha fatto e' rumore), ma nel registro la riga
    esiste, con i suoi punti — un difensore che non segna perde il piccolo credito
    che il difensore medio prende dai gol, ed e' giusto poterlo leggere.

    Il genere viene dall'articolo del singolare, che e' l'unico posto in cui la
    tabella LABELS lo dichiara: "un gol" -> "nessun gol", "un'occasione nitida
    creata" -> "nessun'occasione nitida creata"."""
    singular = entry[1]
    for art, neg in (("un'", "nessun'"), ("uno ", "nessuno "), ("un ", "nessun ")):
        if singular.startswith(art):
            return neg + singular[len(art):]
    return f"nessun {entry[2]}"


def ledger_phrase(role: str, key: str, term_delta: float, raw_value: float) -> str:
    """Il nome della voce nel REGISTRO ESTESO, dove tutto va nominato.

    ``_phrase`` puo' tacere — e tace apposta — su tre casi: un evento che non e'
    successo, il lato negativo di un SIGNAL, e le feature senza riga in LABELS. Nel
    riassunto quel silenzio e' giusto; nel registro no, perche' li' la riga c'e' e
    mostra i suoi punti, e una riga senza nome e' esattamente il buco da cui e'
    nata questa funzione."""
    said = _phrase(role, key, term_delta, raw_value)
    if said:
        return said
    entry = LABELS.get(key)
    if entry is not None and entry[0] == EVENT:
        return _never_happened(entry)
    return LEDGER_LABELS.get(key) or readable_label(key) or key


# Features that carry weight but are never NAMED in a sentence, so they have no
# LABELS entry: one is a provider composite nobody would recognise from a pagella
# ("tanto valore difensivo" explains nothing), the other only ever appears inside a
# merged shooting line. A table that lists every feature still has to say what they
# are, so they get a description here — and only here, which is why this is not in
# LABELS: an entry there would put them into the spoken explanation too.
TABLE_ONLY_LABELS = {
    "defensive_value": "indice difensivo del provider (proxy sintetico)",
    "shots_off": "tiri fuori",
}


def red_card_phrase(detail: dict | None) -> str:
    """"espulsione al 63' per condotta violenta (27' in dieci)" — the three things
    that set the size of the drop: WHY (severity), WHEN, and for HOW LONG the team
    then played a man short. Falls back to the bare word when we have no detail."""
    if not detail:
        return "espulsione"
    reason = RED_REASON_IT.get(detail.get("reason") or "", "")
    if detail.get("second_yellow"):
        reason = f"{reason} (secondo giallo)" if reason else "secondo giallo"
    minute = detail.get("minute")
    down = detail.get("man_down")
    parts = ["espulsione"]
    if minute is not None:
        parts.append(f"al {int(round(minute))}'")
    if reason:
        parts.append(f"per {reason}")
    if down:
        parts.append(f"({int(round(down))}' in dieci)")
    return " ".join(parts)


def own_goal_phrase(detail: dict | None) -> str:
    """An own goal turned in off him and an own goal he made himself are the same
    event in the scoreline and different events in a vote — the drop differs by a
    factor of 2.5, so the reason has to travel with it."""
    if not detail:
        return "autogol"
    n = detail.get("count") or 1
    head = "autogol" if n == 1 else f"{n} autogol"
    kind = detail.get("kind")
    if kind == "deflection":
        return f"{head} su deviazione"
    if kind == "solo":
        return f"{head} in prima persona"
    return head          # ungraded: no sub-minute timing, we claim nothing


def assist_note(assists: int, xa: float, big_chances: float) -> str:
    """Why an assist can leave the base vote where it was.

    Not a claim about the finisher — measured on the case that prompted it (McKennie,
    g14) the scorer's own shot quality was only +0.67σ, so "he did the exceptional
    thing" would be inventing a merit. What IS measurable is the pass: an xA of 0.05
    is a ball that did not, by itself, make a goal likely."""
    if assists < 1 or big_chances > 0 or xa >= ASSIST_LOW_XA:
        return ""
    # Short on purpose: this rides inside ``to_sentence``, which is one line in the
    # app's match detail, and a player who also scored an own goal already has two
    # clauses ahead of it.
    return (f"L'assist nasce da un passaggio di basso valore atteso (xA {xa:.2f}): "
            f"conta come bonus, non nel voto base.")


def readable_label(key: str) -> str:
    """The feature's name in words, for a table that also shows its technical name.

    Deliberately the NOUN and not the phrasing ``_phrase`` builds: a sentence wants
    "tanti duelli vinti", a table column wants "duelli vinti"."""
    entry = LABELS.get(key)
    if entry is None:
        return TABLE_ONLY_LABELS.get(key, "")
    return entry[2] if entry[0] == EVENT else entry[1]


def _all_terms(role: str, terms: dict, mean_terms: dict, per_unit: float,
               totals: dict, minutes: int, exposure: float) -> list[dict]:
    """Every feature of the channel, in the terms the weight tables use.

    Same numbers as the summary breakdown, only nothing merged and nothing folded
    into "altre voci": one row per weighted feature, with its technical name (the
    one in the tuner spreadsheet), what the player did, where that sits on the
    population scale, its weight, and what it moved the vote by. The rows sum to
    (voto − 6) exactly, because they are the same slices ``explain`` shows — see the
    reconciliation note in ``explain``."""
    is_gk = role == Player.ROLE_GK
    weights = dict(GK_WEIGHTS if is_gk else WEIGHTS)
    total_keys = set(GK_TOTAL_WEIGHTS if is_gk else TOTAL_WEIGHTS)
    if not is_gk:
        weights[EXPOSURE_KEY] = -EXPOSURE_WEIGHT
    scales = feature_scales(gk=is_gk)
    values = raw_feature_values(totals, minutes, exposure, gk=is_gk)

    out = []
    for key, w in weights.items():
        # Zero-weight features ARE listed: a weight deliberately set to zero (see
        # last_man_tackle) is a decision, and a table that silently dropped it would
        # hide the decision instead of showing it. It contributes 0 to every column
        # that feeds the vote, so nothing else changes.
        value = values.get(key, 0.0)
        kind = ("EXPOS" if key == EXPOSURE_KEY
                else "DERIV" if key in DERIVED_FEATURES
                else "TOT" if key in total_keys else "PER90")
        # The exposure is standardised ASYMMETRICALLY (EXPOSURE_CREDIT), so its σ has
        # to be read through the same function the index used — otherwise the row
        # shows a σ that does not produce the contribution printed beside it.
        z = (exposure_z(value, scales) if key == EXPOSURE_KEY
             else _feature_z(key, value, scales))
        out.append({
            "key": key,
            "label": readable_label(key),
            "kind": kind,
            # the merged family this feature belongs to, if any: the summary shows
            # one line for all of them, and this is how the two views match up
            "family": MERGE_FAMILY.get(key, ""),
            # For a COUNTED event, what ONE occurrence is worth on the index — the
            # only readable unit for something that happens in 1% of matches, where
            # a σ is a fraction of an occurrence and a per-σ weight reads ten times
            # smaller than it acts. See the note on last_man_tackle.
            "event": (LABELS.get(key) or (None,))[0] == EVENT,
            "z_one": round(_feature_z(key, 1.0, scales), 3),
            "value": round(value, 3),
            "z": round(z, 3),
            "weight": round(w, 4),
            # w·z: what the feature puts into the index, in index points
            "index": round(terms.get(key, 0.0), 4),
            # the same for the AVERAGE player in this role — the yardstick, because
            # what explains a 6.5 rather than a 6 is only the departure from peers
            "index_avg": round(mean_terms.get(key, 0.0), 4),
            "points": round((terms.get(key, 0.0) - mean_terms.get(key, 0.0)) * per_unit, 3),
        })
    # Left in the order of the weight tables — the same order the tuner spreadsheet
    # lists them in, so a row here can be found there. Callers that want the drivers
    # first sort by ``points`` themselves.
    return out


def _terms(role: str, totals: dict, minutes: int, exposure: float = 0.0,
           scales: dict | None = None) -> dict:
    """Each feature's contribution to the index, before comparison to the role mean.

    Reads the feature values and the standardisation from ``classic_rating`` rather
    than repeating them: the breakdown has to reconcile to the vote exactly, so any
    divergence between the two pipelines would show up as a broken explanation."""
    if minutes <= 0:
        return {}
    is_gk = role == Player.ROLE_GK
    weights = GK_WEIGHTS if is_gk else WEIGHTS
    if scales is None:
        scales = feature_scales(gk=is_gk)
    elif "outfield" in scales or "gk" in scales:
        scales = scales.get("gk" if is_gk else "outfield", {})
    values = raw_feature_values(totals, minutes, exposure, gk=is_gk)
    out = {}
    for key, w in weights.items():
        if not w:
            continue
        z = _feature_z(key, values.get(key, 0.0), scales)
        if z:
            out[key] = w * z
    if not is_gk:
        # exposure_z, not _feature_z: the asymmetric credit (EXPOSURE_CREDIT) is
        # part of what the index consumed, so the breakdown must apply it too.
        z = exposure_z(values.get(EXPOSURE_KEY, 0.0), scales)
        if z:
            out[EXPOSURE_KEY] = -EXPOSURE_WEIGHT * z
    return out


def role_average_terms(rows, scales: dict | None = None) -> dict:
    """{role: {feature: mean contribution}} — the yardstick every explanation is
    read against. ``rows`` is an iterable of (role, totals, minutes, exposure)."""
    sums: dict[str, dict[str, float]] = {}
    counts: dict[str, int] = {}
    for role, totals, minutes, exposure in rows:
        terms = _terms(role, totals, minutes, exposure, scales)
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
            own_goal_adjustment: float = 0.0, penalty_adjustment: float = 0.0,
            evidence_weight: float = 1.0, full: bool = False,
            ledger: bool = False,
            red_detail: dict | None = None, own_goal_detail: dict | None = None,
            assists: int = 0) -> dict:
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
                "all_terms": [], "other_terms": [],
                "other_tiny": {"count": 0, "points": 0.0},
                "assist_note": "", "base": VOTE_CENTER,
                "other_points": 0.0, "other_count": 0, "minutes": minutes,
                "low_minutes": False, "note": ""}

    mean_terms = averages.get(role, {})
    # Same two shrinkages the vote applies: how long he played, and — for a keeper —
    # how much of the match actually reached him (``evidence_weight``, see
    # GK_EVIDENCE_FULL). Both scale every slice, so the breakdown keeps adding up.
    weight = (minutes / (minutes + SHRINKAGE_MINUTES) if minutes > 0 else 0.0)
    weight *= evidence_weight
    per_unit = VOTE_SPREAD_K * weight / ref["std"]

    points_by_key = {key: (terms.get(key, 0.0) - mean_terms.get(key, 0.0)) * per_unit
                     for key in set(terms) | set(mean_terms)}

    # The full ledger, before the families are merged and the tail folded away —
    # every feature the channel weighs, named as the weight tables name it. Only
    # built on request: it is four times the size of the vote it explains, which is
    # fine for an analysis page and wasteful in a match-detail API response.
    all_terms = (_all_terms(role, terms, mean_terms, per_unit, totals, minutes,
                            exposure) if full else [])

    scored = []
    # Collapse the overlapping feature families (see MERGES) into one net line each.
    # ``family`` travels with the line so a reader can find the rows it stands for.
    for group, label_pos, label_neg, family in MERGES:
        present = [k for k in group if k in points_by_key]
        net = sum(points_by_key.pop(k, 0.0) for k in group)
        if abs(net) >= 1e-9:
            scored.append((net, group[0], label_pos if net > 0 else label_neg,
                           (family, len(present))))
    # The raw value the phrasing quotes comes from the SAME builder the index uses,
    # so a derived feature (sga_post) or the exposure is quoted as what it actually
    # is, not looked up in a totals dict that has never heard of it.
    raw_values = raw_feature_values(totals, minutes, exposure,
                                    gk=role == Player.ROLE_GK)
    for key, pts in points_by_key.items():
        phrase = _phrase(role, key, pts, raw_values.get(key, 0.0))
        scored.append((pts, key, phrase, None))

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
                   raw + result_nudge + red_adjustment + own_goal_adjustment
                   + penalty_adjustment))
    voto = round(subtotal * 2) / 2

    # The key travels with the line (it used to be dropped here): the ledger below
    # lists the entries that did NOT make it into the summary, and without an
    # identity there is no way to tell which ones those are.
    named = [(pts, key, ph, fam) for pts, key, ph, fam in scored
             if ph and abs(pts) >= 0.05]
    named.sort(key=lambda x: x[0], reverse=True)
    # One-sided at the extremes (see POSITIVES_MIN_VOTE / NEGATIVES_MAX_VOTE): a bad
    # game's "positives" are faint praise, a fine game's "negatives" are nitpicks.
    # Suppressed items fold into "altre voci", so the breakdown still reconciles.
    positives = ([] if voto < POSITIVES_MIN_VOTE
                 else [x for x in named[:top] if x[0] > 0])
    negatives = ([] if voto > NEGATIVES_MAX_VOTE
                 else [x for x in (named[-top:][::-1]) if x[0] < 0])
    shown = positives + negatives

    def entry(pts, label, family=None, kind=None):
        """One visible line. ``family`` is set when the line is the NET of several
        features (see MERGES): without it the summary shows a number that matches no
        single row of the full ledger, which reads as an inconsistency. ``kind`` marks
        the vote-level adjustments, which are not features at all."""
        out = {"label": label, "points": round(pts, 2)}
        if family:
            out["family"], out["family_size"] = family
        if kind:
            out["kind"] = kind
        return out

    contributions = [entry(pts, ph, fam) for pts, _key, ph, fam in shown]
    # The result adjustment is a vote-level term, not a feature, so it rides on top
    # of the feature contributions and is named explicitly.
    # ``kind`` rides along so ``to_sentence`` (and any caller) can recognise these
    # lines without matching on their text — the labels now carry minute, reason and
    # man-down time, and string-matching them was a trap waiting to spring.
    if abs(result_nudge) >= 0.005:
        contributions.append(entry(result_nudge,
                                   "adeguamento al risultato di squadra",
                                   kind="result"))
    if abs(red_adjustment) >= 0.005:
        contributions.append(entry(red_adjustment, red_card_phrase(red_detail),
                                   kind="red"))
    if abs(own_goal_adjustment) >= 0.005:
        contributions.append(entry(own_goal_adjustment,
                                   own_goal_phrase(own_goal_detail),
                                   kind="own_goal"))
    if abs(penalty_adjustment) >= 0.005:
        # "decisivo" when converting it would have flipped the result (the larger
        # drop); a plain miss when the result was already decided.
        pen_label = ("rigore decisivo sbagliato" if penalty_adjustment <= -0.75
                     else "rigore sbagliato")
        contributions.append(entry(penalty_adjustment, pen_label, kind="penalty"))
    shown_rounded = sum(c["points"] for c in contributions)
    other_points = round(subtotal - VOTE_CENTER - shown_rounded, 2)

    # THE LEDGER BEHIND "altre N voci". The summary keeps three lines; on a game
    # that was good at everything the rest is not a tail but most of the vote —
    # Rrahmani, Genoa-Napoli: +0.56 shown, +0.81 unshown, and the biggest single
    # slice of the lot (the defensive index, +0.28) sitting inside the fold with no
    # name on it. So the fold has to be openable, and this is what is under it: the
    # same entries the summary chose from, minus the ones it showed, each one named.
    #
    # Built only on request (see ``ledger``) because it rides in the match payload
    # of twenty-two players, which is re-fetched on every live push.
    other_terms, tiny_count = [], 0
    if ledger:
        shown_keys = {key for _p, key, _ph, _f in shown}
        per90_keys = set(GK_PER90_WEIGHTS if role == Player.ROLE_GK else PER90_WEIGHTS)
        for pts, key, _ph, fam in sorted(scored, key=lambda x: x[0], reverse=True):
            if key in shown_keys:
                continue
            # Under a hundredth of a vote there is nothing to read: those are
            # counted and summed at the bottom instead of printing thirty "+0.00".
            if abs(round(pts, 2)) < 0.005:
                tiny_count += 1
                continue
            row = {"key": key,
                   "label": ledger_phrase(role, key, pts, raw_values.get(key, 0.0)),
                   "points": round(pts, 2)}
            if fam:
                # A merged family is one row here too, as in the summary; the count
                # says how many features it stands for.
                row["family"], row["family_size"] = fam
            else:
                # QUANTE volte l'ha fatto, come si conta nel tabellino: il numero
                # osservato, non quello che l'indice consuma. Per il blocco dei
                # volumi i due differiscono — l'indice ragiona per densita' e
                # proietta sui 90' — e "4,14 respinte" e' un numero che nessuno
                # puo' verificare da nessuna parte, mentre 4 sta nel tabellino.
                #
                # E si scrive solo quando e' un NUMERO DI COSE. Un indice
                # normalizzato (il valore difensivo, l'esposizione) o un valore
                # atteso (xA 0,03) messo li' nudo non spiega niente: quelle righe
                # portano il nome e i punti, che e' quanto si puo' dire con onesta'.
                count = (totals.get(key, 0.0) if key in per90_keys
                         else raw_values.get(key, 0.0))
                event_that_did_not_happen = (
                    (LABELS.get(key) or (None,))[0] == EVENT and round(count) == 0)
                if abs(count - round(count)) < 0.01 and not event_that_did_not_happen:
                    # "nessun gol" non ha bisogno di uno zero accanto: lo zero e'
                    # gia' tutta la frase.
                    row["value"] = int(round(count))
            other_terms.append(row)
    # The remainder is what the printed rows do not account for: the sub-hundredth
    # entries AND the rounding of everything above them. It is carried as one line
    # so the open ledger still adds up to the fold it opened.
    tiny_points = round(other_points - sum(r["points"] for r in other_terms), 2)
    low = minutes < SHRINKAGE_MINUTES * 2
    note = ("Con pochi minuti giocati ogni voce pesa meno: il voto resta piu' "
            "vicino al 6.") if low else ""
    if evidence_weight < 1.0:
        # A keeper who faced almost nothing: say so, or the muted breakdown reads
        # as a bug. This is the same statement the vote itself is making.
        note = ((note + " ") if note else "") + (
            "Gli sono arrivati pochi tiri in porta: c'e' poco su cui giudicarlo, "
            "quindi ogni voce pesa meno e il voto resta vicino al 6.")
    return {
        # perche' un assist puo' non muovere il voto base: e' la ragione piu' comune
        # per cui stiamo sotto una pagella su un giocatore che "ha fatto qualcosa"
        "assist_note": assist_note(assists, raw_values.get("expected_assists", 0.0),
                                   raw_values.get("big_chance_created", 0.0)),
        "positives": [entry(p, ph, fam) for p, _k, ph, fam in positives],
        "negatives": [entry(p, ph, fam) for p, _k, ph, fam in negatives],
        "contributions": contributions,
        "all_terms": all_terms,
        # Le voci NON mostrate, una per una (solo con ``ledger``): la riga "altre N
        # voci" del pannello si apre su queste, e insieme a ``other_tiny`` fanno
        # esattamente ``other_points``.
        "other_terms": other_terms,
        "other_tiny": {"count": tiny_count, "points": tiny_points},
        # vote points per index point for THIS appearance (it carries both
        # shrinkages): the scale that turns the index into the vote.
        "per_unit": round(per_unit, 6),
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
    # The vote-level facts (sending-off, own goal, missed penalty) are not features,
    # so they are absent from positives/negatives — call them out, WITH the reason
    # that set their size and the points they cost. Matched on ``kind``, not on the
    # label text: the labels now carry minute and reason and would break a match.
    by_kind = {c["kind"]: c for c in explanation.get("contributions", [])
               if c.get("kind")}
    for kind in ("red", "own_goal", "penalty"):
        c = by_kind.get(kind)
        if c:
            core += f" {c['label'].capitalize()} ({c['points']:+.2f})."
    note = explanation.get("assist_note")
    if note:
        core += " " + note
    return core
