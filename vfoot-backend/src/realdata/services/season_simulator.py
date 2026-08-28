"""Synthesise a Serie A season in SofaScore's own shape, for a season not yet played.

Why this exists. The 2026-27 calendar is in the database — teams, fixtures, provider
ids — and nothing else: no appearance, no shot, no card. Everything downstream of a
played match (the voto puro, the listone, a league's pagelle, standings, the whole
classic scoring chain) therefore has nothing to work on, and cannot be exercised
until the season is actually played. This module invents the matches.

WHAT IT WRITES, AND WHY THAT AND NOT DATABASE ROWS
--------------------------------------------------
It writes provider-shaped JSON into the SofaScore request cache, and stops there.
The rows are then created by the REAL importer (``import_sofascore``,
``import_sofascore_intervals``) reading that cache, exactly as it does for a real
scrape — ``SofaScoreClient`` serves a cached path without touching the network, so
an offline run needs no network and no ``curl_cffi``.

The alternative — writing MatchAppearance / PlayerZoneFeature / MatchShot directly —
was rejected: it would be a second, parallel implementation of the ingestion, free
to drift from the real one, and every mapping bug it introduced would look like a
scoring bug. Going through the cache means the zone binning, the heatmap
distribution, the own-goal handling, the card taxonomy and the interval
reconstruction are all THE SAME CODE that handles real data. What this module is
responsible for is only the plausibility of the payloads.

HOW A PERFORMANCE IS INVENTED
-----------------------------
Not by drawing sixty statistics from sixty distributions: they are strongly
dependent (a full-back with 90 touches does not have 4 completed passes) and the
result would be incoherent in ways the vote would faithfully report. Instead each
appearance is DONOR-SAMPLED from the 2025-26 season, which is in the database with
its complete stat blobs: a real performance by a real player in the same coarse
position and a similar number of minutes. Its internal coherence comes for free
because it happened.

Quality is expressed by WHICH donor is drawn, not by scaling the numbers. A player's
market value gives him a percentile within his role; the donor is drawn near the
same percentile of the donors' own rating distribution, nudged by how the match is
going for his team. So a stronger player systematically draws better games without
a single feature being hand-multiplied — and the frozen calibration in
``vote_reference.json``, which was computed on exactly this population, keeps
meaning what it means.

The events are decided FIRST (scoreline, scorers, assists, cards, substitutions)
and always win: after the donor blob is drawn, the keys that describe events are
overwritten to match the shotmap and the incidents. The donor supplies the texture,
the event layer supplies the spine.

WHAT IS DELIBERATELY NOT MODELLED
---------------------------------
Injuries and suspensions carrying across matchdays, transfer windows, real tactical
matchups, and any correlation between a player's form and his previous match. A
squad rotates around a stable first choice and that is all. This is a fixture
generator for exercising the application, not a football model, and pretending
otherwise in the docstring would be the first step to someone trusting a number in
it.
"""
from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from realdata.models import (
    CompetitionSeason,
    Match,
    MatchAppearance,
    Player,
    PlayerAlias,
    PlayerMarketValue,
    PlayerTeamStint,
    TeamSeason,
)

from realdata.services.identity import synthetic_sofascore_id

PROVIDER = "sofascore"
SERIE_A_TOURNAMENT_ID = 23

# Measured on the real 2025-26 season (380 matches) — see the numbers each drives.
GOALS_HOME = 1.276           # mean home goals
GOALS_AWAY = 1.150           # mean away goals
SHOTS_PER_TEAM = 12.3        # 24.7 per match
YELLOWS_PER_TEAM = 1.83      # 3.66 per match
SECOND_YELLOW_PER_TEAM = 0.030
STRAIGHT_RED_PER_TEAM = 0.059
SUBS_PER_TEAM = 4.7
BENCH_NAMED = 12             # 46.8 appearances per match / 2 - 11

# Shot outcome mix, excluding goals (which the scoreline fixes): save / miss /
# block / post, renormalised from 2166 / 3556 / 2558 / 179.
SHOT_OUTCOMES = (("save", 0.256), ("miss", 0.421), ("block", 0.302), ("post", 0.021))
# Play the shot came from. ``penalty`` is handled separately (it is awarded, not
# drawn), so it is absent here and its 1.1% is spread over the rest.
SHOT_SITUATIONS = (
    ("assisted", 0.494), ("corner", 0.160), ("regular", 0.132), ("fast-break", 0.078),
    ("set-piece", 0.071), ("throw-in-set-piece", 0.035), ("free-kick", 0.030),
)
PENALTIES_PER_TEAM = 0.14    # 106 penalty shots / 760 team-matches
PENALTY_CONVERSION = 0.76

# HOW MUCH A PLAYER'S PRICE PREDICTS ONE AFTERNOON. The single most important
# constant here, and the one it is easiest to get badly wrong by intuition.
#
# Measured on 9,905 real appearances of at least 20 minutes: the correlation
# between a player's market-value percentile WITHIN HIS ROLE and his rating in a
# given match is +0.170 (DIF +0.184, CEN +0.182, ATT +0.129, POR +0.097), and the
# gap between the top and bottom value quintiles is 0.31 rating points — on a
# distribution whose own spread is 0.56. Being expensive buys barely a third of a
# standard deviation.
#
# The obvious mapping — draw the donor at the player's own percentile — is
# therefore about five times too strong: it made every costly player take a 9 every
# week and every cheap one a 5.5, a season with no overlap at all, which would then
# propagate into the listone as a ranking that merely re-reads Transfermarkt.
#
# So the percentile is COMPRESSED toward the middle and drowned in noise:
#     p = 0.5 + QUALITY_PULL * (quality - 0.5) + N(0, QUALITY_NOISE)
# which reproduces r ~ 0.22 and a top-to-bottom gap near 0.3 rating points. Kept
# marginally above the measured value on purpose: in a fantasy league a squad's
# price has to mean SOMETHING, and erring here is erring toward the game.
#
# QUALITY_NOISE is wide on purpose, and its width is a second, separate target: the
# donor is picked by percentile, so only a nearly FLAT distribution of percentiles
# reproduces the pool's own spread of performances. Narrow it and the whole league
# regresses to the median — at 0.25 the season's rating spread fell to 0.41 against
# a real 0.58, every player becoming interchangeably average. The pull is then
# raised alongside it to hold the correlation where it was measured.
QUALITY_PULL = 0.35
QUALITY_NOISE = 0.45
# How much the way the match is going colours the individual performances, per goal
# of margin. A player in a side three up genuinely has a better afternoon; capped
# so a rout does not hand everyone on the pitch a nine.
RESULT_EDGE_PER_GOAL = 0.045
RESULT_EDGE_CAP = 0.14

# Kick-off slots a Serie A round is spread over, as (days after Saturday, hour,
# minute) in ITALIAN LOCAL time — the times the fixture list is published in. They
# are converted to UTC through Europe/Rome rather than by adding a fixed hour,
# because a season crosses the summer-time boundary in late October and a hardcoded
# offset would put every autumn round an hour out.
#
# Ten slots for ten matches: this is what spreads a round across a weekend, and it
# is the reason a round can be half played — the state the whole simulation exists
# to reproduce.
ROUND_SLOTS = (
    (0, 15, 0), (0, 18, 0), (0, 20, 45),                 # Saturday
    (1, 12, 30), (1, 15, 0), (1, 15, 0), (1, 18, 0),     # Sunday
    (1, 20, 45), (1, 20, 45), (1, 20, 45),
)

# Lineup slots per module: (label, position letter, heatmap anchor x, anchor y).
# x runs from the player's OWN goal (0) to the one he attacks (100), which is the
# frame SofaScore heatmaps already use; y is left (0) to right (100).
GK_SLOT = ("GK", "G", 9.0, 50.0)
MODULES = {
    "4-3-3": [
        ("LB", "D", 34, 16), ("CBL", "D", 26, 39), ("CBR", "D", 26, 61), ("RB", "D", 34, 84),
        ("CM", "M", 47, 30), ("DM", "M", 42, 50), ("AM", "M", 55, 70),
        ("LW", "F", 66, 17), ("ST", "F", 73, 50), ("RW", "F", 66, 83),
    ],
    "4-4-2": [
        ("LB", "D", 34, 16), ("CBL", "D", 26, 39), ("CBR", "D", 26, 61), ("RB", "D", 34, 84),
        ("LM", "M", 52, 15), ("CML", "M", 46, 40), ("CMR", "M", 46, 60), ("RM", "M", 52, 85),
        ("STL", "F", 71, 38), ("STR", "F", 71, 62),
    ],
    "3-5-2": [
        ("CBL", "D", 25, 30), ("CB", "D", 23, 50), ("CBR", "D", 25, 70),
        ("LWB", "M", 50, 12), ("CML", "M", 46, 38), ("DM", "M", 41, 50),
        ("CMR", "M", 46, 62), ("RWB", "M", 50, 88),
        ("STL", "F", 71, 38), ("STR", "F", 71, 62),
    ],
    "4-2-3-1": [
        ("LB", "D", 34, 16), ("CBL", "D", 26, 39), ("CBR", "D", 26, 61), ("RB", "D", 34, 84),
        ("DML", "M", 42, 40), ("DMR", "M", 42, 60),
        ("LAM", "M", 60, 18), ("CAM", "M", 58, 50), ("RAM", "M", 60, 82),
        ("ST", "F", 74, 50),
    ],
}
# How many players of each classic role a module wants, so the squad is filled with
# players who can plausibly occupy the slot.
SLOT_ROLE = {"G": "POR", "D": "DIF", "M": "CEN", "F": "ATT"}

# Heatmap spread around the anchor, by position letter. A forward roams more across
# the width than a centre-back does; a keeper barely moves at all.
HEATMAP_SIGMA = {"G": (7.0, 9.0), "D": (11.0, 12.0), "M": (13.0, 16.0), "F": (14.0, 18.0)}
HEATMAP_POINTS_FULL = 130    # points for a full 90 minutes; scaled by minutes played

# Goal/assist propensity by position letter — who scores in a team that scores.
GOAL_WEIGHT = {"G": 0.0, "D": 0.13, "M": 0.30, "F": 1.00}
ASSIST_WEIGHT = {"G": 0.01, "D": 0.22, "M": 0.55, "F": 0.75}
CARD_WEIGHT = {"G": 0.25, "D": 1.25, "M": 1.20, "F": 0.75}

# Stat keys the event layer OWNS: whatever the donor had in them is discarded and
# rewritten from the shotmap and the incidents. Everything else is the donor's.
EVENT_OWNED_KEYS = (
    "goals", "goalAssist", "totalShots", "onTargetScoringAttempt", "shotOffTarget",
    "blockedScoringAttempt", "hitWoodwork", "expectedGoals", "expectedGoalsOnTarget",
    "penaltyMiss", "penaltyWon", "penaltyConceded", "ownGoals", "penaltySave",
    "penaltyFaced", "saves", "savedShotsFromInsideTheBox", "goalsPrevented",
    "minutesPlayed", "substitute", "position", "id", "name", "shortName",
    "dateOfBirthTimestamp", "userCount",
)


# --------------------------------------------------------------------------- #
# Squads                                                                       #
# --------------------------------------------------------------------------- #
@dataclass
class SimPlayer:
    player_id: int
    sofa_id: str
    name: str
    short_name: str
    dob_ts: int | None
    role: str                  # POR / DIF / CEN / ATT
    value_eur: int
    quality: float = 0.5       # percentile within the whole league, per role
    # True when the provider id was minted here rather than scraped. Carried as a
    # flag and not inferred from the id's shape: real SofaScore ids beginning with 9
    # exist, and testing the prefix quietly registered an alias for a hundred
    # players who already had a perfectly good identity.
    synthetic: bool = False


@dataclass
class SimTeam:
    team_season_id: int
    sofa_id: str
    name: str
    short_name: str
    players: list[SimPlayer] = field(default_factory=list)
    attack: float = 1.0
    defence: float = 1.0
    # The stable first choice, by role: index into the role-sorted squad. Rotation
    # happens around this, so a team fields recognisably the same side week to week.
    depth: dict[str, list[SimPlayer]] = field(default_factory=dict)


# Il formato vive in ``identity`` insieme al suo riconoscimento: v. la nota la'.
# Qui resta solo il nome locale, perche' e' questo modulo a decidere CHI ne ha
# bisogno — un giocatore senza identita' SofaScore — non come sia fatto.
_synthetic_sofa_id = synthetic_sofascore_id


def ensure_aliases(players: list[SimPlayer]) -> int:
    """Register the synthetic ids, so the importer never creates a second Player."""
    made = 0
    for p in players:
        if not p.synthetic:
            continue
        _, created = PlayerAlias.objects.get_or_create(
            player_id=p.player_id, source=PROVIDER, alias=p.sofa_id)
        made += int(created)
    return made


def load_squads(competition_season_id: int) -> dict[int, SimTeam]:
    """{team_season_id: SimTeam} with squads, qualities and strengths."""
    values = dict(
        PlayerMarketValue.objects.filter(provider="transfermarkt")
        .order_by("player_id", "-as_of").values_list("player_id", "value_eur")
    )
    teams: dict[int, SimTeam] = {}
    for ts in (TeamSeason.objects
               .filter(competition_season_id=competition_season_id)
               .select_related("team")):
        teams[ts.id] = SimTeam(
            team_season_id=ts.id, sofa_id=str(ts.team.external_id),
            name=ts.team.name, short_name=ts.team.short_name or ts.team.name[:12])

    stints = (PlayerTeamStint.objects
              .filter(team_season__competition_season_id=competition_season_id)
              .select_related("player", "team_season"))
    aliases = dict(PlayerAlias.objects.filter(source=PROVIDER)
                   .values_list("player_id", "alias"))
    for stint in stints:
        p = stint.player
        synthetic = False
        if p.external_source == PROVIDER and p.external_id:
            sofa_id = str(p.external_id)
        elif p.id in aliases:
            sofa_id = aliases[p.id]
        else:
            sofa_id, synthetic = _synthetic_sofa_id(p.id), True
        role = p.classic_role_seed or ("POR" if p.is_goalkeeper else "CEN")
        teams[stint.team_season_id].players.append(SimPlayer(
            player_id=p.id, sofa_id=sofa_id,
            name=p.full_name, short_name=p.short_name or p.full_name,
            dob_ts=(int(datetime.combine(p.date_of_birth, datetime.min.time(),
                                         tzinfo=dt_timezone.utc).timestamp())
                    if p.date_of_birth else None),
            role=role, value_eur=int(values.get(p.id) or 0), synthetic=synthetic,
        ))

    _rank_quality(teams)
    _rate_strength(teams)
    return teams


def _rank_quality(teams: dict[int, SimTeam]) -> None:
    """Quality percentile within ROLE, across the whole league.

    Within role and not overall, because market values are not comparable across
    roles — the median forward is worth several times the median keeper, and a
    league-wide ranking would make every goalkeeper a bad player and every vote for
    one systematically low.
    """
    by_role: dict[str, list[SimPlayer]] = defaultdict(list)
    for team in teams.values():
        for p in team.players:
            by_role[p.role].append(p)
    for players in by_role.values():
        players.sort(key=lambda p: p.value_eur)
        n = max(1, len(players) - 1)
        for i, p in enumerate(players):
            # A player with no market value at all is unknown, not bad: he is placed
            # low but not at the floor, where he would be guaranteed the worst
            # donor of the pool every single week.
            p.quality = 0.22 if p.value_eur <= 0 else i / n


def _rate_strength(teams: dict[int, SimTeam]) -> None:
    """Attack and defence multipliers from the value of the likely first eleven.

    The squad TOTAL would reward depth over quality — a mid-table club with forty
    registered players out-rating a top one with twenty-five — so this uses the best
    eleven by value, which is roughly who takes the field.
    """
    tops = {}
    for tid, team in teams.items():
        best = sorted((p.value_eur for p in team.players), reverse=True)[:11]
        tops[tid] = sum(best) / max(1, len(best))
    mean = sum(tops.values()) / max(1, len(tops))
    for tid, team in teams.items():
        # log ratio, so a club worth four times another is two steps better rather
        # than four: value buys results with strongly diminishing returns.
        edge = math.log((tops[tid] + 1.0) / (mean + 1.0)) / math.log(4.0)
        team.attack = math.exp(0.42 * edge)
        team.defence = math.exp(-0.42 * edge)
        team.depth = {
            role: sorted([p for p in team.players if p.role == role],
                         key=lambda p: -p.value_eur)
            for role in ("POR", "DIF", "CEN", "ATT")
        }


# --------------------------------------------------------------------------- #
# Donor pool: real performances to draw from                                   #
# --------------------------------------------------------------------------- #
# Minutes buckets. A donor is drawn from the bucket the target minutes fall in, so
# a twenty-minute cameo is never built by scaling down a full match: the SHAPE of a
# cameo differs from a scaled-down 90 (a substitute touches the ball more per minute
# and defends less), and scaling would erase that.
MINUTE_BUCKETS = ((1, 20), (21, 55), (56, 84), (85, 200))

# Keys copied from the donor that describe WHO he is rather than how he played.
IDENTITY_KEYS = ("id", "name", "shortName", "dateOfBirthTimestamp", "userCount",
                 "height", "position", "substitute", "minutesPlayed")

# Keys that are rates or normalised scores, not counts: rescaling them by a minutes
# ratio would be wrong (a normalised defensive value is already per-performance).
NON_VOLUME_KEYS = ("rating", "defensiveValueNormalized", "passValueNormalized",
                   "dribbleValueNormalized", "goalkeeperValueNormalized",
                   "shotValueNormalized", "keeperSaveValue", "goalsPrevented",
                   "bestBallCarryProgression")


@dataclass
class DonorPool:
    """Real 2025-26 appearances, indexed by position and minutes, ranked by rating.

    Ranked by the provider's own rating so that "draw a good game" and "draw a poor
    one" are single lookups, and so a player's quality maps onto a real performance
    of the right calibre instead of onto a synthetic one.
    """
    by_key: dict[tuple[str, int], list[dict]]

    @classmethod
    def load(cls, competition_season_id: int) -> "DonorPool":
        buckets: dict[tuple[str, int], list[dict]] = defaultdict(list)
        rows = (MatchAppearance.objects
                .filter(match__competition_season_id=competition_season_id,
                        minutes_played__gt=0)
                .values_list("minutes_played", "raw_stats"))
        for minutes, raw in rows:
            if not raw:
                continue
            pos = str(raw.get("position") or "")
            if pos not in ("G", "D", "M", "F"):
                continue
            buckets[(pos, _bucket_of(minutes))].append(raw)
        for key, donors in buckets.items():
            # Rating is missing on a handful of appearances (197 of 11,928); they
            # sort to the middle rather than being dropped, which keeps the thin
            # buckets populated.
            donors.sort(key=lambda r: float(r.get("rating") or 6.2))
        return cls(by_key=dict(buckets))

    def draw(self, position: str, minutes: int, quality: float, edge: float,
             rng: random.Random) -> dict:
        """A real performance of roughly the calibre this player, today, deserves.

        ``quality`` is his value percentile within his role and ``edge`` how the
        match is going for his side; both are compressed hard before they choose a
        donor — see QUALITY_PULL for the measurement that says they must be.
        """
        donors = self.by_key.get((position, _bucket_of(minutes)))
        if not donors:
            donors = self.by_key.get((position, _bucket_of(90))) or []
        if not donors:
            return {}
        centre = 0.5 + QUALITY_PULL * (quality - 0.5) + edge
        # Resampled rather than clamped. Clamping looks harmless and is not: with a
        # spread of 0.25 it parks 2% of every player's matches on the single WORST
        # donor in the pool and 2% on the single best, which widened the season's
        # rating spread from the real 0.58 to 0.71 — the tails were pure clipping.
        for _attempt in range(8):
            p = rng.gauss(centre, QUALITY_NOISE)
            if 0.0 <= p < 1.0:
                return donors[int(p * (len(donors) - 1))]
        return donors[int(min(0.999, max(0.0, centre)) * (len(donors) - 1))]


def _bucket_of(minutes: int) -> int:
    for i, (lo, hi) in enumerate(MINUTE_BUCKETS):
        if lo <= minutes <= hi:
            return i
    return len(MINUTE_BUCKETS) - 1


def _texture(donor: dict, minutes: int) -> dict:
    """The donor's blob with identity and events stripped, rescaled to the minutes.

    Rescaling is mild by construction — the donor already comes from the right
    minutes bucket — and applies only to counts. Values are rounded back to integers
    where the provider ships integers, so nothing downstream has to cope with 4.6
    completed passes.
    """
    donor_minutes = int(donor.get("minutesPlayed") or 90) or 90
    scale = minutes / donor_minutes
    out: dict = {}
    for key, value in donor.items():
        if key in IDENTITY_KEYS or key in EVENT_OWNED_KEYS:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if key in NON_VOLUME_KEYS:
            out[key] = value
            continue
        scaled = value * scale
        out[key] = int(round(scaled)) if isinstance(value, int) else round(scaled, 6)
    # SofaScore omits a statistic that is zero rather than sending a 0, and the
    # importer's ">0" filter reads that convention. Reproducing it matters: a blob
    # full of explicit zeroes would make every player look measured everywhere.
    return {k: v for k, v in out.items() if v}


# --------------------------------------------------------------------------- #
# Team selection                                                               #
# --------------------------------------------------------------------------- #
def _module_for(team: SimTeam, matchday: int, rng: random.Random) -> str:
    """A club's shape. Mostly fixed, occasionally varied — enough that the season
    is not eleven identical heatmaps per club, not so much that a side is
    unrecognisable from one week to the next."""
    names = sorted(MODULES)
    base = names[team.team_season_id % len(names)]
    return base if rng.random() < 0.75 else rng.choice(names)


def _pick(depth: list[SimPlayer], count: int, rng: random.Random,
          churn: float) -> list[SimPlayer]:
    """``count`` players off a value-ordered depth chart, with rotation.

    Selection is by rank plus noise rather than by a fresh random draw: the point is
    CONTINUITY. A side picked at random every week would give every squad member the
    same number of appearances, so nobody would have a season worth reading and the
    listone would rank three keepers per club identically. ``churn`` is how wide the
    noise is — small for a goalkeeper, who is the same man almost every week.
    """
    if len(depth) <= count:
        return list(depth)
    scored = [(i + rng.gauss(0.0, churn), p) for i, p in enumerate(depth)]
    scored.sort(key=lambda t: t[0])
    return [p for _, p in scored[:count]]


def pick_lineup(team: SimTeam, matchday: int, rng: random.Random):
    """(module, [(SimPlayer, slot)], bench) — the eleven, their slots, the bench.

    A slot is filled from the squad's players of the matching classic role, and
    falls back to whoever is left when a club has too few of one: some registered
    squads carry two recognised forwards, and refusing to field a side would leave
    the whole matchday without data.
    """
    module = _module_for(team, matchday, rng)
    slots = [GK_SLOT] + MODULES[module]
    need: dict[str, int] = defaultdict(int)
    for _, letter, _x, _y in slots:
        need[SLOT_ROLE[letter]] += 1

    chosen: dict[str, list[SimPlayer]] = {}
    used: set[int] = set()
    for role, count in need.items():
        churn = 0.35 if role == "POR" else 0.95
        picked = _pick(team.depth.get(role, []), count, rng, churn)
        chosen[role] = picked
        used.update(p.player_id for p in picked)

    spare = [p for p in team.players if p.player_id not in used]
    spare.sort(key=lambda p: -p.value_eur)
    starters: list[tuple[SimPlayer, tuple]] = []
    for slot in slots:
        role = SLOT_ROLE[slot[1]]
        pool = chosen.get(role) or []
        if pool:
            starters.append((pool.pop(0), slot))
        elif spare:
            starters.append((spare.pop(0), slot))

    bench_pool = [p for p in team.players
                  if p.player_id not in {s.player_id for s, _ in starters}]
    bench = _pick(sorted(bench_pool, key=lambda p: -p.value_eur),
                  min(BENCH_NAMED, len(bench_pool)), rng, 1.6)
    return module, starters, bench


# --------------------------------------------------------------------------- #
# The match: events first, statistics after                                    #
# --------------------------------------------------------------------------- #
def _poisson(lam: float, rng: random.Random) -> int:
    """Knuth's method. Keeps the module free of a numpy dependency the rest of the
    backend does not have.

    The ceiling is a runaway guard and nothing else. It used to sit at 12, chosen
    while thinking only of goals — but the same function draws SHOTS, whose mean is
    12.3 per side, so it was truncating the top half of that distribution and the
    season came out at 22.3 shots a match against a real 24.7. A cap has to be far
    outside the range of every caller, not just of the one you had in mind.
    """
    lam = max(0.01, lam)
    target, k, product = math.exp(-lam), 0, 1.0
    while True:
        product *= rng.random()
        if product <= target:
            return k
        k += 1
        if k > 60:
            return k


def _weighted(items: list, weights: list[float], rng: random.Random):
    total = sum(weights)
    if total <= 0:
        return rng.choice(items) if items else None
    threshold = rng.random() * total
    running = 0.0
    for item, w in zip(items, weights):
        running += w
        if running >= threshold:
            return item
    return items[-1]


@dataclass
class OnPitch:
    """A player's participation, decided before any statistic is drawn."""
    player: SimPlayer
    slot: tuple
    is_starter: bool
    start_minute: int
    end_minute: int

    @property
    def minutes(self) -> int:
        return max(0, self.end_minute - self.start_minute)

    @property
    def position(self) -> str:
        return self.slot[1]


def _participation(starters, bench, rng: random.Random) -> list[OnPitch]:
    """Who was on the pitch and when: substitutions, and nothing else yet.

    Sendings-off shorten a spell too, but they are decided with the cards further
    down, so the end minute set here is provisional for the player who gets one.
    """
    on = [OnPitch(p, slot, True, 0, 90) for p, slot in starters]
    n_subs = min(len(bench), max(0, min(5, int(round(rng.gauss(SUBS_PER_TEAM, 1.1))))))
    # An outfielder comes off; a goalkeeper is replaced only when something has gone
    # wrong, which this generator does not model.
    replaceable = [o for o in on if o.position != "G"]
    rng.shuffle(replaceable)
    for i in range(n_subs):
        if not replaceable:
            break
        going_off = replaceable.pop()
        minute = int(min(89, max(30, rng.gauss(70, 13))))
        if minute <= going_off.start_minute:
            continue
        going_off.end_minute = minute
        coming_on = bench[i]
        on.append(OnPitch(coming_on, going_off.slot, False, minute, 90))
    return on


def _cards(on: list[OnPitch], rng: random.Random) -> list[dict]:
    """Bookings and sendings-off, at rates measured on the real season.

    A second yellow is modelled as what it is — a player who was ALREADY booked
    getting another — rather than as an independent event type, because the pagella
    charges him for both and a lone 'yellowRed' with no first yellow would understate
    the malus.
    """
    out: list[dict] = []
    booked: dict[int, int] = {}
    candidates = [o for o in on if o.minutes > 0]
    if not candidates:
        return out
    weights = [CARD_WEIGHT[o.position] * (o.minutes / 90.0) for o in candidates]

    for _ in range(_poisson(YELLOWS_PER_TEAM, rng)):
        # The already-booked are removed from the draw rather than drawn and
        # discarded. Discarding lost about a tenth of the season's bookings, because
        # a side's cards concentrate on the same few defenders and a collision was
        # the common case, not the rare one.
        free = [(o, w) for o, w in zip(candidates, weights)
                if o.player.player_id not in booked]
        if not free:
            break
        o = _weighted([o for o, _ in free], [w for _, w in free], rng)
        if o is None:
            continue
        minute = rng.randint(max(1, o.start_minute + 1), max(2, o.end_minute))
        booked[o.player.player_id] = minute
        out.append({"kind": "yellow", "on": o, "minute": minute})

    if rng.random() < SECOND_YELLOW_PER_TEAM and booked:
        pid, first = rng.choice(list(booked.items()))
        o = next(o for o in candidates if o.player.player_id == pid)
        minute = rng.randint(min(89, first + 1), 90)
        if minute < o.end_minute:
            o.end_minute = minute        # off the pitch from here
        out.append({"kind": "yellowRed", "on": o, "minute": minute})
    elif rng.random() < STRAIGHT_RED_PER_TEAM:
        o = _weighted(candidates, weights, rng)
        if o is not None:
            minute = rng.randint(max(1, o.start_minute + 1), max(2, o.end_minute))
            if minute < o.end_minute:
                o.end_minute = minute
            out.append({"kind": "red", "on": o, "minute": minute})
    return out


OWN_GOAL_RATE = 0.055        # 22 own goals in 380 matches

# Chance quality BY OUTCOME, measured over the 9,381 real shots of 2025-26:
#
#   outcome   n      mean xG   mean xGOT
#   goal      922     0.300      0.568
#   save    2,166     0.110      0.192
#   miss    3,556     0.081      0.000
#   block   2,558     0.056      0.000
#   post      179     0.138      0.000
#
# Conditioning xG on the outcome, rather than drawing it once for every shot, is
# what keeps a blocked effort (a shot from a crowd, 0.056) apart from a save
# (0.110) — and it is the only way the keeper channel comes out right, because
# ``goalsPrevented`` is xGOT faced minus goals conceded and the provider's xGOT is
# calibrated so those two agree over a season: 939.9 against 922 goals. Get the
# means wrong and every keeper in the league is systematically a hero or a fraud.
XG_BY_OUTCOME = {"goal": 0.300, "save": 0.110, "miss": 0.081,
                 "block": 0.056, "post": 0.138}
XG_SIGMA = 0.85              # spread of the log-normal the value is drawn from
XGOT_GOAL = (0.568, 0.299)   # mean, sd
XGOT_SAVE = (0.192, 0.195)


def _xg_for(outcome: str, rng: random.Random) -> float:
    """A shot's pre-shot xG, given how it ended.

    Log-normal with the mean pinned to the measured value for that outcome: the
    ``mu`` of a log-normal is not its mean, so it is derived from the target rather
    than typed in, which is the difference between a distribution that reproduces
    the season and one that quietly sits 40% high.
    """
    mean = XG_BY_OUTCOME.get(outcome, 0.09)
    mu = math.log(mean) - XG_SIGMA ** 2 / 2.0
    return round(min(0.95, math.exp(rng.gauss(mu, XG_SIGMA))), 4)


def _xgot_for(outcome: str, rng: random.Random) -> float:
    """Post-shot xG: where it ended up, not where it was taken from. Zero for
    anything that never reached the frame, which is what the provider does."""
    if outcome == "goal":
        return round(min(0.99, max(0.05, rng.gauss(*XGOT_GOAL))), 4)
    if outcome == "save":
        return round(min(0.95, abs(rng.gauss(*XGOT_SAVE))), 4)
    return 0.0


def _shot_point(position: str, rng: random.Random) -> tuple[float, float]:
    """Where the shot was struck, in the HEATMAP frame (own goal at x=0).

    Converted to the shotmap's own frame on the way out — the two payloads disagree
    by a 180 degree rotation, and the importer un-rotates what we write here.

    THE SPREAD IS CALIBRATED, and it matters more than it looks. Real 2025-26, over
    9,381 shots binned into the 5x4 grid: 73.0% land in the two central cells of the
    last column (Z_4_1 37.3%, Z_4_2 35.7%), 24.8% one band further out (Z_3_1,
    Z_3_2), and 1.1% in the wide cells. The first version of this put only 56.5% in
    the two central cells and pushed 38% into the band behind — shots too far from
    goal, and too spread across it.
    That is not a cosmetic difference: ``defensive_exposure`` charges a defender
    with the danger created IN THE ZONES HE OCCUPIED, so moving the shots outward
    moves the blame outward with them, onto deeper and wider defenders. It showed up
    as the defender vote drifting BELOW its calibrated centre while the attacker
    vote drifted above.
    """
    mean_x = 85.5 if position == "F" else 82.0
    x = min(97.0, max(58.0, rng.gauss(mean_x, 6.0)))
    y = min(95.0, max(5.0, rng.gauss(50.0, 11.0)))
    return x, y


def _team_shots(on: list[OnPitch], goals: int, dominance: float,
                rng: random.Random) -> list[dict]:
    """Every shot a side took, with the goals already among them.

    The goals are DEALT FIRST and the rest of the volume is filled in around them,
    so the shot map can never disagree with the scoreline — which it would if shots
    were drawn independently and goals counted afterwards.
    """
    players = [o for o in on if o.minutes > 0 and o.position != "G"]
    if not players:
        return []
    weights = [GOAL_WEIGHT[o.position] * (0.4 + o.player.quality) * (o.minutes / 90.0)
               for o in players]

    total = max(goals, _poisson(SHOTS_PER_TEAM * dominance, rng))
    shots: list[dict] = []
    for i in range(total):
        is_goal = i < goals
        taker = _weighted(players, weights, rng)
        if taker is None:
            continue
        minute = rng.randint(max(1, taker.start_minute + 1), max(2, taker.end_minute))
        # Outcome first, chance quality after: the two are not independent, and
        # drawing them the other way round would give a blocked shot the same
        # expected value as a save.
        outcome = "goal" if is_goal else _weighted(
            [k for k, _ in SHOT_OUTCOMES], [w for _, w in SHOT_OUTCOMES], rng)
        xg, xgot = _xg_for(outcome, rng), _xgot_for(outcome, rng)
        x, y = _shot_point(taker.position, rng)
        shots.append({
            "on": taker, "minute": minute, "outcome": outcome, "xg": xg, "xgot": xgot,
            "situation": _weighted([k for k, _ in SHOT_SITUATIONS],
                                   [w for _, w in SHOT_SITUATIONS], rng),
            "x": x, "y": y, "own_goal": False,
        })
    # Goals were dealt first; shuffling puts them back in chronological disorder so
    # a match does not always open with its goals.
    rng.shuffle(shots)
    return shots


def _award_penalty(shots: list[dict], on: list[OnPitch], rng: random.Random) -> None:
    """Turn one shot into a penalty, or add a missed one.

    Awarded rather than drawn, and reconciled with the scoreline rather than added
    to it: a penalty that changed the score would contradict a result already
    decided. A converted one re-labels a goal that is already there; a missed one is
    an extra shot, which changes nothing but the shot count.
    """
    takers = [o for o in on if o.minutes > 0 and o.position in ("F", "M")]
    if not takers:
        return
    scored = [s for s in shots if s["outcome"] == "goal"]
    if scored and rng.random() < PENALTY_CONVERSION:
        shot = rng.choice(scored)
        shot.update(situation="penalty", xg=0.79, xgot=_xgot_for("goal", rng))
        return
    taker = _weighted(takers, [0.4 + o.player.quality for o in takers], rng)
    if taker is None:
        return
    x, y = 88.0, 50.0
    shots.append({
        "on": taker, "minute": rng.randint(max(1, taker.start_minute + 1),
                                           max(2, taker.end_minute)),
        "outcome": "save" if rng.random() < 0.55 else "miss",
        "xg": 0.79, "xgot": 0.0, "situation": "penalty", "x": x, "y": y,
        "own_goal": False,
    })


def _keeper_stats(keeper: OnPitch, faced: list[dict], conceded: int) -> dict:
    """The goalkeeper's own channel, computed from what was actually shot at him.

    Derived rather than donor-sampled: these are the only statistics in the blob
    that are a fact about the OTHER team's shots, so a donor's saves would contradict
    the shot map in front of him — and ``goalsPrevented``, the feature the whole
    keeper index is anchored on, is precisely xGOT faced minus goals conceded.
    """
    on_target = [s for s in faced if s["xgot"] > 0 or s["outcome"] == "goal"]
    saves = sum(1 for s in faced if s["outcome"] == "save")
    penalties = [s for s in faced if s["situation"] == "penalty"]
    out = {
        "saves": saves,
        "savedShotsFromInsideTheBox": int(round(saves * 0.68)),
        "goalsPrevented": round(sum(s["xgot"] for s in on_target) - conceded, 4),
    }
    if penalties:
        out["penaltyFaced"] = len(penalties)
        saved = sum(1 for s in penalties if s["outcome"] == "save")
        if saved:
            out["penaltySave"] = saved
    return {k: v for k, v in out.items() if v}


def _shot_stats(shots: list[dict]) -> dict:
    """A player's own shooting line, so the blob and the shot map agree exactly."""
    if not shots:
        return {}
    counts = defaultdict(int)
    for s in shots:
        counts[s["outcome"]] += 1
    out = {
        "totalShots": len(shots),
        "goals": counts["goal"],
        "onTargetScoringAttempt": counts["goal"] + counts["save"],
        "shotOffTarget": counts["miss"],
        "blockedScoringAttempt": counts["block"],
        "hitWoodwork": counts["post"],
        "expectedGoals": round(sum(s["xg"] for s in shots), 4),
        "expectedGoalsOnTarget": round(sum(s["xgot"] for s in shots), 4),
        "penaltyMiss": sum(1 for s in shots
                           if s["situation"] == "penalty" and s["outcome"] != "goal"),
    }
    return {k: v for k, v in out.items() if v}


# --------------------------------------------------------------------------- #
# Provider-shaped payloads                                                     #
# --------------------------------------------------------------------------- #
def _player_dict(p: SimPlayer) -> dict:
    out = {"id": int(p.sofa_id), "name": p.name, "shortName": p.short_name,
           "userCount": 100 + (p.player_id % 900)}
    if p.dob_ts is not None:
        out["dateOfBirthTimestamp"] = p.dob_ts
    return out


def _heatmap_points(slot: tuple, minutes: int, rng: random.Random) -> list[dict]:
    """A cloud of positions around the slot's anchor, in the player's attacking frame.

    This is the ONLY source of a player's zone distribution: the importer divides his
    touch total across zones in proportion to it. Its shape therefore decides where
    he counts in the Aura duels and what share of the danger conceded is charged to
    him — which is why it is anchored on the slot he actually occupied rather than
    on his nominal role.
    """
    _label, position, ax, ay = slot
    sx, sy = HEATMAP_SIGMA[position]
    n = max(12, int(HEATMAP_POINTS_FULL * minutes / 90.0))
    points = []
    for _ in range(n):
        x = min(99.0, max(1.0, rng.gauss(ax, sx)))
        y = min(99.0, max(1.0, rng.gauss(ay, sy)))
        points.append({"x": round(x, 1), "y": round(y, 1)})
    return points


def _lineup_entry(o: OnPitch, stats: dict) -> dict:
    return {"player": _player_dict(o.player), "statistics": stats,
            "substitute": not o.is_starter, "position": o.position}


def _unused_entry(p: SimPlayer, position: str) -> dict:
    """A named substitute who never came on. He still needs a record — the classic
    conclusion has to be able to tell 'was not in the squad' from 'was on the bench
    and did not play', and only the second earns an s.v."""
    return {"player": _player_dict(p), "statistics": {"totalShots": 0},
            "substitute": True, "position": position}


def _incidents(side_events: list[tuple[str, list]]) -> list[dict]:
    """Cards, substitutions and goals, in one timeline.

    Cards are the only ones the importer turns into rows of their own, and the
    substitutions are what ``import_sofascore_intervals`` rebuilds the on-pitch
    windows from. The goals are written because a real payload has them and an
    incident feed without goals would be a trap for whoever reads this cache next.
    """
    out: list[dict] = []
    for side, entries in side_events:
        is_home = side == "home"
        for entry in entries:
            kind = entry["kind"]
            if kind in ("yellow", "red", "yellowRed"):
                o = entry["on"]
                out.append({
                    "incidentType": "card", "isHome": is_home,
                    "time": entry["minute"], "incidentClass": kind,
                    "player": _player_dict(o.player),
                    "reason": "Foul" if kind != "yellowRed" else "Second yellow card",
                })
            elif kind == "substitution":
                out.append({
                    "incidentType": "substitution", "isHome": is_home,
                    "time": entry["minute"],
                    "playerIn": _player_dict(entry["player_in"]),
                    "playerOut": _player_dict(entry["player_out"]),
                })
            elif kind == "goal":
                inc = {"incidentType": "goal", "isHome": is_home,
                       "time": entry["minute"],
                       "incidentClass": entry.get("incident_class", "regular"),
                       "player": _player_dict(entry["player"])}
                if entry.get("assist") is not None:
                    inc["assist1"] = _player_dict(entry["assist"])
                out.append(inc)
    out.sort(key=lambda i: i["time"])
    return out


def _shotmap(rows: list[tuple[str, dict]], base_id: int) -> list[dict]:
    """The shot map, in the provider's own coordinate frame.

    ``playerCoordinates`` are measured from the goal being ATTACKED while the
    heatmap is measured from the player's own — a 180 degree rotation on both axes.
    The importer un-rotates; writing the un-rotated value here would put every shot
    inside the shooter's own six-yard box.
    """
    out = []
    for i, (side, shot) in enumerate(rows):
        out.append({
            "id": base_id + i,
            "player": _player_dict(shot["on"].player),
            "isHome": side == "home" if not shot["own_goal"] else side != "home",
            "playerCoordinates": {"x": round(100.0 - shot["x"], 1),
                                  "y": round(100.0 - shot["y"], 1)},
            "xg": shot["xg"], "xgot": shot["xgot"],
            "shotType": shot["outcome"], "situation": shot["situation"],
            "time": shot["minute"], "timeSeconds": shot["minute"] * 60,
        })
    return out


# --------------------------------------------------------------------------- #
# One match                                                                    #
# --------------------------------------------------------------------------- #
@dataclass
class SimMatch:
    """Everything one match contributes to the cache."""
    lineups: dict
    shotmap: list[dict]
    incidents: list[dict]
    heatmaps: dict[int, list[dict]]        # sofascore player id -> points
    home_goals: int
    away_goals: int


def _clip_to_clock(on: list[OnPitch], clock: int) -> None:
    """Cut every spell at the current minute, for a match still being played."""
    for o in on:
        o.end_minute = min(o.end_minute, clock)
        if o.start_minute > clock:
            o.start_minute = o.end_minute = clock


def simulate_match(home: SimTeam, away: SimTeam, matchday: int, pool: DonorPool,
                   rng: random.Random, *, clock: int = 90) -> SimMatch:
    """Play one fixture. ``clock`` under 90 leaves it in progress at that minute.

    THE WHOLE MATCH IS ALWAYS PLAYED, and ``clock`` only decides how much of it is
    shown. That is not an implementation detail, it is the property that makes a
    live match watchable: the ninety minutes are drawn from a stream that does not
    know what time it is, so the same fixture observed at the 35th minute and at
    full time is the SAME match seen twice, and a goal that has been scored can
    never un-score itself.

    Making ``clock`` shorten the simulation instead — fewer expected goals, spells
    clipped before the events are drawn — was the first version and it was wrong in
    a way that only shows up when the clock moves: every draw downstream shifted, so
    advancing time re-rolled the match. Napoli would lead 1-0 at the 35th minute and
    finish 0-0, with different scorers, which is worse than useless for testing a
    live pipeline.
    """
    sides = {}
    for side, team, opponent, base in (("home", home, away, GOALS_HOME),
                                       ("away", away, home, GOALS_AWAY)):
        module, starters, bench = pick_lineup(team, matchday, rng)
        on = _participation(starters, bench, rng)
        sides[side] = {"team": team, "module": module, "on": on, "bench": bench,
                       "lambda": base * team.attack * opponent.defence}

    home_goals = _poisson(sides["home"]["lambda"], rng)
    away_goals = _poisson(sides["away"]["lambda"], rng)

    # Cards first: a sending-off shortens a spell, and every minute drawn afterwards
    # has to fall inside a spell that is already final.
    for side in ("home", "away"):
        sides[side]["cards"] = _cards(sides[side]["on"], rng)

    for side, scored in (("home", home_goals), ("away", away_goals)):
        s = sides[side]
        dominance = 0.80 + 0.40 * (s["lambda"] / max(0.2, sides["home"]["lambda"]
                                                     + sides["away"]["lambda"]))
        s["shots"] = _team_shots(s["on"], scored, dominance, rng)
        if rng.random() < PENALTIES_PER_TEAM:
            _award_penalty(s["shots"], s["on"], rng)

    own_goals: list[dict] = []
    if rng.random() < OWN_GOAL_RATE:
        _convert_to_own_goal(sides, own_goals, rng)

    # Everything above is the full match and never sees ``clock``. Only here is it
    # cut back to what has happened so far.
    if clock < 90:
        home_goals, away_goals = _truncate(sides, own_goals, clock)

    return _assemble(sides, own_goals, home_goals, away_goals, pool, rng, clock)


def _truncate(sides: dict, own_goals: list[dict], clock: int) -> tuple[int, int]:
    """Cut a finished match back to the minute it is being watched at.

    Returns the scoreline AS IT STANDS, recounted from the events that have actually
    happened rather than carried over from full time — which is the whole point: the
    score at the 35th minute is a fact about the first 35 minutes.
    """
    for side in ("home", "away"):
        s = sides[side]
        _clip_to_clock(s["on"], clock)
        s["cards"] = [c for c in s["cards"] if c["minute"] <= clock]
        s["shots"] = [x for x in s["shots"] if x["minute"] <= clock]
    own_goals[:] = [g for g in own_goals if g["minute"] <= clock]

    def scored(side: str) -> int:
        return (sum(1 for x in sides[side]["shots"] if x["outcome"] == "goal")
                + sum(1 for g in own_goals if g["side"] == side))

    return scored("home"), scored("away")


def _convert_to_own_goal(sides: dict, own_goals: list[dict], rng: random.Random) -> None:
    """Re-attribute one goal to a defender of the side that conceded it.

    Modelled as a RE-ATTRIBUTION and not as an extra goal, for the same reason the
    penalty is: the scoreline is already decided, and an own goal that added to it
    would contradict it. The provider files an own goal as a goal-shot by the
    own-scorer tagged with the side it counts FOR, which is what the importer keys
    off to keep it out of his goals — so that is what gets written.
    """
    scoring = [s for s in ("home", "away")
               if any(x["outcome"] == "goal" and not x["own_goal"]
                      for x in sides[s]["shots"])]
    if not scoring:
        return
    side = rng.choice(scoring)
    conceding = "away" if side == "home" else "home"
    defenders = [o for o in sides[conceding]["on"]
                 if o.minutes > 0 and o.position in ("D", "M")]
    if not defenders:
        return
    goal = rng.choice([x for x in sides[side]["shots"]
                       if x["outcome"] == "goal" and not x["own_goal"]])
    sides[side]["shots"].remove(goal)
    scorer = rng.choice(defenders)
    own_goals.append({
        "side": side,                     # the side it COUNTS FOR
        "on": scorer, "minute": goal["minute"], "outcome": "goal",
        "xg": 0.0, "xgot": 0.0, "situation": "own-goal",
        "x": goal["x"], "y": goal["y"], "own_goal": True,
    })


# How often a goal has a provider, by the play it came from. Real Serie A pays 612
# assists on 900 goals — 0.68 — and the first version of this reached only 0.49
# because it credited an assist exactly to the goals whose SHOT was tagged
# ``assisted``. That conflates two different populations: the assisted share of all
# shots is 49%, but a goal is far likelier to have come from a pass than a shot is,
# and a corner or a free kick is credited to its delivery even though the shot
# itself is not tagged assisted. So the probability is per situation, and the
# resulting rate is checked against the 0.68.
ASSIST_CHANCE = {
    "assisted": 0.90,
    "corner": 0.72, "set-piece": 0.72, "free-kick": 0.72, "throw-in-set-piece": 0.72,
    "regular": 0.22, "fast-break": 0.22,
    "penalty": 0.0,          # nobody assists a penalty
}


def _assign_assists(side: dict, rng: random.Random) -> dict[int, int]:
    """Who made the pass, for the goals that came from one."""
    credits: dict[int, int] = defaultdict(int)
    for shot in side["shots"]:
        if shot["outcome"] != "goal":
            shot["assist"] = None
            continue
        if rng.random() >= ASSIST_CHANCE.get(shot["situation"], 0.5):
            shot["assist"] = None
            continue
        mates = [o for o in side["on"]
                 if o.minutes > 0 and o.player.player_id != shot["on"].player.player_id
                 and o.start_minute <= shot["minute"] <= o.end_minute]
        if not mates:
            shot["assist"] = None
            continue
        chosen = _weighted(mates, [ASSIST_WEIGHT[o.position] * (0.5 + o.player.quality)
                                   for o in mates], rng)
        shot["assist"] = chosen.player if chosen else None
        if chosen:
            credits[chosen.player.player_id] += 1
    return credits


def _assemble(sides: dict, own_goals: list[dict], home_goals: int, away_goals: int,
              pool: DonorPool, rng: random.Random, clock: int) -> SimMatch:
    conceded = {"home": away_goals, "away": home_goals}
    for side in ("home", "away"):
        sides[side]["assists"] = _assign_assists(sides[side], rng)

    # What each keeper faced: the opponent's shots, plus any own goal that counted
    # for the opponent — it is a goal he conceded, and ``goalsPrevented`` has to see
    # it as one even though nobody shot at him.
    faced = {
        "home": [s for s in sides["away"]["shots"]] +
                [g for g in own_goals if g["side"] == "away"],
        "away": [s for s in sides["home"]["shots"]] +
                [g for g in own_goals if g["side"] == "home"],
    }

    lineups: dict = {}
    heatmaps: dict[int, list[dict]] = {}
    shot_rows: list[tuple[str, dict]] = []
    incident_sides: list[tuple[str, list]] = []

    for side in ("home", "away"):
        s = sides[side]
        by_player: dict[int, list[dict]] = defaultdict(list)
        for shot in s["shots"]:
            by_player[shot["on"].player.player_id].append(shot)
        own_by_player: dict[int, int] = defaultdict(int)
        for g in own_goals:
            if g["on"] in s["on"]:
                own_by_player[g["on"].player.player_id] += 1

        # Donors are drawn a notch better for the side that is winning: a
        # performance is judged inside a match, and a full-back in a team three up
        # has genuinely had a better afternoon than the same player being overrun.
        margin = conceded["away" if side == "home" else "home"] - conceded[side]
        edge = max(-RESULT_EDGE_CAP,
                   min(RESULT_EDGE_CAP, RESULT_EDGE_PER_GOAL * margin))

        entries = []
        for o in s["on"]:
            if o.minutes <= 0:
                continue
            stats = _texture(
                pool.draw(o.position, o.minutes, o.player.quality, edge, rng),
                o.minutes)
            stats.update(_shot_stats(by_player.get(o.player.player_id, [])))
            if s["assists"].get(o.player.player_id):
                stats["goalAssist"] = s["assists"][o.player.player_id]
            if own_by_player.get(o.player.player_id):
                stats["ownGoals"] = own_by_player[o.player.player_id]
            if o.position == "G":
                stats.pop("goalsPrevented", None)
                stats.update(_keeper_stats(o, faced[side], conceded[side]))
            stats["minutesPlayed"] = o.minutes
            entries.append(_lineup_entry(o, stats))
            heatmaps[int(o.player.sofa_id)] = _heatmap_points(o.slot, o.minutes, rng)

        # Only those who ACTUALLY got on count as used. In a match still in
        # progress a substitution planned for the 70th minute has been clipped to
        # zero minutes, and treating him as used dropped him from the squad sheet
        # altogether — leaving a live match with 36 players instead of 46, and a
        # bench the conclusion could not tell from a squad omission.
        played = {o.player.player_id for o in s["on"] if o.minutes > 0}
        for p in s["bench"]:
            if p.player_id not in played:
                entries.append(_unused_entry(p, _bench_position(p)))
        lineups[side] = {"players": entries, "formation": s["module"]}

        shot_rows.extend((side, shot) for shot in s["shots"])
        events = list(s["cards"])
        events += [{"kind": "substitution", "minute": o.start_minute,
                    "player_in": o.player,
                    "player_out": _replaced_by(s["on"], o)}
                   for o in s["on"] if not o.is_starter and o.minutes > 0]
        events += [{"kind": "goal", "minute": shot["minute"], "player": shot["on"].player,
                    "assist": shot.get("assist"),
                    "incident_class": ("penalty" if shot["situation"] == "penalty"
                                       else "regular")}
                   for shot in s["shots"] if shot["outcome"] == "goal"]
        events += [{"kind": "goal", "minute": g["minute"], "player": g["on"].player,
                    "assist": None, "incident_class": "ownGoal"}
                   for g in own_goals if g["side"] == side]
        incident_sides.append((side, events))

    shot_rows.extend(("home" if g["side"] == "home" else "away", g) for g in own_goals)
    return SimMatch(
        lineups=lineups,
        shotmap=_shotmap(shot_rows, base_id=rng.randint(10_000_000, 99_000_000)),
        incidents=_incidents(incident_sides),
        heatmaps=heatmaps, home_goals=home_goals, away_goals=away_goals,
    )


def _bench_position(p: SimPlayer) -> str:
    return {"POR": "G", "DIF": "D", "CEN": "M", "ATT": "F"}.get(p.role, "M")


def _replaced_by(on: list[OnPitch], sub: OnPitch) -> SimPlayer:
    """The starter whose slot the substitute took. Same slot, ended at the minute the
    substitute began — which is how the pairing was built in the first place."""
    for o in on:
        if o.is_starter and o.slot == sub.slot and o.end_minute == sub.start_minute:
            return o.player
    return sub.player


# --------------------------------------------------------------------------- #
# The season: kick-off slots, statuses, and the cache                          #
# --------------------------------------------------------------------------- #
ROME = "Europe/Rome"


def round_kickoffs(anchor_saturday, count: int) -> list:
    """The ``count`` kick-off instants of a round, in UTC, oldest first."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(ROME)
    out = []
    for day, hour, minute in ROUND_SLOTS[:count]:
        local = datetime(anchor_saturday.year, anchor_saturday.month,
                         anchor_saturday.day, hour, minute,
                         tzinfo=tz) + timedelta(days=day)
        out.append(local.astimezone(dt_timezone.utc))
    return out


def _saturday_of(moment: datetime):
    """The Saturday of the weekend a placeholder kick-off falls in.

    The provider ships a whole round on one identical timestamp until the slots are
    assigned; that timestamp is already the weekend's Saturday for most rounds, and
    for a midweek round this rounds back to the nearest one — the simulation needs A
    weekend, not the real broadcaster's calendar.
    """
    return (moment - timedelta(days=(moment.weekday() - 5) % 7)).date()


def _cache_name(path: str) -> str:
    return path.strip("/").replace("/", "_") + ".json"


def _write(cache_dir: Path, path: str, payload) -> None:
    target = cache_dir / _cache_name(path)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(target)


def _order_fixtures(fixtures: list, headline: str) -> list:
    """The order in which a round's fixtures take the kick-off slots.

    Stable by (matchday, id), so a match keeps its slot whenever the season is
    rebuilt — except for ``headline``, which is moved to the LAST slot of its round:
    the Sunday-night posticipo. That exists so a scenario can say WHICH match should
    be the one in progress ("the round is played, Napoli-Inter is on now") instead of
    whichever fixture happens to sort first.
    """
    if not headline:
        return fixtures
    pick = [f for f in fixtures if str(f.external_id) == str(headline)]
    if not pick:
        return fixtures
    return [f for f in fixtures if str(f.external_id) != str(headline)] + pick


def write_season_cache(*, competition_season: CompetitionSeason, cache_dir: Path,
                       through_matchday: int, now: datetime, live_minute: int,
                       seed: int, year: str, headline: str = "", log=print) -> dict:
    """Write every provider payload the importer will read. Returns a small report.

    Matchdays after ``through_matchday`` are written as fixtures only — no lineups,
    no shots — with the status the provider would give them, so the importer skips
    them and the rest of the season stays a calendar. Inside the simulated stretch a
    match's status comes from the CLOCK: kicked off more than 105 minutes ago means
    finished, kicked off means in progress, otherwise not started. That is the whole
    mechanism behind a half-played matchday 22.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    season_id = str(competition_season.external_id)

    teams = load_squads(competition_season.id)
    aliased = ensure_aliases([p for t in teams.values() for p in t.players])
    log(f"squads: {len(teams)} teams, "
        f"{sum(len(t.players) for t in teams.values())} registered players "
        f"({aliased} new provider aliases for Transfermarkt-only players)")

    pool = DonorPool.load(_donor_season_id(competition_season))
    log(f"donor pool: {sum(len(v) for v in pool.by_key.values())} real appearances "
        f"in {len(pool.by_key)} position/minutes buckets")

    matches = list(Match.objects.filter(competition_season=competition_season)
                   .exclude(matchday=None)
                   .select_related("home_team", "away_team")
                   .order_by("matchday", "id"))
    by_round: dict[int, list[Match]] = defaultdict(list)
    for m in matches:
        by_round[int(m.matchday)].append(m)

    # ``plan`` is what the caller needs and cannot recompute: which state each match
    # is in at this instant, and the kick-off slot assigned to it. Both are decided
    # here, and the database only learns them if it is told — the importer never
    # visits a match that has not started, so its calendar entry would otherwise
    # keep the provider's placeholder time.
    report = {"finished": 0, "live": 0, "scheduled": 0, "rounds": 0,
              "heatmaps": 0, "kickoffs_assigned": 0, "plan": {}}
    events_by_round: dict[int, list[dict]] = {}

    for matchday in sorted(by_round):
        fixtures = _order_fixtures(by_round[matchday], headline)
        simulate = matchday <= through_matchday
        kickoffs = None
        if simulate:
            anchor = _saturday_of(min(f.kickoff for f in fixtures if f.kickoff))
            kickoffs = round_kickoffs(anchor, len(fixtures))
            report["kickoffs_assigned"] += len(fixtures)

        events = []
        for i, fixture in enumerate(fixtures):
            kickoff = kickoffs[i] if kickoffs else fixture.kickoff
            status, clock = (_status_at(kickoff, now, live_minute) if simulate
                             else ("notstarted", 0))
            events.append(_event_dict(fixture, matchday, kickoff, status,
                                      teams, season_id))
            if simulate:
                report["plan"][str(fixture.external_id)] = {
                    "status": status, "clock": clock,
                    "kickoff": kickoff.isoformat() if kickoff else None,
                    # Filled in below for anything that has kicked off. A match in
                    # progress is NOT imported (see the command's _targets), so this
                    # is the only place its score can come from.
                    "home_goals": None, "away_goals": None,
                }
            if status == "notstarted":
                report["scheduled"] += 1
                continue

            home = teams[fixture.home_team_id]
            away = teams[fixture.away_team_id]
            # Seeded from the fixture's OWN identity, not from a shared stream.
            # A stream is consumed only by the matches that get simulated, so
            # moving the observation instant forward — the whole point of this
            # command — changed which draws each match received and re-rolled the
            # season behind the front. Keyed on the provider id instead, a match
            # plays the same way whenever it is asked.
            sim = simulate_match(home, away, matchday, pool,
                                 random.Random(f"{seed}:{fixture.external_id}"),
                                 clock=clock)
            events[-1]["homeScore"] = {"current": sim.home_goals}
            events[-1]["awayScore"] = {"current": sim.away_goals}
            entry = report["plan"][str(fixture.external_id)]
            entry["home_goals"], entry["away_goals"] = sim.home_goals, sim.away_goals

            mid = int(fixture.external_id)
            _write(cache_dir, f"/api/v1/event/{mid}/lineups", sim.lineups)
            _write(cache_dir, f"/api/v1/event/{mid}/shotmap", {"shotmap": sim.shotmap})
            _write(cache_dir, f"/api/v1/event/{mid}/incidents",
                   {"incidents": sim.incidents})
            for pid, points in sim.heatmaps.items():
                _write(cache_dir, f"/api/v1/event/{mid}/player/{pid}/heatmap",
                       {"heatmap": points})
            report["heatmaps"] += len(sim.heatmaps)
            report["finished" if status == "finished" else "live"] += 1

        events_by_round[matchday] = events
        report["rounds"] += 1
        if simulate:
            counts = defaultdict(int)
            for e in events:
                counts[e["status"]["type"]] += 1
            log(f"  matchday {matchday:2d}: "
                + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))

    # The three schedule endpoints the importer walks before any match.
    _write(cache_dir, f"/api/v1/unique-tournament/{SERIE_A_TOURNAMENT_ID}/seasons",
           {"seasons": [{"year": year, "id": int(season_id)}]})
    _write(cache_dir,
           f"/api/v1/unique-tournament/{SERIE_A_TOURNAMENT_ID}"
           f"/season/{season_id}/rounds",
           {"rounds": [{"round": r} for r in sorted(events_by_round)]})
    for matchday, events in events_by_round.items():
        _write(cache_dir,
               f"/api/v1/unique-tournament/{SERIE_A_TOURNAMENT_ID}/season/{season_id}"
               f"/events/round/{matchday}", {"events": events})
    return report


def _donor_season_id(target: CompetitionSeason) -> int:
    """The completed season the performances are borrowed from.

    The most recent OTHER season of the same competition that actually has
    appearances — borrowing from the season being simulated would be circular, and
    an empty pool would silently produce a season of blank players.
    """
    candidates = (CompetitionSeason.objects
                  .filter(competition_id=target.competition_id)
                  .exclude(id=target.id).order_by("-id"))
    for cs in candidates:
        if MatchAppearance.objects.filter(match__competition_season=cs,
                                          minutes_played__gt=0).exists():
            return cs.id
    raise RuntimeError(
        "no completed season with appearances to borrow performances from; "
        "import a real season before simulating one.")


def status_at(kickoff, now: datetime, live_minute: int = 0):
    """(provider status, minute to stop the simulation at) for one fixture.

    THE ONE PLACE this is decided, and it has to be: the scenario builder and the
    simulated provider both answer "what minute is this match at", and if they
    answered differently the same fixture would be at the 60th minute when rebuilt
    and at the 75th when polled — the two paths silently disagreeing about the same
    instant.

    The interval is not played. Without that, wall-clock minute 50 would be match
    minute 50, the second half would arrive a quarter of an hour early, and a match
    the provider still calls in-progress would already be showing its final score.
    """
    if kickoff is None or kickoff > now:
        return "notstarted", 0
    elapsed = (now - kickoff).total_seconds() / 60.0
    if elapsed >= 105:                      # 90 plus the interval and stoppages
        return "finished", 90
    if live_minute:
        return "inprogress", max(1, min(90, int(live_minute)))
    if elapsed <= 45:
        return "inprogress", max(1, int(elapsed))
    if elapsed <= 60:
        return "inprogress", 45             # half time
    return "inprogress", min(90, int(elapsed) - 15)


# Kept as a private alias: the name is used above in this module.
_status_at = status_at


def _event_dict(fixture: Match, matchday: int, kickoff, status: str,
                teams: dict[int, SimTeam], season_id: str) -> dict:
    home, away = teams[fixture.home_team_id], teams[fixture.away_team_id]
    return {
        "id": int(fixture.external_id),
        "roundInfo": {"round": matchday},
        "startTimestamp": int(kickoff.timestamp()) if kickoff else None,
        "status": {"type": status},
        "homeTeam": {"id": int(home.sofa_id), "name": home.name,
                     "shortName": home.short_name},
        "awayTeam": {"id": int(away.sofa_id), "name": away.name,
                     "shortName": away.short_name},
        "homeScore": {"current": None}, "awayScore": {"current": None},
        "season": {"id": int(season_id)},
    }
