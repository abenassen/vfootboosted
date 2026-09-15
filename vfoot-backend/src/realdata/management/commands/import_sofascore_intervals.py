"""Build exact on-pitch intervals for a SofaScore season, from cached incidents.

``PlayerOnPitchInterval`` is the project's canonical answer to "was he playing at
minute X", and it was populated only for the StatsBomb season. Without it the
SofaScore season had to guess: a starter assumed to run from kick-off for as many
minutes as he played, a substitute assumed to finish the match. That guess is
unbiased on average yet misattributes more than 20 percentage points of a match's
conceded danger for one defender in seven — which matters as soon as anything is
charged to a player for events in a window, as the defensive-exposure term is.

The cached ``*_incidents.json`` carries every substitution and card with its
minute, so the intervals can be reconstructed exactly, including the case a guess
cannot represent at all: a substitute who is himself later withdrawn.

A red card ends an interval too — he is off the pitch just as surely.

DAL 15/09/2026 l'importatore scrive gli intervalli da solo a ogni giro (v.
``realdata.services.sofascore_intervals``, che e' anche il codice di questo
comando). Il comando serve per i RIEMPIMENTI: le partite importate prima di quella
data — e con loro la coppia uscito/entrato che il tabellino legge, che le righe
vecchie non portano.

Offline; the scrape is the only network step. Idempotent per match.

    python manage.py import_sofascore_intervals --competition-season 2
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from realdata.models import Match
from realdata.services.sofascore_intervals import (
    appearances_of, build_intervals, ext_to_local_for, replace_intervals,
)


class Command(BaseCommand):
    help = "Build PlayerOnPitchInterval for a SofaScore season from cached incidents."

    def add_arguments(self, parser):
        parser.add_argument("--competition-season", type=int, required=True)
        parser.add_argument("--cache-dir", default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        cache = Path(o["cache_dir"] or settings.VFOOT_SOFASCORE_CACHE)
        matches = list(Match.objects.filter(competition_season_id=o["competition_season"])
                       .exclude(external_id="")
                       .select_related("home_team", "away_team"))
        if not matches:
            raise CommandError(f"No matches for season {o['competition_season']}")

        made = missing = skipped = 0
        subs_seen = reds_seen = 0
        for match in matches:
            path = cache / f"api_v1_event_{match.external_id}_incidents.json"
            if not path.exists():
                missing += 1
                continue
            raw = json.loads(path.read_text())
            rows = raw if isinstance(raw, list) else raw.get("incidents", [])
            subs_seen += sum(1 for r in rows if r.get("incidentType") == "substitution")
            reds_seen += sum(1 for r in rows if r.get("incidentType") == "card"
                             and str(r.get("incidentClass", "")).lower()
                             in ("red", "redyellow", "yellowred"))

            appearances = appearances_of(match)
            # external_id E alias: in produzione un giocatore su quattro sta solo
            # nel secondo, e senza il suo cambio non si vedeva (v. ext_to_local_for).
            ext_to_local = ext_to_local_for(appearances)
            # Una partita in cache e' una partita giocata: la fine aperta e' il
            # fischio finale. Chi e' ancora sul campo passa dall'importatore live.
            rows_out, bad = build_intervals(
                match, rows, appearances, ext_to_local,
                finished=match.status != Match.STATUS_LIVE)
            skipped += bad
            if not o["dry_run"]:
                replace_intervals(match, rows_out)
            made += len(rows_out)

        self.stdout.write(f"partite trattate      : {len(matches) - missing}")
        self.stdout.write(f"incidents mancanti    : {missing}")
        self.stdout.write(f"sostituzioni lette    : {subs_seen}")
        self.stdout.write(f"espulsioni lette      : {reds_seen}")
        self.stdout.write(f"intervalli {'da creare' if o['dry_run'] else 'creati'}  : {made}")
        if skipped:
            self.stdout.write(self.style.WARNING(
                f"scartati per incoerenza del provider: {skipped}"))
