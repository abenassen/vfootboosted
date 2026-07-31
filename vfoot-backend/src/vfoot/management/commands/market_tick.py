"""Repair-market housekeeping tick (meant for the Linode cron).

Two jobs, both idempotent:
  * auto-close every OPEN session whose scheduled ``closes_at`` has passed;
  * promote every leading offer past its 24h deadline to ``accepted`` (the same
    thing that happens lazily when someone opens the Mercato page — this is the
    safety net for sessions nobody is currently watching).

Run it as often as the poll loop ticks (e.g. every 60-90s). Output is a one-line
summary per run so it is greppable in the cron log.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from vfoot.models import MarketSession
from vfoot.services.market_engine import close_session, promote_expired


class Command(BaseCommand):
    help = "Promote expired market offers and auto-close scheduled sessions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without writing.")

    def handle(self, *args, **options):
        now = timezone.now()
        dry = options["dry_run"]

        live = list(MarketSession.objects.filter(
            status__in=(MarketSession.STATUS_OPEN, MarketSession.STATUS_SUSPENDED)))

        closed = 0
        promoted = 0
        for session in live:
            if session.status != MarketSession.STATUS_OPEN:
                continue

            # Promuovere PRIMA di chiudere. Un'offerta che aveva gia' compiuto le
            # sue 24h se le e' guadagnate: se la chiusura la precedesse, il suo
            # esito dipenderebbe da quando e' passato il cron — accettata se un
            # tick l'ha vista in tempo, annullata se il tick successivo trova
            # anche la sessione scaduta. Stesso istante, esito diverso.
            due = session.offers.filter(status="leading", deadline_at__lte=now).count()
            if dry:
                if due:
                    self.stdout.write(f"[dry] session {session.id}: would promote {due} offer(s)")
                promoted += due
            else:
                with transaction.atomic():
                    promoted += len(promote_expired(session, now=now))

            # Chiusura programmata: solo una sessione aperta con closes_at scaduto.
            if session.closes_at is not None and session.closes_at <= now:
                if dry:
                    self.stdout.write(f"[dry] would close session {session.id}")
                else:
                    with transaction.atomic():
                        close_session(session, now=now)
                closed += 1

        self.stdout.write(self.style.SUCCESS(
            f"market_tick: sessions={len(live)} closed={closed} promoted={promoted}"))
