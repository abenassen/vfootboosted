from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from realdata.models import Match, MatchAppearance, PROVIDER_STATSBOMB
from realdata.services.statsbomb_adapter import _extract_minutes_and_starter


class Command(BaseCommand):
    help = "Update StatsBomb MatchAppearance minutes/is_starter from raw lineup files without reimporting features."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dataset-root",
            type=str,
            default="../../historical-data/serie-a/statsbomb",
            help="Path to StatsBomb dataset root containing lineups/*.json.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dataset_root = Path(options["dataset_root"]).resolve()
        lineups_dir = dataset_root / "lineups"
        dry_run = bool(options["dry_run"])
        if not lineups_dir.exists():
            self.stdout.write(self.style.ERROR(f"Lineups directory not found: {lineups_dir}"))
            return

        matches = {
            match.external_id: match
            for match in Match.objects.filter(external_source=PROVIDER_STATSBOMB).only("id", "external_id")
        }

        scanned = 0
        changed = 0
        missing_match = 0
        missing_appearance = 0
        zero_to_nonzero = 0

        with transaction.atomic():
            for path in sorted(lineups_dir.glob("*.json")):
                match = matches.get(path.stem)
                if not match:
                    missing_match += 1
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                for team_entry in data:
                    for player_entry in team_entry.get("lineup", []):
                        positions = player_entry.get("positions") or []
                        minutes, is_starter = _extract_minutes_and_starter(positions)
                        player_external_id = str(player_entry.get("player_id"))
                        appearance = (
                            MatchAppearance.objects.filter(
                                match=match,
                                player__external_source=PROVIDER_STATSBOMB,
                                player__external_id=player_external_id,
                            )
                            .select_related("player")
                            .first()
                        )
                        scanned += 1
                        if appearance is None:
                            missing_appearance += 1
                            continue
                        if appearance.minutes_played == 0 and minutes > 0:
                            zero_to_nonzero += 1
                        if appearance.minutes_played != minutes or appearance.is_starter != is_starter:
                            changed += 1
                            if not dry_run:
                                appearance.minutes_played = minutes
                                appearance.is_starter = is_starter
                                appearance.save(update_fields=["minutes_played", "is_starter"])

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS(
                "StatsBomb minutes sync "
                f"scanned={scanned} changed={changed} zero_to_nonzero={zero_to_nonzero} "
                f"missing_match={missing_match} missing_appearance={missing_appearance} dry_run={dry_run}"
            )
        )

