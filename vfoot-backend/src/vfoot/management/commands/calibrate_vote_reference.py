"""Freeze the per-role vote calibration from a COMPLETED season.

The voto puro centres each role on 6 by z-scoring against its peers' mean and
spread. Computed from the running season those move as results arrive, so a 6 in
September would not equal a 6 in May and matchday 1 would have no scale at all.
This calibrates them ONCE, on a finished season, and writes them to a versioned
file the scorer reads forever after (see services/vote_reference.py).

Run it when the season used for calibration is complete, and again whenever the
weights change — never during a season in progress.

    python manage.py calibrate_vote_reference --season 2
    python manage.py calibrate_vote_reference --season 2 --dry-run
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from realdata.models import CompetitionSeason, Match
from vfoot.services.classic_pagella import compute_role_averages
from vfoot.services.classic_rating import build_reference
from vfoot.services.vote_reference import (
    REFERENCE_PATH, clear_cache, save, weights_fingerprint,
)


class Command(BaseCommand):
    help = "Freeze the per-role voto-puro reference from a completed season."

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, required=True,
                            help="CompetitionSeason to calibrate on (a COMPLETED one).")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        cs = CompetitionSeason.objects.filter(id=o["season"]).first()
        if cs is None:
            raise CommandError(f"No CompetitionSeason id={o['season']}")

        total = Match.objects.filter(competition_season=cs).count()
        finished = Match.objects.filter(competition_season=cs,
                                        status=Match.STATUS_FINISHED).count()
        if finished < total:
            self.stdout.write(self.style.WARNING(
                f"Attenzione: {finished}/{total} partite concluse. La reference "
                "andrebbe calibrata su una stagione FINITA, non in corso."))

        reference = build_reference(cs.id)
        averages = compute_role_averages(cs.id)
        if not reference:
            raise CommandError("Nessun dato: impossibile calibrare.")

        self.stdout.write(f"Calibrazione su '{cs}' ({finished} partite):")
        for role in ("POR", "DIF", "CEN", "ATT"):
            r = reference.get(role)
            if r:
                self.stdout.write(f"   {role}: media {r['mean']:.3f}  "
                                  f"dev.std {r['std']:.3f}  (n={r['n']})")
        self.stdout.write(f"fingerprint pesi: {weights_fingerprint()}")

        if o["dry_run"]:
            self.stdout.write("[dry-run] nulla scritto")
            return
        save(reference, averages, season_id=cs.id)
        clear_cache()
        self.stdout.write(self.style.SUCCESS(f"Scritto {REFERENCE_PATH}"))
