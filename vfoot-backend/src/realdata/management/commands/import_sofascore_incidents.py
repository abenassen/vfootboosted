"""Ingest SofaScore card incidents (already SCRAPED into the local cache) into
MatchDisciplinaryEvent, for seasons whose import only handled lineups/stats.

The SofaScore import populates lineups/statistics/shotmap/heatmap but never parsed
the per-match `*_incidents.json` files, so cards (a fantacalcio malus) were missing
from the DB for the 2025-26 season. This reads those cached files (offline, no
network) and creates normalized disciplinary events.

    python manage.py import_sofascore_incidents --competition-season 2
"""

from __future__ import annotations

import glob
import json
import os

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from realdata.models import (
    CARD_RED,
    CARD_SECOND_YELLOW,
    CARD_UNKNOWN,
    CARD_YELLOW,
    Match,
    MatchDisciplinaryEvent,
    Player,
    PROVIDER_SOFASCORE,
    SIDE_AWAY,
    SIDE_HOME,
)

DEFAULT_CACHE = str(Path(settings.VFOOT_DATA_DIR) / "historical-data" / "serie-a" / "sofascore" / "cache")
# SofaScore incidentClass -> our card taxonomy
_CARD_CLASS = {"yellow": CARD_YELLOW, "red": CARD_RED, "yellowRed": CARD_SECOND_YELLOW}


class Command(BaseCommand):
    help = "Ingest cached SofaScore card incidents into MatchDisciplinaryEvent."

    def add_arguments(self, parser):
        parser.add_argument("--competition-season", type=int, default=2)
        parser.add_argument("--cache-dir", default=DEFAULT_CACHE)
        parser.add_argument("--reset", action="store_true",
                            help="delete existing sofascore disciplinary events for the "
                                 "season first (idempotent re-import)")

    def handle(self, *args, **opts):
        cs_id = opts["competition_season"]
        cache = opts["cache_dir"]
        ext_to_pid = {v: k for k, v in Player.objects.filter(external_source="sofascore")
                      .values_list("id", "external_id")}

        if opts["reset"]:
            n = MatchDisciplinaryEvent.objects.filter(
                match__competition_season_id=cs_id, provider=PROVIDER_SOFASCORE).delete()[0]
            self.stdout.write(f"reset: deleted {n} prior sofascore events")

        created = updated = skipped_no_player = no_file = cards = 0
        for m in Match.objects.filter(competition_season_id=cs_id):
            if not m.external_id:
                continue
            path = f"{cache}/api_v1_event_{m.external_id}_incidents.json"
            if not os.path.exists(path):
                no_file += 1
                continue
            try:
                data = json.load(open(path))
            except ValueError:
                continue
            for inc in data.get("incidents", []):
                if inc.get("incidentType") != "card":
                    continue
                cards += 1
                card_type = _CARD_CLASS.get(inc.get("incidentClass"), CARD_UNKNOWN)
                sofa_id = (inc.get("player") or {}).get("id")
                pid = ext_to_pid.get(str(sofa_id)) if sofa_id is not None else None
                if pid is None:
                    skipped_no_player += 1
                    continue
                minute = int(inc.get("time") or 0)
                side = SIDE_HOME if inc.get("isHome") else SIDE_AWAY
                # stable id so re-runs update rather than duplicate
                ev_id = f"card:{minute}:{sofa_id}:{inc.get('incidentClass')}"
                _, was_created = MatchDisciplinaryEvent.objects.update_or_create(
                    match=m, provider=PROVIDER_SOFASCORE, provider_event_id=ev_id,
                    card_type=card_type,
                    defaults={
                        "player_id": pid,
                        "team_side": side,
                        "minute": minute,
                        "reason": (inc.get("reason") or "")[:80],
                        "source_event_type": "card",
                        "source_card_name": inc.get("incidentClass") or "",
                        "payload": inc,
                    },
                )
                created += int(was_created)
                updated += int(not was_created)

        self.stdout.write(self.style.SUCCESS(
            f"cards seen={cards} created={created} updated={updated} "
            f"skipped(no player match)={skipped_no_player} matches w/o cache file={no_file}"))
