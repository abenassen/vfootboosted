"""Record what a scheduled job was owed and what it produced — one row per run.

Used from the management commands the server runs unattended (``tick``,
``sync_calendar``, ``poll_transfermarkt``, ...). The row it writes is read back by
``health_report``, which is the only thing that turns these numbers into a verdict.

    with job_log.record("tick", dry_run=dry) as run:
        run.due(matches=len(plan.live_round))     # what the plan said BEFORE acting
        ...
        run.did(imported=1)                       # counters, additive
        run.note("egress bloccato")               # one human line, last one wins

THE RULE THIS MODULE OBEYS: **it must never break the job it observes.** A monitor
that takes down the thing it monitors is worse than no monitor — you lose the
service AND you look at the wrong place for a day. So every database write here is
wrapped, and a failure to record degrades to a log line. The one exception is the
job's own exception, which is recorded and then RE-RAISED untouched: systemd has to
keep seeing the failure it already knows how to see.

WHAT THIS IS NOT. It is not a replacement for the journal: ``self.stdout.write``
still tells the story a human reads. This is the machine-readable half, and the two
are complementary — the journal says what happened, the row says how much.

Nor does it cover a database that is down: there is nowhere to write the row then.
That case is loud on its own (the job fails, systemd marks it, ``health_report``
cannot even start) and needs no help from here.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

from django.utils import timezone

from realdata.models import JobRun

log = logging.getLogger(__name__)


class Recorder:
    """The handle a job holds for the length of its run.

    Counters are additive (``did(imported=1)`` called in a loop sums), because a
    job's numbers arrive one match at a time and asking every caller to keep its
    own totals is how a counter ends up wrong. ``due`` is a plain overwrite: it is
    stated once, from the plan, before anything is acted on.
    """

    def __init__(self, run: JobRun | None):
        self._run = run
        self._due: dict[str, object] = {}
        self._did: dict[str, float] = {}
        self._note = ""

    def due(self, **counts) -> None:
        """State what this run is owed. Call once, before acting.

        Zeros are dropped, and that is load-bearing rather than tidiness: an EMPTY
        ``due`` is the definition of a quiet run, which is what lets ``JobRun.prune``
        throw away the thousand daily ticks that had nothing to do while keeping
        every run that was owed something — including, above all, the ones that
        were owed something and produced nothing.
        """
        self._due.update({k: v for k, v in counts.items() if v})

    def did(self, **counts) -> None:
        """Add to what this run produced. Call as often as you like."""
        for key, value in counts.items():
            if value is None:
                continue
            self._did[key] = self._did.get(key, 0) + value

    def note(self, text: str) -> None:
        """One short human line for the row (300 chars). Last call wins."""
        self._note = (text or "")[:300]

    # -- internal ----------------------------------------------------------

    def _close(self, *, ok: bool, error: str = "") -> None:
        if self._run is None:
            return
        self._run.finished_at = timezone.now()
        self._run.ok = ok
        self._run.due = self._due
        self._run.did = self._did
        self._run.note = self._note
        self._run.error = error[:4000]
        try:
            self._run.save(update_fields=["finished_at", "ok", "due", "did",
                                          "note", "error"])
        except Exception:  # noqa: BLE001 — see module docstring
            log.exception("job_log: impossibile chiudere la riga di %s",
                          self._run.job)


@contextmanager
def record(job: str, *, dry_run: bool = False):
    """Open a run row for ``job``, yield its :class:`Recorder`, close it at the end.

    The row is created at the START and closed at the end, rather than written once
    at the end, so a run that never returns still leaves a trace: ``ok`` stays NULL,
    ``finished_at`` empty, and that is precisely the shape of "it was killed
    mid-flight" — invisible if the row were only written on the way out.

    A dry run is recorded too, and marked: it is the same code path, and hiding the
    rehearsal from the log makes the log lie about how often the job ran.
    """
    try:
        run = JobRun.objects.create(job=job, dry_run=dry_run)
    except Exception:  # noqa: BLE001 — never break the job being observed
        log.exception("job_log: impossibile aprire la riga di %s", job)
        run = None

    rec = Recorder(run)
    try:
        yield rec
    except BaseException as exc:  # noqa: BLE001 — record, then let it through
        rec._close(ok=False, error=f"{type(exc).__name__}: {exc}")
        raise
    rec._close(ok=True)


def last_run(job: str, *, ok_only: bool = False) -> JobRun | None:
    """The most recent run of ``job``, or None if it has never run here."""
    qs = JobRun.objects.filter(job=job)
    if ok_only:
        qs = qs.filter(ok=True)
    return qs.order_by("-started_at").first()
