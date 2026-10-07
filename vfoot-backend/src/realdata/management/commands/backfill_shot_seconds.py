"""Backfill MatchShot.elapsed_seconds, .situation and .distance_m from the cached SofaScore shotmaps.

New imports capture the shot's ``timeSeconds`` and ``situation`` (see
sofascore_adapter), but rows imported before that lack them. This reads the shotmaps
already cached under VFOOT_DATA_DIR (offline, no network) and fills both by the
provider shot id. elapsed_seconds lets own goals be graded by fault (a deflection
shares the moment of the shot it turned in); situation flags penalties, so a missed
one carries the -3 fantavoto malus and a result-scaled voto-puro drop (see
classic_rating.penalty_missed_adjustments).

    python manage.py backfill_shot_seconds --season 2
    python manage.py backfill_shot_seconds --season 2 --dry-run

Le ultime due righe che stampa sono il controllo del deploy: «tiri senza coordinate
nella mappa» (l'unico motivo legittimo per cui una distanza manca) e «tiri della
stagione senza distanza dopo il passaggio», che deve essere 0.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from realdata.models import CompetitionSeason, Match, MatchShot
from realdata.services.sofascore_adapter import shot_distance_m


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

        # Solo le partite che hanno tiri da riempire: una partita in calendario e non
        # ancora giocata non ha mappa, e contarla fra le «mancanti» nasconderebbe
        # la mancanza vera (una partita giocata senza mappa in cache).
        with_shots = (MatchShot.objects.filter(match__competition_season_id=o["season"])
                      .values("match_id"))
        matches = list(Match.objects.filter(competition_season_id=o["season"],
                                            id__in=with_shots)
                       .exclude(external_id=""))
        read = missing = filled = no_coords = 0
        for m in matches:
            f = cache / f"api_v1_event_{m.external_id}_shotmap.json"
            if not f.exists():
                missing += 1
                continue
            data = json.loads(f.read_text())
            meta = {}  # shot id -> (timeSeconds|None, situation|"", distance_m|None)
            for s in (data.get("shotmap") or []):
                sid = s.get("id")
                if sid is None:
                    continue
                ts = s.get("timeSeconds")
                dist = shot_distance_m(s.get("playerCoordinates") or {})
                if dist is None:
                    no_coords += 1
                meta[str(sid)] = (int(ts) if isinstance(ts, (int, float)) else None,
                                  str(s.get("situation") or "")[:24], dist)
            to_update = []
            for shot in MatchShot.objects.filter(match=m).exclude(external_id=""):
                info = meta.get(shot.external_id)
                if not info:
                    continue
                ts, sit, dist = info
                dirty = False
                if ts is not None and shot.elapsed_seconds != ts:
                    shot.elapsed_seconds = ts; dirty = True
                if sit and shot.situation != sit:
                    shot.situation = sit; dirty = True
                # La distanza dalla porta (08/10/2026), per il canale del portiere.
                if dist is not None and shot.distance_m != dist:
                    shot.distance_m = dist; dirty = True
                if dirty:
                    to_update.append(shot)
            filled += len(to_update)
            if to_update and not o["dry_run"]:
                MatchShot.objects.bulk_update(to_update, ["elapsed_seconds", "situation",
                                                          "distance_m"])
            read += 1

        verb = "sarebbero aggiornati" if o["dry_run"] else "aggiornati"
        self.stdout.write(f"shotmap lette: {read}/{len(matches)} (mancanti: {missing})")
        self.stdout.write(self.style.SUCCESS(f"tiri {verb}: {filled}"))
        # IL CONTROLLO CHE CONTA, dopo il lavoro: quanti tiri della stagione restano
        # senza distanza. Il canale del portiere legge un nullo come 16 m, e il voto
        # non se ne accorge: «aggiornati N» da solo non dice se N era tutto. Un tiro
        # senza coordinate nella mappa e' l'unico caso legittimo, e si conta a parte.
        season_shots = MatchShot.objects.filter(match__competition_season_id=o["season"])
        left = season_shots.filter(distance_m__isnull=True).count()
        self.stdout.write(f"tiri senza coordinate nella mappa: {no_coords}")
        line = (f"tiri della stagione senza distanza dopo il passaggio: {left} "
                f"su {season_shots.count()}")
        self.stdout.write(self.style.SUCCESS(line) if left == 0 or o["dry_run"]
                          else self.style.WARNING(line))
