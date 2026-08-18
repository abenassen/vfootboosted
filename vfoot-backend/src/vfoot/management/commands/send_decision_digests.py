"""Carry the league consultations out of the building, in one message per burst.

The click that opens a consultation no longer sends anything (see
``services/decision_digest`` for why, and for the window). This command is the
half that does, and it is the ONLY half: if this never runs, the questions are
asked on screen and nobody is ever told by email or push.

That is why it also writes a ``JobRun`` row like the scraping jobs do — a digest
timer that stops firing has to be visible in ``health_report`` rather than
discovered by a member who wonders why the league went quiet.

    python manage.py send_decision_digests
    python manage.py send_decision_digests --dry-run   # who would be told what
    python manage.py send_decision_digests --force     # ignore the window, send now

Idempotent: what has gone out is stamped, so running it twice in a row sends
nothing the second time.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from realdata.services import job_log
from vfoot.services import decision_digest


class Command(BaseCommand):
    help = "Send the pending league-decision digests (consultations and outcomes)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would be sent, send nothing.")
        parser.add_argument("--force", action="store_true",
                            help="Send every pending batch now, window or no window.")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        with job_log.record("send_decision_digests", dry_run=dry) as run:
            pending = (decision_digest.pending_consultations().count()
                       + decision_digest.pending_outcomes().count())
            run.due(decisions=pending)
            stats = decision_digest.flush(force=opts["force"], dry_run=dry)
            run.did(consultations=stats["consultations"], outcomes=stats["outcomes"])

            for league, kind, n in stats["batches"]:
                what = "consultazioni" if kind == decision_digest.CONSULTATION \
                    else "decisioni prese"
                self.stdout.write(f"  [{'dry' if dry else 'send'}] {league.name}: "
                                  f"{n} {what}")
            if stats["waiting"]:
                # Not a problem and worth saying: this is the window doing its job,
                # and without the line a quiet run looks like a broken one.
                run.note(f"{stats['waiting']} in attesa che la finestra si chiuda")
                self.stdout.write(f"  {stats['waiting']} ancora in finestra")

            self.stdout.write(self.style.SUCCESS(
                f"send_decision_digests: leghe={stats['leagues']} "
                f"consultazioni={stats['consultations']} "
                f"esiti={stats['outcomes']} in_attesa={stats['waiting']}"))
