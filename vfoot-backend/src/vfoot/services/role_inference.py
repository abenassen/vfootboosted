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
from django.db.models import Sum

from realdata.models import (
    MatchAppearance, Player, PlayerTeamStint, PlayerZoneFeature, PROVIDER_SOFASCORE,
)

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


@dataclass
class PlayerRoleResult:
    player_id: int
    category: str            # "" when we had no usable data
    confidence: float        # co-association with the category core, 0..1
    role_data: str           # category-driven, for every player
    role_mitigated: str      # TM wins where it is unambiguous
    method: str              # category | tm | default | unknown
    tm_position: str = ""

    @property
    def needs_decision(self) -> bool:
        """A human should settle this one: the position is genuinely ambiguous AND
        we could not measure the player. Everything else has an answer we stand
        behind (an unambiguous position needs no arbitration, and a measured
        player has one)."""
        return self.tm_position in TM_AMBIGUOUS and self.method != "category"


@dataclass
class InferenceReport:
    results: list = field(default_factory=list)
    categories: dict = field(default_factory=dict)   # name -> {size, role, profile}
    n_measured: int = 0
    n_default: int = 0
    n_unknown: int = 0


# --------------------------------------------------------------------------
# feature extraction
# --------------------------------------------------------------------------

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
    for pid, zk, fk, v in (PlayerZoneFeature.objects
                           .filter(provider=PROVIDER_SOFASCORE,
                                   feature_key__in=_COUNTERS,
                                   match__competition_season_id=competition_season_id)
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

    keepers = set(Player.objects.filter(is_goalkeeper=True).values_list("id", flat=True))
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
        labels, conf, _ = consensus_categories(Zs, n_categories, runs)
        cats = describe_categories(Zs, labels)
        by_label = {v["label"]: k for k, v in cats.items()}
        for name, meta in cats.items():
            meta["role"] = _role_for_category(name)
        report.categories = cats
    else:
        labels, conf, by_label = np.zeros(0), np.zeros(0), {}

    measured = {}
    for i, pid in enumerate(ids):
        name = by_label[int(labels[i])]
        measured[pid] = (name, float(conf[i]), _role_for_category(name))

    everyone = set(tm_pos) | set(measured)
    for pid in sorted(everyone):
        pos = tm_pos.get(pid, "")
        if pid in measured:
            cat, c, role = measured[pid]
            method = "category"
            report.n_measured += 1
        elif pos in TM_DETERMINISTIC:
            cat, c, role, method = "", 1.0, TM_DETERMINISTIC[pos], "tm"
        elif pos in TM_DEFAULT:
            cat, c, role, method = "", 0.0, TM_DEFAULT[pos], "default"
            report.n_default += 1
        else:
            cat, c, role, method = "", 0.0, "", "unknown"
            report.n_unknown += 1
        # The mitigated variant: an unambiguous TM position outranks the measured
        # style, so a full-back who plays like a winger stays a defender.
        mitigated = TM_DETERMINISTIC.get(pos, role) if pos else role
        report.results.append(PlayerRoleResult(
            player_id=pid, category=cat, confidence=round(c, 3),
            role_data=role, role_mitigated=mitigated, method=method,
            tm_position=pos))
    return report
