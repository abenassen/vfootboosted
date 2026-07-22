"""Compute classic roles for a season's squads from the previous season's play.

Run once per season, BEFORE any league opens its listone — classic roles are fixed
at the start of a season and must not move afterwards, so this reads the season
that has finished, not the one about to be played.

    python manage.py compute_classic_roles --season 3 --data-season 2
    python manage.py compute_classic_roles --season 3 --data-season 2 --dry-run

Writes ``SeasonPlayerRole`` (both the mitigated and the pure-data variant, so a
league can pick either without a recompute). It does NOT touch any league: a
started listone is frozen and re-running this must never disturb it.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from realdata.models import CompetitionSeason, Player
from vfoot.models import SeasonPlayerRole
from vfoot.services.role_inference import (
    LOW_CONFIDENCE, infer_roles, tm_positions,
)


class Command(BaseCommand):
    help = "Infer per-season classic roles (POR/DIF/CEN/ATT) from play data."

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, required=True,
                            help="CompetitionSeason whose SQUADS get the roles.")
        parser.add_argument("--data-season", type=int, required=True,
                            help="CompetitionSeason whose PLAY is measured "
                                 "(normally the one before).")
        parser.add_argument("--min-minutes", type=int, default=None)
        parser.add_argument("--categories", type=int, default=None)
        parser.add_argument("--runs", type=int, default=None,
                            help="Consensus runs; lower is faster and less stable.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        for key in ("season", "data_season"):
            if not CompetitionSeason.objects.filter(id=o[key]).exists():
                raise CommandError(f"No CompetitionSeason id={o[key]}")
        kw = {k: v for k, v in (("min_minutes", o["min_minutes"]),
                                ("n_categories", o["categories"]),
                                ("runs", o["runs"])) if v is not None}
        rep = infer_roles(o["season"], o["data_season"], **kw)

        self.stdout.write("categorie individuate:")
        for name, meta in sorted(rep.categories.items(),
                                 key=lambda kv: -kv[1]["size"]):
            self.stdout.write(f"   {name:26} n={meta['size']:3}  -> {meta['role']}")

        # Roles are computed for everyone we measured, including players who have
        # since left the league (they may come back, and the rows are harmless).
        # The LISTONE, though, is only this season's squads — counting the rest
        # would report an inventory of attackers that nobody can actually buy.
        roster = set(tm_positions(o["season"]))
        counts: dict[str, int] = {}
        low, needed = 0, []
        names = dict(Player.objects.values_list("id", "short_name"))
        fulls = dict(Player.objects.values_list("id", "full_name"))
        counts_data: dict[str, int] = {}
        for r in rep.results:
            if r.player_id in roster:
                counts[r.role_mitigated or "-"] = counts.get(r.role_mitigated or "-", 0) + 1
                counts_data[r.role_data or "-"] = counts_data.get(r.role_data or "-", 0) + 1
            if r.method == "category" and r.confidence < LOW_CONFIDENCE:
                low += 1
            if r.needs_decision:
                needed.append(names.get(r.player_id) or fulls.get(r.player_id)
                              or str(r.player_id))

        self.stdout.write(f"\ngiocatori trattati       : {len(rep.results)}")
        self.stdout.write(f"  misurati dai dati      : {rep.n_measured}")
        self.stdout.write(f"  da posizione TM certa  : "
                          f"{sum(1 for r in rep.results if r.method == 'tm')}")
        self.stdout.write(f"  default posizionale    : {rep.n_default}")
        self.stdout.write(f"  senza ruolo            : {rep.n_unknown}")
        self.stdout.write(f"\nlistone {o['season']} ({len(roster)} giocatori in rosa):")
        self.stdout.write(f"   mitigata (TM prioritario): {dict(sorted(counts.items()))}")
        self.stdout.write(f"   pura dai dati            : {dict(sorted(counts_data.items()))}")
        self.stdout.write(f"categoria incerta (<{LOW_CONFIDENCE}) : {low}")
        self.stdout.write(self.style.WARNING(
            f"DA DECIDERE PRIMA DELL'ASTA: {len(needed)} giocatori"))
        if needed:
            self.stdout.write("   " + ", ".join(sorted(needed)[:25])
                              + (" ..." if len(needed) > 25 else ""))

        if o["dry_run"]:
            self.stdout.write("\n[dry-run] nulla e' stato scritto")
            return
        with transaction.atomic():
            SeasonPlayerRole.objects.filter(competition_season_id=o["season"]).delete()
            SeasonPlayerRole.objects.bulk_create([
                SeasonPlayerRole(
                    competition_season_id=o["season"], player_id=r.player_id,
                    category=r.category, confidence=r.confidence,
                    role_data=r.role_data, role_mitigated=r.role_mitigated,
                    method=r.method, tm_position=r.tm_position)
                for r in rep.results], batch_size=500)
        self.stdout.write(self.style.SUCCESS(f"\n{len(rep.results)} ruoli salvati."))
