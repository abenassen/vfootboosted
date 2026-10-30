"""Rilegge UNA partita gia' finalizzata e dice cosa e' cambiato.

Il tick fa da solo un solo sguardo tardivo, a +24h dal fischio (v.
``match_scheduler.LATE_CHECK_AFTER``). Una rettifica del fornitore che arriva dopo
le 48h non e' piu' affar suo, ed e' per quella che c'e' questo comando:

    manage.py recheck_match 16285065            # id SofaScore (external_id)
    manage.py recheck_match 473 --pk            # id del database
    manage.py recheck_match 16285065 --dry-run  # solo cosa farebbe

Stessa funzione del tick (``live_ingest.late_check``): lettura leggera, confronto
con cio' che e' salvato, e solo se qualcosa si e' mosso il re-import completo.
``data_ready`` non si tocca. Va lanciato come l'utente dell'app e sul server che ha
l'egress, non dal portatile: e' lui a poter parlare con SofaScore.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as djtz

from realdata.models import Match
from realdata.services import live_ingest


class Command(BaseCommand):
    help = "Re-read one finalized match and report what the provider corrected."

    def add_arguments(self, parser):
        parser.add_argument("match", help="SofaScore id of the match (or the "
                                          "database id with --pk).")
        parser.add_argument("--pk", action="store_true",
                            help="Interpret MATCH as the database id.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Say which match would be re-read; touch nothing.")

    def handle(self, *args, **options):
        lookup = {"pk": options["match"]} if options["pk"] else {
            "external_id": options["match"]}
        try:
            m = Match.objects.select_related(
                "competition_season__season", "home_team__team",
                "away_team__team").get(**lookup)
        except Match.DoesNotExist as exc:
            raise CommandError(f"No match with {lookup}") from exc
        if m.status != Match.STATUS_FINISHED:
            raise CommandError(f"{m} is {m.status}, not finished: a match in "
                               f"progress is the tick's business.")
        if options["dry_run"]:
            self.stdout.write(f"would re-read {m} (data_ready={m.data_ready})")
            return

        ok, changes = live_ingest.late_check(m)
        if not ok:
            raise CommandError("egress blocked: nothing was read; try again.")
        now = djtz.now()
        m.data_checked_at = now
        m.data_imported_at = now
        m.save(update_fields=["data_checked_at", "data_imported_at"])
        if not changes:
            self.stdout.write(self.style.SUCCESS(f"{m}: unchanged."))
            return
        self.stdout.write(self.style.WARNING(f"{m}: CORRECTED"))
        for c in changes:
            self.stdout.write(f"  - {c}")
        # La spinta alle pagine aperte, come fa il tick.
        from vfoot.services import live_updates
        nudge = live_updates.leagues_to_nudge(m)
        if nudge:
            live_updates.broadcast_leagues(nudge)
            self.stdout.write(f"  {len(nudge)} leghe avvisate")
        # E le giornate gia' concluse, come fa il tick: un fatto corretto le segna e
        # avvisa gli admin; il solo xG rivisto no (v. provider_corrections).
        facts = live_ingest.fact_changes(changes)
        if facts:
            from vfoot.services import provider_corrections
            for f in provider_corrections.flag_concluded_rounds(m, facts):
                moving = f["fixtures_moving"]
                self.stdout.write(
                    f"  giornata {f['matchday']} di «{f['league']}» gia' conclusa: "
                    + ("anteprima non riuscita" if moving is None
                       else f"{moving} sfide cambierebbero") + ", admin avvisati")
