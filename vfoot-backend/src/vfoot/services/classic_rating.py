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
    CARD_RED, CARD_SECOND_YELLOW, CARD_YELLOW,
    MatchAppearance, Match, MatchDisciplinaryEvent, MatchShot, Player,
    PlayerOnPitchInterval, PlayerZoneFeature, PROVIDER_SOFASCORE,
)

# Relative value of each action. Errors are negative. Only the ratios matter (the
# index is z-scored downstream), so these encode "how much a good game looks like".
# IMPACT events — counted as TOTALS (NOT rescaled to 90'): a decisive action's value
# doesn't scale with how few minutes you played. TOTALS are also NOT √-compressed;
# they stay LINEAR (integer counts stay integer, xG/xGOT stay linear). Only the
# PER90 volume block below gets √ (see ``_index_from_totals``).
#
# NOTE (hand-tuning 2026-07-27, model v2): the MAGNITUDES below are the analyst's
# hand-tuned weights from the ``build_voto_tuner`` spreadsheet, not a machine fit.
# A constrained NNLS fit on SofaScore confirmed every SIGN but wanted ~4x more xA
# (SofaScore's known offensive bias); the analyst keeps a flatter, less
# offense-heavy hand set instead. The shooting block:
#   * shots_goal (+0.45): the GOAL itself now scores in the base — the analyst chose
#     to weight goals moderately (own goals excluded upstream, see _merge_shot_detail),
#     closing the "scoring halo" gap where BOTH fantacalcio and SofaScore rated
#     scorers ~+0.85 above us. This is ON TOP of the +3 fantavoto bonus (a different
#     dimension: the base credits the finishing quality, the bonus the fantasy points).
#   * xg_on_target (+0.30) − xg_shots (−0.15): the SGA execution term — post-shot xG
#     over pre-shot xG (positioning is only partial merit), the subtraction now
#     softened. Plus shots_post/shots_blocked for a shot that struck the frame / was
#     blocked (from MatchShot.shot_type, see SHOT_TYPE_TO_FEATURE / _merge_shot_detail).
# DROPPED: big_chance_created / big_chance_missed — redundant now that the goal is
# weighted directly (shots_goal) and the miss is already in the SGA (a missed big
# chance has high xg_shots, low xg_on_target). Removing big_chance_missed also
# fixes its double-penalty with the SGA on the same shot.
TOTAL_WEIGHTS = {
    "expected_assists": 0.15,     # xA: chance creation, credited to the CREATOR
    "shots_goal": 0.30,           # the GOAL itself (own goals excluded), on top of +3 bonus
    "xg_on_target": 0.30,         # post-shot xG: the shooter's EXECUTION merit (SGA +)
    "xg_shots": -0.10,            # raw xG: subtracted (softened) — execution over positioning
    "key_passes": 0.0,
    "shots_on_target": 0.05,
    "shots": 0.05,                # shot ACTIVITY now rewarded (analyst v2.2), not penalised
    "shots_off": 0.02,            # even an off-target attempt: small credit for shooting
    "errors_led_to_goal": -0.35,  # decisive error (heavy)
    # Conceding a penalty hands over roughly 0.78 expected goals through a clear
    # individual foul, and — unlike a missed penalty — carries NO fantacalcio
    # malus, so the base vote is the only place it can register at all.
    "penalties_conceded": -0.50,
    # Winning one is the mirror image and equally unrewarded: the bonus goes to
    # whoever converts, never to the player who earned it.
    "penalties_won": 0.30,
    # Rare interventions that prevent a near-certain goal. Kept as impact totals,
    # not per-90: their value does not scale with how long you played.
    "clearances_off_line": 0.20,
    "last_man_tackle": 0.20,
    # An error that let the opponent SHOOT, without a goal following.
    "errors_led_to_shot": -0.10,
    # SGA_Pali shot-outcome detail, from the event-level shot map
    # (MatchShot.shot_type), merged in by _merge_shot_detail. LINEAR totals.
    "shots_post": 0.22,           # hit the frame: execution merit a goal/save can't show
    "shots_blocked": 0.03,        # the defence intervened
}

# VOLUME / involvement — rescaled to PER-90 (density is the signal: 120 touches in 90'
# != 30 in 20'), √-compressed (tail-tamed), with a floor so a short cameo isn't
# projected to 90'. This is the ONLY block that gets √; totals stay linear.
#
# Every key here must be one the provider actually supplies (see
# ``sofascore_adapter.KNOWN_FEATURE_KEYS``; enforced by a test). This table used to
# carry ``passes_into_box``, ``progressive_passes_completed``, ``progressive_carries``
# and ``pressures``, none of which SofaScore reports — they contributed exactly zero
# while reading as if progression and pressing were rewarded, so they were removed.
PER90_WEIGHTS = {
    "dribbles_won": 0.05,
    "duels_won": 0.10,
    "duels_lost": -0.10,          # the losing side of the contests we reward
    "dribbled_past": -0.07,       # subset of duels_lost: beaten one-on-one is worse
    "passes_opp_half": 0.05,      # progression: a pass in the opponent half is worth more
    "aerials_won": 0.05,
    "aerials_lost": -0.05,
    "tackles_won": 0.04,          # a committed, deliberate intervention
    "was_fouled": 0.02,           # an opponent had to stop you illegally
    "long_balls_completed": 0.05,
    "crosses_completed": 0.05,    # (reactivated by the hand-tuning)
    "touches_in_box": 0.01,
    "interceptions": 0.05,
    "ball_recoveries": 0.03,
    "blocks": 0.03,
    "clearances": 0.03,
    # passes_completed/touches held at 0.01: the earlier kurtosis-gradient nudge
    # (0.01 -> 0.02, with passes_opp_half 0.05 -> 0.06) flattened the distribution
    # toward Statistico's, but that low kurtosis is a symptom of Statistico being
    # result-driven, not a target — and the possession up-weight worked against
    # tempering high votes in defeats (Koopmeiners). Reverted; result-awareness is
    # instead carried by the (stronger) result mitigation below.
    "passes_completed": 0.01,
    "touches": 0.01,
    "errors_bad_passes": -0.03,
    "errors_dispossessed": -0.03,
    "errors_miscontrols": -0.03,
    "errors_fouls_committed": -0.02,
    # dribbles_won(+) / dribbles_attempted(-) is a deliberate RATE pairing, like
    # duels_won/duels_lost: the negative on the superset makes the net contribution
    # turn negative below a ~36% success rate, so many failed take-ons cost even if a
    # few come off. NOT here: possession_lost (possessionLostCtrl) — it is 79% the
    # SAME losses already penalised by errors_dispossessed/miscontrols/bad_passes
    # (same sign, no rate counterpart), so it just doubled the malus on one event and
    # made those weights un-interpretable. Raise the specific errors_* to weigh ball
    # loss more, not this aggregate.
    "dribbles_attempted": -0.03,
}

WEIGHTS = {**TOTAL_WEIGHTS, **PER90_WEIGHTS}  # union, for feature fetch / breakdowns

# Shot-outcome detail lives in the event-level shot map (``MatchShot.shot_type``),
# not the per-zone features, so it is fetched and merged separately (see
# ``_merge_shot_detail``). shots_goal / shots_post / shots_blocked carry weight; the
# rest (shots_saved / shots_off) are mapped for completeness and inspection.
SHOT_TYPE_TO_FEATURE = {"post": "shots_post", "goal": "shots_goal",
                        "save": "shots_saved", "miss": "shots_off",
                        "block": "shots_blocked"}
SHOT_DETAIL_FEATURES = frozenset(SHOT_TYPE_TO_FEATURE.values())

# TOTAL features that get √-compressed (but NOT per-90 scaled, being decisive
# events). √ gives diminishing returns on volume:
#   * shots_goal — a brace is worth √2≈1.4, not 2 (keeps single-goal credit intact,
#     stops multi-goal games inflating the top: max 9.5 -> 9.0, ~ Statistico);
#   * shots — the shot-ACTIVITY reward (+0.05) is linear and stacked on 10-shot
#     games (McTominay 10 shots -> +0.84, on top of on_target/xGOT/goal); √ tames the
#     volume outliers (√10≈3.2) while leaving a normal 2-3 shot game almost unchanged.
SQRT_TOTAL_FEATURES = frozenset({"shots_goal", "shots"})

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

# --- Result-mitigation (v2 stage 2) ------------------------------------------
# A mild nudge toward the team's result WHILE THE PLAYER WAS ON THE PITCH, acting
# ONLY on DIVERGENT cases: a high vote in a defeat comes down, a low vote in a win
# goes up — always TOWARD 6, never away. It deliberately leaves aligned votes alone
# (a high vote in a win is untouched), which is what a symmetric additive term got
# wrong: it further exalted a De Ketelaere already high in a win. Calibrated by the
# SofaScore-merit correlation, not the result-based Statistico (which would be
# circular). Outfield only — the GK channel already reflects the result through
# goals-prevented. gd_on is the on-pitch goal difference (see on_pitch_goal_difference).
#
# The severity of the result scales as BASE + K·|gd_on|: K is the per-goal margin
# ("i gol successivi", weighted fine already), BASE is the discrete "a loss is a
# loss / a win is a win" that fires on the FIRST goal — so crossing draw→defeat
# weighs BASE+K, each further goal only K. Still divergence-only (it multiplies how
# far the vote is from 6), so an aligned vote is untouched. BASE=0 ⇒ the old
# purely-linear behaviour.
RESULT_MITIGATION_K = 0.15
RESULT_MITIGATION_BASE = 0.40
RESULT_MITIGATION_CAP = 1.0

# --- Red-card performance adjustment (v2 stage 3) ----------------------------
# A sending-off is a PERFORMANCE fact the base vote must reflect, over and above
# the flat -1 fantacalcio malus in the bonus layer (which stays — real pagelle both
# drop the vote AND the malus applies). Two graded parts:
#   * severity × man-down: how justifiable the offence was, scaled by how long the
#     team then played a man short (match_end - red_minute)/90. A DOGSO ("last man")
#     is a tactical foul, the least culpable; a straight foul mid; violent conduct /
#     argument / bad behaviour the worst.
#   * a fixed extra for the indefensible reasons (violent conduct, argument, bad
#     behaviour) — those are not football and cost regardless of the timing.
# BOTH are gated ON THE PITCH: a post-match/bench card (minute < 0 or outside the
# player's window) had no in-game impact and adds nothing. red_adj = -(K·sev·down + fixed).
RED_CARD_K = 2.0
RED_CARD_SEVERITY = {
    "Professional foul last man": 0.3,   # DOGSO: tactical, least culpable
    "Foul": 0.6,
    "Foul Committed": 0.6,
    "Violent conduct": 1.0,
    "Bad Behaviour": 1.0,
    "Argument": 1.0,
}
RED_CARD_SEVERITY_DEFAULT = 0.6
RED_CARD_FIXED = {"Violent conduct": 0.3, "Argument": 0.3, "Bad Behaviour": 0.3}

# --- Own-goal performance adjustment -----------------------------------------
# An own goal is a negative performance event a real pagella reflects in the vote.
# We grade it by fault ONLY when we have the precision to do so reliably: with
# sub-minute timing (MatchShot.elapsed_seconds), an own goal that shares the moment
# of an opponent shot (within OWN_GOAL_DEFLECTION_WINDOW_S) deflected it in —
# unlucky, light penalty; otherwise it is a solo error — heavier. WITHOUT seconds
# (rows imported before we captured them) a minute is too coarse to tell a deflection
# from a coincidental shot, so we fall back to a single FLAT penalty rather than
# claim a gravity we cannot measure. The flat -2 fantacalcio malus applies ON TOP in
# the bonus layer regardless. Re-scrape to backfill elapsed_seconds and unlock grading.
OWN_GOAL_VOTE_DEFLECTION = -0.75
OWN_GOAL_VOTE_SOLO = -1.5
OWN_GOAL_VOTE_FLAT = -1.0          # when sub-minute timing is unavailable
OWN_GOAL_DEFLECTION_WINDOW_S = 3   # seconds between the OG and the shot it deflected;
# kept tight (deflections sit at Δ1-2s, solo errors at Δ40s+) so a hectic sequence
# with an unrelated close-by shot is not mistaken for a deflection.
# A missed penalty (shot situation='penalty', not scored). The -3 fantavoto malus
# lives in the bonus layer (classic_pagella); THIS is the added voto-puro drop, kept
# small because the voto puro already reads the penalty as a good on-target shot via
# the SGA and we deliberately keep that (the strike itself was well hit). Scaled by
# whether converting it would have changed the result — see penalty_missed_adjustments.
PENALTY_MISSED_VOTE_RELEVANT = -1.0    # +1 goal would have flipped the final result
PENALTY_MISSED_VOTE_IRRELEVANT = -0.5  # result already decided
# Bayesian shrinkage strength: a per-90 rate from few minutes is noisy and fat-tailed
# low-count features (xG, key passes) explode when extrapolated to 90'. The evidence
# weight minutes/(minutes+this) pulls short cameos toward the role prior (vote 6); a
# full game keeps almost all its signal. Higher value = more distrust of short games.
# (Was briefly lowered to 18 alongside the kurtosis nudge to keep spread up; reverted
# to the well-reasoned 25 when that nudge was undone — 18 also inflated full-game
# bases like Koopmeiners' by trusting the sample slightly more than warranted.)
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
# Applied LINEARLY (v2 hand-tuning), unlike the √-compressed volume block: exposure
# is already a small xG figure, not a fat-tailed count, so √ would over-flatten it.
# Weight set by the analyst in the tuner; the effect stays deliberately modest —
# charge the defender for danger in HIS zones while he was on, not collective
# punishment of the whole back line.
DEF_EXPOSURE_WEIGHT = 0.40

# 'A voto' vs 'senza voto' (s.v.): classic fantacalcio rates a player only if he
# played enough AND was involved enough; below that he gets NO vote (a bench player
# replaces him), not a 6. Involvement is proxied by ball touches. Both tunable.
# NB: this is only the MINUTES/INVOLVEMENT gate. A player involved in a decisive
# event (goal, assist, own goal, penalty, booking, sending-off on the pitch) is
# rated regardless — that override lives in ``voto_puro_for_match`` via
# ``rating_forcing_event_players``, because those events are not in the zone totals.
MIN_MINUTES_RATED = 12
MIN_TOUCHES_RATED = 12
# Above this many minutes, minutes ALONE decide: the touch count is a proxy for
# "was he involved enough to judge", and that question only makes sense for a
# cameo. Anyone who is on the pitch this long has been judged by every pagella
# that exists, however little he saw of the ball — he gets a LOW vote, not no
# vote. Without this, 119 appearances a season (four of them full 90') were
# declared unrated purely on a touch count.
ALWAYS_RATED_MINUTES = 20

# Reference bucket for a player we could rate but whose ROLE we don't know (his
# Player row has no classic_role_seed because the squad import never matched him).
# See ``resolve_role``: s.v. is a statement about the PLAYER'S MATCH, so a hole in
# our master data must never be dressed up as one.
POOLED_OUTFIELD = "_OUTFIELD"


def resolve_role(classic_role_seed: str, totals: dict, is_goalkeeper: bool) -> tuple[str, bool]:
    """(role, role_is_known) for scoring purposes.

    Returns the declared classic_role_seed when we have one. When we don't, we do NOT
    give up: a keeper is identifiable from his own match data (only keepers
    produce ``gk_*`` features), and any other player can still be scored on the
    outfield index against the pooled outfield reference. The second element says
    whether the role is declared, so callers can flag an estimate as such instead
    of presenting it as fact.
    """
    if classic_role_seed:
        return classic_role_seed, True
    if is_goalkeeper or any(k.startswith("gk_") for k in totals):
        return Player.ROLE_GK, False
    return "", False


def current_role_map(*, only_declared: bool = False) -> dict:
    """pid -> classic role. THE canonical role source for scoring the voto puro.

    Any code that computes the voto puro / its reference MUST get roles from here,
    never from ``Player.classic_role_seed`` directly. That raw field is only
    Transfermarkt's provider seed, under which every winger is a midfielder by
    convention — reading it for scoring pools wide attackers (Leão, Berardi,
    Neres...) into the CEN reference and z-scores them against the wrong peers.
    This helper instead returns the DISAMBIGUATED current role from the k-means
    style inference (``CurrentPlayerRole.role_mitigated``, written by ``manage.py
    compute_classic_roles``), so Leão is scored as the 'punta d'area' he plays as.
    It falls back to the raw seed only for players the inference never covered.

    Role hierarchy across the app (do not confuse the layers):
      * ``Player.classic_role_seed`` – raw TM seed; SEEDS the rest, never scores.
      * ``CurrentPlayerRole``        – TM + k-means disambiguation, one row per
                                       player, recomputed on a fresh scrape; THIS,
                                       for scoring. No season dimension.
      * ``LeaguePlayerRole``         – a league's frozen snapshot; authority INSIDE
                                       a league (overrides this for that league's
                                       pagella display / lineup legality).

    NB: calibrate a season's reference while the current roles still reflect that
    season's play (i.e. at season end), since there is no per-season role history.

    With ``only_declared`` empty roles are dropped, which is what the reference-
    population builders want (a role has to be known to bucket a sample).
    """
    from vfoot.models import CurrentPlayerRole
    roles = dict(Player.objects.values_list("id", "classic_role_seed"))
    for pid, role in (CurrentPlayerRole.objects
                      .values_list("player_id", "role_mitigated")):
        if role:
            roles[pid] = role
    if only_declared:
        return {pid: r for pid, r in roles.items() if r}
    return roles


def is_rated(minutes: int, totals: dict) -> bool:
    """Minutes/involvement gate for 'a voto' vs senza voto. NOT the whole story:
    a player involved in a decisive event is rated even below this — see
    ``rating_forcing_event_players`` and how ``voto_puro_for_match`` combines them."""
    if minutes >= ALWAYS_RATED_MINUTES:
        return True
    return (minutes >= MIN_MINUTES_RATED
            and totals.get("touches", 0.0) >= MIN_TOUCHES_RATED)


_CARD_TYPES = (CARD_YELLOW, CARD_SECOND_YELLOW, CARD_RED)


def rating_forcing_event_players(match_id: int) -> set:
    """player_ids whose match carried a decisive event that forces a rating no
    matter how few minutes/touches they had — classic fantacalcio never leaves such
    a player 'senza voto'. Covers a goal, assist or own goal; a booking; and a
    sending-off/booking taken ON THE PITCH (the card's minute falls inside the
    player's on-pitch window, which drops the post-match/bench card anomalies at
    minute -5). Penalties won/conceded are handled by the caller from the zone
    totals it already holds. Own goals live in ``MatchAppearance.raw_stats``."""
    apps = list(MatchAppearance.objects.filter(match_id=match_id)
                .values("player_id", "side", "is_starter", "goals", "assists",
                        "minutes_played", "raw_stats"))
    if not apps:
        return set()
    forcing = set()
    for a in apps:
        rs = a.get("raw_stats") or {}
        if a["goals"] or a["assists"] or (rs.get("ownGoals") or 0) > 0:
            forcing.add(a["player_id"])

    minutes = {(match_id, a["player_id"]): a["minutes_played"] for a in apps}
    appearances = {(match_id, a["player_id"]): (a["side"], a["is_starter"])
                   for a in apps}
    windows = on_pitch_windows([match_id], minutes, appearances)
    for pid, minute in (MatchDisciplinaryEvent.objects
                        .filter(match_id=match_id, card_type__in=_CARD_TYPES)
                        .values_list("player_id", "minute")):
        lo, hi = windows.get((match_id, pid), (0.0, 0.0))
        if minute is not None and lo <= minute <= hi:
            forcing.add(pid)
    return forcing


def red_card_adjustments(match_id: int) -> dict:
    """{player_id: voto-puro adjustment (<= 0) for a sending-off taken on the pitch}.

    Grades the sending-off by severity (how justifiable the reason) times how long
    it left the team a man down, plus a fixed extra for the indefensible reasons
    (see RED_CARD_*). Gated on the pitch: a post-match/bench card (minute < 0, or a
    minute outside the player's on-pitch window) had no in-game impact and is
    skipped — this drops the minute -5 anomalies. This is separate from and additive
    to the flat fantacalcio red malus applied in the bonus layer."""
    events = list(MatchDisciplinaryEvent.objects
                  .filter(match_id=match_id,
                          card_type__in=(CARD_RED, CARD_SECOND_YELLOW))
                  .values_list("player_id", "minute", "reason"))
    if not events:
        return {}
    apps = list(MatchAppearance.objects.filter(match_id=match_id)
                .values("player_id", "side", "is_starter", "minutes_played"))
    minutes = {(match_id, a["player_id"]): a["minutes_played"] for a in apps}
    appearances = {(match_id, a["player_id"]): (a["side"], a["is_starter"])
                   for a in apps}
    windows = on_pitch_windows([match_id], minutes, appearances)
    match_end = max((hi for _lo, hi in windows.values()), default=95.0)
    out = {}
    for pid, minute, reason in events:
        lo, hi = windows.get((match_id, pid), (0.0, 0.0))
        if minute is None or minute < 0 or not (lo <= minute <= hi):
            continue
        out[pid] = out.get(pid, 0.0) - red_card_penalty(reason, minute, match_end)
    return out


def own_goal_adjustments(match_id: int) -> dict:
    """{player_id: voto-puro penalty for an own goal}, graded by fault when possible.

    An own goal is a 'goal' shot tagged with the OPPONENT's side (the side it counts
    for), so a goal-shot whose team_side differs from the scorer's own side is an own
    goal. Gravity, ONLY with sub-minute timing (elapsed_seconds): an opponent shot
    within OWN_GOAL_DEFLECTION_WINDOW_S seconds is the shot it deflected in — unlucky
    (OWN_GOAL_VOTE_DEFLECTION); none near reads as a solo error (OWN_GOAL_VOTE_SOLO).
    WITHOUT seconds, a minute is too coarse to tell them apart, so a single FLAT
    penalty (OWN_GOAL_VOTE_FLAT) applies. Additive to the -2 fantacalcio malus."""
    sides = {(match_id, a["player_id"]): a["side"]
             for a in MatchAppearance.objects.filter(match_id=match_id)
             .values("player_id", "side")}
    shots = list(MatchShot.objects.filter(match_id=match_id)
                 .values_list("player_id", "team_side", "is_goal", "shot_type",
                              "elapsed_seconds"))
    own_goals = [(pid, sec) for pid, ts, isg, st, sec in shots
                 if isg and st == "goal" and sides.get((match_id, pid), ts) != ts]
    if not own_goals:
        return {}
    out = {}
    for pid, og_sec in own_goals:
        if og_sec is None:
            out[pid] = out.get(pid, 0.0) + OWN_GOAL_VOTE_FLAT
            continue
        opp = "away" if sides.get((match_id, pid)) == "home" else "home"
        deflection = any(ts == opp and sp != pid and sec is not None
                         and abs(sec - og_sec) <= OWN_GOAL_DEFLECTION_WINDOW_S
                         for sp, ts, _isg, _st, sec in shots)
        out[pid] = out.get(pid, 0.0) + (OWN_GOAL_VOTE_DEFLECTION if deflection
                                        else OWN_GOAL_VOTE_SOLO)
    return out


def penalty_missed_adjustments(match_id: int) -> dict:
    """{player_id: voto-puro drop for a missed penalty}, scaled by result relevance.

    A missed penalty is a shot with ``situation='penalty'`` that is not a goal (saved,
    off target, woodwork). Magnitude: RELEVANT (-1) if converting it would have flipped
    the final result — the taker's team drew (gd 0 → win) or lost by one (gd -1 → draw);
    IRRELEVANT (-0.5) if the result was already decided. Additive to the -3 fantacalcio
    malus in the bonus layer, and ON TOP of the SGA (the strike stays a good on-target
    shot in the index — we only add this performance drop for the miss itself)."""
    m = (Match.objects.filter(id=match_id)
         .values("home_goals", "away_goals").first())
    if not m:
        return {}
    hg, ag = int(m["home_goals"] or 0), int(m["away_goals"] or 0)
    out: dict = {}
    for pid, side in (MatchShot.objects
                      .filter(match_id=match_id, situation="penalty", is_goal=False)
                      .exclude(player__isnull=True)
                      .values_list("player_id", "team_side")):
        gd = (hg - ag) if side == "home" else (ag - hg)
        relevant = gd in (0, -1)
        out[pid] = out.get(pid, 0.0) + (PENALTY_MISSED_VOTE_RELEVANT if relevant
                                        else PENALTY_MISSED_VOTE_IRRELEVANT)
    return out


def red_card_penalty(reason: str, minute: float, match_end: float) -> float:
    """Positive magnitude of a sending-off's voto-puro drop: severity (how
    justifiable the reason) times the man-down fraction (match_end - minute)/90,
    plus a fixed extra for the indefensible reasons. Pure — the on-pitch gating and
    sign live in ``red_card_adjustments``."""
    minutes_down = max(0.0, match_end - minute)
    sev = RED_CARD_SEVERITY.get(reason, RED_CARD_SEVERITY_DEFAULT)
    fixed = RED_CARD_FIXED.get(reason, 0.0)
    return RED_CARD_K * sev * (minutes_down / 90.0) + fixed


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
        idx -= DEF_EXPOSURE_WEIGHT * exposure  # LINEAR (v2), not √-compressed
    return idx


def _index_from_totals(totals: dict, minutes: int) -> float:
    """Weighted performance index (outfield). Impact events count as LINEAR totals;
    the volume/involvement block is per-90 and √-compressed (floored so short cameos
    aren't extrapolated). The two-way split is the v2 selective-√ design."""
    if minutes <= 0:
        return 0.0
    # TOTAL: linear, except SQRT_TOTAL_FEATURES (shots_goal) which is √-compressed
    # for diminishing returns on multiple goals — still no per-90 scaling.
    idx = sum(TOTAL_WEIGHTS[k] * (_compress(totals.get(k, 0.0))
                                  if k in SQRT_TOTAL_FEATURES else totals.get(k, 0.0))
              for k in TOTAL_WEIGHTS)
    scale = 90.0 / max(minutes, EXTRAP_FLOOR_MINUTES)
    idx += sum(PER90_WEIGHTS[k] * _compress(totals.get(k, 0.0) * scale)
               for k in PER90_WEIGHTS)  # √ per-90 block
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
    _merge_shot_detail(out, match_ids)
    return out


def _merge_shot_detail(out: dict, match_ids) -> None:
    """Fold the SGA_Pali shot-outcome counts (shots_post / shots_blocked / ...) into
    the per-player totals. They live in the event-level shot map, not the zone
    features, so they are counted from ``MatchShot.shot_type`` and added in place.
    Only the mapped types are counted; unmapped ones are ignored.

    OWN GOALS are dropped: SofaScore files an own goal as a 'goal' shot by the
    own-scorer but tags it with the side it counts FOR (the opponent's), so a
    goal-shot whose team_side differs from the player's own side is an own goal and
    must not count as a goal for him — it would otherwise pollute shots_goal (used as
    a goals-scored proxy when tuning)."""
    sides = {(a["match_id"], a["player_id"]): a["side"]
             for a in MatchAppearance.objects.filter(match_id__in=match_ids)
             .values("match_id", "player_id", "side")}
    counts = defaultdict(lambda: defaultdict(float))
    for mid, pid, st, ts in (MatchShot.objects
                             .filter(match_id__in=match_ids)
                             .values_list("match_id", "player_id", "shot_type",
                                          "team_side")):
        feat = SHOT_TYPE_TO_FEATURE.get(st)
        if not feat:
            continue
        if st == "goal" and sides.get((mid, pid), ts) != ts:
            continue  # own goal: counts for the opponent, not a goal for him
        counts[(mid, pid)][feat] += 1.0
    for key, feats in counts.items():
        row = out[key]  # defaultdict(dict): materialises a shots-only player too
        for feat, n in feats.items():
            row[feat] = row.get(feat, 0.0) + n


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


def on_pitch_goal_difference(match_ids, minutes: dict) -> dict:
    """{(match_id, player_id): goals_for - goals_against WHILE he was on the pitch}.

    The mitigation nudges a vote toward the team's fortunes, but only for the
    minutes the player actually shared: a defender must not be tempered for goals
    conceded after he came off, nor a sub credited for a lead built before he came
    on. Goals are timed from the shot map (is_goal); presence from the same on-pitch
    windows the exposure uses. Only non-zero differences are returned."""
    goals: dict[int, list] = defaultdict(list)  # match_id -> [(minute, side)]
    for mid, minute, side in (MatchShot.objects
                              .filter(match_id__in=match_ids, is_goal=True,
                                      provider=PROVIDER_SOFASCORE)
                              .values_list("match_id", "minute", "team_side")):
        goals[mid].append((minute, side))
    if not goals:
        return {}
    appearances = {(a["match_id"], a["player_id"]): (a["side"], a["is_starter"])
                   for a in MatchAppearance.objects.filter(match_id__in=match_ids)
                   .values("match_id", "player_id", "side", "is_starter")}
    windows = on_pitch_windows(match_ids, minutes, appearances)
    out = {}
    for key, (side, is_starter) in appearances.items():
        scored = goals.get(key[0])
        if not scored:
            continue
        lo, hi = windows.get(key, _fallback_window(minutes.get(key, 0), is_starter))
        gf = ga = 0
        for minute, gside in scored:
            if minute is None or not (lo <= minute <= hi):
                continue
            if gside == side:
                gf += 1
            else:
                ga += 1
        if gf != ga:
            out[key] = gf - ga
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
    roles = current_role_map(only_declared=True)

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


def _raw_vote_from_index(index: float, ref_key: str, minutes: int, reference: dict,
                         spread_k: float = VOTE_SPREAD_K) -> float:
    """The vote before the 0.5-grid rounding (and before result mitigation), clamped
    to the pagella range. Split out so the mitigation nudge can be applied to the
    raw value and the result rounded once."""
    r = reference.get(ref_key)
    if not r:
        return VOTE_CENTER
    z = (index - r["mean"]) / r["std"]
    # Shrink toward the role prior (z -> 0) when minutes are few: we don't trust a
    # per-90 rate extrapolated from a short cameo, so the vote regresses to 6 in
    # proportion to the evidence. w -> 1 for full games, ~0.4 at 20', ~0.3 at 10'.
    w = minutes / (minutes + SHRINKAGE_MINUTES) if minutes > 0 else 0.0
    raw = VOTE_CENTER + spread_k * w * z
    return max(VOTE_MIN, min(VOTE_MAX, raw))


def _round_half(vote: float) -> float:
    return round(vote * 2) / 2.0  # 0.5 grid


def _vote_from_index(index: float, ref_key: str, minutes: int, reference: dict,
                     spread_k: float = VOTE_SPREAD_K) -> float:
    return _round_half(_raw_vote_from_index(index, ref_key, minutes, reference,
                                            spread_k))


def result_mitigation(raw_vote: float, gd_on: int,
                      k: float = RESULT_MITIGATION_K,
                      base: float = RESULT_MITIGATION_BASE,
                      cap: float = RESULT_MITIGATION_CAP) -> float:
    """Divergence-only nudge toward the on-pitch result (see RESULT_MITIGATION_K).

    Fires only for a high vote (>6) in a net defeat (gd_on<0) — pulled DOWN — or a
    low vote (<6) in a net win (gd_on>0) — pulled UP; an aligned vote gets neither,
    so the nudge always moves TOWARD 6 and never inflates. The result severity is
    ``base + k·|gd_on|``: the discrete ``base`` marks that it IS a defeat/win (fires
    on the first goal), ``k`` weights each further goal of margin. Clamped to ±cap."""
    over = max(0.0, raw_vote - VOTE_CENTER)   # only a high vote is tempered in a loss
    under = max(0.0, VOTE_CENTER - raw_vote)  # only a low vote is lifted in a win
    if gd_on < 0:
        return max(-cap, -over * (base + k * (-gd_on)))
    if gd_on > 0:
        return min(cap, under * (base + k * gd_on))
    return 0.0


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
    gd_on = on_pitch_goal_difference([match.id], minutes)
    roles = current_role_map()
    keepers = dict(Player.objects.values_list("id", "is_goalkeeper"))
    names = dict(Player.objects.values_list("id", "short_name"))
    full = dict(Player.objects.values_list("id", "full_name"))
    # Decisive-event override for s.v.: a scorer/assist-man/booked/sent-off (on the
    # pitch) player is rated even below the minutes/touches gate.
    forcing = rating_forcing_event_players(match.id)
    red_adj = red_card_adjustments(match.id)
    og_adj = own_goal_adjustments(match.id)
    pen_adj = penalty_missed_adjustments(match.id)
    outfield_roles = (Player.ROLE_DEF, Player.ROLE_MID, Player.ROLE_FWD)

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
        # Rated if he played/was involved enough, OR was in a decisive event
        # (goal/assist/own goal/booking/sending-off), OR won/conceded a penalty.
        rated = (is_rated(mins, feats) or pid in forcing
                 or feats.get("penalties_won", 0.0) > 0
                 or feats.get("penalties_conceded", 0.0) > 0)
        raw = _raw_vote_from_index(idx, ref_key, mins, reference, spread_k)
        # Result mitigation: divergence-only, outfield only (the GK channel already
        # reflects the result). Recorded so the vote explanation can reconcile.
        nudge = (result_mitigation(raw, gd_on[(mid, pid)])
                 if role in outfield_roles and (mid, pid) in gd_on else 0.0)
        # Red-card + own-goal + missed-penalty performance drops (post-adjustments,
        # any role; the missed penalty stays a good shot in the index, this is the
        # added drop for the miss — see penalty_missed_adjustments).
        radj = red_adj.get(pid, 0.0)
        oadj = og_adj.get(pid, 0.0)
        padj = pen_adj.get(pid, 0.0)
        voto = (_round_half(max(VOTE_MIN, min(VOTE_MAX, raw + nudge + radj + oadj + padj)))
                if rated else None)
        results.append({
            "player_id": pid,
            "name": names.get(pid) or full.get(pid) or str(pid),
            "role": role,
            "role_known": role_known,
            "minutes": mins,
            "touches": round(feats.get("touches", 0.0), 1),
            "index": round(idx, 2),
            "rated": rated,
            "result_nudge": round(nudge, 3),
            "red_adjustment": round(radj, 3),
            "own_goal_adjustment": round(oadj, 3),
            "penalty_adjustment": round(padj, 3),
            "voto_puro": voto,
        })
    results.sort(key=lambda d: (d["voto_puro"] is None, -(d["voto_puro"] or 0)))
    return results
