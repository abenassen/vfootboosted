"""Tests for the calendar sync + scheduler tick (Phase-1 ingestion pipeline)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from realdata.models import (
    Competition,
    CompetitionSeason,
    Match,
    Season,
    Team,
    TeamSeason,
)
from realdata.services import calendar_sync
from django.test import override_settings

from realdata.services.match_scheduler import (
    FINAL_CHECK_AFTER,
    FINAL_CONFIRM_AFTER,
    LIVE_POLL_WINDOW,
    plan_tick,
)

UTC = timezone.utc


def _m(**kw) -> Match:
    """An unsaved Match with sensible scheduler-relevant defaults."""
    defaults = dict(status=Match.STATUS_SCHEDULED, kickoff=None,
                    kickoff_provisional=False, data_ready=False, finished_at=None)
    defaults.update(kw)
    return Match(**defaults)


class PlanTickTests(SimpleTestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 22, 15, 0, tzinfo=UTC)

    def test_confirmed_kickoff_in_window_polls_live(self):
        m = _m(kickoff=self.now - timedelta(minutes=30))
        self.assertIn(m, plan_tick(self.now, [m]).live_poll)

    def test_provisional_kickoff_never_polls(self):
        m = _m(kickoff=self.now - timedelta(minutes=30), kickoff_provisional=True)
        self.assertTrue(plan_tick(self.now, [m]).is_empty())

    def test_before_kickoff_nothing_due(self):
        m = _m(kickoff=self.now + timedelta(minutes=30))
        self.assertTrue(plan_tick(self.now, [m]).is_empty())

    def test_past_live_window_no_poll(self):
        m = _m(kickoff=self.now - LIVE_POLL_WINDOW - timedelta(minutes=1))
        self.assertTrue(plan_tick(self.now, [m]).is_empty())

    def test_status_live_always_polls_even_outside_window(self):
        m = _m(status=Match.STATUS_LIVE,
               kickoff=self.now - LIVE_POLL_WINDOW - timedelta(hours=2))
        self.assertIn(m, plan_tick(self.now, [m]).live_poll)

    def test_finished_without_stamp_gets_stamped(self):
        m = _m(status=Match.STATUS_FINISHED)
        self.assertIn(m, plan_tick(self.now, [m]).stamp_ft)

    def test_final_check_at_15_min(self):
        m = _m(status=Match.STATUS_FINISHED,
               finished_at=self.now - FINAL_CHECK_AFTER)
        plan = plan_tick(self.now, [m])
        self.assertIn(m, plan.final_check)
        self.assertNotIn(m, plan.final_confirm)

    def test_just_before_15_min_nothing(self):
        m = _m(status=Match.STATUS_FINISHED,
               finished_at=self.now - FINAL_CHECK_AFTER + timedelta(minutes=1))
        self.assertTrue(plan_tick(self.now, [m]).is_empty())

    def test_final_confirm_at_1h(self):
        m = _m(status=Match.STATUS_FINISHED,
               finished_at=self.now - FINAL_CONFIRM_AFTER)
        self.assertIn(m, plan_tick(self.now, [m]).final_confirm)

    def test_data_ready_finished_is_done(self):
        m = _m(status=Match.STATUS_FINISHED, data_ready=True,
               finished_at=self.now - timedelta(hours=3))
        self.assertTrue(plan_tick(self.now, [m]).is_empty())


class FakeClient:
    """Minimal stand-in for SofaScoreClient returning canned calendar JSON."""

    def __init__(self, rounds_payload, events_by_round):
        self._rounds = rounds_payload
        self._events = events_by_round

    def get_valid_seasons(self):
        return {"26/27": 95836}

    def get(self, path):
        if path.endswith("/rounds"):
            return self._rounds
        for rnd, payload in self._events.items():
            if path.endswith(f"/events/round/{rnd}"):
                return payload
        return {}


def _team(tid, name):
    return {"id": tid, "name": name, "shortName": name[:3]}


def _event(eid, ts, status_type, rnd, home, away, hs=None, aws=None):
    return {
        "id": eid, "startTimestamp": ts,
        "status": {"type": status_type},
        "roundInfo": {"round": rnd},
        "homeTeam": home, "awayTeam": away,
        "homeScore": {"current": hs}, "awayScore": {"current": aws},
    }


class SyncCalendarTests(TestCase):
    def _client(self, r2_status="notstarted"):
        genoa, lecce = _team(1, "Genoa"), _team(2, "Lecce")
        roma, fiore = _team(3, "Roma"), _team(4, "Fiorentina")
        base = 1_756_000_000
        rounds = {"rounds": [{"round": 1}, {"round": 2}], "currentRound": {"round": 1}}
        events = {
            # round 1: distinct kickoffs -> confirmed; finished with scores
            1: {"events": [
                _event(101, base, "finished", 1, genoa, lecce, 2, 1),
                _event(102, base + 7200, "finished", 1, roma, fiore, 0, 0),
            ]},
            # round 2: identical kickoff -> provisional placeholder
            2: {"events": [
                _event(201, base + 600000, r2_status, 2, lecce, roma),
                _event(202, base + 600000, r2_status, 2, fiore, genoa),
            ]},
        }
        return FakeClient(rounds, events)

    def test_resolve_stamps_season_external_id(self):
        client = self._client()
        cs, sid = calendar_sync.resolve_competition_season(
            client, "26/27", season_id=95836, logger=lambda *_: None)
        self.assertEqual(sid, 95836)
        self.assertEqual(cs.external_id, "95836")
        self.assertEqual(cs.external_source, calendar_sync.PROVIDER)

    def test_full_sync_creates_and_flags_provisional(self):
        client = self._client()
        cs, sid = calendar_sync.resolve_competition_season(
            client, "26/27", season_id=95836, logger=lambda *_: None)
        report = calendar_sync.sync_calendar(client, cs, sid, logger=lambda *_: None)

        self.assertEqual(report.total, 4)
        self.assertEqual(report.created, 4)
        self.assertEqual(Match.objects.filter(competition_season=cs).count(), 4)

        r1 = Match.objects.get(external_id="101")
        self.assertEqual(r1.status, Match.STATUS_FINISHED)
        self.assertFalse(r1.kickoff_provisional)
        self.assertEqual(r1.home_goals, 2)

        r2 = Match.objects.get(external_id="201")
        self.assertTrue(r2.kickoff_provisional)
        self.assertEqual(r2.status, Match.STATUS_SCHEDULED)

    def test_resync_is_idempotent(self):
        client = self._client()
        cs, sid = calendar_sync.resolve_competition_season(
            client, "26/27", season_id=95836, logger=lambda *_: None)
        calendar_sync.sync_calendar(client, cs, sid, logger=lambda *_: None)
        again = calendar_sync.sync_calendar(client, cs, sid, logger=lambda *_: None)
        self.assertEqual(again.created, 0)
        self.assertEqual(again.updated, 0)
        self.assertEqual(again.unchanged, 4)

    def test_postponement_is_detected(self):
        cs, sid = calendar_sync.resolve_competition_season(
            self._client(), "26/27", season_id=95836, logger=lambda *_: None)
        calendar_sync.sync_calendar(self._client(), cs, sid, logger=lambda *_: None)
        # a round-2 fixture is now postponed
        report = calendar_sync.sync_calendar(
            self._client(r2_status="postponed"), cs, sid, logger=lambda *_: None)
        self.assertEqual(report.updated, 2)
        kinds = {c.kind for c in report.changes}
        self.assertIn("postponed", kinds)
        self.assertEqual(Match.objects.get(external_id="201").status,
                         Match.STATUS_POSTPONED)


class TickCommandTests(TestCase):
    """End-to-end: the tick command applies the state machine it owns."""

    def setUp(self):
        comp = Competition.objects.create(
            external_source=calendar_sync.PROVIDER, external_id="23", name="Serie A")
        season = Season.objects.create(code="2026-2027")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=season, name="Serie A 2026-2027",
            external_source=calendar_sync.PROVIDER, external_id="95836")
        home = Team.objects.create(external_source=calendar_sync.PROVIDER,
                                   external_id="1", name="Genoa")
        away = Team.objects.create(external_source=calendar_sync.PROVIDER,
                                   external_id="2", name="Lecce")
        self.home_ts = TeamSeason.objects.create(competition_season=self.cs, team=home)
        self.away_ts = TeamSeason.objects.create(competition_season=self.cs, team=away)

    def _match(self, **kw):
        return Match.objects.create(
            competition_season=self.cs, home_team=self.home_ts,
            away_team=self.away_ts, external_source=calendar_sync.PROVIDER,
            external_id="999", **kw)

    def _tick(self, iso):
        call_command("tick", "--now", iso, stdout=StringIO())

    def test_full_finalization_lifecycle(self):
        ft = datetime(2026, 8, 22, 15, 45, tzinfo=UTC)
        m = self._match(status=Match.STATUS_FINISHED, kickoff=ft - timedelta(hours=2))

        # first tick at FT: stamps finished_at, not yet ready
        self._tick(ft.isoformat())
        m.refresh_from_db()
        self.assertEqual(m.finished_at, ft)
        self.assertFalse(m.data_ready)

        # +16min: first finalization check runs, still not confirmed
        self._tick((ft + timedelta(minutes=16)).isoformat())
        m.refresh_from_db()
        self.assertIsNotNone(m.data_checked_at)
        self.assertFalse(m.data_ready)

        # +61min: confirmation promotes to data_ready
        self._tick((ft + timedelta(minutes=61)).isoformat())
        m.refresh_from_db()
        self.assertTrue(m.data_ready)

    def test_dry_run_mutates_nothing(self):
        m = self._match(status=Match.STATUS_FINISHED)
        call_command("tick", "--now", "2026-08-22T18:00:00Z", "--dry-run",
                     stdout=StringIO())
        m.refresh_from_db()
        self.assertIsNone(m.finished_at)


class LivePollCadenceTests(SimpleTestCase):
    """The scrape interval is a knob: the tick may fire every minute, but a single
    match must not be re-scraped more often than configured."""

    def setUp(self):
        self.now = datetime(2026, 8, 22, 15, 0, tzinfo=UTC)

    def _live(self, last_checked):
        return _m(kickoff=self.now - timedelta(minutes=30),
                  data_checked_at=last_checked)

    @override_settings(VFOOT_LIVE_POLL_MINUTES=2)
    def test_never_polled_is_due(self):
        m = self._live(None)
        self.assertIn(m, plan_tick(self.now, [m]).live_poll)

    @override_settings(VFOOT_LIVE_POLL_MINUTES=2)
    def test_polled_recently_is_skipped(self):
        m = self._live(self.now - timedelta(seconds=30))
        self.assertTrue(plan_tick(self.now, [m]).is_empty())

    @override_settings(VFOOT_LIVE_POLL_MINUTES=2)
    def test_polled_longer_ago_than_the_interval_is_due(self):
        m = self._live(self.now - timedelta(minutes=3))
        self.assertIn(m, plan_tick(self.now, [m]).live_poll)

    @override_settings(VFOOT_LIVE_POLL_MINUTES=5)
    def test_widening_the_interval_reduces_scraping(self):
        m = self._live(self.now - timedelta(minutes=3))
        # at 5 minutes the same match is NOT yet due (it was at 2)
        self.assertTrue(plan_tick(self.now, [m]).is_empty())
