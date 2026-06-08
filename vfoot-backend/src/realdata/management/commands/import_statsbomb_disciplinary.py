from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.utils import OperationalError

from realdata.services.statsbomb_adapter import import_statsbomb_disciplinary_events


class Command(BaseCommand):
    help = "Import StatsBomb disciplinary events into provider-normalized realdata tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dataset-root",
            type=str,
            default=str(Path(__file__).resolve().parents[5] / "historical-data" / "serie-a" / "statsbomb"),
            help="Path to StatsBomb dataset root containing events/.",
        )
        parser.add_argument("--events-dir", type=str, default="events")
        parser.add_argument("--limit-matches", type=int, default=None)
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
                "Database appears busy/locked. Stop Django runserver and retry disciplinary import. "
                f"Details: {exc}"
            ) from exc

    def handle(self, *args, **options):
        dataset_root = Path(options["dataset_root"]).resolve()
        if not dataset_root.exists():
            raise CommandError(f"Dataset root not found: {dataset_root}")

        if not options["skip_lock_check"]:
            self._ensure_db_writable()

        self.stdout.write(self.style.NOTICE(f"Importing StatsBomb disciplinary data from: {dataset_root}"))
        result = import_statsbomb_disciplinary_events(
            dataset_root=dataset_root,
            events_dir=options["events_dir"],
            limit_matches=options["limit_matches"],
            safe_writes=options["safe_writes"],
        )
        self.stdout.write(self.style.SUCCESS("StatsBomb disciplinary import completed."))
        self.stdout.write(
            "\n".join(
                [
                    f"matches_scanned={result.matches}",
                    f"disciplinary_events={result.disciplinary_events}",
                ]
            )
        )
