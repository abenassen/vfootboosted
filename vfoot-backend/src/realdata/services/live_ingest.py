"""Wire the tick's live/finalization hooks to the egress + the OFFLINE import.

The tick (unprivileged, DB-aware) decides WHICH matches are due; this module warms
their cache through the root egress tunnel, then reads that warm cache with the
existing offline import. It never touches the network itself (the egress does), so
with the egress mocked it is fully testable.

Two entry points, and the difference between them is the match's lifecycle, not the
amount of work: ``live_round`` for a match being played (never promotes it),
``finalize`` after full time (the caller promotes it at the +1h confirmation). Both
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
    +15min check, the +1h confirmation, and every live round), and the point of each
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
            # calendar this once rather than skip the match.
            if not egress_client.warm_schedule(year):
                return False
            ingest_sofascore_season(scraper=client, year=year,
                                    match_ids=[int(match.external_id)],
                                    only_finished=only_finished,
                                    skip_existing=False)
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
