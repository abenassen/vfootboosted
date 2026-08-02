"""Remind the admins of leagues whose ledger is behind.

A league whose admin forgets to conclude keeps playing — lineups, locks and market
windows all read the real calendar and never wait for him. What stops is only the
counting: results and table stay frozen. This command is what makes sure somebody
notices, without ever taking the decision away from him.

Only matchdays that are actually closeable are counted (the real round is complete),
so a postponement never produces a reminder for something the admin cannot do; that
case is his to park as `awaiting`.

    python manage.py nudge_conclusions --dry-run
    python manage.py nudge_conclusions --cooldown-hours 48

Meant for the same cron/systemd timer as the rest of the semiautomatic pipeline;
daily is plenty.
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from vfoot.models import FantasyLeague, LeagueMembership
from vfoot.services import league_notifications, matchday_state


class Command(BaseCommand):
    help = "Email/push the admins of leagues with matchdays waiting to be concluded."

    def add_arguments(self, parser):
        parser.add_argument("--cooldown-hours", type=int, default=24,
                            help="Do not re-nudge about the same matchday within "
                                 "this many hours (default 24).")
        parser.add_argument("--league-id", type=int, default=None,
                            help="Restrict to one league (for testing).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report who would be nudged, send nothing.")

    def handle(self, *args, **opts):
        now = timezone.now()
        cutoff = now - timedelta(hours=opts["cooldown_hours"])
        leagues = FantasyLeague.objects.all()
        if opts["league_id"]:
            leagues = leagues.filter(id=opts["league_id"])

        nudged_leagues = 0
        for league in leagues:
            queue = matchday_state.conclusion_queue(league)
            due = [md for md in queue if md.nudged_at is None or md.nudged_at <= cutoff]
            if not due:
                continue
            rounds = ", ".join(str(md.real_matchday) for md in due)
            admins = [
                m.user for m in LeagueMembership.objects
                .filter(league=league, role=LeagueMembership.ROLE_ADMIN)
                .select_related("user")
            ]
            if not admins:
                self.stdout.write(f"  [skip] {league.name}: giornate {rounds}, nessun admin")
                continue
            self.stdout.write(
                f"  [nudge] {league.name}: giornate {rounds} -> "
                f"{', '.join(a.username for a in admins)}"
                + (" (dry-run)" if opts["dry_run"] else "")
            )
            if opts["dry_run"]:
                continue
            league_notifications.notify_conclusions_pending(league, due, admins)
            for md in due:
                md.nudged_at = now
                md.save(update_fields=["nudged_at"])
            nudged_leagues += 1

        self.stdout.write(self.style.SUCCESS(f"Leghe sollecitate: {nudged_leagues}"))
