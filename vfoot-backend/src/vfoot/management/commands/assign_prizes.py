"""Assegna i premi delle competizioni gia' finite.

Serve perche' i premi ora si SCRIVONO al momento della conclusione, e c'e' un
mondo di partite che quel momento non l'ha mai vissuto: le leghe demo e quelle
simulate hanno i risultati messi li' dal seed, senza che nessuno abbia mai
premuto "Concludi". Senza questo comando il loro albo d'oro nascerebbe vuoto pur
avendo alle spalle stagioni intere.

    manage.py assign_prizes                  # tutte le leghe
    manage.py assign_prizes --league 53
    manage.py assign_prizes --dry-run        # dimmi cosa faresti

E' idempotente e lo si puo' rilanciare: assegna solo cio' che manca e corregge
cio' che non torna piu'. Per la stessa ragione e' anche il rimedio se un giorno
un percorso di rettifica dimenticasse di ricontrollare i premi da solo — meglio
un comando da lanciare che un ricalcolo perpetuo a ogni apertura di pagina.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from vfoot.models import FantasyLeague, FantasyTeam
from vfoot.services import honours


class Command(BaseCommand):
    help = "Assegna i premi delle competizioni concluse che non li hanno ancora."

    def add_arguments(self, parser):
        parser.add_argument("--league", type=int, default=None,
                            help="Solo questa lega (predefinito: tutte).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Non scrive niente: dice solo cosa cambierebbe.")

    def handle(self, *args, **o):
        leagues = FantasyLeague.objects.all().order_by("id")
        if o["league"]:
            leagues = leagues.filter(id=o["league"])

        names = dict(FantasyTeam.objects.values_list("id", "name"))
        totale = 0
        for league in leagues:
            with transaction.atomic():
                changes = honours.review_league(league)
                if o["dry_run"]:
                    transaction.set_rollback(True)
            if not changes:
                continue
            self.stdout.write(self.style.MIGRATE_HEADING(f"{league.name}"))
            for c in changes:
                vinto = ", ".join(names.get(t, str(t)) for t in c["added"]) or "—"
                perso = ", ".join(names.get(t, str(t)) for t in c["removed"])
                riga = f"  {c['prize'].icon or '🏆'} {c['prize'].name} ({c['competition'].name}): {vinto}"
                if perso:
                    riga += f"   [prima: {perso}]"
                self.stdout.write(riga)
                totale += 1

        verbo = "assegnerebbe" if o["dry_run"] else "assegnati"
        self.stdout.write(self.style.SUCCESS(f"\n{totale} premi {verbo}."))
