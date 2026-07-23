"""Wire the tick's live/finalization hooks to the egress + the OFFLINE import.

The tick (unprivileged, DB-aware) decides WHICH matches are due; this module warms
their cache through the root egress tunnel, then reads that warm cache with the
existing offline code — a light status/score update for an in-progress match, the
full ``ingest_sofascore_season`` for finalization. It never touches the network
itself (the egress does), so with the egress mocked it is fully testable.

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
from realdata.services.sofascore_adapter import ingest_sofascore_season
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


def poll_live(match) -> bool:
    """Warm an in-progress match and update its status/score/kickoff (the tick's
    'stato-prima' step: it also catches a status flip to finished and a last-second
    postponement). True iff the egress warmed the cache."""
    if not egress_client.warm_matches([match.external_id], "live"):
        return False
    event = _cached_event(match.external_id)
    if event is not None:
        _apply_status(match, event)
    return True


def finalize(match) -> bool:
    """Warm the full match data and import it OFFLINE (lineups/shotmap/incidents/
    heatmaps -> DB, incl. voto puro). The schedule is warmed too because the import
    resolves the fixture from it (cache-first, so ~free once Loop A has run). True
    iff warmed AND imported."""
    year = year_for(match)
    if not egress_client.warm_schedule(year):
        return False
    if not egress_client.warm_matches([match.external_id], "final"):
        return False
    client = SofaScoreClient(cache_dir=_cache_dir(), logger=lambda _m: None)
    try:
        ingest_sofascore_season(scraper=client, year=year,
                                match_ids=[int(match.external_id)])
    except (SofaScoreBlocked, SofaScoreError):
        # Something the import needed was not in the warm cache and it tried the
        # network (blocked from here). Bail; the next tick retries.
        return False
    return True
