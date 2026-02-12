from django.core.management.base import BaseCommand
from django.db import transaction

from vfoot.models import ZoneSet
from vfoot.services.zones import materialize_grid_zoneset


class Command(BaseCommand):
    help = "Create (or recreate) the default grid ZoneSet (4x3) and materialize its zones."

    def add_arguments(self, parser):
        parser.add_argument("--nx", type=int, default=4)
        parser.add_argument("--ny", type=int, default=3)
        parser.add_argument("--name", type=str, default="Default grid")
        parser.add_argument(
            "--replace",
            action="store_true",
            help="If set, delete existing ZoneSet(s) with same name and create a new one.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        nx = options["nx"]
        ny = options["ny"]
        name = options["name"]
        replace = options["replace"]

        if replace:
            ZoneSet.objects.filter(name=name, kind=ZoneSet.KIND_GRID).delete()

        zoneset, created = ZoneSet.objects.get_or_create(
            name=name,
            kind=ZoneSet.KIND_GRID,
            defaults={"params": {"nx": nx, "ny": ny}},
        )

        # If it existed, update params to requested values
        zoneset.params = {"nx": nx, "ny": ny}
        zoneset.save(update_fields=["params"])

        n = materialize_grid_zoneset(zoneset)

        self.stdout.write(self.style.SUCCESS(
            f"ZoneSet id={zoneset.id} ({'created' if created else 'updated'}) materialized zones={n}"
        ))

