"""Fonde due righe ``Player`` che sono la stessa persona.

Il caso che l'ha fatta scrivere: un giocatore entra dall'import rose di
Transfermarkt (quindi ha lo stint, il valore di mercato, il ruolo congelato e —
se qualcuno l'ha comprato — lo slot in rosa), poi esordisce, e SofaScore conia
una SECONDA riga perche' l'adozione per identita' non l'ha riconosciuto. Da
quel momento le due meta' non si parlano piu': la meta' comprata non ha nessuna
presenza e resta senza voto per sempre, mentre la meta' che gioca non e' nel
listone e non e' di nessuno.

Chi vince e chi perde NON e' una scelta di merito: vince la riga che l'app ha
gia' in mano — quella nel listone, che le rose, le formazioni salvate, le
offerte e l'asta nominano per id. Spostare quella significherebbe riscrivere
anche la storia di una lega. Perde la riga SofaScore, di cui si sposta tutto il
patrimonio (presenze, zone, tiri, cartellini, intervalli) e si conserva l'unica
cosa che vale: l'id SofaScore, che diventa un alias del vincitore ed e' quello
che fara' atterrare li' anche i prossimi import.

    manage.py merge_duplicate_players                  # elenca i sospetti
    manage.py merge_duplicate_players --apply          # li fonde
    manage.py merge_duplicate_players --pair 943:998   # una coppia sola
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from realdata.models import (MatchAppearance, Player, PlayerAlias,
                             PROVIDER_SOFASCORE)
from realdata.services import roster_integrity
from realdata.services.identity import is_synthetic_sofascore_id

PROVIDER = PROVIDER_SOFASCORE

# Liste di id giocatore salvate come JSON, che nessuna chiave esterna protegge:
# se il perdente ci comparisse dentro, cancellarlo lascerebbe un id che non
# nomina piu' nessuno. (modello, campi)
_JSON_ID_FIELDS = [
    ("vfoot.FantasyLineupSubmission",
     ("starter_player_ids", "bench_player_ids", "starter_backups")),
    ("vfoot.SavedLineupSnapshot",
     ("starter_player_ids", "bench_player_ids", "starter_backups")),
]


@transaction.atomic
def merge(winner: Player, loser: Player, *, stdout=None) -> dict:
    """Sposta tutto dal perdente al vincitore e cancella il perdente."""
    if winner.pk == loser.pk:
        raise CommandError("vincitore e perdente sono la stessa riga")
    moved: dict[str, int] = {}
    dropped: dict[str, int] = {}

    for rel in Player._meta.related_objects:
        if rel.many_to_many:                   # nessuna M2M oggi; se ne arriva una
            raise CommandError(                # va gestita a mano, non in silenzio
                f"relazione non gestita: {rel.related_model._meta.label}.{rel.field.name}")
        model, attname = rel.related_model, rel.field.attname
        label = f"{model._meta.label}.{rel.field.name}"
        for obj in model.objects.filter(**{attname: loser.pk}):
            setattr(obj, attname, winner.pk)
            try:
                with transaction.atomic():
                    obj.save(update_fields=[attname])
                moved[label] = moved.get(label, 0) + 1
            except IntegrityError:
                # Il vincitore ha gia' la sua riga per quella chiave (stessa
                # partita, stesso provider): la copia del perdente e' un doppione
                # e non c'e' niente da salvare.
                setattr(obj, attname, loser.pk)
                obj.delete()
                dropped[label] = dropped.get(label, 0) + 1

    from django.apps import apps as django_apps
    for label, fields in _JSON_ID_FIELDS:
        model = django_apps.get_model(label)
        for obj in model.objects.all():
            touched = False
            for f in fields:
                val = getattr(obj, f) or []
                new = _swap_ids(val, loser.pk, winner.pk)
                if new != val:
                    setattr(obj, f, new)
                    touched = True
            if touched:
                obj.save(update_fields=list(fields))
                moved[label] = moved.get(label, 0) + 1

    # L'unica cosa del perdente che non e' una riga figlia: il suo id SofaScore.
    if loser.external_source == PROVIDER and loser.external_id:
        PlayerAlias.objects.get_or_create(
            player=winner, source=PROVIDER, alias=str(loser.external_id))
        # L'alias sintetico del simulatore sullo stesso vincitore ora e' solo
        # rumore che puo' vincere su quello vero in una lettura distratta.
        for a in PlayerAlias.objects.filter(player=winner, source=PROVIDER):
            if is_synthetic_sofascore_id(a.alias):
                a.delete()
    # Le righe Transfermarkt non hanno nome breve; quello del fornitore e' il nome
    # che si legge in tutta l'app, e va preso — mai sopra una correzione a mano.
    if (not winner.short_name and loser.short_name
            and winner.short_name_source != Player.SHORT_NAME_ADMIN):
        winner.short_name = loser.short_name
        winner.save(update_fields=["short_name"])

    loser.delete()
    return {"moved": moved, "dropped": dropped}


def _swap_ids(value, old: int, new: int):
    """Sostituisce ``old`` con ``new`` dentro una lista di id, anche annidata."""
    if isinstance(value, list):
        return [_swap_ids(v, old, new) for v in value]
    return new if value == old else value


class Command(BaseCommand):
    help = "Fonde le righe Player duplicate (una da Transfermarkt, una da SofaScore)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="esegue la fusione (senza, elenca soltanto)")
        parser.add_argument("--pair", action="append", default=[],
                            metavar="VINCITORE:PERDENTE",
                            help="una coppia esplicita, invece del rilevamento")

    def handle(self, *args, **opts):
        if opts["pair"]:
            pairs = []
            for raw in opts["pair"]:
                try:
                    w, l = (int(x) for x in raw.split(":"))
                except ValueError:
                    raise CommandError(f"--pair vuole VINCITORE:PERDENTE, non {raw!r}")
                pairs.append((Player.objects.get(pk=w), Player.objects.get(pk=l),
                              "coppia indicata a mano"))
        else:
            pairs = [(Player.objects.get(pk=s.keeper_id),
                      Player.objects.get(pk=s.stray_id), s.evidence)
                     for s in roster_integrity.split_identities()]

        if not pairs:
            self.stdout.write("Nessun doppione.")
            return

        for winner, loser, why in pairs:
            self.stdout.write(
                f"\n{winner.full_name} — {why}\n"
                f"  TIENE   id={winner.id} {winner.external_source}/{winner.external_id} "
                f"dob={winner.date_of_birth} presenze="
                f"{MatchAppearance.objects.filter(player=winner).count()}\n"
                f"  ASSORBE id={loser.id} {loser.external_source}/{loser.external_id} "
                f"dob={loser.date_of_birth} presenze="
                f"{MatchAppearance.objects.filter(player=loser).count()}")
            if not opts["apply"]:
                continue
            report = merge(winner, loser)
            for label, n in sorted(report["moved"].items()):
                self.stdout.write(f"    spostate {n:>3}  {label}")
            for label, n in sorted(report["dropped"].items()):
                self.stdout.write(f"    scartate {n:>3}  {label} (doppione)")

        if not opts["apply"]:
            self.stdout.write(self.style.WARNING(
                f"\n{len(pairs)} coppie. Niente e' stato scritto: --apply per fondere."))
            return

        # LA CACHE VA SVUOTATA, e non e' un di piu'. Le pagelle in cache vivono
        # sotto una chiave che porta l'impronta dei DATI del turno — partite,
        # minuti, gol, assist — e una fusione non ne muove nemmeno uno: sposta di
        # riga chi quei minuti li ha giocati. La chiave resta identica, e per sei
        # ore l'applicazione continuerebbe a servire la pagella in cui il
        # giocatore appena riunito non c'e'. E' tutta la cache e non le sole voci
        # coinvolte di proposito: calcolare a mano le chiavi da buttare vuol dire
        # tenerle allineate per sempre a quelle di chi le scrive, e una chiave
        # dimenticata qui non fallisce, mente. Il prezzo e' un ricalcolo, e in
        # produzione nemmeno quello (la taratura del voto viene da un file).
        from django.core.cache import cache
        cache.clear()
        self.stdout.write(self.style.SUCCESS(
            f"\n{len(pairs)} coppie fuse. Cache svuotata: le pagelle gia' servite "
            f"non conterrebbero i giocatori riuniti."))
