"""The scheduler tick, run INSIDE the web server — for a machine without Redis.

WHY THIS EXISTS. The live nudge travels on the channel layer, and with no
``REDIS_URL`` that layer is ``InMemoryChannelLayer``, which does not fan out across
PROCESSES. The tick is normally its own process (``tick_loop``, or a systemd
timer), so the nudge lands in the tick's memory and the browser never hears it: the
page simply stops updating, with no error anywhere. That is the trap already
documented in ``services/live_realtime``.

A Redis fixes it, and is what production uses. But a development machine without
Docker and without administrator rights cannot always have one — and on that
machine the whole live pipeline becomes untestable for a reason that has nothing to
do with the product.

So: same process, same layer, and the nudge arrives. This is NOT a substitute for
Redis in production, where the web server is several worker processes and only a
real broker can reach all of them. It is a way to make one developer's laptop able
to watch the thing work.

THE GUARDS ARE THE POINT. Three of them, and all three must hold:

* ``VFOOT_TICK_IN_PROCESS`` explicitly set — never a default;
* ``DEBUG`` on — so it cannot start in a deployment even if the variable leaks
  into the environment;
* ``runserver`` on the command line — because ``AppConfig.ready()`` runs for EVERY
  management command, and without this check a background scheduler would start
  under ``migrate``, under ``shell``, and under the test suite, where a thread
  writing to the database mid-test is the kind of failure that takes a day to
  understand.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time

log = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}
_started = False


def _wanted() -> bool:
    from django.conf import settings

    if os.environ.get("VFOOT_TICK_IN_PROCESS", "").strip().lower() not in _TRUE:
        return False
    if not settings.DEBUG:
        log.warning("VFOOT_TICK_IN_PROCESS ignorato: DEBUG e' spento.")
        return False
    # `runserver` covers the dev server (with and without --noreload). Anything
    # else — migrate, shell, test, a management command — must not grow a timer.
    return "runserver" in sys.argv


def _loop(every: float) -> None:
    from django.core.management import call_command

    # The server is still finishing its own startup when ready() returns; a tick
    # firing into a half-built process would work, but its log lines would land in
    # the middle of the banner and read like an error.
    time.sleep(2.0)
    while True:
        try:
            call_command("tick")
        except Exception:  # noqa: BLE001
            # A failed tick must never take the WEB SERVER down with it: this
            # thread is a guest in that process. The next one is a minute away.
            log.exception("tick in-process fallito")
        time.sleep(every)


def start_if_requested() -> bool:
    """Start the tick thread when asked and allowed. Returns whether it started."""
    global _started
    if _started or not _wanted():
        return False
    try:
        every = float(os.environ.get("VFOOT_TICK_EVERY", "60"))
    except ValueError:
        every = 60.0
    if every <= 0:
        return False
    _started = True
    # Daemon: the tick has nothing to flush and nothing to close, and a
    # non-daemon thread would keep the server alive after Ctrl-C — turning
    # "stop the simulation" into "wait a minute, then stop the simulation".
    threading.Thread(target=_loop, args=(every,), name="vfoot-tick",
                     daemon=True).start()
    log.warning("tick IN PROCESS ogni %gs (niente Redis: la spinta WebSocket "
                "resta dentro questo processo, ed e' esattamente cio' che serve)", every)
    return True
