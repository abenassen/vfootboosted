"""Backfill the coarse SofaScore lineup position onto existing appearances.

New imports store ``MatchAppearance.raw_stats['position']`` (F/M/D/G) directly (see
sofascore_adapter), but rows imported before that field existed lack it. The role
inference uses this position to disambiguate players with too few minutes to
cluster, so this one-off reads the local /lineups cache and fills it in.

    python manage.py backfill_sofascore_position --season 2
    python manage.py backfill_sofascore_position --season 2 --dry-run

Offline: it only reads the JSON already cached under VFOOT_DATA_DIR, no network.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from realdata.models import CompetitionSeason, Match, MatchAppearance


class Command(BaseCommand):
    help = "Fill MatchAppearance.raw_stats['position'] from the SofaScore lineup cache."

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, required=True,
                            help="CompetitionSeason whose appearances get the position.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        if not CompetitionSeason.objects.filter(id=o["season"]).exists():
            raise CommandError(f"No CompetitionSeason id={o['season']}")
        cache = (Path(settings.VFOOT_DATA_DIR)
                 / "historical-data" / "serie-a" / "sofascore" / "cache")
        if not cache.is_dir():
            raise CommandError(f"Cache dir not found: {cache}")

        matches = list(Match.objects.filter(competition_season_id=o["season"])
                       .exclude(external_id=""))
        updated = missing_file = filled = 0
        for m in matches:
            f = cache / f"api_v1_event_{m.external_id}_lineups.json"
            if not f.exists():
                missing_file += 1
                continue
            data = json.loads(f.read_text())
            pos_by_ext = {}
            for side in ("home", "away"):
                for pl in (data.get(side) or {}).get("players", []):
                    ext = (pl.get("player") or {}).get("id")
                    if ext is not None and pl.get("position"):
                        pos_by_ext[str(ext)] = str(pl["position"])
            for app in (MatchAppearance.objects.filter(match=m)
                        .select_related("player")):
                pos = pos_by_ext.get(str(app.player.external_id))
                if not pos:
                    continue
                rs = dict(app.raw_stats or {})
                if rs.get("position") == pos:
                    continue
                rs["position"] = pos
                filled += 1
                if not o["dry_run"]:
                    app.raw_stats = rs
                    app.save(update_fields=["raw_stats"])
            updated += 1

        verb = "sarebbero aggiornate" if o["dry_run"] else "aggiornate"
        self.stdout.write(f"partite con cache lette : {updated}/{len(matches)}"
                          f" (cache mancante: {missing_file})")
        self.stdout.write(self.style.SUCCESS(f"posizioni {verb}: {filled}"))
