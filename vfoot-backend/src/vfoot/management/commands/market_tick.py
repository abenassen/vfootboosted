"""Manutenzione del mercato di riparazione: apre le sessioni programmate, chiude
quelle scadute e promuove le offerte che hanno compiuto le 24h.

NON serve alla correttezza. Ogni endpoint del mercato passa da
``market_engine.sync_session``, quindi una scadenza produce i suoi effetti alla
prima richiesta che la incontra: nessuno riesce a offrire dopo il termine, e
nessuno vede aperta una sessione chiusa. Questo comando fa la stessa cosa senza
aspettare quella richiesta — utile se un domani la chiusura dovra' mandare una
notifica push, perche' quella non puo' partire da sola.

Idempotente: eseguirlo spesso, di rado, o mai, non cambia cio' che gli utenti
vedono. Output di una riga per run, greppabile nel log del cron.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from vfoot.models import MarketSession
from vfoot.services.market_engine import sync_session


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
        opened = 0
        promoted = 0
        for session in live:
            if session.status != MarketSession.STATUS_OPEN:
                continue
            if session.opens_at is not None and session.opens_at > now:
                # Programmata: annunciata alla lega, ma non e' ancora la sua ora.
                continue
            # L'apertura vera (aggiorna il listone) di una sessione programmata.
            due_open = session.opened_at is None

            due_close = session.closes_at is not None and session.closes_at <= now
            # Alla chiusura passa in validazione TUTTO cio' che e' in testa, non
            # solo chi ha compiuto le 24h: e' la regola di gioco, non un caso
            # limite del comando.
            due = session.offers.filter(
                status="leading",
                **({} if due_close else {"deadline_at__lte": now}),
            ).count()

            if dry:
                if due_open:
                    self.stdout.write(f"[dry] would open session {session.id}")
                if due:
                    self.stdout.write(f"[dry] session {session.id}: would promote {due} offer(s)")
                if due_close:
                    self.stdout.write(f"[dry] would close session {session.id}")
            else:
                sync_session(session, now=now)
            promoted += due
            opened += 1 if due_open else 0
            closed += 1 if due_close else 0

        self.stdout.write(self.style.SUCCESS(
            f"market_tick: sessions={len(live)} opened={opened} closed={closed} "
            f"promoted={promoted}"))
