"""Costruisce ``vfoot/data/participation_reference.json``: per ruolo, la distribuzione
di tocchi e azioni per 90' delle presenze da almeno 80' di una stagione conclusa.

La tabella e' congelata e viaggia nel repo come ``vote_reference.json``: si costruisce
UNA volta, sulla stagione di riferimento (25-26), e ricostruirla sposta voti — la sua
impronta e' in ``scoring_fingerprint``. Non contiene id di nessun tipo, quindi vale
uguale in locale e in produzione."""
from django.core.management.base import BaseCommand

from realdata.models import Match
from vfoot.services import classic_rating as cr, participation


class Command(BaseCommand):
    help = "Build the frozen participation table (touches / actions per 90 by role)."

    def add_arguments(self, parser):
        parser.add_argument("--season-id", type=int, required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, season_id, dry_run, **opts):
        mids = list(Match.objects.filter(competition_season_id=season_id, status="finished")
                    .values_list("id", flat=True))
        roles = cr.current_role_map()
        rows = []
        for i in range(0, len(mids), 40):
            chunk = mids[i:i + 40]
            totals = cr._per_match_player_totals(chunk)
            minutes = cr._minutes_map(chunk)
            for key, feats in totals.items():
                role = roles.get(key[1])
                if role in participation.ROLES:
                    rows.append((role, minutes.get(key, 0), feats))
        table = participation.build(rows)
        for role, d in table["roles"].items():
            n = sum(c for _v, c in d["touches"])
            self.stdout.write(f"{role}: {n} presenze da {participation.POPULATION_MIN_MINUTES}'+")
        if dry_run:
            return
        participation.save(table, season_id)
        self.stdout.write(self.style.SUCCESS(f"scritta {participation.DATA_PATH} "
                                             f"(impronta {participation.sha()})"))
