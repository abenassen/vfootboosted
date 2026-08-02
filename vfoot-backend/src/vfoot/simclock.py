"""A shifted clock, for looking at a simulated season from inside it.

The problem it solves. A simulated season lives at ITS dates: 2026-27 starts on 22
August 2026 and reaches matchday 22 on 30 January 2027. Looking at it from today
means seeing twenty-one concluded matchdays that the calendar places in the future
— and with them every deadline inverted: lineups still settable for rounds already
played, negative market countdowns, ``playing_matchday`` forever empty.

There are two ways to put that right, and it is worth saying why this one. The
first is to translate the calendar, bringing matchday 22 under today's date: that
changes the DATA, and from then on the calendar in the database is no longer the
provider's — the next ``sync_calendar`` would restore it and the simulation would
come apart. The second, this one, moves the OBSERVER: the data stays what the
provider actually publishes, and what moves is the only thing that is not data,
namely the moment you look from.

How. The whole project reads the time through ``django.utils.timezone.now``, so
there is a single place to hook. It has to be hooked EARLY, though: fields declared
``default=timezone.now`` capture the function when the model class is defined, i.e.
while the apps load, and a patch installed after that would miss them — leaving
creation stamps on the real clock while everything else is shifted. Which is why
``install()`` is called from settings.py, which Django runs before importing the
models, and not from ``AppConfig.ready()``, which is too late.

The clock WALKS: it shifts the origin, it does not freeze time. A frozen clock
would make every countdown never expire and two consecutive requests
indistinguishable — a different way of not being able to exercise the app.

It only activates with the environment variable; without it this module touches
nothing:

    VFOOT_FAKE_NOW="2027-01-31T17:00:00+01:00"
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone as dt_timezone

# The gap between the real clock and the simulated one, measured once: from then on
# the fake clock advances exactly like the real one.
_OFFSET: timedelta | None = None
_ORIGIN: datetime | None = None


def offset() -> timedelta | None:
    """How far the clock is shifted, or None if it was never shifted."""
    return _OFFSET


def origin() -> datetime | None:
    """The simulated instant that was asked for, as of installation time."""
    return _ORIGIN


def is_active() -> bool:
    return _OFFSET is not None


def parse(raw: str) -> datetime:
    """Read the requested instant. A value with no explicit offset is read as UTC:
    guessing the server's local zone would move the simulation by an hour between
    the development laptop and the VPS."""
    value = datetime.fromisoformat(str(raw).strip())
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_timezone.utc)
    return value


def install(raw: str | None = None) -> datetime | None:
    """Hook the fake clock. Idempotent; returns the simulated instant.

    Must be called from settings.py — see the module docstring for why.
    """
    global _OFFSET, _ORIGIN
    raw = raw if raw is not None else os.environ.get("VFOOT_FAKE_NOW", "")
    if not raw:
        return None
    if _OFFSET is not None:
        return _ORIGIN

    from django.utils import timezone as dj_timezone

    real_now = dj_timezone.now  # the REAL function, captured before replacing it
    _ORIGIN = parse(raw)
    # The gap is measured against the system clock, not against ``real_now()``: we
    # are inside the execution of settings.py, and ``timezone.now()`` would read
    # USE_TZ from a settings module that is only half-built — the one moment that
    # read is not safe. The two answer the same question anyway ("now"), and the
    # gap is what matters.
    _OFFSET = _ORIGIN - datetime.now(dt_timezone.utc)

    def now():
        return real_now() + _OFFSET

    now.__doc__ = (f"timezone.now() shifted by {_OFFSET} "
                   f"(simulated clock, VFOOT_FAKE_NOW={raw!r})")
    dj_timezone.now = now
    return _ORIGIN
