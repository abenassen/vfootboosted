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

from realdata.services.calendar_sync import (
    SERIE_A_TID,
    resolve_competition_season,
    sync_calendar,
)


def _default_cache_dir() -> Path:
    # repo_root/historical-data/serie-a/sofascore/cache (same as import_sofascore)
    return (Path(__file__).resolve().parents[5]
            / "historical-data" / "serie-a" / "sofascore" / "cache")


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
        rounds = None
        if options["rounds"]:
            try:
                rounds = [int(r) for r in options["rounds"].split(",") if r.strip()]
            except ValueError as exc:
                raise CommandError(f"Invalid --rounds: {exc}") from exc

        if options["offline"] and options["season_id"] is None:
            self.stdout.write(self.style.WARNING(
                "--offline without --season-id: relying on a cached seasons list."))

        client = self._build_client(options)
        try:
            cs, season_id = resolve_competition_season(
                client, options["year"], season_id=options["season_id"],
                logger=self.stdout.write)

            self.stdout.write(self.style.NOTICE(
                f"Syncing calendar for {cs} (season_id={season_id})"
                f"{' rounds=' + str(rounds) if rounds else ''}"))

            report = sync_calendar(client, cs, season_id, rounds=rounds,
                                   logger=self.stdout.write)
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
