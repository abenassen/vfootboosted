"""Backfill MatchAppearance.goals/assists from the cached SofaScore lineup stats.

The original SofaScore import stored minutes/is_starter but not the per-player
goals/assists (they were read on the fly from the cache by downstream scorers). The
adapter now persists them for future scrapes; this command fills the existing rows
for a season offline (no network), from the same cached lineups files.

    python manage.py backfill_appearance_goals --competition-season 2
"""

from __future__ import annotations

import json
import os

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from realdata.models import Match, MatchAppearance, Player

DEFAULT_CACHE = str(Path(settings.VFOOT_DATA_DIR) / "historical-data" / "serie-a" / "sofascore" / "cache")


class Command(BaseCommand):
    help = "Backfill MatchAppearance.goals/assists from cached SofaScore lineups."

    def add_arguments(self, parser):
        parser.add_argument("--competition-season", type=int, default=2)
        parser.add_argument("--cache-dir", default=DEFAULT_CACHE)

    def handle(self, *args, **opts):
        cs_id = opts["competition_season"]
        cache = opts["cache_dir"]
        ext_to_pid = {v: k for k, v in Player.objects.filter(external_source="sofascore")
                      .values_list("id", "external_id")}
        updated = no_file = scorers = 0
        for m in Match.objects.filter(competition_season_id=cs_id):
            if not m.external_id:
                continue
            path = f"{cache}/api_v1_event_{m.external_id}_lineups.json"
            if not os.path.exists(path):
                no_file += 1
                continue
            try:
                d = json.load(open(path))
            except ValueError:
                continue
            stats = {}
            for side in ("home", "away"):
                for pl in d.get(side, {}).get("players", []):
                    pid = ext_to_pid.get(str((pl.get("player") or {}).get("id")))
                    st = pl.get("statistics") or {}
                    if pid is not None:
                        stats[pid] = (int(st.get("goals", 0) or 0), int(st.get("goalAssist", 0) or 0))
            for app in MatchAppearance.objects.filter(match=m):
                g, a = stats.get(app.player_id, (0, 0))
                if app.goals != g or app.assists != a:
                    app.goals, app.assists = g, a
                    app.save(update_fields=["goals", "assists"])
                    updated += 1
                if g:
                    scorers += 1
        self.stdout.write(self.style.SUCCESS(
            f"updated {updated} appearances; scorer-appearances={scorers}; "
            f"matches w/o cache={no_file}"))
