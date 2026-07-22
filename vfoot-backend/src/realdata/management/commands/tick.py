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

    # -- scrape hooks (stubbed in Phase 1) ---------------------------------

    def _scrape_live(self, match, now):
        # TODO(ingestion phase): scrape live stats/incidents; update status,
        # goals, and set finished_at when the provider flips to finished.
        self.stdout.write(f"  [live-poll] {match} — would scrape provisional data")

    def _scrape_final(self, match, now, *, confirm: bool):
        # TODO(ingestion phase): scrape the full final data set (shotmap +
        # heatmaps + per-player stats + incidents) and compute definitive votes.
        tag = "confirm" if confirm else "check"
        self.stdout.write(f"  [final-{tag}] {match} — would scrape final data")

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

        # 2) Live polling (stamp it, so the cadence above can be honoured).
        for m in plan.live_poll:
            self._scrape_live(m, now)
            if not dry:
                m.data_checked_at = now
                m.save(update_fields=["data_checked_at"])

        # 3) Finalization: +15min provisional-final re-scrape.
        for m in plan.final_check:
            self._scrape_final(m, now, confirm=False)
            if not dry:
                m.data_checked_at = now
                m.save(update_fields=["data_checked_at"])

        # 4) Finalization: +1h confirmation -> data_ready.
        for m in plan.final_confirm:
            self._scrape_final(m, now, confirm=True)
            if not dry:
                m.data_checked_at = now
                m.data_ready = True
                m.save(update_fields=["data_checked_at", "data_ready"])

        if not dry:
            self.stdout.write(self.style.SUCCESS("  applied"))
