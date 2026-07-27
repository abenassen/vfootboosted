"""Backfill MatchShot.elapsed_seconds and .situation from the cached SofaScore shotmaps.

New imports capture the shot's ``timeSeconds`` and ``situation`` (see
sofascore_adapter), but rows imported before that lack them. This reads the shotmaps
already cached under VFOOT_DATA_DIR (offline, no network) and fills both by the
provider shot id. elapsed_seconds lets own goals be graded by fault (a deflection
shares the moment of the shot it turned in); situation flags penalties, so a missed
one carries the -3 fantavoto malus and a result-scaled voto-puro drop (see
classic_rating.penalty_missed_adjustments).

    python manage.py backfill_shot_seconds --season 2
    python manage.py backfill_shot_seconds --season 2 --dry-run
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from realdata.models import CompetitionSeason, Match, MatchShot


class Command(BaseCommand):
    help = "Fill MatchShot.elapsed_seconds from the cached SofaScore shotmaps."

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, required=True)
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
        read = missing = filled = 0
        for m in matches:
            f = cache / f"api_v1_event_{m.external_id}_shotmap.json"
            if not f.exists():
                missing += 1
                continue
            data = json.loads(f.read_text())
            meta = {}  # shot id -> (timeSeconds|None, situation|"")
            for s in (data.get("shotmap") or []):
                sid = s.get("id")
                if sid is None:
                    continue
                ts = s.get("timeSeconds")
                meta[str(sid)] = (int(ts) if isinstance(ts, (int, float)) else None,
                                  str(s.get("situation") or "")[:24])
            to_update = []
            for shot in MatchShot.objects.filter(match=m).exclude(external_id=""):
                info = meta.get(shot.external_id)
                if not info:
                    continue
                ts, sit = info
                dirty = False
                if ts is not None and shot.elapsed_seconds != ts:
                    shot.elapsed_seconds = ts; dirty = True
                if sit and shot.situation != sit:
                    shot.situation = sit; dirty = True
                if dirty:
                    to_update.append(shot)
            filled += len(to_update)
            if to_update and not o["dry_run"]:
                MatchShot.objects.bulk_update(to_update, ["elapsed_seconds", "situation"])
            read += 1

        verb = "sarebbero aggiornati" if o["dry_run"] else "aggiornati"
        self.stdout.write(f"shotmap lette: {read}/{len(matches)} (mancanti: {missing})")
        self.stdout.write(self.style.SUCCESS(f"tiri {verb}: {filled}"))
