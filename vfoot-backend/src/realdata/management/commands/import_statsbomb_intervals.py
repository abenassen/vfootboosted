from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.utils import OperationalError

from realdata.services.statsbomb_adapter import import_statsbomb_on_pitch_intervals


class Command(BaseCommand):
    help = "Import StatsBomb on-pitch intervals into provider-normalized realdata tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dataset-root",
            type=str,
            default=str(Path(__file__).resolve().parents[5] / "historical-data" / "serie-a" / "statsbomb"),
            help="Path to StatsBomb dataset root containing lineups/.",
        )
        parser.add_argument("--lineups-dir", type=str, default="lineups")
        parser.add_argument("--events-dir", type=str, default="events")
        parser.add_argument("--limit-matches", type=int, default=None)
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
                "Database appears busy/locked. Stop Django runserver and retry interval import. "
                f"Details: {exc}"
            ) from exc

    def handle(self, *args, **options):
        dataset_root = Path(options["dataset_root"]).resolve()
        if not dataset_root.exists():
            raise CommandError(f"Dataset root not found: {dataset_root}")

        if not options["skip_lock_check"]:
            self._ensure_db_writable()

        self.stdout.write(self.style.NOTICE(f"Importing StatsBomb on-pitch intervals from: {dataset_root}"))
        result = import_statsbomb_on_pitch_intervals(
            dataset_root=dataset_root,
            lineups_dir=options["lineups_dir"],
            events_dir=options["events_dir"],
            limit_matches=options["limit_matches"],
        )
        self.stdout.write(self.style.SUCCESS("StatsBomb interval import completed."))
        self.stdout.write(
            "\n".join(
                [
                    f"matches_scanned={result.matches}",
                    f"players_created={result.players}",
                    f"on_pitch_intervals={result.on_pitch_intervals}",
                ]
            )
        )
