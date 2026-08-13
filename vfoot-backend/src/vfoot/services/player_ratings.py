"""Player VALUE signals for the championship pool (the "listone").

A player's value is an average voto puro. Which season it comes from must EVOLVE
with the calendar:

  * pre-season / early rounds -> last season's average (the only evidence);
  * as the current season progresses -> current form progressively takes over.

So the value is a Bayesian blend, weight ``n/(n+K)`` on the current season's rated
appearances, shrinking toward last season's average (the prior). At n=0 it IS last
season's value; by n=K it is half current form; late season it is essentially
current form. A player with NO history in either season has no value (None) —
typically a newcomer who hasn't played yet.

Expensive aggregates are cached under a DATA VERSION key (match count + last data
check of the season) AND the scoring fingerprint, so a cached value is reused
across restarts and workers, invalidates itself as soon as new matches are
finalized, and stops being served the moment the model that produced it changes.

That cache is a per-machine directory (``.django_cache``, gitignored, and in
production deliberately outside the checkout): it is a speed-up, never a source.
The SNAPSHOT below is the source of last resort — see ``snapshot_ratings``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.cache import cache

from realdata.models import CompetitionSeason, Match, Player, PlayerZoneFeature
from vfoot.services.classic_pagella import data_version, get_reference
from vfoot.services.vote_reference import scoring_fingerprint
from vfoot.services.classic_rating import PROVIDER_SOFASCORE, voto_puro_for_match

log = logging.getLogger(__name__)

# Versioned in the repo next to the code, exactly like vote_reference.json, and for
# the same reason: it is a computed artefact that has to travel with the SOURCE
# rather than with the database.
SNAPSHOT_PATH = Path(settings.BASE_DIR) / "vfoot" / "data" / "player_ratings_snapshot.json"

# Bumped when the SHAPE of the file changes. Version 1 keyed seasons and players on
# the primary keys of the database that produced it, and shipping it to a different
# database is what this number exists to prevent — see ``_portable_key``. A file
# whose format is not this one is ignored rather than interpreted: reading version 1
# with version 2's rules would be exactly the silent misattribution being fixed.
SNAPSHOT_FORMAT = 2

# Rated appearances at which current form and last season's value weigh the same.
SHRINKAGE_APPEARANCES = 5

# A season average built on 1-2 games is nearly meaningless: one great night would
# otherwise top the whole listone. Shrink each season average toward the neutral 6
# in proportion to the evidence — n/(n+K) — so a regular's average survives almost
# intact while a cameo regresses to the middle. Same Bayesian idea already used for
# minutes inside classic_rating.
SEASON_SHRINKAGE_N = 5
NEUTRAL_VOTE = 6.0


def _shrunk(avg: float, n: int) -> float:
    """Season average pulled toward the neutral vote when it rests on few games."""
    return (n * avg + SEASON_SHRINKAGE_N * NEUTRAL_VOTE) / (n + SEASON_SHRINKAGE_N)

VALUE_CURRENT = "corrente"
VALUE_PREVIOUS = "precedente"
VALUE_MIXED = "misto"
VALUE_ESTIMATED = "stimato"

# An estimate inferred from a transfer valuation is far weaker evidence than a
# measured performance, so it is kept inside the central band: it must place a
# newcomer sensibly in the list, never crown him above proven top performers.
VOTE_MIN_EST, VOTE_MAX_EST = 5.0, 6.6


def _compute_season_player_ratings(cs_id: int) -> dict:
    """Average voto puro per player over a season — THE SAME voto puro the pagella
    shows, because it is literally the same function.

    This used to reimplement the scoring inline, and reimplementing it meant
    drifting from it. Four divergences had accumulated, none of them visible from
    the outside: the defensive exposure was not passed to the index at all (+0.157
    of a vote on defenders); the keeper's evidence damping was skipped, so a keeper
    who faced one shot was judged on it; the post-adjustments for sending-off, own
    goal, missed penalty and result mitigation were all missing; and the rated gate
    ignored the decisive-event override, so a scorer with few minutes was dropped
    here while the pagella rated him.

    The listone calls this value "la media del voto puro (la nostra pagella)", so
    anything other than the pagella's own number is a lie in the interface. Going
    through ``voto_puro_for_match`` costs about 3x (≈4s → ≈10s on a full Serie A
    season) because the per-match event queries no longer run in bulk — paid once
    per scoring fingerprint, behind the cache, and worth it to make the two paths
    incapable of disagreeing.
    """
    matches = list(Match.objects
                   .filter(competition_season_id=cs_id,
                           status=Match.STATUS_FINISHED))
    if not matches:
        return {}
    # Cheap probe before 380 scoring passes that would each find nothing: a slim
    # database (see export_dev_db) has no zone features, and the snapshot fallback
    # in season_player_ratings is what answers for it.
    if not PlayerZoneFeature.objects.filter(
            match_id__in=[m.id for m in matches],
            provider=PROVIDER_SOFASCORE).exists():
        return {}

    ref = get_reference(cs_id)
    agg: dict[int, list] = defaultdict(lambda: [0.0, 0])
    for match in matches:
        for row in voto_puro_for_match(match, ref):
            if row["voto_puro"] is None:
                continue
            a = agg[row["player_id"]]
            a[0] += row["voto_puro"]
            a[1] += 1
    return {pid: {"avg": round(s / n, 2), "n": n}
            for pid, (s, n) in agg.items() if n}


def _portable_key(obj) -> str:
    """``source:external_id`` — the identity of a season or a player OUTSIDE this
    database.

    The reason this function exists, and the bug it comes from. The snapshot used to
    key on ``CompetitionSeason.id`` and ``Player.id``, which are autoincrement
    surrogates: they mean something only in the database that assigned them. The
    development database carries the 2015-16 StatsBomb season and the simulated
    2026-27 one, production carries neither, so the SAME number is a different
    season and a different person on the two machines. Shipped to production on
    2026-08-11, the file said "season 2, player 957 = 6.66 over 35 appearances":
    locally that is Nico Paz in the concluded 2025-26 season, in production it is
    Matteo Barbini in the 2026-27 season, which had not kicked off. Every one of the
    211 ids that existed on both sides landed on the wrong player — not one match —
    and the remaining 343 vanished. Nothing in the interface could show it: the
    numbers were real votes, plausibly distributed, on real players.

    Provider ids are the opposite kind of identifier: they come from the source both
    databases imported, so 76457 is the 2025-26 Serie A everywhere, and a season or a
    player this database never imported simply fails to resolve — which is the
    behaviour we want, because an entry that cannot be resolved must disappear, never
    be handed to whoever happens to sit at that row number.
    """
    return f"{obj.external_source}:{obj.external_id}"


def _resolve_player_keys(keys) -> dict[str, int]:
    """{provider key: local Player.id} for the keys this database knows."""
    by_source: dict[str, list[str]] = defaultdict(list)
    for key in keys:
        source, _, external_id = str(key).partition(":")
        if source and external_id:
            by_source[source].append(external_id)
    out: dict[str, int] = {}
    for source, external_ids in by_source.items():
        for pid, external_id in (Player.objects
                                 .filter(external_source=source,
                                         external_id__in=external_ids)
                                 .values_list("id", "external_id")):
            out[f"{source}:{external_id}"] = pid
    return out


def _finished_match_count(cs_id: int) -> int:
    """How many matches of this season are played here — the count inside
    ``data_version``, which is the half of it that has to AGREE with the snapshot."""
    return Match.objects.filter(competition_season_id=cs_id,
                                status=Match.STATUS_FINISHED).count()


_snapshot_memo: dict | None = None
_snapshot_digest_memo: str | None = None


def clear_snapshot_cache() -> None:
    """Drop the in-process copy of the snapshot (after regenerating it, or in tests)."""
    global _snapshot_memo, _snapshot_digest_memo
    _snapshot_memo = None
    _snapshot_digest_memo = None


def _snapshot() -> dict:
    global _snapshot_memo
    if _snapshot_memo is None:
        try:
            _snapshot_memo = json.loads(SNAPSHOT_PATH.read_text())
        except (OSError, ValueError):
            # A missing or unreadable snapshot is not an error: a full database
            # never needs it.
            _snapshot_memo = {}
        if _snapshot_memo.get("format") != SNAPSHOT_FORMAT:
            # Not a warning at import time on purpose: a checkout without the file,
            # or with an older one, must keep working. It becomes a warning in
            # snapshot_ratings, where somebody is actually asking for the numbers.
            _snapshot_memo = {}
    return _snapshot_memo


def snapshot_digest() -> str:
    """Short hash of the snapshot FILE, for cache keys.

    The scoring fingerprint does not cover this: regenerating the snapshot without
    touching the model — which is exactly what fixing a wrong snapshot looks like —
    leaves every derived cache key identical, and the machines that had already
    served the old numbers keep serving them after the deploy. There is nothing to
    notice: the page is fast and the values are believable. Same failure the
    fingerprint was added to close, one layer further out.
    """
    global _snapshot_digest_memo
    if _snapshot_digest_memo is None:
        try:
            _snapshot_digest_memo = hashlib.sha256(
                SNAPSHOT_PATH.read_bytes()).hexdigest()[:12]
        except OSError:
            _snapshot_digest_memo = "-"
    return _snapshot_digest_memo


def snapshot_ratings(cs) -> dict:
    """Season ratings read from the versioned snapshot, or {} if it cannot serve.

    The reason this file exists rather than a database table: the slim copy from
    ``export_dev_db`` has no zone features, so a table shipped inside it would have
    to be populated BEFORE the export — which does nothing for the copies people
    already downloaded. Shipping the numbers with the SOURCE fixes those too, with
    a plain ``git pull`` and without replacing anyone's database (and the local
    leagues, rosters and test data in it). 9 KB of JSON against 54 MB of SQLite.

    Travelling with the source is exactly what makes it dangerous, and the three
    rules below are what make it safe:

      * it is a FALLBACK, never an override — a database that can compute always
        wins, so fresh data can never be masked by a stored figure;
      * it is addressed by PROVIDER identity, never by primary key, so a season or
        a player this database does not have simply does not resolve
        (``_portable_key``, and the misattribution it comes from);
      * it must describe THIS season's played data. A snapshot built on 380 matches
        answers only where 380 matches have been played. The season not started, the
        season half played, the season simulated somewhere else: all refused, because
        for them the honest listone is the empty one, and a plausible wrong one has
        no way of being noticed from the outside.

    A stale scoring fingerprint only warns: those numbers are the previous model's,
    which is a worse listone but still this season's football.
    """
    season = (_snapshot().get("seasons") or {}).get(_portable_key(cs))
    if not season:
        return {}

    played = _finished_match_count(cs.id)
    stored_played = int(str(season.get("data_version") or "0:-").split(":")[0])
    if played != stored_played:
        log.warning("player_ratings snapshot NOT used for %s: it was built on %d "
                    "played matches and this database has %d.",
                    cs, stored_played, played)
        return {}
    if season.get("data_version") != data_version(cs.id):
        # Same number of matches, different last check: the data is the same, the
        # stamp moved. Worth a line, not worth refusing the numbers.
        log.info("player_ratings snapshot for %s carries a different data stamp "
                 "(%s != %s).", cs, season.get("data_version"), data_version(cs.id))

    stored_fp = _snapshot().get("scoring_fingerprint")
    if stored_fp != scoring_fingerprint():
        log.warning("player_ratings snapshot was built by a different scoring model "
                    "(%s != %s); rebuild it with `manage.py "
                    "build_player_ratings_snapshot`.", stored_fp, scoring_fingerprint())

    ratings = season.get("ratings") or {}
    local_id = _resolve_player_keys(ratings)
    if len(local_id) < len(ratings):
        # Normal in itself — a squad list is never identical across databases — but
        # a collapse here means the two sides do not share a provider, and the
        # listone would come out mostly empty without a word.
        log.info("player_ratings snapshot for %s: %d of %d players resolved in this "
                 "database.", cs, len(local_id), len(ratings))
    return {local_id[key]: {"avg": avg, "n": n}
            for key, (avg, n) in ratings.items() if key in local_id}


def season_player_ratings(cs_id: int) -> dict:
    """{player_id: {"avg", "n"}} for a season, version-cached across restarts.

    Keyed on the SCORING fingerprint as well as the played-data version. Keying
    on the data alone was wrong in the one case that matters most: a CONCLUDED
    season never plays another match, so its key was frozen and the entry, stored
    with no expiry, outlived every change to the model. The 25-26 listone served
    ratings computed on 2026-07-21 straight through the v3 retuning — believable
    numbers, silently pre-tuning, and no way to tell from the outside.

    And on the snapshot FILE, for the same reason one layer out: a value that came
    from the file has to fall the moment the file changes, or correcting the file
    corrects nothing on the machines that already answered from it.
    """
    key = (f"vfoot:player_ratings:{cs_id}:{data_version(cs_id)}"
           f":{scoring_fingerprint()}:{snapshot_digest()}")
    hit = cache.get(key)
    if hit is not None:
        return hit
    data = _compute_season_player_ratings(cs_id)
    if not data:
        # Nothing computable: either a season this model cannot score at all, or a
        # database whose zone features were stripped. The snapshot answers the
        # second case and stays empty for the first.
        cs = CompetitionSeason.objects.filter(id=cs_id).first()
        data = snapshot_ratings(cs) if cs else {}
        if data:
            log.info("season %s scored from the versioned snapshot (%d players): "
                     "no zone features in this database.", cs_id, len(data))
    cache.set(key, data, None)
    return data


def previous_season_with_data(reference_cs) -> CompetitionSeason | None:
    """Most recent PRIOR edition of the same competition that has played data."""
    return (CompetitionSeason.objects
            .filter(competition=reference_cs.competition,
                    matches__status=Match.STATUS_FINISHED,
                    matches__appearances__isnull=False)
            .exclude(id=reference_cs.id)
            .filter(season__code__lt=reference_cs.season.code)
            .distinct()
            .order_by("-season__code")
            .first())


def fit_value_from_market(values: dict, market: dict):
    """Least-squares fit of the measured voto on log10(market value), using only
    players that have BOTH signals. Returns (a, b, r, n) for value ≈ a + b·log10(mv),
    or None when there is too little overlap to fit responsibly."""
    pts = [(math.log10(mv), values[pid]["value"])
           for pid, mv in market.items()
           if mv and mv > 0 and pid in values]
    n = len(pts)
    if n < 30:
        return None
    mx = sum(x for x, _ in pts) / n
    my = sum(y for _, y in pts) / n
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    syy = sum((y - my) ** 2 for _, y in pts)
    sxy = sum((x - mx) * (y - my) for x, y in pts)
    if sxx <= 0 or syy <= 0:
        return None
    b = sxy / sxx
    return (my - b * mx, b, sxy / math.sqrt(sxx * syy), n)


def player_values(reference_cs, market: dict | None = None):
    """Blended value per player for a league on ``reference_cs``.

    Each entry carries:
      * ``value``           – the MEASURED voto (None when he has never been rated);
      * ``estimated_value`` – a HOMOGENEOUS figure for every player: the measured
        voto when there is one, otherwise a voto ESTIMATED from the market value via
        a fit calibrated on players who have both. This is what lets the listone be
        a single ranked list instead of dumping newcomers at the bottom.
      * ``basis``           – corrente | precedente | misto | stimato.

    Returns (values, previous_season, fit) where ``fit`` describes the market→voto
    calibration (or None if it could not be fitted).
    """
    current = season_player_ratings(reference_cs.id)
    prev_cs = previous_season_with_data(reference_cs)
    previous = season_player_ratings(prev_cs.id) if prev_cs else {}

    out: dict[int, dict] = {}
    for pid in set(current) | set(previous):
        cur, pre = current.get(pid), previous.get(pid)
        n_cur = cur["n"] if cur else 0
        # Each season average is first shrunk by its own sample size, so a player
        # with a single brilliant game cannot outrank a season-long performer.
        cur_avg = _shrunk(cur["avg"], cur["n"]) if cur else None
        pre_avg = _shrunk(pre["avg"], pre["n"]) if pre else None
        if cur and pre:
            w = n_cur / (n_cur + SHRINKAGE_APPEARANCES)
            value, basis = w * cur_avg + (1 - w) * pre_avg, VALUE_MIXED
        elif cur:
            value, basis = cur_avg, VALUE_CURRENT
        else:
            value, basis = pre_avg, VALUE_PREVIOUS
        v = round(value, 2)
        out[pid] = {"value": v, "estimated_value": v, "n_cur": n_cur,
                    "n_prev": pre["n"] if pre else 0, "basis": basis}

    fit = fit_value_from_market(out, market or {})
    if fit and market:
        a, b, _r, _n = fit
        for pid, mv in market.items():
            if pid in out or not mv or mv <= 0:
                continue
            est = a + b * math.log10(mv)
            # An estimate must not out-rank measured performance at the extremes.
            est = max(VOTE_MIN_EST, min(VOTE_MAX_EST, est))
            out[pid] = {"value": None, "estimated_value": round(est, 2),
                        "n_cur": 0, "n_prev": 0, "basis": VALUE_ESTIMATED}
    return out, prev_cs, fit


def latest_market_values(player_ids, provider: str = "transfermarkt") -> dict:
    """{player_id: value_eur} from the most recent quote per player.

    External-source signal (provenanced in PlayerMarketValue), used ONLY as a
    secondary ordering hint for players with no on-pitch history — never as a
    substitute for a performance voto.
    """
    from realdata.models import PlayerMarketValue

    out: dict[int, int | None] = {}
    for pid, val in (PlayerMarketValue.objects
                     .filter(player_id__in=player_ids, provider=provider)
                     .order_by("player_id", "-as_of")
                     .values_list("player_id", "value_eur")):
        out.setdefault(pid, val)  # first row per player = latest quote
    return out
