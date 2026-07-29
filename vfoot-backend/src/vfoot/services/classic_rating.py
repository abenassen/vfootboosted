"""Heuristic 'voto puro' (base pagella vote) for classic-mode leagues.

Classic fantacalcio scores each player as: fantavoto = voto puro + bonus/malus
(gol/assist/cartellini). The voto puro is the performance grade a pagella would give,
independent of the discrete bonus events. We don't have an external rating provider,
so we DERIVE it from the per-player zone features we already store (the user's choice:
a heuristic from our own data).

Design:
  * Aggregate a player's PlayerZoneFeature values across all 20 zones for the match
    into feature totals, converting the volume block to a per-90 rate (so a sub is
    compared fairly to a starter).
  * STANDARDISE every feature by its own spread, compress, and standardise again —
    see ``_feature_z``. This is what makes the weights readable: a weight IS the
    contribution to the index of ONE SIGMA of that feature. Under the older scheme
    (raw values, weights absorbing whatever scale the provider happened to use)
    that reading was impossible, and hand-tuning was guesswork: halving the xA
    weight did NOT halve its effect relative to a goal, because the two live on
    distributions of very different width.
  * Sum the weighted standardised features into a *performance index*, then z-score
    the index WITHIN the player's classic role (POR/DIF/CEN/ATT) over the season —
    so every role centres on 6 and a defender isn't dragged down by an attacker's
    shot volume. Only the RELATIVE weighting matters: scaling every weight by the
    same constant is a no-op.
  * Map z -> vote: 6 + K*z, then regress short cameos toward 6 (few minutes = little
    evidence), clamp to a pagella range and round to the 0.5 grid.

Goalkeepers (POR) have their OWN feature channel and weights (anchored on
goals-prevented) but go through the same z-score-within-role pipeline, so a keeper's
voto is on the same pagella scale (its mean sitting a little lower than outfield is
expected and fine — the UI filters by role). ``REFERENCE`` (per-role mean/std of the per-90 index) is
computed once over a season and reused.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict

from django.db.models import Sum

from realdata.models import (
    CARD_RED, CARD_SECOND_YELLOW, CARD_YELLOW,
    MatchAppearance, Match, MatchDisciplinaryEvent, MatchShot, Player,
    PlayerOnPitchInterval, PlayerZoneFeature, PROVIDER_SOFASCORE,
)

log = logging.getLogger(__name__)

# EVERY WEIGHT BELOW IS IN THE SAME UNIT: the contribution to the index of ONE
# STANDARD DEVIATION of that feature, measured over the calibration population (see
# ``_feature_z`` and FEATURE_SCALES). Errors are negative. Only ratios matter — the
# index is z-scored downstream — so scaling the whole table by a constant is a no-op.
#
# Why that unit and not the raw provider scale (which is what these were until
# 2026-07-29): with raw values a weight had to absorb whatever units the provider
# happened to use, so two weights were never comparable and hand-tuning could not
# express an intent. The xA case made it concrete: the analyst wanted a created
# chance to be worth about half a goal and halved the weight to get there — which
# did not work, because xA and goals live on distributions of very different width,
# so half the weight was nowhere near half the effect. Now it is: to make feature A
# count half of feature B, give it half the weight.
#
# TOTALS are NOT rescaled to 90': a decisive action's value does not scale with how
# few minutes you played. The PER90 volume block below is (density is the signal).
#
# NOTE (hand-tuning 2026-07-27, model v2): the RELATIVE magnitudes are the analyst's,
# from the ``build_voto_tuner`` spreadsheet, not a machine fit. A constrained NNLS fit
# on SofaScore confirmed every SIGN but wanted ~4x more xA (SofaScore's known
# offensive bias); the analyst keeps a flatter, less offense-heavy hand set instead.
#
# THE SHOOTING BLOCK is one formula, not a free list:
#
#     shooting credit = S·(xGOT − xG + woodwork)  +  β·xG
#                       └──── execution: sga_post ────┘  └ mass of chances ┘
#
# Until the standardisation this was stored EXPANDED, as w(xg_on_target)=S and
# w(xg_shots)=β−S. That is no longer possible: the compression is non-linear, so
# f(xGOT) − f(xG) is not f(xGOT − xG) and the SGA cannot be reconstructed from two
# separately-transformed parts. It is therefore a DERIVED feature of its own,
# ``sga_post`` (see ``derived_features``), and the mass of chances keeps its own
# positive weight — which also reads better than the old +0.48/−0.32 pair.
#
#   * sga_post — post-shot xG over pre-shot xG: where the shot ended up, over where
#     it was taken from. Plus the woodwork, at SGA_POST_WOODWORK, because the
#     provider gives a shot off the frame no xGOT at all and its execution merit
#     would otherwise vanish.
#   * β/S = 1/3 — the mass of chances is worth a third of the execution. This ratio
#     decides WHICH GOAL scores highest and the benchmark cannot arbitrate it
#     (agreement is flat for β/S between 1/3 and 1): it is a design choice, judged on
#     the ordering it produces. At the previous 2/3 a tap-in (xG 0.70, xGOT 0.80)
#     outscored a hard finish (xG 0.055, xGOT 0.513) — an easy chance carries a high
#     xGOT by construction. At 1/3 the ordering inverts, and the correlation between
#     a goal's credit and how EASY the chance was drops from +0.41 to +0.11 over the
#     season's 841 open-play goals.
#   * The block was scaled x1.6 on 2026-07-29. Measured against the external base
#     votes, a goal used to lift an ATTACKER's vote by 0.82 against 1.23 for
#     fantacalcio and 1.32 for the Statistico — a 35% shortfall; it is now 0.96, and
#     the error on scorers falls from 0.488 to 0.398 (ATT r 0.730 -> 0.760). KNOWN
#     COST: the same scaling overpays a DEFENDER's goal (1.31 against ~1.05
#     externally) because the tighter defender index divides the same gain by a
#     smaller σ — accepted deliberately, since fixing it properly needs a per-role
#     shooting scale and this model keeps ONE global outfield weight vector.
# DROPPED: big_chance_missed — the miss is already in the SGA (a missed big chance
# has high xg_shots, low xg_on_target), so weighting it double-penalised the same
# shot. Its sibling big_chance_created is NOT the same statistic and is weighted
# below: that earlier removal conflated the two faces of one event.
TOTAL_WEIGHTS = {
    "expected_assists": 0.11,   # xA: chance creation, credited to the CREATOR
    # The DISCRETE counterpart of xA, and the creator's side of a big chance —
    # verified as the PASSER's stat, not the shooter's: it never exceeds the
    # player's own key passes (0 violations in 10,067 player-matches), 36% of the
    # matches carrying one have no shot by that player at all, and it correlates
    # +0.48 with key passes against +0.13 with his own shots. Its mirror image
    # big_chance_missed is the opposite (+0.41 with shots, +0.06 with key passes).
    # Why it is here: 64% of created big chances never become assists, so this
    # rewards the gesture where the outcome never arrives.
    #
    # BOTH creation weights were raised on 2026-07-29 (xA 0.0168 -> 0.11, this one
    # 0.0363 -> 0.07) because the block was below the resolution of the output. At
    # the old weights xA never moved a single vote by half a grid step in 9,303
    # player-matches — max 0.199 points — so it only ever tipped roundings; and the
    # whole creation block was relevant (worth >= half a step) in 3.6% of matches
    # against 25.4% for the shooting block and 61.7% for volume. It is now 17.7%,
    # roughly three quarters of the shooting block: creating counts less than
    # finishing, which is right, but not seven times less.
    # KNOWN COST, accepted as a design choice: agreement falls, and unlike the
    # earlier creation experiments it falls on EVERY role (DIF r 0.627 -> 0.603,
    # CEN 0.698 -> 0.693, ATT 0.770 -> 0.764). Part of that is expected — neither
    # benchmark pays for creation that the finisher wastes, so diverging there is
    # the point — but the monotone decline says some of it is noise, mostly a
    # defender's xA being the residue of a hopeful cross. If the defender vote ever
    # needs recovering, this is the first weight to look at.
    "big_chance_created": 0.07,
    "shots_goal": 0.1386,         # the GOAL itself (own goals excluded), on top of +3 bonus
    "sga_post": 0.0905,           # = S: EXECUTION merit, derived (xGOT − xG + woodwork)
    "xg_shots": 0.0323,           # = β: the mass of chances occupied, β/S = 1/3
    "key_passes": 0.0,
    "shots_on_target": 0.0494,
    "shots": 0.0558,              # shot ACTIVITY now rewarded (analyst v2.2), not penalised
    "shots_off": 0.0196,          # even an off-target attempt: small credit for shooting
    "errors_led_to_goal": -0.0354,   # decisive error (heavy)
    # Conceding a penalty hands over roughly 0.78 expected goals through a clear
    # individual foul, and — unlike a missed penalty — carries NO fantacalcio
    # malus, so the base vote is the only place it can register at all.
    "penalties_conceded": -0.0505,
    # Winning one is the mirror image and equally unrewarded: the bonus goes to
    # whoever converts, never to the player who earned it.
    "penalties_won": 0.0244,
    # Rare interventions that prevent a near-certain goal. Kept as impact totals,
    # not per-90: their value does not scale with how long you played.
    "clearances_off_line": 0.035,
    "last_man_tackle": 0.05,
    # An error that let the opponent SHOOT, without a goal following.
    "errors_led_to_shot": -0.0189,
    "shots_blocked": 0.0278,      # the defence intervened
    # PROVIDER PROXY, and the only one in the model — read the note below before
    # touching it.
    "defensive_value": 0.10,
}

# --- The one feature we do not measure ourselves ------------------------------
# ``defensive_value`` is SofaScore's own ``defensiveValueNormalized``, shipped with
# the per-player statistics and until now discarded along with 28 other fields.
#
# Why it is here. Most of a defender's job is invisible in an event feed: holding
# the line, the position taken, the tackle that never had to happen. Measured on
# defenders with neither goal nor assist, our vote agreed with the human pagella at
# r 0.493 — against 0.566 for SofaScore's own rating, and 0.818 between fantacalcio's
# two columns. This single column, alone, correlates 0.590 with that pagella: more
# than our whole model did. It is a synthesis of a feed we do not have (every duel
# with its location, opponent and phase), not a repackaging of what we already hold
# — our own features explain only 62% of it for defenders.
#
# Why this is NOT importing their rating. We take one INPUT dimension and weigh it
# ourselves among forty others; we do not take their ``rating``, which is the model
# output and carries their offensive bias wholesale. The distinction is the reason
# it is acceptable at all, and it stops being true the moment this weight grows
# large enough to dominate.
#
# What it costs, and the guardrail that fixes the weight. The field is heavily
# outcome-loaded: it correlates -0.530 with goals conceded while on the pitch, MORE
# than SofaScore's own rating does (-0.320). So part of what it buys is not defensive
# reading but the scoreline, which the exposure term already models deliberately and
# with a cap. The weight is therefore set by the same guardrail: at 0.10 the defender
# vote correlates -0.552 with goals conceded, still under the -0.578 of the external
# sources; at 0.16 it overshoots them. Within that ceiling the gain is most of what
# is available — agreement on goalless defenders goes 0.493 -> 0.582, past SofaScore's
# own 0.566, and 0.10 is also where the curve flattens (+0.089 up to it, +0.018 after).
#
# OPERATIONAL RISK. Unlike every other feature this one cannot be rebuilt from
# anything else: if SofaScore renames or drops the field, defenders silently lose
# ~0.09 of correlation and nothing raises an alarm. ``_merge_defensive_value`` logs
# when coverage collapses, and a test pins the field name. Coverage measured on
# 25-26: 99.9% above 15 minutes, 84.6% below (shrinkage already mutes those votes),
# absent for unused subs — a missing value reads as 0.0, which is the population
# median, i.e. "an ordinary defensive game" rather than a penalty.
DEFENSIVE_VALUE_SOURCE = "defensiveValueNormalized"

# VOLUME / involvement — rescaled to PER-90 (density is the signal: 120 touches in 90'
# != 30 in 20'), with a floor so a short cameo isn't projected to 90'.
#
# THE WHOLE BLOCK WAS SCALED x0.8 on 2026-07-29. It was winning on breadth: 23
# features against the 7 of the shooting block, each small but almost all moving
# together in a dominant game (whoever touches many balls wins many duels, loses
# few, plays high up the pitch). Summed, that carried more weight than scoring —
# De Ketelaere's best match took +1.03 from volume against +1.27 from two goals,
# and a third of that volume edge came from things he did NOT do (zero duels lost,
# zero times dribbled past: a negative-weighted feature at zero pays, because the
# average player carries its malus). No per-feature transform can address that:
# compression tames ONE extreme value, it has no grip on the sum of many moderate
# ones. Only the block's total weight does. Measured: r improves on every role
# (DIF 0.622->0.627, CEN 0.692->0.699, ATT 0.757->0.768) and the attacker MAE
# falls 0.395->0.388. It does NOT fix the ceiling inversion (defenders and
# midfielders still reach 9.0 where attackers stop at 8.0) — that one is the
# per-role z-scoring, not the weights.
#
# Every key here must be one the provider actually supplies (see
# ``sofascore_adapter.KNOWN_FEATURE_KEYS``; enforced by a test). This table used to
# carry ``passes_into_box``, ``progressive_passes_completed``, ``progressive_carries``
# and ``pressures``, which contributed exactly zero while reading as if progression
# and pressing were rewarded, so they were removed.
#
# CORRECTION (2026-07-29): that removal was right for three of the four and WRONG
# about carrying. SofaScore does not report passes into the box, progressive passes
# or pressures — but it does report the carry, under names nobody thought to look
# for: ``totalProgression``, ``ballCarriesCount``, ``progressiveBallCarriesCount``,
# ``totalBallCarriesDistance``, ``totalProgressiveBallCarriesDistance`` and
# ``bestBallCarryProgression``. They arrive on 15-45% of appearances (the provider
# omits the field rather than sending a zero) and land in
# ``MatchAppearance.raw_stats`` like everything else, so no re-scrape is needed to
# start using them. Carrying the ball forward is currently worth nothing in this
# model, and that is an omission we chose by accident, not on purpose. Measured
# against the human pagella the raw signal is thin on its own (``totalProgression``
# correlates 0.069 with it for defenders), which is why it has not simply been
# added: it needs its own calibration, not a weight guessed here.
PER90_WEIGHTS = {
    "dribbles_won": 0.0252,
    "duels_won": 0.0632,
    "duels_lost": -0.0631,          # the losing side of the contests we reward
    "dribbled_past": -0.0341,       # subset of duels_lost: beaten one-on-one is worse
    "passes_opp_half": 0.0548,      # progression: a pass in the opponent half is worth more
    "aerials_won": 0.0318,
    "aerials_lost": -0.0314,
    "tackles_won": 0.0214,          # a committed, deliberate intervention
    "was_fouled": 0.0117,           # an opponent had to stop you illegally
    "long_balls_completed": 0.0331,
    "crosses_completed": 0.0222,    # (reactivated by the hand-tuning)
    "touches_in_box": 0.0072,
    "interceptions": 0.026,
    "ball_recoveries": 0.0187,
    "blocks": 0.0116,
    "clearances": 0.0226,
    # passes_completed/touches held at 0.01: the earlier kurtosis-gradient nudge
    # (0.01 -> 0.02, with passes_opp_half 0.05 -> 0.06) flattened the distribution
    # toward Statistico's, but that low kurtosis is a symptom of Statistico being
    # result-driven, not a target — and the possession up-weight worked against
    # tempering high votes in defeats (Koopmeiners). Reverted; result-awareness is
    # instead carried by the (stronger) result mitigation below.
    "passes_completed": 0.0142,
    "touches": 0.0125,
    "errors_bad_passes": -0.0189,
    "errors_dispossessed": -0.0163,
    "errors_miscontrols": -0.019,
    "errors_fouls_committed": -0.0114,
    # dribbles_won(+) / dribbles_attempted(-) is a deliberate RATE pairing, like
    # duels_won/duels_lost: the negative on the superset makes the net contribution
    # turn negative below a ~36% success rate, so many failed take-ons cost even if a
    # few come off. NOT here: possession_lost (possessionLostCtrl) — it is 79% the
    # SAME losses already penalised by errors_dispossessed/miscontrols/bad_passes
    # (same sign, no rate counterpart), so it just doubled the malus on one event and
    # made those weights un-interpretable. Raise the specific errors_* to weigh ball
    # loss more, not this aggregate.
    "dribbles_attempted": -0.0194,
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

# --- Derived features ---------------------------------------------------------
# The execution term has to be built BEFORE the compression (see the shooting-block
# note above): once each part is transformed separately it can no longer be
# recombined. A woodwork strike gets no xGOT from the provider, so its execution
# merit — a shot that beat the keeper and hit the frame — would read as zero; it is
# credited here at the rate our own weights gave it relative to an xGOT unit.
SGA_POST_WOODWORK = 0.73
DERIVED_FEATURES = ("sga_post",)
# Weighted features that are neither zone features nor computed: folded in from
# elsewhere in the DB (see ``_merge_defensive_value``). Kept apart from
# DERIVED_FEATURES so "computed from other features" keeps meaning that.
MERGED_FEATURES = ("defensive_value",)
# Inputs consumed by ``derived_features`` that carry no weight of their own and so
# would otherwise never be fetched.
DERIVED_INPUTS = frozenset({"xg_on_target", "shots_post"})


def derived_features(totals: dict) -> dict:
    """{feature: value} for features computed FROM the provider totals, not stored.

    ``sga_post`` = xGOT − xG + woodwork: the shot's post-strike value over its
    pre-strike value, i.e. what the player added by hitting it the way he did. It is
    legitimately NEGATIVE for a wasteful shooter (five shots off target: xGOT 0, xG
    0.4) and the compression preserves that sign."""
    return {
        "sga_post": (totals.get("xg_on_target", 0.0) - totals.get("xg_shots", 0.0)
                     + SGA_POST_WOODWORK * totals.get("shots_post", 0.0)),
    }

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
    "gk_goals_prevented": 1.8842,   # SIGNED: negative when he underperforms the xG faced
    "gk_penalty_saves": 0.1672,
    "errors_led_to_goal": -0.2962,
    # Same event, same anchor as the outfield channel (which already shares the
    # -1.50 above). Calibrated on outfield players — keeper errors of this kind
    # are too rare in one season to fit separately — so it rides on the symmetry,
    # not on its own evidence.
    "errors_led_to_shot": -0.102,
}
GK_PER90_WEIGHTS = {
    "gk_saves_inside_box": 0.2486,
    "gk_saves": 0.1356,
    "gk_high_claims": 0.1315,       # command of the area
    "gk_sweeper": 0.0848,           # sweeper-keeper interventions
    "gk_punches": 0.0528,
    "gk_crosses_not_claimed": -0.0535,
    "errors_bad_passes": -0.103,
    "passes_completed": 0.0085,     # distribution, marginal
}
GK_WEIGHTS = {**GK_TOTAL_WEIGHTS, **GK_PER90_WEIGHTS}

# --- Tail compression ---------------------------------------------------------
# Applied to EVERY feature, in units of that feature's own spread (see
# ``_feature_z``). The shape is
#
#     f(u) = K · log(1 + |u| / K) · sign(u)
#
# which is the identity to first order at the origin (f'(0) = 1) and logarithmic
# far out: it shortens tails WITHOUT the defect of the √ it replaces, whose
# derivative is infinite at zero and therefore inflated every small value — the
# known problem with √ on quantities living in [0, 1] like xG and xGOT, where a
# 0.02 chance was magnified to 0.14. Being odd, it also handles the features that
# are legitimately negative (goals prevented, and now sga_post) without the special
# case ``_compress_signed`` used to carry.
#
# K is in SIGMA units, and that is the whole point of doing it after the first
# standardisation: compression starts at the same distance from the mean for every
# feature. Applied to raw values instead — the literal 2·log(1 + x/2) — the same
# constant means 0.09σ for touches and 18σ for xA, so it would crush the
# well-behaved volume features and leave the fat-tailed ones untouched, which is
# backwards. Measured over the season, K = 2 takes xA's maximum from 13.1σ to 6.6σ
# and its excess kurtosis from 16.0 to 4.5, while touches moves only 4.5σ -> 3.2σ.
# Rare binary events (an error leading to a goal) are untouched by construction, as
# they should be: nothing about a 1-in-70 event is a "tail" to be tamed.
#
# Lowered 2.0 -> 1.0 on 2026-07-29. The effect sits inside the noise on agreement
# (defender r -0.004, midfielder -0.003, attacker +0.005) but moves the one thing
# it can move in the right direction: the attackers' share of votes >= 8 falls from
# 3.5% to 2.9% against 1.2% externally, and their excess kurtosis from +0.3 to +0.1.
# It cannot do more, and it is worth knowing why. The >= 8 tail is 100% goalscorers,
# and for an attacker who scored exactly once our mean matches fantacalcio's to two
# decimals (7.01 against 7.03) while our spread is 0.55 against their 0.33 — they
# put 187 of 265 such matches on exactly 7.0 and stop, we read the rest of the game
# on top. Closing that gap would mean compressing the performance reading
# CONDITIONAL on the goal, i.e. converging on "a goal is worth 7 whatever else
# happened" — the outcome-driven behaviour this model deliberately avoids. The
# residual is therefore a choice, not a defect.
COMPRESS_K = 1.0

# --- One spread for every outfield role ---------------------------------------
# Each role keeps its own CENTRE (so a 6 means the same thing everywhere, which the
# pagelle agree with: their per-role means are 5.95 / 6.05 / 6.10) but they SHARE
# one spread instead of each being normalised to unit variance.
#
# Normalising per role looks neutral and is not: it makes the same event worth more
# to whoever's peers never do it. A goal adds roughly the same absolute amount to
# any index, but dividing by the role's own spread (DIF 0.368, CEN 0.418, ATT 0.478)
# made it 1.30σ for a defender and 1.00σ for an attacker — so we paid +1.34 for a
# defender's goal against fantacalcio's +1.02, and +0.96 for an attacker's against
# their +1.23. Exactly inverted. And self-reinforcing: an attacker scores in 23% of
# his matches against a defender's 4%, so goals are already inside the attacker's
# spread — the very spread that then divides them.
#
# The pagelle do the opposite: same centre for everyone, but a MUCH wider scale for
# attackers (their vote std is 0.606 / 0.614 / 0.752 for DIF / CEN / ATT). They
# treat a goal as an absolute value, not one relative to the role. Sharing the
# spread reproduces that almost exactly (0.560 / 0.614 / 0.708) because the index's
# own per-role dispersion turns out to be the right one — forcing each role to unit
# variance was destroying real signal.
#
# Measured: defender max 9.0 -> 8.5 and votes >= 8 from 1.2% to 0.9% (externally
# 0.2%), defender MAE 0.407 -> 0.388, attacker r 0.768 -> 0.770, and the goal
# premium flattens toward the external ordering. KNOWN COST: attackers reach >= 8 in
# 3.5% of matches against 1.2% externally — we go from too few to too many. The
# midfielder ceiling (9.0) is untouched by this and remains open: it is a breadth
# effect (a goal AND high volume in the same match), not a spread one.
POOLED_ROLE_SPREAD = True

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

# --- Exposure: danger conceded where AND while a player was on the pitch ------
# An outfielder's index is otherwise built from clearances, interceptions, blocks
# and duels — the VOLUME of defending. Under siege those all rise while the team
# concedes, so the two signals cancel and the vote ends up blind to the outcome.
#
# The fix is deliberately NOT "the team conceded, so the back four all drop". That
# is collective punishment, and it is demonstrably what the external sources do:
# among defenders with no recorded individual error at all, their vote still falls
# from 6.28 to 5.12 as the team goes from 0 to 4 conceded. Instead each conceded
# shot is charged to the players who were IN ITS ZONE, and only to them.
#
# Three decisions, each measured against the external base votes over a full
# season (agreement of the DEFENDER vote with fantacalcio's Statistico):
#
# * WHAT is charged. The first version charged raw xG, which barely moved the
#   vote (r 0.510 without the term, 0.506 with it): a defensive error that yields
#   a low-xG goal is invisible, and most conceded xG never becomes anything. What
#   works is the OUTCOME — but charging goals alone erases every error the keeper
#   bailed out, and 44% of the xGOT conceded in a season dies in a save. So the
#   charge splits a FIXED budget between the two (EXPOSURE_LAMBDA):
#       amount = λ·outcome + (1−λ)·xGOT
#   λ=0.5 is a true half-and-half because xGOT is calibrated on goals (940 vs 922
#   over 25-26), so the two halves carry the same total mass and no goal is
#   counted twice. A saved shot is charged its own xGOT: 8% of an average goal at
#   the median, 31% at the 90th percentile, 51% at the 99th — the weak shot costs
#   nothing, the sitter the keeper had to fly for costs half a goal. Woodwork gets
#   no xGOT from the provider, so it is charged on the OUTCOME side at the rate
#   our own attacking weights already assign it (shots_post / shots_goal).
#   This also composes cleanly with the keeper channel, which scores him on
#   xGOT-faced MINUS goals: the defence answers for the danger allowed, the keeper
#   for the part he failed to stop, and the two sum to the goals conceded.
#
# * TO WHOM. Presence is the player's heatmap share of the zone (see
#   ``_zone_presence``), but taken RELATIVE to his team-mates on the pitch at that
#   minute rather than absolute. Absolute presence answers "what fraction of MY
#   match did I spend there", which dilutes exactly the ball-playing defender we
#   want to charge — Bastoni had 2.4% of his heatmap in the zone all of Verona's
#   shots came from — and hands the danger to whoever lives in the box, i.e. the
#   keeper. The relative share instead sums to 1 over the outfielders on the pitch,
#   so every shot is distributed in full and no more than in full. The keeper is
#   excluded from the split: his own channel already answers for the save.
#   EXPOSURE_KERNEL blurs the presence into the adjacent zones, so a shot landing
#   just across a grid boundary is not charged to the wrong man.
#
# * TO WHICH ROLES. Every outfield role, attackers included. They are the ones who
#   lost the ball or failed to track back, and exempting them was an asymmetry with
#   no argument behind it: they were computing a share and not paying it.
#
# Result: the defender vote goes from r 0.517 to 0.621 against the Statistico
# (MAE 0.448 -> 0.406), and its correlation with goals conceded while on the pitch
# from -0.23 to -0.53 — against -0.578 for the Statistico itself. It stays a
# reading of the individual, not of the scoreline: 43% of the term's variance
# still separates defenders of the SAME back line (a purely collective measure
# has 4%).
#
# EXPOSURE_WEIGHT is the knee of the curve AND the last value that stays under the
# external sources' own dependence on the scoreline; past it both criteria break
# together (at 1.5 the correlation with goals conceded overshoots the Statistico's,
# at 2.0 the term is 70% of the defender index and no defender can earn above 8.5).
# Applied LINEARLY, unlike the √-compressed volume block: it is already a small
# goal-equivalent figure, not a fat-tailed count.
EXPOSURE_WEIGHT = 0.1594    # same unit as every other weight: index points per 1σ
EXPOSURE_KEY = "_exposure"  # its name in the scales/breakdowns (it is not a provider stat)
EXPOSURE_LAMBDA = 0.50      # share of the charge carried by the OUTCOME; 1−λ by xGOT
EXPOSURE_KERNEL = 0.30      # weight of the four adjacent zones in the presence
# A woodwork strike carries no provider xGOT, so it is charged on the outcome side
# at the value our OWN attacking weights give it relative to a goal — the same
# event, read the same way from both ends of the pitch.
EXPOSURE_POST_OUTCOME = SGA_POST_WOODWORK
_NEIGHBOURS = ((-1, 0), (1, 0), (0, -1), (0, 1))

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


def _compress(u: float) -> float:
    """Odd, unit-slope-at-zero, log-tailed compression (see COMPRESS_K).

    ``u`` is already in units of the feature's own standard deviation, so the same
    constant means the same thing for every feature. f(0)=0, f'(0)=1 — a small value
    passes through essentially untouched, which is exactly what the √ it replaces
    got wrong."""
    if u == 0:
        return 0.0
    return math.copysign(COMPRESS_K * math.log1p(abs(u) / COMPRESS_K), u)


def raw_feature_values(totals: dict, minutes: int, exposure: float = 0.0,
                       *, gk: bool = False) -> dict:
    """{feature: value} in the units the weights are calibrated against.

    One place decides what a feature's value IS — per-90 scaling for the volume
    block, derived features folded in, exposure included as a feature so it is
    standardised like everything else. Everything downstream (the index, the
    explanation, the tuner, the calibration) reads from here, so they cannot drift
    apart."""
    if minutes <= 0:
        return {}
    total_w = GK_TOTAL_WEIGHTS if gk else TOTAL_WEIGHTS
    per90_w = GK_PER90_WEIGHTS if gk else PER90_WEIGHTS
    scale = 90.0 / max(minutes, EXTRAP_FLOOR_MINUTES)
    derived = {} if gk else derived_features(totals)
    out = {k: derived.get(k, totals.get(k, 0.0)) for k in total_w}
    out.update({k: totals.get(k, 0.0) * scale for k in per90_w})
    if not gk:
        out[EXPOSURE_KEY] = exposure
    return out


def _feature_z(key: str, value: float, scales: dict) -> float:
    """Standardise -> compress -> standardise again.

    The first division puts every feature on a common σ scale (so COMPRESS_K means
    the same distance from the mean everywhere, and so a WEIGHT means the same
    thing everywhere); the compression shortens the tail; the second division
    restores unit spread, which is what makes a weight literally "the contribution
    of one sigma". Both σ come from the frozen calibration, never from the match
    being scored."""
    s = scales.get(key)
    if not s or not s.get("sigma_raw") or not s.get("sigma_z"):
        return 0.0
    return _compress(value / s["sigma_raw"]) / s["sigma_z"]


def index_for_role(role: str, totals: dict, minutes: int, exposure: float = 0.0,
                   scales: dict | None = None) -> float:
    """Weighted performance index for a player's match.

    Goalkeepers go through their own feature channel and weights; every outfield
    role shares one weight vector (the roles differ only in the mean/σ the index is
    z-scored against). ``exposure`` — the danger the opponent created in the zones
    this player occupied — applies to every outfield role, an attacker included,
    and to none of the keeper's, whose own channel already answers for what
    reached him.
    """
    if minutes <= 0:
        return 0.0
    gk = role == Player.ROLE_GK
    weights = GK_WEIGHTS if gk else WEIGHTS
    scales = feature_scales(gk=gk) if scales is None else scales
    values = raw_feature_values(totals, minutes, exposure, gk=gk)
    idx = sum(w * _feature_z(k, values.get(k, 0.0), scales)
              for k, w in weights.items() if w)
    if not gk:
        idx -= EXPOSURE_WEIGHT * _feature_z(EXPOSURE_KEY,
                                            values.get(EXPOSURE_KEY, 0.0), scales)
    return idx


def _per_match_player_totals(match_ids):
    """{(match_id, player_id): {feature_key: total_over_zones}} for sofascore.

    Fetches the union of the outfield AND goalkeeper weight keys: restricting it to
    the outfield set silently starved the GK index of every keeper feature, leaving
    it driven by inaccurate long balls alone (good sweeper-keepers ranked worst).
    """
    rows = (PlayerZoneFeature.objects
            .filter(match_id__in=match_ids, provider=PROVIDER_SOFASCORE,
                    feature_key__in=sorted((set(WEIGHTS) | set(GK_WEIGHTS)
                                            | DERIVED_INPUTS)
                                           - set(DERIVED_FEATURES)
                                           - set(MERGED_FEATURES)))
            .values("match_id", "player_id", "feature_key")
            .annotate(v=Sum("value")))
    out = defaultdict(dict)
    for r in rows:
        out[(r["match_id"], r["player_id"])][r["feature_key"]] = r["v"]
    _merge_shot_detail(out, match_ids)
    _merge_defensive_value(out, match_ids)
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


def _merge_defensive_value(out: dict, match_ids) -> None:
    """Fold the provider's defensive value into the per-player totals.

    It lives in ``MatchAppearance.raw_stats``, not in the zone features, and it is
    read from there rather than being spread over the heatmap at import time. That
    split is deliberate: the zone distribution exists for the AURA mode's zone
    duels, and this feature belongs to the classic channel only — spreading a
    normalised scalar across zones and summing it back would be a round trip for
    nothing, and would need the whole season re-imported to boot.

    Absent for a player means 0.0, the population median: an ordinary defensive
    game, not a punishment (see the DEFENSIVE_VALUE_SOURCE note).
    """
    rows = list(MatchAppearance.objects.filter(match_id__in=match_ids)
                .values_list("match_id", "player_id", "minutes_played", "raw_stats"))
    seen = 0
    eligible = 0
    for mid, pid, mins, raw in rows:
        if (mins or 0) >= 15:
            eligible += 1
        value = (raw or {}).get(DEFENSIVE_VALUE_SOURCE)
        if value is None:
            continue
        seen += 1
        out[(mid, pid)]["defensive_value"] = float(value)
    # The field is a provider proxy we cannot rebuild: if it stops arriving the
    # defender vote quietly degrades, so say so rather than scoring on zeroes.
    if eligible and seen / eligible < 0.5:
        log.warning("%s present on only %d of %d appearances over 15 minutes — the "
                    "defensive proxy is degraded and defender votes with it.",
                    DEFENSIVE_VALUE_SOURCE, seen, eligible)


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


def _zone_presence(match_ids) -> dict:
    """{(match_id, player_id): {(col, row): share}}, shares summing to 1.

    The provider gives a positional heatmap per player, and the importer spreads
    his touch total over the zones in proportion to it — so dividing the per-zone
    touches by their total recovers the heatmap itself: what fraction of his time
    on the pitch he spent in each zone. It is a POSITIONAL measure, not a
    ball-contact one, which is what charging conceded danger requires (a defender
    beaten in his own box touches nothing at all).
    """
    zones: dict[tuple, dict] = defaultdict(dict)
    for mid, pid, zk, v in (PlayerZoneFeature.objects
                            .filter(match_id__in=match_ids, provider=PROVIDER_SOFASCORE,
                                    feature_key="touches")
                            .values_list("match_id", "player_id", "zone_key")
                            .annotate(v=Sum("value"))
                            .values_list("match_id", "player_id", "zone_key", "v")):
        _, col, row = zk.split("_")
        zones[(mid, pid)][(int(col), int(row))] = v
    out = {}
    for key, z in zones.items():
        total = sum(z.values())
        if total > 0:
            out[key] = {k: v / total for k, v in z.items()}
    return out


def _presence_at(zones: dict, zone: tuple) -> float:
    """Presence in a zone, blurred into its four neighbours by EXPOSURE_KERNEL.

    The 5x4 grid is coarse: a shot two metres the other side of a boundary would
    otherwise be charged entirely to the next man along. The blur is deliberately
    NOT normalised — it is a similarity kernel, and the relative share it feeds
    divides it out anyway."""
    v = zones.get(zone, 0.0)
    if EXPOSURE_KERNEL:
        v += EXPOSURE_KERNEL * sum(zones.get((zone[0] + dc, zone[1] + dr), 0.0)
                                   for dc, dr in _NEIGHBOURS)
    return v


def _charge_of_shot(is_goal: bool, xgot, shot_type: str) -> float:
    """Goal-equivalent danger a single conceded shot puts on the defence.

    ``λ·outcome + (1−λ)·xGOT`` (see EXPOSURE_LAMBDA). Off-target and blocked shots
    carry no xGOT and no outcome, so they charge exactly nothing — the defence
    dealt with them."""
    outcome = 1.0 if is_goal else (EXPOSURE_POST_OUTCOME if shot_type == "post" else 0.0)
    return EXPOSURE_LAMBDA * outcome + (1.0 - EXPOSURE_LAMBDA) * (xgot or 0.0)


def defensive_exposure(match_ids, minutes: dict) -> dict:
    """{(match_id, player_id): danger conceded where AND WHILE this player played}.

    Each conceded shot carries a charge (``_charge_of_shot``) that is split across
    the outfielders on the pitch in proportion to their presence in the zone it
    came from — so a shot is always distributed in full, and a player answers for
    the danger born where he was standing, not for his team's scoreline. See the
    EXPOSURE_* block for what is charged, to whom, and why.

    Two frames have to line up, and both are verified rather than assumed:

    * the two teams' zone grids are a 180 degree rotation of each other, so an
      attacking zone (col, row) is (4-col, 3-row) for the defence. Attributing
      with the row mirrored puts more conceded danger on the defenders who
      actually committed a shot-conceding error (1.21x vs 1.14x unmirrored),
      matching the rotation independently established for the shot map;
    * only shots struck while he was on the pitch count, for the shooter's side
      AND for every team-mate the charge is split with. Scaling a whole-match
      total by minutes played, which is what this did first, is unbiased on
      average (-0.005) yet misattributes more than 20 percentage points of a
      match's danger for one defender in seven. A defender must not answer for a
      goal conceded after he came off.

    Penalties are skipped outright: zone presence says nothing about who stands
    near the spot, and the foul itself is already charged to whoever conceded it
    (``penalties_conceded``).
    """
    conceded: dict[tuple, list] = defaultdict(list)
    for mid, side, minute, zk, xgot, is_goal, situation, shot_type in (
            MatchShot.objects
            .filter(match_id__in=match_ids, provider=PROVIDER_SOFASCORE)
            .values_list("match_id", "team_side", "minute", "zone_key", "xgot",
                         "is_goal", "situation", "shot_type")):
        if situation == "penalty":
            continue
        charge = _charge_of_shot(is_goal, xgot, shot_type)
        if charge <= 0:
            continue
        _, col, row = zk.split("_")
        # stored already mirrored into the DEFENDING side's frame
        conceded[(mid, side)].append((minute, (4 - int(col), 3 - int(row)), charge))
    if not conceded:
        return {}

    appearances = {(a["match_id"], a["player_id"]): (a["side"], a["is_starter"])
                   for a in MatchAppearance.objects.filter(match_id__in=match_ids)
                   .values("match_id", "player_id", "side", "is_starter")}
    presence = _zone_presence(match_ids)
    windows = on_pitch_windows(match_ids, minutes, appearances)
    # The keeper is excluded from the split, not merely spared the charge: his
    # heatmap sits entirely in the zone the danger arrives in, so leaving him in
    # would swallow the share the defenders in front of him should carry.
    keepers = set(Player.objects.filter(is_goalkeeper=True).values_list("id", flat=True))
    keepers |= {pid for pid, role in current_role_map().items() if role == Player.ROLE_GK}

    # who can be charged, per (match, side), with their window and presence map
    squads: dict[tuple, list] = defaultdict(list)
    for key, zones in presence.items():
        mid, pid = key
        if pid in keepers:
            continue
        side, is_starter = appearances.get(key, (None, False))
        if not side:
            continue
        lo, hi = windows.get(key, _fallback_window(minutes.get(key, 0), is_starter))
        squads[(mid, side)].append((pid, lo, hi, zones))

    opposite = {"home": "away", "away": "home"}
    out: dict = {}
    for (mid, shooting_side), shots in conceded.items():
        defending = opposite.get(shooting_side)
        squad = squads.get((mid, defending))
        if not squad:
            continue
        for minute, zone, charge in shots:
            on_pitch = [(pid, _presence_at(zones, zone)) for pid, lo, hi, zones in squad
                        if minute is None or lo <= minute <= hi]
            total = sum(v for _pid, v in on_pitch)
            if total <= 0:
                continue
            for pid, v in on_pitch:
                if v:
                    out[(mid, pid)] = out.get((mid, pid), 0.0) + v / total * charge
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


def _reference_population(competition_season_id: int):
    """[(role, totals, minutes, exposure)] — the games that define every calibration.

    One definition, used by the feature scales, the role reference and the
    explanation's role averages alike: a drifting population between them would put
    the vote and its justification on different scales."""
    match_ids = list(Match.objects
                     .filter(competition_season_id=competition_season_id)
                     .values_list("id", flat=True))
    totals = _per_match_player_totals(match_ids)
    minutes = _minutes_map(match_ids)
    exposure = defensive_exposure(match_ids, minutes)
    roles = current_role_map(only_declared=True)
    for (mid, pid), feats in totals.items():
        role = roles.get(pid)
        if not role:
            continue
        mins = minutes.get((mid, pid), 0)
        if mins < MIN_MINUTES_REFERENCE or not is_rated(mins, feats):
            continue
        yield role, feats, mins, exposure.get((mid, pid), 0.0)


def build_feature_scales(competition_season_id: int) -> dict:
    """{"outfield"|"gk": {feature: {"sigma_raw", "sigma_z"}}} over a season.

    The two spreads the standardisation needs (see ``_feature_z``), frozen next to
    the role reference so a weight keeps its meaning between recalibrations. Two
    passes are unavoidable: the second σ is the spread of the COMPRESSED variable,
    which cannot be known before the first σ has fixed the compression scale.
    """
    raw: dict[str, dict[str, list]] = {"outfield": defaultdict(list), "gk": defaultdict(list)}
    for role, feats, mins, exp in _reference_population(competition_season_id):
        gk = role == Player.ROLE_GK
        bucket = raw["gk" if gk else "outfield"]
        for k, v in raw_feature_values(feats, mins, exp, gk=gk).items():
            bucket[k].append(v)

    def _sd(values, centre=0.0):
        n = len(values)
        if n < 2:
            return 0.0
        m = sum(values) / n
        return math.sqrt(sum((x - m) ** 2 for x in values) / n)

    out: dict[str, dict] = {}
    for channel, cols in raw.items():
        scales = {}
        for k, values in cols.items():
            s_raw = _sd(values)
            if not s_raw:
                continue  # a feature with no spread carries no information
            s_z = _sd([_compress(v / s_raw) for v in values])
            if not s_z:
                continue
            scales[k] = {"sigma_raw": s_raw, "sigma_z": s_z, "n": len(values)}
        out[channel] = scales
    return out


_scales_cache: dict | None = None


def feature_scales(*, gk: bool = False) -> dict:
    """The frozen per-feature spreads for a channel (see ``build_feature_scales``).

    Read from the calibration file. Missing (a fresh checkout, a test database) is
    not fatal: the weights simply have nothing to standardise against, so every
    feature returns 0 and the vote falls back to the role centre — loudly wrong
    rather than quietly rescaled, which is the failure mode we want."""
    global _scales_cache
    if _scales_cache is None:
        from vfoot.services.vote_reference import fixed_feature_scales
        _scales_cache = fixed_feature_scales() or {}
    return _scales_cache.get("gk" if gk else "outfield", {})


def clear_scales_cache() -> None:
    """Drop the in-process copy (after a recalibration, or in tests)."""
    global _scales_cache
    _scales_cache = None


def build_reference(competition_season_id: int, *,
                    pooled_std: bool = POOLED_ROLE_SPREAD,
                    scales: dict | None = None) -> dict:
    """Per-role (mean, std) of the performance index over a season.

    Returns {role: {"mean": m, "std": s, "n": n}}. With ``pooled_std`` every
    outfield role keeps its own centre but shares ONE spread — see
    POOLED_ROLE_SPREAD for why that is the default.

    ``scales`` must be the ones the votes will be scored with; the calibration
    command passes the freshly built set, since the frozen file is still the old one
    at that point.
    """
    samples = defaultdict(list)  # role -> [performance index]
    for role, feats, mins, exp in _reference_population(competition_season_id):
        # GKs get their own index AND their own role bucket, so they are z-scored
        # WITHIN the role: the keeper scale is self-calibrating like every other.
        chan = (scales or {}).get("gk" if role == Player.ROLE_GK else "outfield")
        samples[role].append(index_for_role(role, feats, mins, exp, chan))

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
        # OUTFIELD ONLY, and this is not a detail: the keeper index lives on its own
        # scale entirely (spread ~2.2 against ~0.4), so pooling him in would blow the
        # shared spread up by a factor of five and flatten every outfield vote toward
        # 6. He keeps his own, as he keeps his own feature channel.
        residuals = [x - ref[role]["mean"] for role, vals in samples.items()
                     if role != Player.ROLE_GK for x in vals]
        if residuals:
            m = sum(residuals) / len(residuals)
            pooled = math.sqrt(sum((r - m) ** 2 for r in residuals) / len(residuals))
            for role in ref:
                if role != Player.ROLE_GK:
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
