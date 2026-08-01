"""Write the versioned snapshot of season player ratings (the listone "valore").

Why a file in the repository and not a table in the database: the slim copy from
``export_dev_db`` has no zone features, so the votes cannot be recomputed there —
and a table would have to be filled BEFORE the export, which does nothing for the
copies people have already downloaded. Shipping the numbers with the SOURCE reaches
those too, with a plain ``git pull``, and without asking anyone to replace their
database and lose the leagues and test data inside it. It is 9 KB of JSON against
54 MB of SQLite.

It is a FALLBACK, never an override: ``season_player_ratings`` uses it only when
computing from the zone features yields nothing. A full database always wins.

Run it whenever the scoring model changes — same discipline as
``calibrate_vote_reference``, and in the same order: calibrate first, snapshot
after, because the snapshot records the fingerprint of the model that produced it
and warns at read time when the two no longer agree.

    manage.py build_player_ratings_snapshot
    manage.py build_player_ratings_snapshot --check   # CI: is it up to date?
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from realdata.models import CompetitionSeason
from vfoot.services.classic_pagella import data_version
from vfoot.services.player_ratings import (
    SNAPSHOT_PATH, _compute_season_player_ratings, clear_snapshot_cache,
)
from vfoot.services.vote_reference import scoring_fingerprint


def build_snapshot() -> dict:
    """Recompute every scoreable season from the zone features."""
    seasons = {}
    for cs in CompetitionSeason.objects.all().order_by("season__code"):
        # Deliberately the raw computation, not season_player_ratings: going
        # through the cache could write the previous snapshot back into the new
        # one, and going through the fallback would let a stale file perpetuate
        # itself for a season that can no longer be computed.
        ratings = _compute_season_player_ratings(cs.id)
        if not ratings:
            continue
        seasons[str(cs.id)] = {
            "label": str(cs),
            "data_version": data_version(cs.id),
            "ratings": {str(pid): [d["avg"], d["n"]]
                        for pid, d in sorted(ratings.items())},
        }
    return {"scoring_fingerprint": scoring_fingerprint(), "seasons": seasons}


class Command(BaseCommand):
    help = "Write vfoot/data/player_ratings_snapshot.json (listone values for slim DBs)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check", action="store_true",
            help="Do not write: exit 1 if the file on disk differs from a fresh build.")

    def handle(self, *args, **opts):
        snapshot = build_snapshot()
        # Indented and key-sorted so a regeneration produces a reviewable diff
        # rather than one unreadable line.
        text = json.dumps(snapshot, indent=1, sort_keys=True) + "\n"

        if opts["check"]:
            current = SNAPSHOT_PATH.read_text() if SNAPSHOT_PATH.exists() else ""
            if current == text:
                self.stdout.write(self.style.SUCCESS("snapshot aggiornato"))
                return
            self.stderr.write(self.style.ERROR(
                "snapshot NON aggiornato: rilancia "
                "`manage.py build_player_ratings_snapshot`"))
            raise SystemExit(1)

        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(text)
        clear_snapshot_cache()

        self.stdout.write(f"fingerprint: {snapshot['scoring_fingerprint']}")
        for cs_id, season in sorted(snapshot["seasons"].items()):
            self.stdout.write(
                f"  {season['label']}: {len(season['ratings'])} giocatori "
                f"(dati {season['data_version']})")
        if not snapshot["seasons"]:
            self.stdout.write(self.style.WARNING(
                "nessuna stagione calcolabile: questo database non ha zone feature, "
                "quindi non puo' PRODURRE lo snapshot (solo consumarlo)."))
        self.stdout.write(self.style.SUCCESS(
            f"scritto {SNAPSHOT_PATH} ({len(text)/1024:.1f} KB)"))
