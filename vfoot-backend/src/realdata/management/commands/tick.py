"""Scheduler tick — the always-on heartbeat of the semiautomatic pipeline.

Runs frequently (e.g. every minute via cron/systemd on the server). Each run it
asks the DB "what is due now?" and acts:

* stamps observed full-time on freshly-finished matches;
* polls in-progress matches (light: lifecycle and score);
* imports the FULL per-player data of in-progress matches on a slower clock, so
  the votes move while the match is being played — without promoting it;
* runs the +15min / +1h post-FT finalization, promoting a match to
  ``data_ready`` at confirmation.

It is also where the two ways of telling somebody are triggered, and they are not
interchangeable. The WebSocket nudge goes to pages that are OPEN, after any import
that changed something. The push goes to people who are NOT looking — a goal by one
of their players, a sending-off, full time — and never for a vote that moved, which
would be unbearable.

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

        # Imported here and not at module scope: the tick belongs to realdata, the
        # leagues to vfoot, and only this step needs to cross.
        from vfoot.services import live_updates

        # Collected across every step and sent ONCE at the end. A Sunday evening
        # tick imports three matches; nudging inside the loop had every open page
        # re-read the whole calendar three times in eight seconds, for a round that
        # changed once.
        nudge: set[int] = set()

        # 1) Stamp observed full-time (state we own). This is the ONE instant at
        #    which a match is first seen to be over, so it is where the full-time
        #    notification belongs — not in the import, which runs again afterwards.
        for m in plan.stamp_ft:
            self.stdout.write(f"  [stamp-ft] {m} — full-time observed")
            if not dry:
                m.finished_at = now
                m.save(update_fields=["finished_at"])
                sent = live_updates.announce_full_time(m)
                nudge |= live_updates.leagues_to_nudge(m)
                if sent:
                    self.stdout.write(f"    push fine partita: {sent}")

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

        # 3) Live import: the full per-player data of a match still being played.
        #    data_ready is NOT touched — the votes this produces are provisional by
        #    construction, and that is what the league marks them as.
        for m in plan.live_import:
            if dry:
                self.stdout.write(f"  [live-import] {m} — would warm+import (live)")
                continue
            before = live_updates.snapshot_events(m)
            if not live_ingest.import_live(m):
                self.stdout.write(f"  [live-import] {m} — egress blocked; will retry")
                continue
            m.data_imported_at = now
            m.save(update_fields=["data_imported_at"])
            events = live_updates.announce_events(m, before)
            nudge |= live_updates.leagues_to_nudge(m)
            self.stdout.write(
                f"  [live-import] {m} — imported (provisional)"
                + (f", push: {events}" if events else ""))

        # 5) Finalization: +15min provisional-final import.
        for m in plan.final_check:
            if dry:
                self.stdout.write(f"  [final-check] {m} — would warm+import")
                continue
            if live_ingest.finalize(m):
                m.data_checked_at = now
                m.data_imported_at = now
                m.save(update_fields=["data_checked_at", "data_imported_at"])
                nudge |= live_updates.leagues_to_nudge(m)
                self.stdout.write(f"  [final-check] {m} — imported (provisional)")
            else:
                self.stdout.write(f"  [final-check] {m} — egress blocked; will retry")

        # 6) Finalization: +1h confirmation -> data_ready (official). The nudge here
        #    is the one that clears the "provvisorio" mark on every open page.
        for m in plan.final_confirm:
            if dry:
                self.stdout.write(f"  [final-confirm] {m} — would warm+import -> data_ready")
                continue
            if live_ingest.finalize(m):
                m.data_checked_at = now
                m.data_imported_at = now
                m.data_ready = True
                m.save(update_fields=["data_checked_at", "data_imported_at",
                                      "data_ready"])
                nudge |= live_updates.leagues_to_nudge(m)
                self.stdout.write(f"  [final-confirm] {m} — data_ready")
            else:
                self.stdout.write(f"  [final-confirm] {m} — egress blocked; will retry")

        if nudge:
            live_updates.broadcast_leagues(nudge)
            self.stdout.write(f"  {len(nudge)} leghe avvisate")

        if not dry:
            self.stdout.write(self.style.SUCCESS("  applied"))
