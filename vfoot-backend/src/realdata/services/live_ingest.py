"""Wire the tick's live/finalization hooks to the egress + the OFFLINE import.

The tick (unprivileged, DB-aware) decides WHICH matches are due; this module warms
their cache through the root egress tunnel, then reads that warm cache with the
existing offline import. It never touches the network itself (the egress does), so
with the egress mocked it is fully testable.

Two entry points, and the difference between them is the match's lifecycle, not the
amount of work: ``live_round`` for a match being played (never promotes it),
``finalize`` after full time (the caller promotes it at the +8h confirmation). Both
take the same road; ``live_round`` takes the cheap version of it on the rounds that
are not the k-th.

Each entry point returns True on success and False when the egress was blocked /
unavailable — the caller then simply does NOT advance the match's state, so the
next tick retries (the on-disk cache makes a retry cheap).
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings

from realdata.services import egress_client
from realdata.services.calendar_sync import _kickoff, _map_status
from realdata.services.sofascore_adapter import (
    ingest_sofascore_matches, ingest_sofascore_season,
)
from realdata.services.sofascore_client import (
    SofaScoreBlocked, SofaScoreClient, SofaScoreError,
)


def year_for(match) -> str:
    """SofaScore year string for a match, e.g. Season.code '2026-2027' -> '26/27'."""
    code = (match.competition_season.season.code or "").replace(" ", "")
    parts = code.split("-")
    if len(parts) == 2 and len(parts[0]) == 4 and len(parts[1]) == 4:
        return f"{parts[0][2:]}/{parts[1][2:]}"
    return code


def _cache_dir() -> Path:
    return Path(settings.VFOOT_SOFASCORE_CACHE)


def _cached_event(event_id: str) -> dict | None:
    """The light /event/{id} the egress warmed, as a plain dict (or None)."""
    p = _cache_dir() / f"api_v1_event_{event_id}.json"
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    return data.get("event") if isinstance(data, dict) else None


def _apply_status(match, event: dict) -> list[str]:
    """Update the match's lifecycle/score/kickoff from a fetched event. Reuses the
    calendar-sync mapping. Returns the changed field names."""
    fields: list[str] = []
    new_status = _map_status(event)
    if match.status != new_status:
        match.status = new_status
        fields.append("status")
    hg = (event.get("homeScore") or {}).get("current")
    ag = (event.get("awayScore") or {}).get("current")
    if match.home_goals != hg:
        match.home_goals = hg
        fields.append("home_goals")
    if match.away_goals != ag:
        match.away_goals = ag
        fields.append("away_goals")
    kick = _kickoff(event)
    # Only accept a real kickoff move (self-correction for a last-second
    # postponement); ignore churn while the kickoff is still a placeholder.
    if kick and match.kickoff != kick and not match.kickoff_provisional:
        match.kickoff = kick
        fields.append("kickoff")
    if fields:
        match.save(update_fields=fields)
    return fields


def _offline_client() -> SofaScoreClient:
    """A client for READING the warm cache. It must never sit waiting on the
    network: this side of the egress cannot reach SofaScore anyway, so a cache miss
    is a fact to report at once, not something to retry with backoff for the length
    of a half."""
    return SofaScoreClient(cache_dir=_cache_dir(), max_retries=1,
                           logger=lambda _m: None)


def _warm(match, *, heavy: bool) -> bool:
    """Ask the egress for this match's bytes. The kind is the kind of FETCH, not a
    claim about the match: 'final' means "everything the importer can read", 'live'
    the cheap half of it — the same four endpoints minus a heatmap per player."""
    return egress_client.warm_matches([match.external_id],
                                      "final" if heavy else "live")


def _import_warm(match, *, only_finished: bool, heavy: bool) -> bool:
    """Import the warm cache OFFLINE (lineups/shotmap/incidents -> DB, incl. voto
    puro). True iff the import went through.

    ``heavy`` is the whole difference in cost. A light round reads four endpoints; a
    heavy one adds a heatmap per player — some twenty-two more — and with them the
    positional half of the model. The light round still writes every player's
    totals, because the scorer sums each feature over all zones and the sum of a
    distributed stat is the stat itself (see ``sofascore_adapter``).

    The fixture is resolved from its OWN address (``/event/{id}``), which the warm
    has just refreshed anyway — not by pulling seasons -> rounds -> every round's
    events to find a match whose id we already hold. The calendar remains the
    safety net for when that address stops answering with something usable.

    ``only_finished`` still has to be passed through: the importer skips anything
    the provider does not call finished, so a match still in progress would be
    silently passed over.

    ``skip_existing=False`` always: this is called repeatedly on the same match (the
    +15min check, the +8h confirmation, and every live round), and the point of each
    call is to pick up what has changed since the last one.
    """
    year = year_for(match)
    client = _offline_client()
    try:
        result = ingest_sofascore_matches(
            scraper=client, year=year, match_ids=[int(match.external_id)],
            only_finished=only_finished, skip_existing=False, with_heatmaps=heavy)
        if result.unresolved:
            # The address did not answer with a usable fixture. Pay for the whole
            # calendar this once rather than skip the match. Still the round's own
            # weight, though: a light warm dropped the heatmaps and did not fetch
            # them back, so asking for them here would send this side of the egress
            # to the network — which from here is a block.
            if not egress_client.warm_schedule(year):
                return False
            ingest_sofascore_season(scraper=client, year=year,
                                    match_ids=[int(match.external_id)],
                                    only_finished=only_finished,
                                    skip_existing=False, with_heatmaps=heavy)
    except (SofaScoreBlocked, SofaScoreError):
        # Something the import needed was not in the warm cache and it tried the
        # network (blocked from here). Bail; the next tick retries.
        return False
    return True


def finalize(match) -> bool:
    """The post-full-time import: the match is over, so only a finished one counts,
    and it is always heavy — the heatmaps are what full time was waited for."""
    return (_warm(match, heavy=True)
            and _import_warm(match, only_finished=True, heavy=True))


def live_round(match, *, heavy: bool) -> bool:
    """One round of a match being played: its lifecycle and score, then its
    per-player data. True iff the egress warmed the cache AND the import went
    through.

    The two used to be separate steps on separate clocks. They are one because the
    light half is what sets the cadence: the votes move on every round, and the
    status flip to finished (or a last-second postponement) is caught on the same
    pass rather than by a second one racing it.

    What it does NOT do, on any round, is touch ``data_ready``. That flag means "the
    provider has stopped changing this match", and it is the one marker of
    instability in the whole system (a vote is provisional exactly when the real
    match behind it is not data_ready). Importing mid-match gives the league a vote
    that moves; promoting the match would freeze a number the next round is going to
    change.
    """
    if not _warm(match, heavy=heavy):
        return False
    event = _cached_event(match.external_id)
    if event is not None:
        _apply_status(match, event)
    return _import_warm(match, only_finished=False, heavy=heavy)


# Below this, a revision of a shot's xG + xGOT is nothing a vote can show: a fifth
# of one half-point of xGOT on a single shot (the same eps as ``revision_probe``).
SHOT_REVISION_EPS = 0.02
REVISION_PREFIX = "xG/xGOT rivisti"


def _facts(match) -> dict:
    """What a provider correction can move, read off the DATABASE: the score, each
    player's goals/assists/own goals, who struck each goal and for which side, and
    the xG/xGOT of every shot.

    The goal shots are in the set on purpose. The tabellino and the shot map are two
    separate reads of the provider and the vote reads BOTH (the fantavoto bonus the
    first, the credit and ``is_own_goal`` the second), so a correction that reached
    only one of them is exactly the case this has to see.
    """
    from realdata.models import MatchAppearance, MatchShot
    match.refresh_from_db(fields=["home_goals", "away_goals"])
    apps = {}
    for pid, goals, assists, raw in MatchAppearance.objects.filter(
            match=match).values_list("player_id", "goals", "assists", "raw_stats"):
        og = int((raw or {}).get("ownGoals") or 0)
        if goals or assists or og:
            apps[pid] = (goals, assists, og)
    shots = sorted(MatchShot.objects.filter(match=match, shot_type="goal")
                   .values_list("player_id", "team_side", "minute"))
    # The shot rows have no provider id (the import deletes and re-inserts them), so
    # a shot is known by who struck it and when. Two shots of one player in the same
    # second do not happen; if they ever did, the later row would simply hide one.
    values = {(pid, minute, secs): (xg or 0.0, xgot or 0.0)
              for pid, minute, secs, xg, xgot in MatchShot.objects.filter(
                  match=match).values_list("player_id", "minute", "elapsed_seconds",
                                           "xg", "xgot")}
    return {"score": (match.home_goals, match.away_goals), "players": apps,
            "goal_shots": shots, "shot_values": values}


def _describe(before: dict, after: dict) -> list[str]:
    """What moved, in words an admin can act on: they go into the log AND into the
    message that asks a league to re-score a closed round."""
    from realdata.models import Player
    out = []
    if before["score"] != after["score"]:
        (bh, ba), (ah, aa) = before["score"], after["score"]
        out.append(f"risultato {bh}-{ba} -> {ah}-{aa}")
    moved = sorted(pid for pid in set(before["players"]) | set(after["players"])
                   if before["players"].get(pid, (0, 0, 0))
                   != after["players"].get(pid, (0, 0, 0)))
    names = {pid: (short or full) for pid, short, full in Player.objects.filter(
        id__in=moved).values_list("id", "short_name", "full_name")}
    for pid in moved:
        b = before["players"].get(pid, (0, 0, 0))
        a = after["players"].get(pid, (0, 0, 0))
        parts = [f"{label} {x} -> {y}" for label, x, y in
                 zip(("gol", "assist", "autogol"), b, a) if x != y]
        out.append(f"{names.get(pid, 'giocatore')} (#{pid}): " + ", ".join(parts))
    if before["goal_shots"] != after["goal_shots"]:
        out.append("mappa dei tiri: i gol non sono piu' gli stessi")
    # The revision the +8h confirmation waits for. Seen at +24h it is the exception
    # this look exists for, and it moves votes (the keeper's above all) without
    # touching a single fact — which is why "invariata" used to be said over it.
    old, new = before.get("shot_values", {}), after.get("shot_values", {})
    deltas = [abs(new[k][0] - old[k][0]) + abs(new[k][1] - old[k][1])
              for k in old.keys() & new.keys()]
    moved = [d for d in deltas if d > SHOT_REVISION_EPS]
    if moved:
        out.append(f"{REVISION_PREFIX} su {len(moved)} tiri (il piu' grosso "
                   f"{max(moved):.3f})")
    return out


def fact_changes(changes: list[str]) -> list[str]:
    """The changes that are FACTS — score, goals, assists, own goals, authorship —
    out of what ``late_check`` reported.

    The split is the league's policy, not tidiness: a fact moves a bonus (three
    points for a goal), can turn a result and is worth asking a league to re-score
    a closed round for. A late re-estimate of xG moves decimals that the half-point
    rounding nearly always swallows, and is only logged.
    """
    return [c for c in changes if not c.startswith(REVISION_PREFIX)]


def late_check(match) -> tuple[bool, list[str]]:
    """One late look at a match that is already ``data_ready``.

    Returns ``(ok, changes)``: ``ok`` False when the egress was blocked (nothing was
    read, the caller must not stamp and the next tick retries), ``changes`` the
    list of what moved — empty when the provider still says what we stored.

    The look is the LIGHT one (four requests, no heatmaps) compared with what the
    database held beforehand. Only if something moved does the match get the full
    ``finalize`` again, so the positional half is re-read too: a correction is rare,
    and then it is worth the twenty-odd extra requests. ``data_ready`` is never
    touched — it says "the provider has stopped changing this", and one late
    correction does not turn a finished match back into a live one.
    """
    before = _facts(match)
    if not live_round(match, heavy=False):
        return False, []
    changes = _describe(before, _facts(match))
    if changes:
        # Best effort: the light import already wrote the correction, so a blocked
        # heavy re-read costs only the heatmaps, which a change of authorship
        # does not move.
        finalize(match)
    return True, changes
