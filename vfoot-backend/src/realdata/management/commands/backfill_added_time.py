"""Backfill Match.added_time_second_half from the cached SofaScore incidents.

New imports read the announced stoppage time themselves (see
``sofascore_intervals.second_half_added_minutes``); matches imported before that
lack it, and the senza-voto gate then assumes the usual five minutes. This reads
the incidents already cached under VFOOT_DATA_DIR (offline, no network).

    python manage.py backfill_added_time --season 2
    python manage.py backfill_added_time --season 2 --dry-run

L'ultima riga e' il controllo del deploy: «partite giocate senza recupero» deve
essere 0 (un incidente ``injuryTime`` manca solo se il fornitore non l'ha mai
pubblicato, ed e' il caso da guardare a mano).
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from realdata.models import CompetitionSeason, Match
from realdata.services.sofascore_intervals import second_half_added_minutes


class Command(BaseCommand):
    help = "Fill Match.added_time_second_half from the cached SofaScore incidents."

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

        matches = list(Match.objects
                       .filter(competition_season_id=o["season"], status="finished")
                       .exclude(external_id=""))
        changed = missing_file = no_announcement = 0
        for m in matches:
            f = cache / f"api_v1_event_{m.external_id}_incidents.json"
            if not f.exists():
                missing_file += 1
                continue
            added = second_half_added_minutes(json.loads(f.read_text()).get("incidents", []))
            if added is None:
                no_announcement += 1
                continue
            if m.added_time_second_half != added:
                changed += 1
                if not o["dry_run"]:
                    m.added_time_second_half = added
                    m.save(update_fields=["added_time_second_half"])
        verb = "da aggiornare" if o["dry_run"] else "aggiornate"
        self.stdout.write(f"{len(matches)} partite giocate · {verb} {changed} · "
                          f"incidenti non in cache {missing_file}")
        self.stdout.write(self.style.SUCCESS(
            f"partite giocate senza recupero annunciato: {no_announcement}"))
