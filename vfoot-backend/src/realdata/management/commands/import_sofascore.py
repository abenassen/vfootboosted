"""Import SofaScore Serie A data into the realdata zone-feature schema.

Fetch layer is a controlled curl_cffi client (``SofaScoreClient``) with
per-request throttling, on-disk cache, and clean stop-on-block; this command
wires it to ``sofascore_adapter.ingest_sofascore_season``.

Prerequisites (run these yourself — they touch the network / install tooling):

    pip install curl_cffi

Typical usage:

    # 1. discover the exact SofaScore year string for the season you want
    python manage.py import_sofascore --list-seasons

    # 2. PILOT a single match first, to verify mapping + orientation
    python manage.py import_sofascore --year 25/26 --pilot 13980073 --no-skip-existing

    # 3. full season (resumable: re-run skips done matches AND cached requests)
    python manage.py import_sofascore --year 25/26
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from realdata.services.sofascore_adapter import (
    LEAGUE_KEY,
    ingest_sofascore_season,
    season_code_from_year,
)
from realdata.services.sofascore_client import SofaScoreClient, SofaScoreError


class Command(BaseCommand):
    help = "Import SofaScore Serie A data (via ScraperFC) as zone features."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=str, default="25/26",
                            help="SofaScore season year string, e.g. '25/26'.")
        parser.add_argument("--season-code", type=str, default=None,
                            help="Override Season.code (default derived, e.g. 2025-2026).")
        parser.add_argument("--pilot", type=str, default=None,
                            help="Comma-separated match id(s) to ingest only (pilot mode).")
        parser.add_argument("--limit-matches", type=int, default=None)
        parser.add_argument("--no-skip-existing", action="store_true",
                            help="Re-ingest matches even if they already have features.")
        parser.add_argument("--include-unfinished", action="store_true",
                            help="Also ingest matches not marked 'finished'.")
        parser.add_argument("--zone-cols", type=int, default=5)
        parser.add_argument("--zone-rows", type=int, default=4)
        parser.add_argument("--flip-away", action="store_true",
                            help="Mirror away-team coords if SofaScore uses an absolute frame.")
        parser.add_argument("--delay", type=float, default=2.0,
                            help="Seconds to wait before every request (throttle).")
        parser.add_argument("--list-seasons", action="store_true",
                            help="Print the valid SofaScore seasons for Serie A and exit.")

    def handle(self, *args, **options):
        cache_dir = (Path(__file__).resolve().parents[5]
                     / "historical-data" / "serie-a" / "sofascore" / "cache")
        try:
            client = SofaScoreClient(
                cache_dir=cache_dir,
                min_delay=options["delay"],
                logger=lambda msg: self.stdout.write(msg),
            )
        except SofaScoreError as exc:
            raise CommandError(str(exc)) from exc

        if options["list_seasons"]:
            seasons = client.get_valid_seasons()
            self.stdout.write(self.style.NOTICE(f"Valid SofaScore seasons for {LEAGUE_KEY}:"))
            for year, season_id in seasons.items():
                self.stdout.write(f"  {year}  -> id {season_id}  (Season.code "
                                  f"{season_code_from_year(year)})")
            return

        match_ids = None
        if options["pilot"]:
            match_ids = [int(x) for x in options["pilot"].split(",") if x.strip()]

        self.stdout.write(self.style.NOTICE(
            f"Importing SofaScore {LEAGUE_KEY} {options['year']} (pilot={match_ids}) "
            f"min_delay={options['delay']}s\n  cache={cache_dir}"))

        result = ingest_sofascore_season(
            scraper=client,
            year=options["year"],
            season_code=options["season_code"],
            only_finished=not options["include_unfinished"],
            skip_existing=not options["no_skip_existing"],
            limit_matches=options["limit_matches"],
            match_ids=match_ids,
            zone_cols=options["zone_cols"],
            zone_rows=options["zone_rows"],
            flip_away=options["flip_away"],
            logger=lambda msg: self.stdout.write(msg),
        )

        self.stdout.write(self.style.SUCCESS("SofaScore import completed."))
        self.stdout.write("\n".join([
            f"matches={result.matches}",
            f"teams={result.teams}",
            f"players={result.players}",
            f"appearances={result.appearances}",
            f"cards={result.cards}",
            f"player_zone_features={result.player_zone_features}",
            f"team_zone_features={result.team_zone_features}",
            f"players_without_heatmap={result.players_without_heatmap}",
            f"skipped_not_finished={result.skipped_not_finished}",
            f"skipped_existing={result.skipped_existing}",
        ]))
