from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.utils import OperationalError

from realdata.services.statsbomb_adapter import ingest_statsbomb


class Command(BaseCommand):
    help = "Import StatsBomb historical dataset into realdata feature tables (feature-only mode)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dataset-root",
            type=str,
            default=str(Path(__file__).resolve().parents[5] / "historical-data" / "serie-a" / "statsbomb"),
            help="Path to StatsBomb dataset root containing matches/events/lineups.",
        )
        parser.add_argument("--matches-file", type=str, default="matches_12_27.json")
        parser.add_argument("--events-dir", type=str, default="events")
        parser.add_argument("--lineups-dir", type=str, default="lineups")
        parser.add_argument("--limit-matches", type=int, default=None)
        parser.add_argument("--zone-cols", type=int, default=5)
        parser.add_argument("--zone-rows", type=int, default=4)
        parser.add_argument("--data-version", type=str, default="statsbomb_seriea_2015_2016_v1")
        parser.add_argument("--formula-version", type=str, default="features_v1")
        parser.add_argument(
            "--skip-events",
            action="store_true",
            help="Only import entities/appearances from matches + lineups.",
        )
        parser.add_argument(
            "--safe-writes",
            action="store_true",
            help="Use conservative inserts (slower) with fallback for local SQLite edge cases.",
        )
        parser.add_argument(
            "--skip-lock-check",
            action="store_true",
            help="Skip pre-import SQLite lock check.",
        )

    def _ensure_db_writable(self):
        try:
            with connection.cursor() as cursor:
                cursor.execute("BEGIN IMMEDIATE;")
                cursor.execute("ROLLBACK;")
        except OperationalError as exc:
            raise CommandError(
                "Database appears busy/locked. Stop Django runserver and retry import. "
                f"Details: {exc}"
            ) from exc

    def handle(self, *args, **options):
        dataset_root = Path(options["dataset_root"]).resolve()
        if not dataset_root.exists():
            raise CommandError(f"Dataset root not found: {dataset_root}")

        if not options["skip_lock_check"]:
            self._ensure_db_writable()

        self.stdout.write(self.style.NOTICE(f"Importing StatsBomb data from: {dataset_root}"))
        result = ingest_statsbomb(
            dataset_root=dataset_root,
            matches_file=options["matches_file"],
            events_dir=options["events_dir"],
            lineups_dir=options["lineups_dir"],
            limit_matches=options["limit_matches"],
            zone_cols=options["zone_cols"],
            zone_rows=options["zone_rows"],
            include_events=not options["skip_events"],
            safe_writes=options["safe_writes"],
            data_version=options["data_version"],
            formula_version=options["formula_version"],
        )

        self.stdout.write(self.style.SUCCESS("StatsBomb import completed."))
        self.stdout.write(
            "\n".join(
                [
                    f"matches={result.matches}",
                    f"teams={result.teams}",
                    f"players={result.players}",
                    f"appearances={result.appearances}",
                    f"player_zone_features={result.player_zone_features}",
                    f"team_zone_features={result.team_zone_features}",
                ]
            )
        )
