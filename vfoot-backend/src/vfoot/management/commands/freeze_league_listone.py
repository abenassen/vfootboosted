"""Freeze (or refresh) a classic-mode league's role listone.

    python manage.py freeze_league_listone --league 42
    python manage.py freeze_league_listone --league 42 --reset   # redo seed rows
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from vfoot.models import FantasyLeague
from vfoot.services.listone import snapshot_league_listone


class Command(BaseCommand):
    help = "Snapshot a league's classic-mode role listone (per-league, frozen)."

    def add_arguments(self, parser):
        parser.add_argument("--league", type=int, required=True)
        parser.add_argument("--reset", action="store_true",
                            help="Re-snapshot seed rows from current TM roles "
                                 "(admin overrides are still preserved).")

    def handle(self, *args, **opts):
        try:
            league = FantasyLeague.objects.get(id=opts["league"])
        except FantasyLeague.DoesNotExist:
            raise CommandError(f"No FantasyLeague id={opts['league']}")

        s = snapshot_league_listone(league, reset=opts["reset"])
        self.stdout.write(self.style.SUCCESS(
            f"Listone for league {league.id} ({league.name}):"))
        self.stdout.write(f"  roster players       : {s['roster']}")
        self.stdout.write(f"  created (new seed)   : {s['created']}")
        self.stdout.write(f"  reset from TM        : {s['reset']}")
        self.stdout.write(f"  admin overrides kept : {s['preserved_admin']}")
        self.stdout.write(f"  seed rows kept frozen: {s['kept_seed']}")
        self.stdout.write(f"  skipped (no role)    : {s['skipped_no_role']}")
