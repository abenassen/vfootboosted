"""Tests for the calendar sync + scheduler tick (Phase-1 ingestion pipeline)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from io import StringIO
from unittest import mock

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
    _in_live_window,
    clock_drift,
    data_high_water,
    human_gap,
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
        self.assertIn(m, plan_tick(self.now, [m]).live_round)

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
        self.assertIn(m, plan_tick(self.now, [m]).live_round)

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


class FinalCheckHappensOnceTests(SimpleTestCase):
    """The +15min scrape is ONE scrape, not a window to sit inside.

    Without the guard it came due on every tick from +15 to +1h: 45 full imports
    of the same finished match, ~1.650 requests, and — measured on the rig over a
    whole simulated evening — not one of them ever changed a vote. Nine times the
    cost of the live match it was finalizing.
    """

    def setUp(self):
        self.now = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)
        self.ft = self.now - FINAL_CHECK_AFTER

    def _finished(self, **kw):
        return _m(status=Match.STATUS_FINISHED, finished_at=self.ft, **kw)

    def test_the_first_tick_after_15_min_is_due(self):
        m = self._finished(data_imported_at=self.ft - timedelta(minutes=1))
        self.assertIn(m, plan_tick(self.now, [m]).final_check)

    def test_the_next_tick_is_not(self):
        m = self._finished(data_imported_at=self.now)
        later = self.now + timedelta(minutes=1)
        self.assertTrue(plan_tick(later, [m]).is_empty())

    def test_nor_is_any_tick_up_to_the_confirmation(self):
        m = self._finished(data_imported_at=self.now)
        for minutes in (2, 10, 30, 44):
            later = self.now + timedelta(minutes=minutes)
            self.assertTrue(plan_tick(later, [m]).is_empty(),
                            f"ridotto a scansione unica, ma +{minutes}' è dovuto")

    def test_a_blocked_check_is_retried(self):
        """"Once" means once SUCCESSFULLY. The tick stamps data_imported_at only
        on an import that went through, so a blocked egress leaves the checkpoint
        unmet and the match comes due again."""
        m = self._finished(data_imported_at=self.ft - timedelta(minutes=1))
        later = self.now + timedelta(minutes=1)
        self.assertIn(m, plan_tick(later, [m]).final_check)

    def test_the_confirmation_still_comes(self):
        """The guard must not swallow the scrape that matters: the +1h one is the
        authority on the final numbers, and the only one that promotes."""
        m = self._finished(data_imported_at=self.now)
        at_confirm = self.ft + FINAL_CONFIRM_AFTER
        plan = plan_tick(at_confirm, [m])
        self.assertIn(m, plan.final_confirm)
        self.assertEqual(plan.final_check, [])

    def test_a_tick_that_slept_through_the_window_still_checks(self):
        """Nothing is measured from "the last tick": if the machine was down from
        +15 to +40, the check is simply late, not skipped."""
        m = self._finished(data_imported_at=self.ft - timedelta(minutes=1))
        self.assertIn(m, plan_tick(self.ft + timedelta(minutes=40), [m]).final_check)


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


class _TickDBTests(TestCase):
    """The fixtures a DB-backed tick test needs: one season, two teams, a match
    factory and a one-line tick. Kept apart from the tests that use them so a second
    class can inherit the fixtures without also inheriting — and re-running — the
    assertions."""

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
        # setdefault and not a positional default: a test that needs TWO matches has
        # to be able to tell them apart, and the id is the only thing that does it.
        kw.setdefault("external_id", "999")
        return Match.objects.create(
            competition_season=self.cs, home_team=self.home_ts,
            away_team=self.away_ts, external_source=calendar_sync.PROVIDER, **kw)

    def _tick(self, iso):
        call_command("tick", "--now", iso, stdout=StringIO())


class TickCommandTests(_TickDBTests):
    """End-to-end: the tick command applies the state machine it owns."""

    def test_full_finalization_lifecycle(self):
        # This asserts the tick's STATE MACHINE (stamp FT, +15m/+1h), so the ingest
        # is mocked to succeed — the ingest itself is covered in tests_live_pipeline.
        ft = datetime(2026, 8, 22, 15, 45, tzinfo=UTC)
        m = self._match(status=Match.STATUS_FINISHED, kickoff=ft - timedelta(hours=2))

        with mock.patch("realdata.services.live_ingest.finalize", return_value=True), \
             mock.patch("realdata.services.live_ingest.live_round", return_value=True):
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


class ClockBehindTheDataTests(_TickDBTests):
    """A clock moved BACK under data already written — a rig started on one scenario
    over the database of another, which is the only way to produce it here and was
    the way it actually happened.

    Everything about the tick keeps working: the matches are candidates, they are in
    the live window, the loop runs. Only the cadence gate quietly never opens, and
    the log says the two words it says when there is honestly nothing to do."""

    LIVE_AT = datetime(2026, 8, 22, 20, 45, tzinfo=UTC)

    def _stranded(self):
        """Live, and stamped three hours after the clock we will tick at."""
        return self._match(status=Match.STATUS_LIVE, kickoff=self.LIVE_AT,
                           data_checked_at=self.LIVE_AT + timedelta(minutes=44))

    def test_a_future_stamp_gates_the_round_out_without_leaving_the_window(self):
        m = self._stranded()
        now = self.LIVE_AT - timedelta(hours=3)
        plan = plan_tick(now, [m])
        self.assertTrue(_in_live_window(m, now))   # still live by every other test
        self.assertEqual(plan.live_round, [])      # ...and yet nothing is due

    def test_the_drift_is_reported_as_the_gap_to_the_furthest_stamp(self):
        self._stranded()
        now = self.LIVE_AT - timedelta(hours=3)
        self.assertEqual(clock_drift(now), timedelta(hours=3, minutes=44))

    def test_the_tick_says_so_instead_of_only_nothing_due(self):
        self._stranded()
        out = StringIO()
        call_command("tick", "--now",
                     (self.LIVE_AT - timedelta(hours=3)).isoformat(),
                     "--dry-run", stdout=out)
        written = out.getvalue()
        self.assertIn("AVANTI all'orologio di 3h44m", written)
        self.assertIn("nothing due", written)      # the old words are still there

    def test_a_clock_merely_ahead_of_its_data_is_not_drift(self):
        """The ordinary case, and the one a guard must not cry over: data behind the
        clock is every match ever played."""
        self._match(status=Match.STATUS_FINISHED, kickoff=self.LIVE_AT,
                    data_checked_at=self.LIVE_AT)
        self.assertIsNone(clock_drift(self.LIVE_AT + timedelta(hours=3)))

    def test_a_stamp_a_few_seconds_ahead_is_not_worth_saying(self):
        """The tick writes the ``now`` it read, so a stamp equal to the clock is
        normal and one a hair past it is a corrected clock, not a rewound one."""
        self._match(status=Match.STATUS_LIVE, kickoff=self.LIVE_AT,
                    data_checked_at=self.LIVE_AT + timedelta(seconds=30))
        self.assertIsNone(clock_drift(self.LIVE_AT))

    def test_an_empty_database_has_no_opinion(self):
        self.assertIsNone(clock_drift(self.LIVE_AT))


class DataHighWaterTests(_TickDBTests):
    """Where `resume` gets its clock: how far the season was actually played, which
    is a question about the stamps and not about anybody's clock."""

    AT = datetime(2026, 8, 22, 20, 45, tzinfo=UTC)

    def test_nothing_imported_has_no_high_water(self):
        self._match(status=Match.STATUS_SCHEDULED, kickoff=self.AT)
        self.assertIsNone(data_high_water())

    def test_it_is_the_furthest_stamp_of_any_kind(self):
        """Whichever of the three ran last — a full-time seen after the last round
        is the ordinary case, and reading only data_checked_at would resume before
        it and re-play the end of the match."""
        self._match(status=Match.STATUS_FINISHED, kickoff=self.AT,
                    data_checked_at=self.AT + timedelta(minutes=90),
                    data_imported_at=self.AT + timedelta(minutes=88),
                    finished_at=self.AT + timedelta(minutes=97))
        self.assertEqual(data_high_water(), self.AT + timedelta(minutes=97))

    def test_it_is_the_furthest_across_matches_not_the_last_one(self):
        self._match(external_id="1", status=Match.STATUS_LIVE, kickoff=self.AT,
                    data_checked_at=self.AT + timedelta(minutes=30))
        self._match(external_id="2", status=Match.STATUS_LIVE, kickoff=self.AT,
                    data_checked_at=self.AT + timedelta(minutes=10))
        self.assertEqual(data_high_water(), self.AT + timedelta(minutes=30))

    def test_resuming_a_minute_past_it_leaves_no_drift(self):
        """The property the rig's `resume` rests on: the instant it computes is
        always AFTER the data, so the guard has nothing to say."""
        self._match(status=Match.STATUS_LIVE, kickoff=self.AT,
                    data_checked_at=self.AT + timedelta(minutes=30, seconds=30))
        top = data_high_water()
        resume_at = (top + timedelta(minutes=1)).replace(second=0, microsecond=0)
        self.assertGreater(resume_at, top)
        self.assertIsNone(clock_drift(resume_at))


class HumanGapTests(SimpleTestCase):
    def test_reads_as_hours_and_minutes(self):
        self.assertEqual(human_gap(timedelta(hours=2, minutes=51, seconds=18)),
                         "2h51m")

    def test_under_an_hour_drops_the_hours(self):
        self.assertEqual(human_gap(timedelta(minutes=7)), "7m")


class LiveRoundCadenceTests(SimpleTestCase):
    """The TIME knob: the tick may fire every minute, but a single match gets a
    round no more often than configured."""

    def setUp(self):
        self.now = datetime(2026, 8, 22, 15, 0, tzinfo=UTC)

    def _live(self, last_checked, last_imported=None):
        return _m(kickoff=self.now - timedelta(minutes=30),
                  data_checked_at=last_checked,
                  data_imported_at=last_imported)

    @override_settings(VFOOT_LIVE_POLL_MINUTES=2)
    def test_never_polled_is_due(self):
        m = self._live(None)
        self.assertIn(m, plan_tick(self.now, [m]).live_round)

    @override_settings(VFOOT_LIVE_POLL_MINUTES=2)
    def test_polled_recently_is_skipped(self):
        m = self._live(self.now - timedelta(seconds=30))
        self.assertEqual(plan_tick(self.now, [m]).live_round, [])

    @override_settings(VFOOT_LIVE_POLL_MINUTES=2)
    def test_polled_longer_ago_than_the_interval_is_due(self):
        m = self._live(self.now - timedelta(minutes=3))
        self.assertIn(m, plan_tick(self.now, [m]).live_round)

    @override_settings(VFOOT_LIVE_POLL_MINUTES=5)
    def test_widening_the_interval_reduces_scraping(self):
        m = self._live(self.now - timedelta(minutes=3))
        # at 5 minutes the same match is NOT yet due (it was at 2)
        self.assertEqual(plan_tick(self.now, [m]).live_round, [])


@override_settings(VFOOT_LIVE_POLL_MINUTES=2, VFOOT_LIVE_HEAVY_EVERY=4)
class LiveHeavyCadenceTests(SimpleTestCase):
    """The SHAPE knob: every k-th round also pulls the heatmaps.

    The property that matters is that the heavy pass is a FLAG ON A ROUND and not a
    second clock. Two clocks is what this used to be, and they competed: the light
    one, firing five times as often, would have kept pushing the heavy one's due
    time out for as long as the match lasted if they had shared a stamp — so they
    had one each, and then failed independently without either knowing.
    """

    def setUp(self):
        self.now = datetime(2026, 8, 22, 15, 0, tzinfo=UTC)

    def _live(self, last_imported, last_checked=None):
        return _m(kickoff=self.now - timedelta(minutes=30),
                  data_checked_at=last_checked,
                  data_imported_at=last_imported)

    def test_the_first_round_of_a_match_is_heavy(self):
        """So the zones — and with them the defensive exposure — are there from the
        first vote, instead of arriving k rounds late."""
        m = self._live(None, last_checked=None)
        plan = plan_tick(self.now, [m])
        self.assertIn(m, plan.live_round)
        self.assertIn(m, plan.live_heavy)

    def test_a_round_before_k_have_passed_is_light(self):
        m = self._live(self.now - timedelta(minutes=4),
                       last_checked=self.now - timedelta(minutes=2))
        plan = plan_tick(self.now, [m])
        self.assertIn(m, plan.live_round)
        self.assertEqual(plan.live_heavy, [])

    def test_after_k_intervals_the_round_is_heavy(self):
        m = self._live(self.now - timedelta(minutes=8),
                       last_checked=self.now - timedelta(minutes=2))
        plan = plan_tick(self.now, [m])
        self.assertIn(m, plan.live_heavy)

    def test_a_heavy_pass_never_happens_outside_a_round(self):
        """The whole point of one clock: with the light round not yet due, there is
        nothing for the heavy pass to ride on, however long ago it last ran."""
        m = self._live(self.now - timedelta(hours=1),
                       last_checked=self.now - timedelta(seconds=30))
        plan = plan_tick(self.now, [m])
        self.assertEqual(plan.live_round, [])
        self.assertEqual(plan.live_heavy, [])

    def test_the_heavy_bucket_is_a_subset_of_the_rounds(self):
        m = self._live(None)
        plan = plan_tick(self.now, [m])
        for heavy in plan.live_heavy:
            self.assertIn(heavy, plan.live_round)

    @override_settings(VFOOT_LIVE_HEAVY_EVERY=1)
    def test_k_of_one_makes_every_round_heavy(self):
        """The rig's escape hatch, and the reason it is not the default: at k=1 the
        distinction the cadence is built on does not exist."""
        m = self._live(self.now - timedelta(minutes=2),
                       last_checked=self.now - timedelta(minutes=2))
        plan = plan_tick(self.now, [m])
        self.assertIn(m, plan.live_heavy)

    def test_a_match_that_has_not_kicked_off_gets_nothing(self):
        m = _m(kickoff=self.now + timedelta(minutes=30))
        plan = plan_tick(self.now, [m])
        self.assertEqual((plan.live_round, plan.live_heavy), ([], []))
