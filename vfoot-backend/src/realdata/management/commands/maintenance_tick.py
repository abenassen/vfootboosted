"""Execute the maintenance proposals that have been approved. Nothing else.

    python manage.py maintenance_tick              # apply what was approved
    python manage.py maintenance_tick --dry-run    # say what it would do

WHY THIS IS A SEPARATE PROCESS FROM THE AGENT. The approval arrives hours after the
proposal — you read the mail at breakfast, or tap the button from a beach — and by
then the agent's process has been dead a long time. Something that is alive on a
timer has to be the thing that acts, and that something must be ordinary code: the
model is not in this loop at all.

Idempotent. A proposal leaves ``approved`` the moment it is executed, so running
this every ninety seconds, once an hour, or twice by accident all do the same thing.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from realdata.models import MaintenanceProposal
from realdata.services import job_log, maintenance


class Command(BaseCommand):
    help = "Execute approved maintenance proposals."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report without executing.")

    def handle(self, *args, **opts):
        with job_log.record("maintenance_tick", dry_run=opts["dry_run"]) as job:
            self._tick(job, opts["dry_run"])

    def _tick(self, job, dry: bool) -> None:
        pending = list(MaintenanceProposal.objects
                       .filter(status=MaintenanceProposal.STATUS_APPROVED)
                       .order_by("created_at"))
        job.due(approved=len(pending))
        if not pending:
            self.stdout.write("niente da eseguire.")
            return

        for proposal in pending:
            label = f"#{proposal.id} {proposal.kind} {proposal.payload}"
            if dry:
                self.stdout.write(f"  [eseguirei] {label}")
                continue
            ok = maintenance.execute(proposal)
            job.did(executed=1, failed=0 if ok else 1)
            style = self.style.SUCCESS if ok else self.style.ERROR
            self.stdout.write(style(f"  [{'fatto' if ok else 'FALLITO'}] {label}"))
            for line in proposal.result.splitlines()[:12]:
                self.stdout.write(f"      {line}")
