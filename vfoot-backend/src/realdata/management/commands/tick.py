"""Scheduler tick — the always-on heartbeat of the semiautomatic pipeline.

Runs frequently (e.g. every minute via cron/systemd on the server). Each run it
asks the DB "what is due now?" and acts:

* stamps observed full-time on freshly-finished matches;
* polls in-progress matches (live provisional data);
* runs the +15min / +1h post-FT finalization, promoting a match to
  ``data_ready`` at confirmation.

Phase-1 scope: the STATE MACHINE and scheduling decisions are real and applied;
the per-match SCRAPE calls are stubbed (logged as the action that will be wired
in the ingestion phase). So the timing/finalization logic is fully exercisable
now, and the scrapers drop into clearly marked hooks later.

    python manage.py tick                     # apply, real clock
    python manage.py tick --dry-run           # report only
    python manage.py tick --now 2026-08-22T15:30:00Z --dry-run   # test a moment
"""
from __future__ import annotations

from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as djtz

from realdata.models import Match
from realdata.services import live_ingest
from realdata.services.match_scheduler import candidate_matches, plan_tick


class Command(BaseCommand):
    help = "One scheduler tick: advance live/finalization state for due matches."

    def add_arguments(self, parser):
        parser.add_argument("--now", type=str, default=None,
                            help="Override the clock (ISO 8601, e.g. "
                                 "'2026-08-22T15:30:00Z'); for testing.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report due actions without mutating anything.")

    def _resolve_now(self, raw) -> datetime:
        if not raw:
            return djtz.now()
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CommandError(f"Invalid --now {raw!r}: {exc}") from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    # -- main --------------------------------------------------------------

    def handle(self, *args, **options):
        now = self._resolve_now(options["now"])
        dry = options["dry_run"]

        matches = list(candidate_matches())
        plan = plan_tick(now, matches)

        mode = "DRY-RUN" if dry else "APPLY"
        self.stdout.write(self.style.NOTICE(
            f"tick @ {now.isoformat()} [{mode}] — "
            f"{len(matches)} candidate matches — {plan.summary()}"))

        if plan.is_empty():
            self.stdout.write("  nothing due")
            return

        # 1) Stamp observed full-time (state we own).
        for m in plan.stamp_ft:
            self.stdout.write(f"  [stamp-ft] {m} — full-time observed")
            if not dry:
                m.finished_at = now
                m.save(update_fields=["finished_at"])

        # 2) Live polling: warm + update status/score (honours the per-match
        #    cadence via data_checked_at). Only stamp checked on a real warm, so a
        #    blocked egress simply retries next tick.
        for m in plan.live_poll:
            if dry:
                self.stdout.write(f"  [live-poll] {m} — would warm+update")
                continue
            if live_ingest.poll_live(m):
                m.data_checked_at = now
                m.save(update_fields=["data_checked_at"])
                self.stdout.write(
                    f"  [live-poll] {m} — {m.status} {m.home_goals}-{m.away_goals}")
            else:
                self.stdout.write(f"  [live-poll] {m} — egress blocked; will retry")

        # 3) Finalization: +15min provisional-final import.
        for m in plan.final_check:
            if dry:
                self.stdout.write(f"  [final-check] {m} — would warm+import")
                continue
            if live_ingest.finalize(m):
                m.data_checked_at = now
                m.save(update_fields=["data_checked_at"])
                self.stdout.write(f"  [final-check] {m} — imported (provisional)")
            else:
                self.stdout.write(f"  [final-check] {m} — egress blocked; will retry")

        # 4) Finalization: +1h confirmation -> data_ready (official).
        for m in plan.final_confirm:
            if dry:
                self.stdout.write(f"  [final-confirm] {m} — would warm+import -> data_ready")
                continue
            if live_ingest.finalize(m):
                m.data_checked_at = now
                m.data_ready = True
                m.save(update_fields=["data_checked_at", "data_ready"])
                self.stdout.write(f"  [final-confirm] {m} — data_ready")
            else:
                self.stdout.write(f"  [final-confirm] {m} — egress blocked; will retry")

        if not dry:
            self.stdout.write(self.style.SUCCESS("  applied"))
