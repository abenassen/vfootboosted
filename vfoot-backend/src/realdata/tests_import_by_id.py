"""What an import COSTS, endpoint by endpoint.

The live import used to pull the whole fixture list to rediscover a match whose id
it already held: seasons -> rounds -> one request per round, before a single byte of
the match itself. These tests count the requests rather than describe them, because
the count is the thing the change was made for — and a count is the one property
that decays silently as code moves around.

The recorder subclasses the real client, so what it counts is what a cache miss
would really fetch: cache, throttle and retry are the client's, only the wire is
replaced.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from django.test import TestCase

from realdata.models import Match, PlayerZoneFeature, PROVIDER_SOFASCORE
from realdata.services.sofascore_adapter import (
    ingest_sofascore_matches, ingest_sofascore_season,
)
from realdata.services.sofascore_client import SofaScoreClient

MATCH_ID = 16283209
SEASON_ID = 95836
TOURNAMENT = 23

_HOME = {"id": 2696, "name": "Torino", "shortName": "Torino"}
_AWAY = {"id": 2697, "name": "Inter", "shortName": "Inter"}


def _player_row(pid: int, name: str, side: str, minutes: int = 90) -> dict:
    return {"id": pid, "name": name, "shortName": name, "side": side,
            "substitute": False, "position": "M",
            "minutesPlayed": minutes, "touches": 40, "totalPass": 30,
            "accuratePass": 25, "duelWon": 3}


def _lineups() -> dict:
    def entry(pid, name):
        return {"player": {"id": pid, "name": name, "shortName": name},
                "substitute": False, "position": "M",
                "statistics": {"minutesPlayed": 90, "touches": 40,
                               "totalPass": 30, "accuratePass": 25, "duelWon": 3}}
    return {"home": {"players": [entry(1, "Primo"), entry(2, "Secondo")]},
            "away": {"players": [entry(3, "Terzo")]}}


def _event(**over) -> dict:
    event = {"id": MATCH_ID, "status": {"type": "inprogress"},
             "startTimestamp": 1801424700, "roundInfo": {"round": 7},
             "homeScore": {"current": 1}, "awayScore": {"current": 0},
             "homeTeam": dict(_HOME), "awayTeam": dict(_AWAY)}
    event.update(over)
    return event


def _payloads() -> dict[str, object]:
    """Everything a provider would serve for this one match, plus the calendar."""
    heat = {"heatmap": [{"x": 50, "y": 50}, {"x": 55, "y": 40}]}
    return {
        f"/api/v1/event/{MATCH_ID}": {"event": _event()},
        f"/api/v1/event/{MATCH_ID}/lineups": _lineups(),
        f"/api/v1/event/{MATCH_ID}/shotmap": {"shotmap": []},
        f"/api/v1/event/{MATCH_ID}/incidents": {"incidents": []},
        f"/api/v1/event/{MATCH_ID}/player/1/heatmap": heat,
        f"/api/v1/event/{MATCH_ID}/player/2/heatmap": heat,
        f"/api/v1/event/{MATCH_ID}/player/3/heatmap": heat,
        f"/api/v1/unique-tournament/{TOURNAMENT}/seasons": {
            "seasons": [{"year": "26/27", "id": SEASON_ID}]},
        f"/api/v1/unique-tournament/{TOURNAMENT}/season/{SEASON_ID}/rounds": {
            "rounds": [{"round": r} for r in range(1, 39)]},
        **{f"/api/v1/unique-tournament/{TOURNAMENT}/season/{SEASON_ID}"
           f"/events/round/{r}": {"events": [_event()] if r == 7 else []}
           for r in range(1, 39)},
    }


class _Recording(SofaScoreClient):
    """The real client with the wire replaced: every path it actually requests is
    recorded, so the count is the client's, not the test's idea of it."""

    def __init__(self, cache_dir, payloads):
        super().__init__(cache_dir, min_delay=0.0, jitter=0.0, max_retries=1,
                         logger=lambda _m: None)
        self.payloads = payloads
        self.requested: list[str] = []

    def _raw_get(self, path: str):
        self.requested.append(path)
        return self.payloads.get(path)


class ImportByIdTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.client_ = _Recording(Path(self._tmp.name), _payloads())

    def _schedule_requests(self) -> list[str]:
        return [p for p in self.client_.requested if "unique-tournament" in p]

    def test_by_id_never_touches_the_calendar(self):
        result = ingest_sofascore_matches(
            scraper=self.client_, year="26/27", match_ids=[MATCH_ID],
            only_finished=False, skip_existing=False, logger=lambda _m: None)
        self.assertEqual((result.matches, result.unresolved), (1, 0))
        self.assertEqual(self._schedule_requests(), [])
        self.assertEqual(self.client_.requested[0], f"/api/v1/event/{MATCH_ID}")

    def test_the_same_import_from_the_calendar_costs_forty_requests_more(self):
        """The number the change exists for: one seasons call, one rounds call and
        one per round, all to find a fixture whose address we already had."""
        ingest_sofascore_season(
            scraper=self.client_, year="26/27", match_ids=[MATCH_ID],
            only_finished=False, skip_existing=False, logger=lambda _m: None)
        # 1 seasons + 1 rounds + 38 rounds of events
        self.assertEqual(len(self._schedule_requests()), 40)

    def test_by_id_writes_the_same_match_the_calendar_would(self):
        ingest_sofascore_matches(
            scraper=self.client_, year="26/27", match_ids=[MATCH_ID],
            only_finished=False, skip_existing=False, logger=lambda _m: None)
        match = Match.objects.get(external_source=PROVIDER_SOFASCORE,
                                  external_id=str(MATCH_ID))
        self.assertEqual(match.matchday, 7)
        self.assertEqual(match.home_team.team.external_id, "2696")
        self.assertEqual((match.home_goals, match.away_goals), (1, 0))
        self.assertEqual(match.appearances.count(), 3)
        self.assertTrue(PlayerZoneFeature.objects.filter(match=match).exists())

    def test_only_finished_still_reads_the_status_from_the_event(self):
        """Finalization asks for a finished match; the per-id event is what answers,
        so the guard has to survive the change of route."""
        result = ingest_sofascore_matches(
            scraper=self.client_, year="26/27", match_ids=[MATCH_ID],
            only_finished=True, skip_existing=False, logger=lambda _m: None)
        self.assertEqual((result.matches, result.skipped_not_finished), (0, 1))

    def test_an_event_without_teams_is_reported_unresolved_not_imported(self):
        """The one thing the import cannot invent. Silently writing a shell of a
        match would be worse than paying for the calendar."""
        payloads = _payloads()
        payloads[f"/api/v1/event/{MATCH_ID}"] = {"event": {"id": MATCH_ID}}
        client = _Recording(Path(self._tmp.name) / "b", payloads)
        result = ingest_sofascore_matches(
            scraper=client, year="26/27", match_ids=[MATCH_ID],
            only_finished=False, skip_existing=False, logger=lambda _m: None)
        self.assertEqual((result.matches, result.unresolved), (0, 1))
        self.assertFalse(Match.objects.filter(external_id=str(MATCH_ID)).exists())

    def test_a_thin_event_does_not_erase_the_matchday_the_calendar_set(self):
        """A round entry always carries roundInfo; /event/{id} may not. An update
        from the thinner payload must not null what the fuller one established."""
        ingest_sofascore_season(
            scraper=self.client_, year="26/27", match_ids=[MATCH_ID],
            only_finished=False, skip_existing=False, logger=lambda _m: None)
        payloads = _payloads()
        payloads[f"/api/v1/event/{MATCH_ID}"] = {"event": _event(roundInfo=None)}
        client = _Recording(Path(self._tmp.name) / "c", payloads)
        ingest_sofascore_matches(
            scraper=client, year="26/27", match_ids=[MATCH_ID],
            only_finished=False, skip_existing=False, logger=lambda _m: None)
        self.assertEqual(Match.objects.get(external_id=str(MATCH_ID)).matchday, 7)
