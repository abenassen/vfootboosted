"""Calendar sync — keep the local ``Match`` rows in step with the provider's
published fixture calendar for a real season.

This is the FOUNDATION of the semiautomatic pipeline: it is match-centric and
network-agnostic (it takes an already-built SofaScore client, so the same code
runs offline against a warm cache in dev and against the browser transport on
the always-on server). It does NOT scrape per-match data — only the schedule:
which matches exist, their kickoff, round and lifecycle status.

Two responsibilities:

1. ``resolve_competition_season`` — turn a season NAME (e.g. "26/27") into the
   local ``CompetitionSeason`` and stamp its provider ``external_id`` (the
   SofaScore season id, resolved once via ``get_valid_seasons``). Every league
   points at this shared edition, so ingestion is per-real-season (dedup), not
   per-league.

2. ``sync_calendar`` — upsert every fixture of the season, mapping the provider
   status onto ``Match.status``, flagging PROVISIONAL kickoffs (a whole round
   sharing one placeholder timestamp), and returning a diff report of what
   changed since the last run (new fixtures, kickoff moves, status flips,
   postponements) so the scheduler can react.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.db import transaction

from realdata.models import CompetitionSeason, Match
from realdata.services.sofascore_adapter import (
    PROVIDER,
    _get_or_create_competition_season,
    _kickoff,
    _team_season,
    season_code_from_year,
)

SERIE_A_TID = 23

# SofaScore ``status.type`` -> our Match lifecycle status.
STATUS_MAP = {
    "notstarted": Match.STATUS_SCHEDULED,
    "inprogress": Match.STATUS_LIVE,
    "finished": Match.STATUS_FINISHED,
    "postponed": Match.STATUS_POSTPONED,
    "canceled": Match.STATUS_CANCELLED,
    "cancelled": Match.STATUS_CANCELLED,
}


def _map_status(event: dict[str, Any]) -> str:
    raw = (event.get("status") or {}).get("type", "")
    return STATUS_MAP.get(str(raw).lower(), Match.STATUS_SCHEDULED)


def _round_is_provisional(events: list[dict[str, Any]]) -> bool:
    """A round is provisional when the provider hasn't assigned real slots yet —
    every fixture then carries one identical placeholder timestamp."""
    stamps = {e.get("startTimestamp") for e in events if e.get("startTimestamp")}
    return len(events) > 1 and len(stamps) == 1


# -- reporting -----------------------------------------------------------------


@dataclass
class MatchChange:
    external_id: str
    label: str
    kind: str  # created | kickoff | status | postponed
    detail: str = ""

    def __str__(self) -> str:
        return f"[{self.kind}] {self.label} ({self.external_id}) {self.detail}".rstrip()


@dataclass
class SyncReport:
    season: str = ""
    rounds: int = 0
    total: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    provisional: int = 0
    changes: list[MatchChange] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{self.season}: {self.total} fixtures over {self.rounds} rounds "
                f"— {self.created} created, {self.updated} updated, "
                f"{self.unchanged} unchanged, {self.provisional} with provisional kickoff")


# -- season resolution ---------------------------------------------------------


def resolve_competition_season(
    client,
    year_label: str,
    *,
    tournament_id: int = SERIE_A_TID,
    season_id: int | None = None,
    logger=print,
) -> tuple[CompetitionSeason, int]:
    """Resolve/create the local ``CompetitionSeason`` for a season name and stamp
    its SofaScore season id. ``season_id`` may be passed to skip the network
    lookup (useful offline or when the id is already known, e.g. 95836 for 26/27).

    NOTE: currently Serie A only (``_get_or_create_competition_season`` pins the
    Serie A competition). Generalising to other competitions is a later step.
    """
    season_code = season_code_from_year(year_label)
    if season_id is None:
        seasons = client.get_valid_seasons()  # {"26/27": 95836, ...}
        if year_label not in seasons:
            raise ValueError(
                f"Season {year_label!r} not among SofaScore seasons: {sorted(seasons)}")
        season_id = seasons[year_label]

    cs = _get_or_create_competition_season(season_code)
    update_fields = []
    if cs.external_source != PROVIDER:
        cs.external_source = PROVIDER
        update_fields.append("external_source")
    if str(cs.external_id) != str(season_id):
        cs.external_id = str(season_id)
        update_fields.append("external_id")
    if update_fields:
        cs.save(update_fields=update_fields)
    logger(f"CompetitionSeason: {cs} (season_id={season_id})")
    return cs, int(season_id)


# -- calendar sync -------------------------------------------------------------


def _published_rounds(client, season_id: int, tournament_id: int) -> list[int]:
    data = client.get(
        f"/api/v1/unique-tournament/{tournament_id}/season/{season_id}/rounds")
    return sorted({r.get("round") for r in data.get("rounds", [])
                   if r.get("round") is not None})


def _fetch_round_events(client, season_id: int, rnd: int,
                        tournament_id: int) -> list[dict[str, Any]]:
    data = client.get(
        f"/api/v1/unique-tournament/{tournament_id}/season/{season_id}"
        f"/events/round/{rnd}")
    return data.get("events", []) or []


def _fields_for(event: dict[str, Any], cs: CompetitionSeason, home_ts, away_ts,
                provisional: bool) -> dict[str, Any]:
    matchday = (event.get("roundInfo") or {}).get("round")
    return {
        "competition_season": cs,
        "matchday": int(matchday) if matchday is not None else None,
        "kickoff": _kickoff(event),
        "kickoff_provisional": provisional,
        "home_team": home_ts,
        "away_team": away_ts,
        "home_goals": (event.get("homeScore") or {}).get("current"),
        "away_goals": (event.get("awayScore") or {}).get("current"),
        "status": _map_status(event),
    }


def _label(home_ts, away_ts) -> str:
    h = home_ts.team.short_name or home_ts.team.name
    a = away_ts.team.short_name or away_ts.team.name
    return f"{h} v {a}"


def _upsert_fixture(event, cs, home_ts, away_ts, provisional, report) -> None:
    ext = str(event.get("id"))
    fields = _fields_for(event, cs, home_ts, away_ts, provisional)
    label = _label(home_ts, away_ts)

    match = Match.objects.filter(external_source=PROVIDER, external_id=ext).first()
    if match is None:
        Match.objects.create(external_source=PROVIDER, external_id=ext, **fields)
        report.created += 1
        report.changes.append(MatchChange(
            ext, label, "created",
            f"{fields['status']} kickoff={fields['kickoff']}"))
        return

    old_kick, old_status = match.kickoff, match.status
    changed = [f for f, v in fields.items() if getattr(match, f) != v]
    if not changed:
        report.unchanged += 1
        return

    for f in changed:
        setattr(match, f, fields[f])
    match.save(update_fields=changed)
    report.updated += 1

    # Surface the two changes the scheduler cares about (ignore pure score/goal
    # churn and provisional-flag flips). A real kickoff move only when it stops
    # being a placeholder.
    if "kickoff" in changed and not provisional:
        report.changes.append(MatchChange(
            ext, label, "kickoff", f"{old_kick} -> {fields['kickoff']}"))
    if "status" in changed:
        kind = "postponed" if fields["status"] == Match.STATUS_POSTPONED else "status"
        report.changes.append(MatchChange(
            ext, label, kind, f"{old_status} -> {fields['status']}"))


def sync_calendar(
    client,
    competition_season: CompetitionSeason,
    season_id: int,
    *,
    rounds: list[int] | None = None,
    tournament_id: int = SERIE_A_TID,
    logger=print,
) -> SyncReport:
    """Upsert every fixture of ``competition_season`` from the provider calendar.

    ``rounds`` limits the sync to specific rounds (e.g. the current + next round
    for a cheap frequent run); ``None`` syncs all published rounds.
    """
    report = SyncReport(season=str(competition_season))
    if rounds is None:
        rounds = _published_rounds(client, season_id, tournament_id)

    team_cache: dict[str, Any] = {}
    for rnd in rounds:
        events = _fetch_round_events(client, season_id, rnd, tournament_id)
        if not events:
            continue
        report.rounds += 1
        provisional = _round_is_provisional(events)
        with transaction.atomic():
            for ev in events:
                home = ev.get("homeTeam") or {}
                away = ev.get("awayTeam") or {}
                if not home.get("id") or not away.get("id"):
                    continue
                home_ts = _team_season(home, competition_season, team_cache)
                away_ts = _team_season(away, competition_season, team_cache)
                _upsert_fixture(ev, competition_season, home_ts, away_ts,
                                provisional, report)
                report.total += 1
                if provisional:
                    report.provisional += 1
        logger(f"  round {rnd}: {len(events)} events"
               f"{' [provisional kickoffs]' if provisional else ''}")

    return report
