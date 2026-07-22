"""Heuristic 'voto puro' (base pagella vote) for classic-mode leagues.

Classic fantacalcio scores each player as: fantavoto = voto puro + bonus/malus
(gol/assist/cartellini). The voto puro is the performance grade a pagella would give,
independent of the discrete bonus events. We don't have an external rating provider,
so we DERIVE it from the per-player zone features we already store (the user's choice:
a heuristic from our own data).

Design:
  * Aggregate a player's PlayerZoneFeature values across all 20 zones for the match
    into feature totals, then a single weighted *performance index* (positive actions
    minus errors). Absolute weights barely matter — the index is z-scored, so only the
    RELATIVE weighting of actions counts. That makes the scale self-calibrating.
  * Convert to a per-90 rate (compare a sub fairly to a starter), then z-score the rate
    WITHIN the player's classic role (POR/DIF/CEN/ATT) over the season — so every role
    centres on 6 and a defender isn't dragged down by an attacker's shot volume.
  * Map z -> vote: 6 + K*z, then regress short cameos toward 6 (few minutes = little
    evidence), clamp to a pagella range and round to the 0.5 grid.

Goalkeepers (POR) have their OWN feature channel and weights (anchored on
goals-prevented) but go through the same z-score-within-role pipeline, so a keeper's
voto is on the same pagella scale (its mean sitting a little lower than outfield is
expected and fine — the UI filters by role). ``REFERENCE`` (per-role mean/std of the per-90 index) is
computed once over a season and reused.
"""

from __future__ import annotations

import math
from collections import defaultdict

from django.db.models import Sum

from realdata.models import (
    MatchAppearance, Match, MatchShot, Player, PlayerOnPitchInterval,
    PlayerZoneFeature, PROVIDER_SOFASCORE,
)

# Relative value of each action. Errors are negative. Only the ratios matter (the
# index is z-scored downstream), so these encode "how much a good game looks like".
# IMPACT events — counted as TOTALS (NOT rescaled to 90'): a decisive action's value
# doesn't scale with how few minutes you played, and these fat-tailed features are what
# blew up under per-90 extrapolation. The shooting block encodes the agreed combination:
#   xG (getting into the position) small + xGOT (execution) large − big_chance_missed
#   (squandering an easy chance) > the xG credit, so a glaring miss nets NEGATIVE.
TOTAL_WEIGHTS = {
    "expected_assists": 1.20,    # xA: chance creation, credited to the CREATOR
    "xg_on_target": 1.20,        # post-shot xG: the shooter's EXECUTION merit
    "big_chance_created": 0.80,
    "xg_shots": 0.50,            # raw xG: only partial 'got into position' merit
    "key_passes": 0.50,
    "shots_on_target": 0.25,
    "shots": 0.15,
    "errors_led_to_goal": -1.50,  # decisive error (heavy)
    # Conceding a penalty hands over roughly 0.78 expected goals through a clear
    # individual foul, and — unlike a missed penalty — carries NO fantacalcio
    # malus, so the base vote is the only place it can register at all. Below the
    # error that concedes a goal, because a penalty is not yet a goal.
    "penalties_conceded": -1.20,
    # Winning one is the mirror image and equally unrewarded: the bonus goes to
    # whoever converts, never to the player who earned it.
    "penalties_won": 0.80,
    # Rare interventions that prevent a near-certain goal. Kept as impact totals,
    # not per-90: their value does not scale with how long you played.
    "clearances_off_line": 0.80,
    "last_man_tackle": 0.60,
    # An error that let the opponent SHOOT, without a goal following. Anchored at
    # a third of the error-that-conceded, which is both the intuitive expected
    # cost (a chance handed to an opponent converts roughly one time in three)
    # and the empirical optimum: swept against a full season of real pagelle,
    # -0.50 maximised agreement both overall (0.4593 -> 0.4627) and on the 327
    # affected player-matches (0.4882 -> 0.5113), with heavier weights doing
    # worse. The two features barely overlap (7 player-matches in a season), so
    # this does not double-count the conceded goal.
    "errors_led_to_shot": -0.50,
    "big_chance_missed": -0.80,   # squandering an easy chance > the xG positioning credit
}

# VOLUME / involvement — rescaled to PER-90 (density is the signal: 120 touches in 90'
# != 30 in 20'), tail-compressed, with a floor so a short cameo isn't projected to 90'.
#
# Every key here must be one the provider actually supplies (see
# ``sofascore_adapter.KNOWN_FEATURE_KEYS``; enforced by a test). This table used to
# carry ``passes_into_box`` at 0.40 — the largest weight in the block — plus
# ``progressive_passes_completed``, ``progressive_carries`` and ``pressures``,
# none of which SofaScore reports. They were not merely empty for a season: the
# adapter never writes them, so they contributed exactly zero to every voto ever
# computed, while reading as if progression and pressing were being rewarded.
# Removing them changes no vote (verified over a full season); what it removes is
# the illusion. The intent behind them — credit for creating and progressing — is
# in fact carried by the TOTAL block, where expected_assists, key_passes and
# big_chance_created are the three heaviest positive terms.
PER90_WEIGHTS = {
    "dribbles_won": 0.25,
    # The losing side of the contests we already reward. Without it a defender who
    # won 5 duels out of 6 scored exactly like one who won 5 out of 20: we were
    # treating a RATE as a count, and against the provider's own rating the rate
    # tracks performance better than the count (+0.387 vs +0.348). Mirroring the
    # +0.20 on duels won lets the index respond to the rate while still keeping
    # volume, which a bare ratio would throw away — and a ratio over three duels
    # is noise anyway.
    "duels_lost": -0.20,
    # Being dribbled past is a subset of duels lost (verified: 0 violations in
    # 8659 appearances), so this is deliberate EXTRA weight, not new evidence —
    # getting beaten one-on-one is worse than losing a shoulder-to-shoulder. It is
    # also the individual defensive failure our features could not see at all,
    # which is what made "no recorded error" such a poor proxy for "no fault".
    "dribbled_past": -0.15,
    # Also a subset of accuratePass (weight 0.02): the claim is not that these are
    # extra passes but that a pass played in the opponent half is worth more than
    # one played in your own. This is the progression signal the deleted
    # passes_into_box and progressive_passes were reaching for and never had.
    "passes_opp_half": 0.05,
    "touches_in_box": 0.10,
    "duels_won": 0.20,
    "interceptions": 0.30,
    "ball_recoveries": 0.15,
    "blocks": 0.30,
    "clearances": 0.10,
    "passes_completed": 0.02,
    "touches": 0.01,
    "errors_bad_passes": -0.15,
    "errors_dispossessed": -0.20,
    "errors_miscontrols": -0.20,
    "errors_fouls_committed": -0.15,
}

WEIGHTS = {**TOTAL_WEIGHTS, **PER90_WEIGHTS}  # union, for feature fetch / breakdowns

# --- Goalkeeper channel ------------------------------------------------------
# Keepers produce almost none of the outfield features above, so they need their own
# index. The anchor is goals_prevented (xG-on-target faced MINUS goals conceded): the
# cleanest "did he do better or worse than expected" measure, and the only one that
# accounts for shot difficulty. Save VOLUME is deliberately secondary — a keeper with
# many saves may simply be behind a poor defence — and saves from inside the box
# (harder) weigh more than saves overall.
# NOTE the raw goal count is NOT here: conceding goals is handled by the classic
# -1/goal MALUS in the bonus layer, exactly as the voto-puro/bonus split requires.
GK_TOTAL_WEIGHTS = {
    "gk_goals_prevented": 2.50,   # SIGNED: negative when he underperforms the xG faced
    "gk_penalty_saves": 1.00,
    "errors_led_to_goal": -1.50,
    # Same event, same anchor as the outfield channel (which already shares the
    # -1.50 above). Calibrated on outfield players — keeper errors of this kind
    # are too rare in one season to fit separately — so it rides on the symmetry,
    # not on its own evidence.
    "errors_led_to_shot": -0.50,
}
GK_PER90_WEIGHTS = {
    "gk_saves_inside_box": 0.35,
    "gk_saves": 0.20,
    "gk_high_claims": 0.20,       # command of the area
    "gk_sweeper": 0.15,           # sweeper-keeper interventions
    "gk_punches": 0.10,
    "gk_crosses_not_claimed": -0.30,
    "errors_bad_passes": -0.10,
    "passes_completed": 0.01,     # distribution, marginal
}
GK_WEIGHTS = {**GK_TOTAL_WEIGHTS, **GK_PER90_WEIGHTS}

# Features that are legitimately negative and must keep their sign through the
# tail-compression step.
SIGNED_FEATURES = {"gk_goals_prevented"}

# Tunables (calibrate against the real distribution before fixing).
VOTE_CENTER = 6.0
VOTE_SPREAD_K = 0.8        # vote points per 1 std of within-role index
VOTE_MIN, VOTE_MAX = 3.0, 10.0
MIN_MINUTES_REFERENCE = 20  # only games >= this define the reference distribution
# Bayesian shrinkage strength: a per-90 rate from few minutes is noisy and fat-tailed
# low-count features (xG, key passes) explode when extrapolated to 90'. The evidence
# weight minutes/(minutes+this) pulls short cameos toward the role prior (vote 6); a
# full game keeps almost all its signal. Higher value = more distrust of short games.
SHRINKAGE_MINUTES = 25
# Extrapolation floor: never project a per-90 rate from FEWER than this many minutes
# as if the player had played 90'. A 26' cameo that created one big chance must not be
# read as a 3.5x/90 rate — we cap the projection at this minute baseline. This tackles
# the fat-tailed-cameo problem at its source (the per-90 blow-up), before shrinkage.
EXTRAP_FLOOR_MINUTES = 55

# --- Defensive exposure (outfield defenders) ---------------------------------
# A defender's index is otherwise built from clearances, interceptions, blocks and
# duels — the VOLUME of defending. Under siege those all rise while the team
# concedes, so the two signals cancel and the vote ends up blind to the outcome:
# measured over a season, our defender vote correlated -0.055 with goals conceded
# against -0.53 for both an external pagella and SofaScore's own rating.
#
# The fix is deliberately NOT "the team conceded, so the back four all drop". That
# is collective punishment, and it is demonstrably what the external sources do:
# among defenders with no recorded individual error at all, their vote still falls
# from 6.28 to 5.12 as the team goes from 0 to 4 conceded. Instead we charge each
# defender with the danger the opponent created IN THE ZONES HE PATROLLED, from
# the shot map, scaled by how long he was on the pitch. A centre-back does not pay
# for a goal born on the far flank.
#
# That measure turns out to carry both components on its own, in a proportion the
# data chose rather than one we imposed: 57% of its variance is between back
# lines (the team suffered) and 43% within one (this defender was exposed).
#
# Weight 1.0: swept against SofaScore's INDEPENDENT rating, agreement peaks there
# (0.531 -> 0.541) and falls away beyond it, while agreement with the external
# pagella keeps climbing to 3.0. Past 1.0 we would not be measuring better, only
# importing their collective punishment — the independent referee is what sets the
# stop. The effect is deliberately modest: defenders end up at -0.09 against goals
# conceded, not the -0.53 of the sources that punish the whole back line.
DEF_EXPOSURE_WEIGHT = 1.0

# 'A voto' vs 'senza voto' (s.v.): classic fantacalcio rates a player only if he
# played enough AND was involved enough; below that he gets NO vote (a bench player
# replaces him), not a 6. Involvement is proxied by ball touches. Both tunable.
MIN_MINUTES_RATED = 15
MIN_TOUCHES_RATED = 12
# Above this many minutes, minutes ALONE decide: the touch count is a proxy for
# "was he involved enough to judge", and that question only makes sense for a
# cameo. Anyone who is on the pitch this long has been judged by every pagella
# that exists, however little he saw of the ball — he gets a LOW vote, not no
# vote. Without this, 119 appearances a season (four of them full 90') were
# declared unrated purely on a touch count.
ALWAYS_RATED_MINUTES = 20

# Reference bucket for a player we could rate but whose ROLE we don't know (his
# Player row has no classic_role because the squad import never matched him).
# See ``resolve_role``: s.v. is a statement about the PLAYER'S MATCH, so a hole in
# our master data must never be dressed up as one.
POOLED_OUTFIELD = "_OUTFIELD"


def resolve_role(classic_role: str, totals: dict, is_goalkeeper: bool) -> tuple[str, bool]:
    """(role, role_is_known) for scoring purposes.

    Returns the declared classic_role when we have one. When we don't, we do NOT
    give up: a keeper is identifiable from his own match data (only keepers
    produce ``gk_*`` features), and any other player can still be scored on the
    outfield index against the pooled outfield reference. The second element says
    whether the role is declared, so callers can flag an estimate as such instead
    of presenting it as fact.
    """
    if classic_role:
        return classic_role, True
    if is_goalkeeper or any(k.startswith("gk_") for k in totals):
        return Player.ROLE_GK, False
    return "", False


def is_rated(minutes: int, totals: dict) -> bool:
    """Whether a player goes 'a voto' (vs senza voto) given minutes + involvement."""
    if minutes >= ALWAYS_RATED_MINUTES:
        return True
    return (minutes >= MIN_MINUTES_RATED
            and totals.get("touches", 0.0) >= MIN_TOUCHES_RATED)


def _compress(rate: float) -> float:
    """Tail compression on a per-90 action rate: sqrt keeps order but stops a single
    fat-tailed feature (one player with 27 duels) from dominating the index — sqrt(27)
    is ~2.6x sqrt(4), not 6.75x. Index is z-scored downstream, so the transform only
    tames tails, it doesn't bias the scale."""
    return math.sqrt(rate) if rate > 0 else 0.0


def _compress_signed(value: float) -> float:
    """Tail compression that PRESERVES sign — sqrt(|x|) with the original sign, so a
    keeper who concedes more than the xG he faced keeps his negative signal (plain
    ``_compress`` would floor it to 0 and silently drop bad games)."""
    if value == 0:
        return 0.0
    return math.copysign(math.sqrt(abs(value)), value)


def _gk_index_from_totals(totals: dict, minutes: int) -> float:
    """Weighted performance index for a GOALKEEPER (see GK_*_WEIGHTS)."""
    if minutes <= 0:
        return 0.0
    idx = 0.0
    for k, w in GK_TOTAL_WEIGHTS.items():
        raw = totals.get(k, 0.0)
        idx += w * (_compress_signed(raw) if k in SIGNED_FEATURES else _compress(raw))
    scale = 90.0 / max(minutes, EXTRAP_FLOOR_MINUTES)
    idx += sum(w * _compress(totals.get(k, 0.0) * scale)
               for k, w in GK_PER90_WEIGHTS.items())
    return idx


def index_for_role(role: str, totals: dict, minutes: int,
                   exposure: float = 0.0) -> float:
    """Dispatch to the goalkeeper or outfield index for a player's role.

    ``exposure`` is the opponent xG created in the zones a DEFENDER patrolled (see
    DEF_EXPOSURE_WEIGHT); it is ignored for every other role, whose job is not to
    prevent it."""
    if role == Player.ROLE_GK:
        return _gk_index_from_totals(totals, minutes)
    idx = _index_from_totals(totals, minutes)
    if role == Player.ROLE_DEF and exposure > 0:
        idx -= DEF_EXPOSURE_WEIGHT * _compress(exposure)
    return idx


def _index_from_totals(totals: dict, minutes: int) -> float:
    """Weighted, tail-compressed performance index. Impact events count as totals;
    volume/involvement is per-90 (floored so short cameos aren't extrapolated)."""
    if minutes <= 0:
        return 0.0
    idx = sum(TOTAL_WEIGHTS[k] * _compress(totals.get(k, 0.0)) for k in TOTAL_WEIGHTS)
    scale = 90.0 / max(minutes, EXTRAP_FLOOR_MINUTES)
    idx += sum(PER90_WEIGHTS[k] * _compress(totals.get(k, 0.0) * scale)
               for k in PER90_WEIGHTS)
    return idx


def _per_match_player_totals(match_ids):
    """{(match_id, player_id): {feature_key: total_over_zones}} for sofascore.

    Fetches the union of the outfield AND goalkeeper weight keys: restricting it to
    the outfield set silently starved the GK index of every keeper feature, leaving
    it driven by inaccurate long balls alone (good sweeper-keepers ranked worst).
    """
    rows = (PlayerZoneFeature.objects
            .filter(match_id__in=match_ids, provider=PROVIDER_SOFASCORE,
                    feature_key__in=sorted(set(WEIGHTS) | set(GK_WEIGHTS)))
            .values("match_id", "player_id", "feature_key")
            .annotate(v=Sum("value")))
    out = defaultdict(dict)
    for r in rows:
        out[(r["match_id"], r["player_id"])][r["feature_key"]] = r["v"]
    return out


def _fallback_window(minutes: int, is_starter: bool) -> tuple[float, float]:
    """Last-resort on-pitch window when no interval was recorded for the match.

    A starter is assumed to run from kick-off, a substitute to finish the match.
    Wrong whenever a substitute is himself withdrawn later — a case this shape
    cannot express at all — which is exactly why PlayerOnPitchInterval exists and
    is preferred wherever it has been built.
    """
    minutes = max(0, min(int(minutes or 0), 95))
    if is_starter:
        return 0.0, float(minutes)
    return float(max(0, 95 - minutes)), 95.0


def on_pitch_windows(match_ids, minutes: dict, appearances: dict) -> dict:
    """{(match_id, player_id): (from_minute, to_minute)}.

    Prefers the recorded interval — built from the provider's substitution and
    red-card incidents, so it is exact and covers the substitute who is himself
    replaced — and falls back to the crude assumption only for matches where no
    interval exists.
    """
    windows = {(mid, pid): (float(a), float(b)) for mid, pid, a, b in
               (PlayerOnPitchInterval.objects
                .filter(match_id__in=match_ids)
                .values_list("match_id", "player_id", "start_minute", "end_minute"))}
    for key, (side, is_starter) in appearances.items():
        if key not in windows:
            windows[key] = _fallback_window(minutes.get(key, 0), is_starter)
    return windows


def defensive_exposure(match_ids, minutes: dict) -> dict:
    """{(match_id, player_id): opponent xG created where AND WHILE this player played}.

    Two frames have to line up, and both are verified rather than assumed:

    * the two teams' zone grids are a 180 degree rotation of each other, so an
      attacking zone (col, row) is (4-col, 3-row) for the defence. Attributing
      with the row mirrored puts more conceded danger on the defenders who
      actually committed a shot-conceding error (1.21x vs 1.14x unmirrored),
      matching the rotation independently established for the shot map;
    * only shots struck while he was on the pitch count. Scaling a whole-match
      total by minutes played, which is what this did first, is unbiased on
      average (-0.005) yet misattributes more than 20 percentage points of a
      match's danger for one defender in seven. A defender must not answer for a
      goal conceded after he came off.
    """
    minute_of: dict[tuple, list] = defaultdict(list)
    for mid, side, minute, zk, xg in (MatchShot.objects
                                      .filter(match_id__in=match_ids,
                                              provider=PROVIDER_SOFASCORE)
                                      .values_list("match_id", "team_side", "minute",
                                                   "zone_key", "xg")):
        if not xg:
            continue
        _, col, row = zk.split("_")
        minute_of[(mid, side)].append((minute, int(col), int(row), xg))
    if not minute_of:
        return {}

    appearances = {(a["match_id"], a["player_id"]): (a["side"], a["is_starter"])
                   for a in MatchAppearance.objects.filter(match_id__in=match_ids)
                   .values("match_id", "player_id", "side", "is_starter")}
    presence: dict[tuple, dict] = defaultdict(dict)
    for mid, pid, zk, v in (PlayerZoneFeature.objects
                            .filter(match_id__in=match_ids, provider=PROVIDER_SOFASCORE,
                                    feature_key="touches")
                            .values_list("match_id", "player_id", "zone_key")
                            .annotate(v=Sum("value"))
                            .values_list("match_id", "player_id", "zone_key", "v")):
        _, col, row = zk.split("_")
        presence[(mid, pid)][(int(col), int(row))] = v

    windows = on_pitch_windows(match_ids, minutes, appearances)
    opposite = {"home": "away", "away": "home"}
    out = {}
    for key, zones in presence.items():
        side, is_starter = appearances.get(key, (None, False))
        opp = opposite.get(side)
        total = sum(zones.values())
        if not opp or total <= 0:
            continue
        lo, hi = windows.get(key, _fallback_window(minutes.get(key, 0), is_starter))
        exposure = 0.0
        for minute, col, row, xg in minute_of.get((key[0], opp), ()):
            if minute is not None and not (lo <= minute <= hi):
                continue
            exposure += zones.get((4 - col, 3 - row), 0.0) / total * xg
        if exposure:
            out[key] = exposure
    return out


def _minutes_map(match_ids):
    return {(a["match_id"], a["player_id"]): a["minutes_played"]
            for a in MatchAppearance.objects
            .filter(match_id__in=match_ids)
            .values("match_id", "player_id", "minutes_played")}


def build_reference(competition_season_id: int, *, pooled_std: bool = False) -> dict:
    """Per-role (mean, std) of the per-90 performance index over a season.

    Returns {role: {"mean": m, "std": s, "n": n}}; outfield roles only. With
    ``pooled_std`` every role keeps its own centre but shares ONE spread (the std of
    within-role residuals) — this stops the tight defender distribution from handing
    defenders systematically higher z-scores (and thus topping the charts).
    """
    match_ids = list(Match.objects
                     .filter(competition_season_id=competition_season_id)
                     .values_list("id", flat=True))
    totals = _per_match_player_totals(match_ids)
    minutes = _minutes_map(match_ids)
    exposure = defensive_exposure(match_ids, minutes)
    roles = dict(Player.objects.exclude(classic_role="")
                 .values_list("id", "classic_role"))

    samples = defaultdict(list)  # role -> [performance index]
    for (mid, pid), feats in totals.items():
        role = roles.get(pid)
        if not role:
            continue
        mins = minutes.get((mid, pid), 0)
        if mins < MIN_MINUTES_REFERENCE or not is_rated(mins, feats):
            continue
        # GKs get their own index AND their own role bucket, so they are z-scored
        # WITHIN the role: the keeper scale is self-calibrating like every other.
        samples[role].append(index_for_role(role, feats, mins,
                                            exposure.get((mid, pid), 0.0)))

    ref = {}
    for role, vals in samples.items():
        n = len(vals)
        mean = sum(vals) / n
        var = sum((x - mean) ** 2 for x in vals) / n if n > 1 else 0.0
        ref[role] = {"mean": mean, "std": math.sqrt(var) or 1.0, "n": n}

    # Bucket for players whose role we don't know: pool every OUTFIELD sample
    # (keepers excluded — their index lives on a different scale entirely). Less
    # precise than the right role bucket, but a real vote beats a fake s.v.
    outfield = [x for role, vals in samples.items() if role != Player.ROLE_GK
                for x in vals]
    if outfield:
        n = len(outfield)
        mean = sum(outfield) / n
        var = sum((x - mean) ** 2 for x in outfield) / n if n > 1 else 0.0
        ref[POOLED_OUTFIELD] = {"mean": mean, "std": math.sqrt(var) or 1.0, "n": n}

    if pooled_std:
        residuals = [x - ref[role]["mean"] for role, vals in samples.items()
                     for x in vals]
        if residuals:
            m = sum(residuals) / len(residuals)
            pooled = math.sqrt(sum((r - m) ** 2 for r in residuals) / len(residuals))
            for role in ref:
                ref[role]["std"] = pooled or 1.0
    return ref


def _vote_from_index(index: float, ref_key: str, minutes: int, reference: dict,
                     spread_k: float = VOTE_SPREAD_K) -> float:
    r = reference.get(ref_key)
    if not r:
        return VOTE_CENTER
    z = (index - r["mean"]) / r["std"]
    # Shrink toward the role prior (z -> 0) when minutes are few: we don't trust a
    # per-90 rate extrapolated from a short cameo, so the vote regresses to 6 in
    # proportion to the evidence. w -> 1 for full games, ~0.4 at 20', ~0.3 at 10'.
    w = minutes / (minutes + SHRINKAGE_MINUTES) if minutes > 0 else 0.0
    raw = VOTE_CENTER + spread_k * w * z
    vote = max(VOTE_MIN, min(VOTE_MAX, raw))
    return round(vote * 2) / 2.0  # 0.5 grid


def voto_puro_for_match(match, reference: dict,
                        spread_k: float = VOTE_SPREAD_K) -> list[dict]:
    """Per-player voto puro for one match. List of dicts with components.

    Players below the rating threshold get ``rated=False`` and ``voto_puro=None``
    (senza voto). Goalkeepers are included, scored on the GK channel.

    A player with no declared role is NOT skipped: he is scored against the
    pooled outfield reference (or the GK one if his features give him away) and
    flagged ``role_known=False``. Dropping him used to render as s.v., which is a
    verdict on his performance — so a goalscorer could be shown as unrated.
    """
    totals = _per_match_player_totals([match.id])
    minutes = _minutes_map([match.id])
    exposure = defensive_exposure([match.id], minutes)
    roles = dict(Player.objects.values_list("id", "classic_role"))
    keepers = dict(Player.objects.values_list("id", "is_goalkeeper"))
    names = dict(Player.objects.values_list("id", "short_name"))
    full = dict(Player.objects.values_list("id", "full_name"))

    results = []
    for (mid, pid), feats in totals.items():
        mins = minutes.get((mid, pid), 0)
        if mins <= 0:
            continue
        role, role_known = resolve_role(roles.get(pid) or "", feats,
                                        bool(keepers.get(pid)))
        idx = index_for_role(role, feats, mins, exposure.get((mid, pid), 0.0))
        # An inferred KEEPER still belongs in the keeper distribution — his own
        # features identified him. Only an unknown outfielder needs the pool.
        ref_key = role if role else POOLED_OUTFIELD
        rated = is_rated(mins, feats)
        results.append({
            "player_id": pid,
            "name": names.get(pid) or full.get(pid) or str(pid),
            "role": role,
            "role_known": role_known,
            "minutes": mins,
            "touches": round(feats.get("touches", 0.0), 1),
            "index": round(idx, 2),
            "rated": rated,
            "voto_puro": (_vote_from_index(idx, ref_key, mins, reference, spread_k)
                          if rated else None),
        })
    results.sort(key=lambda d: (d["voto_puro"] is None, -(d["voto_puro"] or 0)))
    return results
