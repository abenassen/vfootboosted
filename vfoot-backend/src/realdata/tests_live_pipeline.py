"""SofaScore live pipeline wiring: egress warms the cache, the offline code reads it.

The egress (root, netns, network) is mocked, so this exercises the DB-aware half —
poll_live's status/score update, finalize's warm+import, and the tick advancing
state only on success — with no root and no tunnel.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from realdata.models import (
    Competition, CompetitionSeason, Match, Season, Team, TeamSeason,
)
from realdata.services import live_ingest


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class _Base(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            external_source="sofascore", external_id="95836")
        self.home = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Torino"))
        self.away = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Inter"))

    def _match(self, ext="111", **kw):
        return Match.objects.create(
            external_source="sofascore", external_id=ext,
            competition_season=self.cs, home_team=self.home, away_team=self.away, **kw)


class LiveIngestTests(_Base):
    def test_year_for(self):
        self.assertEqual(live_ingest.year_for(self._match()), "26/27")

    def test_poll_live_updates_status_and_score_from_warm_cache(self):
        m = self._match(status=Match.STATUS_LIVE)
        event = {"id": 111, "status": {"type": "finished"},
                 "homeScore": {"current": 2}, "awayScore": {"current": 1}}
        with mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=True), \
             mock.patch.object(live_ingest, "_cached_event", return_value=event):
            self.assertTrue(live_ingest.poll_live(m))
        m.refresh_from_db()
        self.assertEqual(m.status, Match.STATUS_FINISHED)
        self.assertEqual((m.home_goals, m.away_goals), (2, 1))

    def test_poll_live_blocked_egress_leaves_match_untouched(self):
        m = self._match(status=Match.STATUS_LIVE)
        with mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=False):
            self.assertFalse(live_ingest.poll_live(m))
        m.refresh_from_db()
        self.assertEqual(m.status, Match.STATUS_LIVE)

    def test_finalize_warms_then_imports_the_right_match(self):
        m = self._match(status=Match.STATUS_FINISHED)
        with mock.patch.object(live_ingest.egress_client, "warm_schedule",
                               return_value=True) as ws, \
             mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=True) as wm, \
             mock.patch.object(live_ingest, "ingest_sofascore_season") as ing:
            self.assertTrue(live_ingest.finalize(m))
        ws.assert_called_once()
        wm.assert_called_once_with([m.external_id], "final")
        self.assertEqual(ing.call_args.kwargs["match_ids"], [111])

    def test_finalize_bails_when_egress_blocked_and_never_imports(self):
        m = self._match(status=Match.STATUS_FINISHED)
        with mock.patch.object(live_ingest.egress_client, "warm_schedule",
                               return_value=True), \
             mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=False), \
             mock.patch.object(live_ingest, "ingest_sofascore_season") as ing:
            self.assertFalse(live_ingest.finalize(m))
        ing.assert_not_called()

    def test_import_live_asks_the_importer_not_to_require_a_finished_match(self):
        """The importer resolves the match from the SCHEDULE and skips whatever the
        schedule does not call finished. Without only_finished=False the live import
        would report success and import nothing at all."""
        m = self._match(status=Match.STATUS_LIVE)
        with mock.patch.object(live_ingest.egress_client, "warm_schedule",
                               return_value=True), \
             mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=True), \
             mock.patch.object(live_ingest, "ingest_sofascore_season") as ing:
            self.assertTrue(live_ingest.import_live(m))
        self.assertIs(ing.call_args.kwargs["only_finished"], False)
        # And it must not skip a match it has already written rows for: the whole
        # point of the second import is what changed since the first.
        self.assertIs(ing.call_args.kwargs["skip_existing"], False)

    def test_import_live_does_not_promote_the_match(self):
        m = self._match(status=Match.STATUS_LIVE)
        with mock.patch.object(live_ingest.egress_client, "warm_schedule",
                               return_value=True), \
             mock.patch.object(live_ingest.egress_client, "warm_matches",
                               return_value=True), \
             mock.patch.object(live_ingest, "ingest_sofascore_season"):
            live_ingest.import_live(m)
        m.refresh_from_db()
        self.assertFalse(m.data_ready)


class TickWiringTests(_Base):
    def test_final_confirm_sets_data_ready_only_on_success(self):
        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        m = self._match(status=Match.STATUS_FINISHED,
                        finished_at=now - timedelta(hours=3))
        with mock.patch.object(live_ingest, "finalize", return_value=True) as fin:
            call_command("tick", "--now", _iso(now))
        fin.assert_called_once()
        m.refresh_from_db()
        self.assertTrue(m.data_ready)

    def test_final_confirm_leaves_data_ready_false_when_blocked(self):
        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        m = self._match(status=Match.STATUS_FINISHED,
                        finished_at=now - timedelta(hours=3))
        with mock.patch.object(live_ingest, "finalize", return_value=False):
            call_command("tick", "--now", _iso(now))
        m.refresh_from_db()
        self.assertFalse(m.data_ready)

    def test_dry_run_does_not_touch_the_egress(self):
        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        self._match(status=Match.STATUS_FINISHED, finished_at=now - timedelta(hours=3))
        with mock.patch.object(live_ingest, "finalize") as fin:
            call_command("tick", "--now", _iso(now), "--dry-run")
        fin.assert_not_called()

    def test_live_import_stamps_its_own_clock_and_leaves_data_ready_alone(self):
        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        m = self._match(status=Match.STATUS_LIVE,
                        kickoff=now - timedelta(minutes=30))
        with mock.patch.object(live_ingest, "poll_live", return_value=True), \
             mock.patch.object(live_ingest, "import_live", return_value=True) as imp:
            call_command("tick", "--now", _iso(now))
        imp.assert_called_once()
        m.refresh_from_db()
        self.assertEqual(m.data_imported_at, now)
        self.assertFalse(m.data_ready)

    def test_a_blocked_live_import_does_not_stamp(self):
        """So the next tick retries it instead of waiting out the whole interval."""
        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        m = self._match(status=Match.STATUS_LIVE,
                        kickoff=now - timedelta(minutes=30))
        with mock.patch.object(live_ingest, "poll_live", return_value=True), \
             mock.patch.object(live_ingest, "import_live", return_value=False):
            call_command("tick", "--now", _iso(now))
        m.refresh_from_db()
        self.assertIsNone(m.data_imported_at)

    def test_full_time_is_announced_at_the_stamp_and_not_again(self):
        """The full-time push belongs to ``stamp_ft``, which by construction happens
        exactly once per match — the later finalization steps must stay silent."""
        from vfoot.services import live_updates

        now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        m = self._match(status=Match.STATUS_FINISHED)
        with mock.patch.object(live_updates, "announce_full_time",
                               return_value=0) as ann:
            call_command("tick", "--now", _iso(now))          # stamps FT
            ann.assert_called_once()
            ann.reset_mock()
            with mock.patch.object(live_ingest, "finalize", return_value=True):
                call_command("tick", "--now", _iso(now + timedelta(hours=2)))
            ann.assert_not_called()
