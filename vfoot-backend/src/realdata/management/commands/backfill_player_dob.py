"""Backfill Player.date_of_birth from cached SofaScore lineups.

SofaScore lineups carry ``player.dateOfBirthTimestamp`` for every player, but the
original import didn't store it. This reads the on-disk request cache OFFLINE
(no network) and sets ``date_of_birth`` on existing sofascore Player rows — a
strong key for future cross-provider (StatsBomb<->SofaScore) identity matching.
Idempotent: re-running changes nothing once filled.

    python manage.py backfill_player_dob
"""

from __future__ import annotations

import glob
import json
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand

from realdata.models import Player, PROVIDER_SOFASCORE


class Command(BaseCommand):
    help = "Backfill Player.date_of_birth from cached SofaScore lineups."

    def add_arguments(self, parser):
        parser.add_argument(
            "--cache-dir", default=None,
            help="SofaScore request cache dir (default: the project's "
                 "historical-data/serie-a/sofascore/cache).")

    def handle(self, *args, **options):
        cache_dir = (Path(options["cache_dir"]) if options["cache_dir"]
                     else (Path(__file__).resolve().parents[5]
                           / "historical-data" / "serie-a" / "sofascore" / "cache"))
        files = sorted(glob.glob(str(cache_dir / "api_v1_event_*_lineups.json")))
        if not files:
            self.stderr.write(f"No lineups files in {cache_dir}")
            return

        # collect player_id -> date_of_birth from every cached lineup
        dob_by_id: dict[str, "datetime.date"] = {}
        for f in files:
            try:
                data = json.load(open(f))
            except (OSError, ValueError):
                continue
            for side in ("home", "away"):
                for entry in (data.get(side) or {}).get("players", []):
                    pl = entry.get("player") or {}
                    pid = pl.get("id")
                    ts = pl.get("dateOfBirthTimestamp")
                    if pid is None or ts is None:
                        continue
                    try:
                        dob_by_id[str(pid)] = datetime.fromtimestamp(
                            int(ts), tz=timezone.utc).date()
                    except (TypeError, ValueError, OSError):
                        continue

        self.stdout.write(f"Parsed {len(files)} lineups; "
                          f"{len(dob_by_id)} distinct players with a DOB.")

        players = {p.external_id: p for p in
                   Player.objects.filter(external_source=PROVIDER_SOFASCORE)}
        changed, missing = [], 0
        for ext_id, dob in dob_by_id.items():
            p = players.get(ext_id)
            if p is None:
                missing += 1
                continue
            if p.date_of_birth != dob:
                p.date_of_birth = dob
                changed.append(p)

        Player.objects.bulk_update(changed, ["date_of_birth"], batch_size=500)
        already = len(players) - len(changed)
        self.stdout.write(self.style.SUCCESS(
            f"Updated {len(changed)} players; {already} already correct/blank; "
            f"{missing} cached ids had no matching Player row."))
        with_dob = Player.objects.filter(
            external_source=PROVIDER_SOFASCORE, date_of_birth__isnull=False).count()
        self.stdout.write(f"sofascore players with DOB now: "
                          f"{with_dob}/{len(players)}")
