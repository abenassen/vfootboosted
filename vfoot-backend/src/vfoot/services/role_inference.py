"""Derive classic fantasy roles (POR/DIF/CEN/ATT) from how a player actually played.

The problem this solves: Transfermarkt's position is authoritative for most of the
squad but genuinely ambiguous for wide players. Measured against a season of
fantacalcio.it roles, ten TM labels agree 100% of the time, while ``left winger``
splits 11/11 between midfielder and attacker — the label carries no information
there. So TM tells us the AREA of the pitch; our own data has to resolve the rest.

How, in three steps:

1. **Micro-categories, discovered not decreed.** Every outfielder with enough
   minutes is described by 15 measures — the heatmap along the attacking axis,
   width, box presence, shots, xG, key passes, xA, dribbles, duels, defensive
   actions, recoveries — and grouped by similarity. Real playing styles fall out:
   centre-backs, full-backs/wing-backs, holding midfielders, box strikers, and a
   clean WIDE ATTACKER group (dribbles +1.84, defensive actions -0.91).

   This ordering matters. Asking directly "is this winger an attacker?" means
   measuring his distance from the centre-forward archetype — which every winger
   is far from, so the answer is noise. Asking "which style is he?" first puts
   Boga with Pulisic and Politano, where he belongs, and only THEN condenses.

2. **Condensation to the four fantasy roles**, one deliberate decision per
   category rather than per player. Note that fantacalcio.it itself splits the
   wide-attacker group 22/14 between midfielder and attacker: there is no
   convention to copy, so we make ours explicit and reviewable in CATEGORY_ROLE.

3. **Two variants.** ``mitigated`` lets an unambiguous TM position win (a
   left-back who plays like a winger stays a defender); ``data`` lets the measured
   category decide for everyone. Leagues choose at listone time.

Stability: k-means depends on its seed, and a role that changed with the seed
would be exactly the arbitrariness this is meant to remove. So categories come
from CONSENSUS over many runs — how often two players land together — which
agrees with itself across seeds ~96% of the time. The same co-association gives
each player a confidence, and the players below it are the ones worth putting to
a human (see the league decision flow).

Timing: the listone is drawn at the start of a season, so everything here reads
the PREVIOUS season. A player who changes job over the summer will be wrong until
the next listone; that is inherent, not a defect.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from django.db import transaction
from django.db.models import Sum

from realdata.models import (
    MatchAppearance, Player, PlayerTeamStint, PlayerZoneFeature, PROVIDER_SOFASCORE,
)
from realdata.services.sofascore_adapter import METHOD_UNPLACED

PROVIDER_TM = "transfermarkt"

# TM positions whose fantasy role is not in doubt (verified at 100% against a full
# season of external roles, bar attacking midfield at 96%).
TM_DETERMINISTIC = {
    "goalkeeper": Player.ROLE_GK,
    "centre-back": Player.ROLE_DEF,
    "sweeper": Player.ROLE_DEF,
    "defender": Player.ROLE_DEF,
    "left-back": Player.ROLE_DEF,
    "right-back": Player.ROLE_DEF,
    "defensive midfield": Player.ROLE_MID,
    "central midfield": Player.ROLE_MID,
    "attacking midfield": Player.ROLE_MID,
    "midfielder": Player.ROLE_MID,
    "centre-forward": Player.ROLE_FWD,
    "striker": Player.ROLE_FWD,
    "forward": Player.ROLE_FWD,
    "attack": Player.ROLE_FWD,
}
# ...and the ones that are a coin flip, which is what the categories are for.
TM_AMBIGUOUS = {"left winger", "right winger", "left midfield", "right midfield",
                "second striker"}

# Fallback when a player has no usable history (a newcomer), pending a human
# decision. Deliberately CONSERVATIVE rather than modal: most wingers we measure
# turn out to be wide attackers, but an unknown winger is far more often a squad
# filler than a starter, and defaulting him to attacker inflates the one pool the
# auction is most sensitive to (it would add ~40 attackers to a 660-man listone).
# Midfield is the choice that costs least if it is wrong.
TM_DEFAULT = {"left winger": Player.ROLE_MID, "right winger": Player.ROLE_MID,
              "left midfield": Player.ROLE_DEF, "right midfield": Player.ROLE_DEF,
              "second striker": Player.ROLE_FWD}

# Minutes below which a season tells us too little to describe a style.
MIN_MINUTES = 600
N_CATEGORIES = 8          # where category quality stops improving
CONSENSUS_RUNS = 60       # k-means runs whose agreement defines the categories
LOW_CONFIDENCE = 0.55     # below this, ask a human rather than guess

FEATURE_NAMES = ([f"heat_col{i}" for i in range(5)] +
                 ["width", "box_share", "shots", "xg", "key_passes", "xa",
                  "dribbles", "duels", "defensive", "recoveries"])
_COUNTERS = ("touches", "touches_in_box", "shots", "shots_on_target", "xg_shots",
             "key_passes", "duels_won", "dribbles_won", "clearances",
             "interceptions", "blocks", "ball_recoveries", "expected_assists",
             "big_chance_created")


# A measured player goes to a human when the clustering cannot separate his TOP TWO
# fantasy roles by more than this. See ``role_margin``: it is a margin between
# ROLES, not the confidence in a category — a player can bounce between two styles
# that condense to the SAME role and still be perfectly determined for us.
ROLE_MARGIN_REVIEW = 0.25

# ...and the same question asked again in the space where the first one goes blind.
# See ``role_boundaries``: above this ratio a player sits nearly as close to a
# category of ANOTHER role as to his own. 0.80 was read off the 44 measured players
# whose TM position is ambiguous — the only ones this can ever fire on — and it is
# where the queue stops growing faster than what it catches.
BOUNDARY_REVIEW = 0.80


@dataclass
class PlayerRoleResult:
    player_id: int
    category: str            # "" when we had no usable data
    confidence: float        # co-association with the category core, 0..1
    role_data: str           # category-driven, for every player
    role_mitigated: str      # TM wins where it is unambiguous
    method: str              # category | tm | default | unknown
    tm_position: str = ""
    # How far the winning fantasy role is ahead of the runner-up, 0..1 (see
    # ``role_margin``). 1.0 when the role did not come from the clustering at all.
    role_margin: float = 1.0
    # How close he sits to a category of ANOTHER role, as a ratio of the distance
    # to his own (see ``role_boundaries``). 0.0 when the role did not come from
    # the clustering — the two "no doubt" defaults point in opposite directions
    # because the two quantities do.
    role_boundary: float = 0.0

    @property
    def needs_decision(self) -> bool:
        """A human should settle this one — and ONLY these, measured.

        An unambiguous Transfermarkt position ends the question whatever else we
        know: over a full season it matched the fantacalcio listone 351 times out
        of 352, and it did so in EVERY band of ``role_margin`` — 100% even where
        our own measurement was a coin flip. So a tight margin under a certain TM
        position says our clustering wobbled, not that TM is wrong, and asking a
        human there is nine questions with nothing to correct. The one case in the
        season where the measurement beat TM (De Ketelaere) had a margin of 0.76,
        the most CONFIDENT of the disagreeing group — the exact opposite of what a
        margin filter would have caught.

        Where the TM position is ambiguous nobody overrules the measurement, so
        the doubt is real and comes in two shapes:

        * we could not measure him — the SofaScore lineup position is all we have,
          and for a winger it is F/M/D, which cannot answer the CEN-or-ATT question
          fantacalcio itself splits down the middle: it agrees 8 times out of 15;
        * we did measure him and the measurement itself sits on the CEN/ATT line.
          That doubt has two shapes too, and one of them is invisible to the other:

          - ``role_margin`` below ROLE_MARGIN_REVIEW — the runs themselves could
            not agree. Berardi is this case: 60 runs put him at CEN 56% / ATT 35%.
          - ``role_boundary`` above BOUNDARY_REVIEW — the runs agreed, but he sits
            on the border in the FEATURE space. Esposito is this case, and only
            this one: margin 0.44 (settled), boundary 0.82 (on the line).

          The second exists because the first is computed on the co-association
          matrix, and that is precisely where players in doubt stop looking like
          it: two of them float between the same groups in the same proportions,
          so their co-association PROFILES converge even when they land apart half
          the runs. Barella and Esposito are 2.57σ apart on ball recoveries and
          3.27 apart overall — and only two players out of 370 have a
          co-association profile closer to Barella's than Esposito does. A margin
          read there cannot see a border it has already averaged away.

          Measured against the 2026-27 listone on the 44 players this can fire on:
          the margin alone asks 7 questions and lands on 1 real disagreement; the
          boundary asks 11 and lands on 6. They are kept in OR — the margin still
          catches players the boundary does not (Ngonge, Cancellieri, Cambiaghi),
          and nobody the queue holds today is dropped by adding a criterion.

        Note that ``confidence`` answers neither question: it measures how firmly
        he sits in his CATEGORY, and oscillating between two styles that condense
        to the SAME role is not a problem. In the loosest category 39 players out
        of 41 are below LOW_CONFIDENCE, which would make it a filter that fires on
        nearly everyone it is shown.
        """
        if self.tm_position not in TM_AMBIGUOUS:
            return False
        if self.method != "category":
            return True
        return (self.role_margin < ROLE_MARGIN_REVIEW
                or self.role_boundary > BOUNDARY_REVIEW)


@dataclass
class InferenceReport:
    results: list = field(default_factory=list)
    categories: dict = field(default_factory=dict)   # name -> {size, role, profile}
    n_measured: int = 0
    n_sofa: int = 0
    n_default: int = 0
    n_unknown: int = 0


# --------------------------------------------------------------------------
# feature extraction
# --------------------------------------------------------------------------

# SofaScore's coarse lineup position -> classic role. A crude signal, used ONLY
# for players we could not cluster (too few minutes) whose TM position is
# ambiguous — it still beats the blind positional default (a winger SofaScore
# lines up as a forward should not become a midfielder by convention).
SOFA_POSITION_ROLE = {"G": Player.ROLE_GK, "D": Player.ROLE_DEF,
                      "M": Player.ROLE_MID, "F": Player.ROLE_FWD}


def sofascore_position_roles(data_season_id: int) -> dict[int, str]:
    """player_id -> classic role from the MAJORITY of his SofaScore lineup
    positions (F/M/D/G) over ``data_season_id``. Reads the position persisted in
    ``MatchAppearance.raw_stats['position']``; empty for imports predating that
    field (run ``manage.py backfill_sofascore_position``)."""
    from collections import Counter, defaultdict
    tally: dict[int, Counter] = defaultdict(Counter)
    # Every appearance that carries a position counts, bench included: a player
    # named in a lineup has a coarse position even at 0 minutes, and it still beats
    # the raw TM default. Only a player who never appears at all falls through to
    # the TM identification.
    for pid, raw in (MatchAppearance.objects
                     .filter(match__competition_season_id=data_season_id)
                     .values_list("player_id", "raw_stats")):
        pos = (raw or {}).get("position")
        if pos:
            tally[pid][pos] += 1
    roles = {}
    for pid, counter in tally.items():
        role = SOFA_POSITION_ROLE.get(counter.most_common(1)[0][0])
        if role:
            roles[pid] = role
    return roles


def tm_positions(competition_season_id: int) -> dict[int, str]:
    """player_id -> the position his squad entry carried IN THAT SEASON.

    Read from the roster stint rather than from the player: a position belongs to
    a season, and the listone for season N must reason with season N's squads even
    while measuring season N-1's play.
    """
    return {pid: pos for pid, pos in (
        PlayerTeamStint.objects
        .filter(team_season__competition_season_id=competition_season_id)
        .exclude(tm_position="")
        .values_list("player_id", "tm_position"))}


def player_profiles(competition_season_id: int, min_minutes: int = MIN_MINUTES):
    """(player_ids, feature matrix) for outfielders with enough football played."""
    totals: dict[int, dict[str, float]] = {}
    grid: dict[int, np.ndarray] = {}
    # The unplaced rows of a match still being played carry no position, and the
    # split below would raise on their key rather than misread it — which is the
    # point of that key. Either way they have no business in a spatial cluster.
    for pid, zk, fk, v in (PlayerZoneFeature.objects
                           .filter(provider=PROVIDER_SOFASCORE,
                                   feature_key__in=_COUNTERS,
                                   match__competition_season_id=competition_season_id)
                           .exclude(source_method=METHOD_UNPLACED)
                           .values_list("player_id", "zone_key", "feature_key")
                           .annotate(v=Sum("value"))
                           .values_list("player_id", "zone_key", "feature_key", "v")):
        totals.setdefault(pid, {}).setdefault(fk, 0.0)
        totals[pid][fk] += v
        if fk == "touches":
            _, col, row = zk.split("_")
            grid.setdefault(pid, np.zeros((5, 4)))[int(col)][int(row)] += v

    minutes: dict[int, float] = {}
    for pid, m in (MatchAppearance.objects
                   .filter(match__competition_season_id=competition_season_id)
                   .values_list("player_id", "minutes_played")):
        minutes[pid] = minutes.get(pid, 0.0) + (m or 0)

    # CHI È UN PORTIERE, e perché non basta il tag. ``Player.is_goalkeeper`` viene
    # dal cartellino Transfermarkt, quindi esiste solo per chi sta in una rosa che
    # abbiamo importato: su un'installazione che ha le rose della stagione NUOVA ma
    # non di quella misurata — la produzione all'11/08/2026 — sette portieri della
    # 2025-26 avevano il tag a False. Senza questa seconda prova finivano qui dentro,
    # venivano raggruppati per stile con i giocatori di movimento e ne uscivano
    # centrocampisti: da lì un voto sul canale sbagliato (Montipò 5.0 invece di 6.0)
    # e categorie spostate anche per gli altri, perché la popolazione del clustering
    # non era la stessa. La distinta SofaScore dice chi era in porta senza inferire
    # niente, e c'è dove c'è una partita.
    keepers = set(Player.objects.filter(is_goalkeeper=True).values_list("id", flat=True))
    keepers |= {pid for pid, role in
                sofascore_position_roles(competition_season_id).items()
                if role == Player.ROLE_GK}
    ids, rows = [], []
    for pid, g in grid.items():
        if pid in keepers or minutes.get(pid, 0) < min_minutes or g.sum() <= 0:
            continue
        t = totals[pid].get("touches", 0.0)
        if t <= 0:
            continue
        m = minutes[pid]
        col = g.sum(axis=1) / g.sum()
        row = g.sum(axis=0) / g.sum()
        p90 = lambda k: totals[pid].get(k, 0.0) * 90 / m  # noqa: E731
        ids.append(pid)
        rows.append(list(col) + [
            row[0] + row[3],                       # how wide he stays
            totals[pid].get("touches_in_box", 0.0) / t,
            p90("shots"), p90("xg_shots"), p90("key_passes"),
            p90("expected_assists"), p90("dribbles_won"), p90("duels_won"),
            p90("clearances") + p90("interceptions") + p90("blocks"),
            p90("ball_recoveries"),
        ])
    return ids, np.array(rows) if rows else np.zeros((0, len(FEATURE_NAMES)))


# --------------------------------------------------------------------------
# consensus clustering
# --------------------------------------------------------------------------

def _kmeans(Z: np.ndarray, k: int, seed: int, iters: int = 200):
    r = np.random.default_rng(seed)
    C = Z[r.integers(len(Z))][None, :]
    for _ in range(k - 1):                                   # k-means++
        d = ((Z[:, None, :] - C[None, :, :]) ** 2).sum(2).min(1)
        s = d.sum()
        C = np.vstack([C, Z[r.choice(len(Z), p=d / s) if s > 0 else r.integers(len(Z))]])
    lab = np.zeros(len(Z), dtype=int)
    for _ in range(iters):
        lab = ((Z[:, None, :] - C[None, :, :]) ** 2).sum(2).argmin(1)
        new = np.array([Z[lab == j].mean(0) if (lab == j).any() else C[j]
                        for j in range(k)])
        if np.allclose(new, C):
            break
        C = new
    return lab, C


def consensus_categories(Z: np.ndarray, k: int = N_CATEGORIES,
                         runs: int = CONSENSUS_RUNS):
    """Seed-independent categories, plus each player's confidence in his own.

    A single k-means run moves the boundary of the wide-attacker group between 24
    and 49 players depending on the seed. Averaging membership over many runs (the
    co-association matrix) and clustering THAT is stable to ~96%, and the average
    co-association with one's own group is a natural, honest confidence.
    """
    if len(Z) < k:
        return np.zeros(len(Z), dtype=int), np.ones(len(Z)), np.zeros((len(Z), len(Z)))
    M = np.zeros((len(Z), len(Z)))
    for s in range(runs):
        lab, _ = _kmeans(Z, k, 1000 + s)
        M += (lab[:, None] == lab[None, :])
    M /= runs
    labels, _ = _kmeans(M, k, 7)          # cluster the co-association profiles
    conf = np.array([M[i][labels == labels[i]].mean() for i in range(len(Z))])
    return labels, conf, M


# --------------------------------------------------------------------------
# naming + condensation
# --------------------------------------------------------------------------

def describe_categories(Z: np.ndarray, labels: np.ndarray) -> dict:
    """Name each category from its own profile, so the output is readable without
    having to look up cluster numbers."""
    mu, sd = Z.mean(0), np.where(Z.std(0) == 0, 1, Z.std(0))
    out = {}
    for j in sorted(set(labels.tolist())):
        c = (Z[labels == j].mean(0) - mu) / sd
        f = dict(zip(FEATURE_NAMES, c))
        deep = f["heat_col0"] > 0.4
        high = f["heat_col4"] > 0.6
        wide = f["width"] > 0.5
        if deep and f["defensive"] > 0.5:
            name = "centrale difensivo" if not wide else "terzino"
        elif wide and f["defensive"] > -0.3 and not high:
            name = "esterno basso"
        elif high and f["box_share"] > 0.8:
            name = "punta d'area"
        elif high and (wide or f["dribbles"] > 0.8):
            name = "ala offensiva"
        elif f["recoveries"] > 0.5:
            name = "mediano"
        elif high or f["shots"] > 0.2:
            name = "centrocampista offensivo"
        else:
            name = "centrocampista"
        while name in out:                 # keep names unique and stable
            name += " ii"
        out[name] = {"label": j, "size": int((labels == j).sum()),
                     "profile": {k: round(float(v), 2) for k, v in f.items()}}
    return out


# Category -> fantasy role. THIS is where a convention is chosen, deliberately and
# in one place. "ala offensiva" -> ATT is the substantive call: fantacalcio.it
# splits that same group 22/14, so there is no convention to inherit. Sending it
# to ATT costs 0.8 points of agreement with them and takes the listone from 77 to
# 106 attackers (5.3 per club), which is what a 12-manager league needs.
CATEGORY_ROLE = {
    "centrale difensivo": Player.ROLE_DEF,
    "terzino": Player.ROLE_DEF,
    "esterno basso": Player.ROLE_DEF,
    "mediano": Player.ROLE_MID,
    "centrocampista": Player.ROLE_MID,
    "centrocampista offensivo": Player.ROLE_MID,
    "ala offensiva": Player.ROLE_FWD,
    "punta d'area": Player.ROLE_FWD,
}


def _role_for_category(name: str) -> str:
    base = name.replace(" ii", "").strip()
    return CATEGORY_ROLE.get(base, Player.ROLE_MID)


def role_margins(M: np.ndarray, labels: np.ndarray, by_label: dict) -> np.ndarray:
    """How firmly the clustering picks each player's FANTASY ROLE, 0..1.

    ``confidence`` answers "which style is he?", which is step 2 of the pipeline;
    what actually reaches the listone is step 3, the condensation of eight styles
    into four roles. The two questions have different answers. A midfielder who
    oscillates between 'mediano' and 'centrocampista' has a low category
    confidence and a completely determined role — both condense to CEN — while a
    winger split between 'centrocampista offensivo' and 'ala offensiva' is torn
    across the CEN/ATT line, which is the only kind of doubt worth a human's time.

    So the co-association mass is re-aggregated BY ROLE (how often, over the runs,
    he lands with players who end up in that role) and the margin is the gap
    between the top role and the runner-up. Berardi comes out at CEN 56% / ATT 35%
    — margin 0.21, below ROLE_MARGIN_REVIEW — where his category confidence of
    0.336 said nothing about which role was at stake.
    """
    role_of = {lab: _role_for_category(name) for lab, name in by_label.items()}
    roles = sorted(set(role_of.values()))
    if len(roles) < 2:
        return np.ones(len(M))
    mass = np.stack([M[:, np.array([role_of[int(l)] == r for l in labels])].sum(1)
                     for r in roles], axis=1)
    total = mass.sum(1, keepdims=True)
    share = np.divide(mass, total, out=np.zeros_like(mass), where=total > 0)
    top2 = np.sort(share, axis=1)[:, -2:]
    return top2[:, 1] - top2[:, 0]


def role_boundaries(Z: np.ndarray, labels: np.ndarray, by_label: dict) -> np.ndarray:
    """How close each player sits to a category of ANOTHER fantasy role, 0..∞.

    ``distance to his own category's centre / distance to the nearest centre whose
    category condenses to a different role``. Near 1 he is on the border; well
    below it his role is not in question whatever the runs did.

    This is ``role_margin``'s question asked in the space where it can still be
    answered. The margin lives on the co-association matrix, which averages over
    60 runs — and averaging is exactly what erases a border for the players
    standing on it, because two undecided players drift between the same groups
    and end up with the same PROFILE of indecision. The feature space keeps the
    geometry: Esposito is 0.82 here and 0.44 there, and 0.82 is the true reading.

    Zero when there is no category of another role to be close to, which cannot
    happen with the shipped categories and would mean "no doubt" if it did.
    """
    role_of = {lab: _role_for_category(name) for lab, name in by_label.items()}
    labs = sorted(role_of)
    C = np.stack([Z[labels == lab].mean(0) for lab in labs])
    D = np.linalg.norm(Z[:, None, :] - C[None, :, :], axis=2)
    own_col = {lab: j for j, lab in enumerate(labs)}
    out = np.zeros(len(Z))
    for i in range(len(Z)):
        own = int(labels[i])
        other = [j for j, lab in enumerate(labs) if role_of[lab] != role_of[own]]
        if not other:
            continue
        nearest = D[i, other].min()
        out[i] = D[i, own_col[own]] / nearest if nearest > 0 else 0.0
    return out


# --------------------------------------------------------------------------
# the pipeline
# --------------------------------------------------------------------------

def infer_roles(roster_season_id: int, data_season_id: int, *,
                min_minutes: int = MIN_MINUTES,
                n_categories: int = N_CATEGORIES,
                runs: int = CONSENSUS_RUNS) -> InferenceReport:
    """Roles for the squads of ``roster_season_id``, measured on the football
    actually played in ``data_season_id`` (normally the season before)."""
    tm_pos = tm_positions(roster_season_id)
    competition_season_id = data_season_id

    ids, Z = player_profiles(competition_season_id, min_minutes)
    report = InferenceReport()
    if len(ids):
        mu, sd = Z.mean(0), np.where(Z.std(0) == 0, 1, Z.std(0))
        Zs = (Z - mu) / sd
        labels, conf, M = consensus_categories(Zs, n_categories, runs)
        cats = describe_categories(Zs, labels)
        by_label = {v["label"]: k for k, v in cats.items()}
        for name, meta in cats.items():
            meta["role"] = _role_for_category(name)
        report.categories = cats
        margins = role_margins(M, labels, by_label)
        boundaries = role_boundaries(Zs, labels, by_label)
    else:
        labels, conf, by_label = np.zeros(0), np.zeros(0), {}
        margins = boundaries = np.zeros(0)

    measured = {}
    for i, pid in enumerate(ids):
        name = by_label[int(labels[i])]
        measured[pid] = (name, float(conf[i]), _role_for_category(name),
                         float(margins[i]), float(boundaries[i]))

    # Coarse SofaScore lineup position: too few minutes to cluster (< MIN_MINUTES)
    # is NOT the same as no data — a player who lined up at all has a position, and
    # for an ambiguous TM label it beats the blind positional default.
    sofa_roles = sofascore_position_roles(competition_season_id)

    everyone = set(tm_pos) | set(measured) | set(sofa_roles)
    for pid in sorted(everyone):
        pos = tm_pos.get(pid, "")
        # margin 1.0 / boundary 0.0 = the role did not come from the clustering, so
        # there is no runner-up to be close to and no border to stand on; only a
        # measured player can be torn.
        margin, boundary = 1.0, 0.0
        if pid in measured:
            cat, c, role, margin, boundary = measured[pid]
            method = "category"
            report.n_measured += 1
        elif pos in TM_DETERMINISTIC:
            cat, c, role, method = "", 1.0, TM_DETERMINISTIC[pos], "tm"
        elif pid in sofa_roles:
            cat, c, role, method = "", 0.0, sofa_roles[pid], "sofa"
            report.n_sofa += 1
        elif pos in TM_DEFAULT:
            cat, c, role, method = "", 0.0, TM_DEFAULT[pos], "default"
            report.n_default += 1
        else:
            cat, c, role, method = "", 0.0, "", "unknown"
            report.n_unknown += 1
        # The mitigated variant: an unambiguous TM position outranks the measured
        # style, so a full-back who plays like a winger stays a defender.
        #
        # It does NOT overwrite the margin. That was the first attempt and it was
        # wrong: letting TM settle the DECISION is right, letting it erase the
        # measurement's own uncertainty is not. Nico Paz (0.24) and McTominay (0.23)
        # are as torn between roles as Berardi (0.22), and were being recorded as
        # margin 1.0 — "no doubt at all" — purely because TM had an opinion. The
        # margin is a diagnostic of the clustering; whoever wins the role, it stays
        # what it measured.
        mitigated = TM_DETERMINISTIC.get(pos, role) if pos else role
        report.results.append(PlayerRoleResult(
            player_id=pid, category=cat, confidence=round(c, 3),
            role_data=role, role_mitigated=mitigated, method=method,
            tm_position=pos, role_margin=round(margin, 3),
            role_boundary=round(boundary, 3)))
    return report


# --------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------


def store_roles(report: InferenceReport) -> int:
    """Replace the whole ``CurrentPlayerRole`` table with this report.

    Destructive by design, and that is the right shape: the model is "the current
    role", one row per player with no season dimension, so a recompute overwrites
    in place. It is only the GLOBAL estimate — a league's own ``LeaguePlayerRole``
    is frozen and is never touched from here, which is what lets this run as often
    as we like without a settled squad ever moving under its owner.
    """
    from vfoot.models import CurrentPlayerRole

    with transaction.atomic():
        CurrentPlayerRole.objects.all().delete()
        CurrentPlayerRole.objects.bulk_create([
            CurrentPlayerRole(
                player_id=r.player_id,
                category=r.category, confidence=r.confidence,
                role_margin=r.role_margin, role_boundary=r.role_boundary,
                role_data=r.role_data, role_mitigated=r.role_mitigated,
                method=r.method, tm_position=r.tm_position)
            for r in report.results], batch_size=500)
    return len(report.results)


def refresh_current_roles(roster_cs, *, data_cs=None, **kw) -> dict:
    """Re-derive the global roles for a season's squads. The unattended entry point.

    Called after every Transfermarkt import so that a player who signed today gets
    the same treatment as everyone else — a measured role where there is play data,
    the provider position where there is not, and BOTH variants stored, so each
    league resolves him under its own ``role_mode``. Before this existed a newcomer
    had no row at all and fell through to ``Player.classic_role_seed``: the raw
    provider map, identical for every league, which quietly made a league's choice
    of role mode not apply to precisely the players it was most likely to matter for.

    Returns a summary dict; ``written`` says whether the table was replaced.
    """
    from vfoot.models import CurrentPlayerRole
    from vfoot.services.player_ratings import previous_season_with_data

    if data_cs is None:
        data_cs = previous_season_with_data(roster_cs)
    if data_cs is None:
        return {"written": False, "reason": "no_data_season",
                "detail": f"nessuna stagione precedente con dati per {roster_cs}"}

    report = infer_roles(roster_cs.id, data_cs.id, **kw)

    # The guard that matters in practice. ``infer_roles`` degrades gracefully — no
    # play data means everyone falls back to the provider position — and that is
    # right for one player, but catastrophic for a whole table: it would trade a
    # set of MEASURED roles for provider defaults and report success. A data
    # season without zone features (never imported, or wiped) is the ordinary way
    # to arrive here, so it must fail loudly and change nothing.
    if not report.n_measured and CurrentPlayerRole.objects.filter(
            method=CurrentPlayerRole.METHOD_CATEGORY).exists():
        return {"written": False, "reason": "no_measurement",
                "detail": (f"{data_cs} non ha dati di gioco utilizzabili: la tabella "
                           f"esistente contiene ruoli misurati e non viene toccata"),
                "data_season": str(data_cs)}

    return {"written": True, "reason": "ok", "data_season": str(data_cs),
            "stored": store_roles(report),
            "measured": report.n_measured, "sofa": report.n_sofa,
            "default": report.n_default, "unknown": report.n_unknown}
