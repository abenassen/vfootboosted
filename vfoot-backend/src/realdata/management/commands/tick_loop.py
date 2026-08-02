"""The scheduler timer, as a foreground loop — for a machine without systemd.

In production the tick is a systemd timer (``vfoot-tick.timer``, OnUnitActiveSec
1min). On a development laptop there is no timer, and the pipeline's whole point is
that it runs UNATTENDED: a live match that only advances when someone types a
command is not a live match, it is a slideshow.

So this is the timer, and deliberately nothing more. It does not poll, import or
decide anything; it calls ``manage.py tick`` on a cadence, exactly as the unit
file does. Everything interesting stays where it already lives — which is also why
watching this loop is worth something: what scrolls past is the real scheduler
making real decisions.

    manage.py tick_loop                    # every 60s, like the timer
    manage.py tick_loop --every 20         # faster, to watch a match move
    manage.py tick_loop --until 2027-01-31T23:00:00+01:00

Pair it with VFOOT_EGRESS_SIMULATED so the scraping is served by the generator
(see realdata/services/egress_sim.py), and with VFOOT_FAKE_NOW so the clock sits
inside the simulated season. Note that this is a SEPARATE PROCESS from the web
server: each reads VFOOT_FAKE_NOW for itself, so they must be started from the
same value or the two will disagree about what time it is.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone as dt_timezone

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from vfoot import simclock


class Command(BaseCommand):
    help = "Run the scheduler tick on a loop, as the systemd timer does."

    def add_arguments(self, parser):
        parser.add_argument("--every", type=float, default=60.0,
                            help="Seconds between ticks (default 60, the timer's).")
        parser.add_argument("--until", type=str, default=None,
                            help="Stop when the (simulated) clock passes this "
                                 "instant. Without it, runs until interrupted.")
        parser.add_argument("--max-ticks", type=int, default=0,
                            help="Stop after this many ticks; 0 means no limit.")

    def handle(self, *args, **o):
        every = float(o["every"])
        if every <= 0:
            raise CommandError("--every must be positive.")
        until = _parse(o["until"]) if o["until"] else None
        limit = int(o["max_ticks"])

        clock = (f"simulated, {simclock.offset()} ahead" if simclock.is_active()
                 else "real")
        self.stdout.write(self.style.NOTICE(
            f"tick loop: every {every:g}s · clock {clock}"
            + (f" · until {until.isoformat()}" if until else "")))

        ticks = 0
        try:
            while True:
                now = timezone.now()
                if until is not None and now >= until:
                    self.stdout.write(self.style.SUCCESS(
                        f"reached {until.isoformat()} after {ticks} ticks"))
                    return
                self.stdout.write(f"\n--- {now.isoformat(timespec='seconds')} ---")
                # Called in-process rather than as a subprocess: a subprocess would
                # re-read VFOOT_FAKE_NOW and restart the simulated clock from its
                # origin at every tick, so the match would never leave its first
                # minute.
                call_command("tick")
                ticks += 1
                if limit and ticks >= limit:
                    self.stdout.write(self.style.SUCCESS(f"{ticks} ticks, stopping"))
                    return
                time.sleep(every)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING(f"\ninterrupted after {ticks} ticks"))


def _parse(raw: str) -> datetime:
    try:
        value = datetime.fromisoformat(str(raw).strip())
    except ValueError as exc:
        raise CommandError(f"Invalid --until {raw!r}: {exc}") from exc
    return value if value.tzinfo else value.replace(tzinfo=dt_timezone.utc)
