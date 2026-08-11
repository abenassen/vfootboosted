"""Marca come portiere chi la DISTINTA schiera in porta, quando il cartellino tace.

``Player.is_goalkeeper`` viene dal cartellino Transfermarkt, quindi esiste solo per
chi sta in una rosa che abbiamo importato. Un'installazione che ha le rose della
stagione nuova ma non di quella misurata resta con dei portieri non marcati — la
produzione all'11/08/2026 ne aveva sette della 2025-26 (Sommer, Montipò, Ravaglia,
Leali, Scuffet, Šemper, Sava), tutti senza rosa perché nel 2026-27 non ci sono.

Cosa comportava, ed è il motivo per cui questo comando esiste: il tag decide chi
NON entra nel raggruppamento per stile di gioco, e quei sette ci entravano —
uscendone centrocampisti. Da lì un voto calcolato sul canale sbagliato, una fetta
del pericolo concesso sottratta ai difensori davanti a loro, e le categorie
spostate anche per gli altri, perché la popolazione del clustering era diversa. Il
codice adesso non si fida più del solo tag (v. ``match_lineup_keepers`` e
``player_profiles``), ma il tag serve comunque al resto dell'applicazione: la
casella in formazione, il ruolo nel listone, la scelta del portiere in rosa.

    python manage.py backfill_goalkeeper_flag --season 1
    python manage.py backfill_goalkeeper_flag --season 1 --dry-run
    python manage.py backfill_goalkeeper_flag            # tutte le stagioni

Solo verso il vero: se il cartellino dice portiere e la distinta no, vince il
cartellino. Togliere un tag su una distinta anomala (un giocatore di movimento
finito in porta dopo un'espulsione del portiere) farebbe più danni di quanti ne
ripari, e comunque non è questo il comando che deve deciderlo.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError

from realdata.models import CompetitionSeason, MatchAppearance, Player

GK_POSITION = "G"


class Command(BaseCommand):
    help = "Marca is_goalkeeper=True per chi la distinta SofaScore schiera in porta."

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, default=None,
                            help="CompetitionSeason da leggere (default: tutte).")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        apps = MatchAppearance.objects.all()
        if o["season"] is not None:
            if not CompetitionSeason.objects.filter(id=o["season"]).exists():
                raise CommandError(f"Nessuna CompetitionSeason id={o['season']}")
            apps = apps.filter(match__competition_season_id=o["season"])

        # La maggioranza delle sue distinte, non una sola: una partita chiusa in porta
        # da un difensore non fa di lui un portiere.
        tally: dict[int, Counter] = defaultdict(Counter)
        for pid, raw in apps.values_list("player_id", "raw_stats"):
            pos = (raw or {}).get("position")
            if pos:
                tally[pid][pos] += 1
        candidati = {pid for pid, c in tally.items()
                     if c.most_common(1)[0][0] == GK_POSITION}
        self.stdout.write(f"presenze lette         : {apps.count()}")
        self.stdout.write(f"giocatori con distinta : {len(tally)}")
        self.stdout.write(f"in porta a maggioranza : {len(candidati)}")

        da_marcare = list(Player.objects.filter(id__in=candidati, is_goalkeeper=False)
                          .values_list("id", "short_name", "full_name"))
        self.stdout.write(self.style.WARNING(
            f"da marcare (tag mancante): {len(da_marcare)}"))
        for _pid, short, full in sorted(da_marcare, key=lambda r: r[1] or r[2] or ""):
            self.stdout.write(f"   {short or full}")
        # E il contrario, che NON tocchiamo ma vale saperlo: chi ha il tag e in
        # distinta non è mai in porta (un portiere di riserva mai schierato non
        # compare qui, perché senza presenze non ha distinte).
        contrari = Player.objects.filter(is_goalkeeper=True).exclude(id__in=candidati) \
            .filter(id__in=tally.keys()).count()
        if contrari:
            self.stdout.write(f"(taggati ma mai in porta in distinta: {contrari} — lasciati stare)")

        if o["dry_run"]:
            self.stdout.write("\n[dry-run] niente scritto")
            return
        n = Player.objects.filter(id__in=[p for p, _, _ in da_marcare]) \
            .update(is_goalkeeper=True)
        self.stdout.write(self.style.SUCCESS(f"\n{n} giocatori marcati portiere."))
        if n:
            self.stdout.write("Ora ricalcola i ruoli: manage.py compute_classic_roles "
                              "--season <rose> --data-season <dati>")
