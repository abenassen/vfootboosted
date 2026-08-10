"""Sync the local Match calendar for a real season from SofaScore.

Schedule-only (no per-match scraping): keeps Match rows in step with the
provider's published fixtures — kickoff, round, lifecycle status, and the
provisional-kickoff flag — and reports what changed since the last run.

Portable: this is a plain management command, so on the always-on server it is
driven by cron/systemd (e.g. daily, plus a lighter run on match days). The
transport is chosen by flag; default is OFFLINE (warm cache, no network) so it
is safe to run in dev.

    # dev, offline against the warm 25-26 cache (season id known)
    python manage.py sync_calendar --year 25/26 --season-id 76457 --offline

    # upcoming season, resolving the season id over the network (browser transport)
    python manage.py sync_calendar --year 26/27 --browser

    # cheap frequent run: only the current + next round
    python manage.py sync_calendar --year 26/27 --browser --rounds 1,2
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from django.utils import timezone as djtz

from realdata.services import egress_client, job_log
from realdata.services.calendar_sync import (
    SERIE_A_TID,
    resolve_competition_season,
    rounds_to_sync,
    sync_calendar,
    sync_is_due,
)


def _default_cache_dir() -> Path:
    # Same cache as import_sofascore. Driven by settings so the server can keep it
    # outside the checkout (VFOOT_DATA_DIR).
    return Path(settings.VFOOT_SOFASCORE_CACHE)


class Command(BaseCommand):
    help = "Sync the local Match calendar for a real season from SofaScore."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=str, default="25/26",
                            help="SofaScore season label, e.g. '26/27'.")
        parser.add_argument("--season-id", type=int, default=None,
                            help="Skip the network season lookup with a known id "
                                 "(e.g. 95836 for 26/27, 76457 for 25/26).")
        parser.add_argument("--rounds", type=str, default=None,
                            help="Comma-separated rounds to limit the sync "
                                 "(e.g. '1,2'); default = all published rounds.")
        parser.add_argument("--cache-dir", type=str, default=None,
                            help="Override the SofaScore cache directory.")
        parser.add_argument("--offline", action="store_true",
                            help="Use only the on-disk cache (no network). "
                                 "Requires --season-id if the seasons list "
                                 "isn't cached.")
        parser.add_argument("--egress", action="store_true",
                            help="Warm the schedule through the root SofaScore "
                                 "egress (Surfshark netns), then read it offline. "
                                 "The production transport on the Linode.")
        parser.add_argument("--browser", action="store_true",
                            help="Use the Playwright browser transport (passes "
                                 "Cloudflare) instead of the plain client.")
        parser.add_argument("--channel", type=str, default=None,
                            help="Browser channel, e.g. 'chrome' (with --browser).")
        parser.add_argument("--chromium-path", type=str, default=None,
                            help="Browser binary to drive; defaults to "
                                 "settings.VFOOT_CHROMIUM_PATH (the system Chromium "
                                 "on the server).")
        parser.add_argument("--headful", action="store_true",
                            help="Run the browser headful (with --browser).")
        parser.add_argument("--if-due", action="store_true",
                            help="Sync only if one is due — the floor interval has "
                                 "passed, or a kickoff is approaching. Lets the "
                                 "timer fire on a fixed cadence while the density "
                                 "follows the calendar. Needs --season-id.")
        parser.add_argument("--auto-rounds", action="store_true",
                            help="Pick the rounds from the calendar instead of "
                                 "--rounds: the next few, plus any earlier round "
                                 "that still owes a match. Needs --season-id.")

    def _build_client(self, options):
        cache_dir = Path(options["cache_dir"]) if options["cache_dir"] \
            else _default_cache_dir()
        if options["browser"]:
            # Playwright's sync API runs an asyncio loop, which makes Django flag
            # every ORM call as "async-unsafe". Here the DB writes are genuinely
            # synchronous (the browser loop never touches the DB) and this is a CLI
            # command, not a server, so allowing them is safe — and it lets a single
            # cron/systemd invocation do fetch + upsert in one process.
            import os
            os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")
            from realdata.services.sofascore_browser_client import (
                SofaScoreBrowserClient,
            )
            return SofaScoreBrowserClient(
                cache_dir, min_delay=1.0, logger=self.stdout.write,
                headless=not options["headful"], channel=options["channel"],
                chromium_path=(options["chromium_path"]
                               or getattr(settings, "VFOOT_CHROMIUM_PATH", None)),
                tournament_id=SERIE_A_TID)
        from realdata.services.sofascore_client import SofaScoreClient
        return SofaScoreClient(cache_dir=cache_dir, logger=self.stdout.write,
                               tournament_id=SERIE_A_TID)

    def handle(self, *args, **options):
        with job_log.record("sync_calendar") as run:
            self._sync(run, **options)

    def _sync(self, run, **options):
        rounds = None
        if options["rounds"]:
            try:
                rounds = [int(r) for r in options["rounds"].split(",") if r.strip()]
            except ValueError as exc:
                raise CommandError(f"Invalid --rounds: {exc}") from exc

        deciding = options["if_due"] or options["auto_rounds"]
        if deciding and options["season_id"] is None:
            # Both questions are about the calendar we ALREADY hold, and both have
            # to be asked before the warm — otherwise they cannot cancel it, which
            # is the entire saving. Answering them needs the edition without a
            # network round trip, and --season-id is what gives us that.
            raise CommandError("--if-due / --auto-rounds need --season-id.")

        if options["offline"] and options["season_id"] is None:
            self.stdout.write(self.style.WARNING(
                "--offline without --season-id: relying on a cached seasons list."))

        if options["egress"]:
            options["browser"] = False   # the egress fetches; here we only read

        client = self._build_client(options)
        try:
            cs = season_id = None
            if deciding:
                cs, season_id = resolve_competition_season(
                    client, options["year"], season_id=options["season_id"],
                    logger=self.stdout.write)
                if options["if_due"]:
                    due, why = sync_is_due(cs)
                    run.note(why)
                    self.stdout.write(f"Due? {'yes' if due else 'no'} — {why}")
                    if not due:
                        # Not owed: the row stays "quiet" (empty ``due``) on
                        # purpose. Nineteen scatti out of twenty end here, and if
                        # each left a busy row the interesting ones would drown.
                        return
                if options["auto_rounds"]:
                    rounds = rounds_to_sync(cs)
                    if not rounds:
                        self.stdout.write("Nothing owed: no round left to sync.")
                        return
            run.due(rounds=len(rounds) if rounds else 38)

            if options["egress"]:
                self.stdout.write(
                    f"Warming schedule {options['year']} via egress"
                    + (f" (rounds {rounds})…" if rounds else " (whole season)…"))
                if not egress_client.warm_schedule(options["year"], rounds):
                    raise CommandError("egress could not warm the schedule (blocked / "
                                       "no good exit IP). Nothing synced.")

            if cs is None:
                cs, season_id = resolve_competition_season(
                    client, options["year"], season_id=options["season_id"],
                    logger=self.stdout.write)

            self.stdout.write(self.style.NOTICE(
                f"Syncing calendar for {cs} (season_id={season_id})"
                f"{' rounds=' + str(rounds) if rounds else ''}"))

            report = sync_calendar(client, cs, season_id, rounds=rounds,
                                   logger=self.stdout.write)
            # ``fixtures`` is the number that matters most here: a sync that reads
            # the rounds it asked for and comes back with zero fixtures has found
            # an empty answer, which the summary line renders as a cheerful
            # "0 created, 0 updated" and looks like a day with no news.
            run.did(fixtures=report.total, created=report.created,
                    updated=report.updated, provisional=report.provisional,
                    postponed=sum(1 for c in report.changes
                                  if c.kind == "postponed"),
                    kickoff_moves=sum(1 for c in report.changes
                                      if c.kind == "kickoff"))
            if not options["offline"]:
                # Only after a read that really went out: the stamp is what the
                # next run measures "am I due?" from, so stamping an offline pass
                # would tell it the provider had been checked when it had not.
                cs.calendar_synced_at = djtz.now()
                cs.save(update_fields=["calendar_synced_at"])
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(report.summary()))
        if report.changes:
            self.stdout.write(f"\nChanges ({len(report.changes)}):")
            for ch in report.changes:
                self.stdout.write(f"  {ch}")
