"""The simulated clock: what has to hold for it to be worth having.

The two interesting properties are neither of them "it returns the date I gave it".
The first is that the clock WALKS: freezing it would make every countdown eternal.
The second is that without the environment variable nothing changes at all —
because this module is loaded ALWAYS, production included, and doing nothing is the
condition for keeping it there.
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import TestCase

from vfoot import simclock


class ParseTests(TestCase):
    def test_naive_is_utc(self):
        """An instant with no offset means UTC, not the machine's local time: the
        same simulation must land at the same moment on the laptop and on the
        server, which are not necessarily in the same zone."""
        self.assertEqual(simclock.parse("2027-01-31T17:00:00").tzinfo, dt_timezone.utc)

    def test_explicit_offset_is_respected(self):
        value = simclock.parse("2027-01-31T17:00:00+01:00")
        self.assertEqual(value.astimezone(dt_timezone.utc).hour, 16)


class InstallTests(TestCase):
    """``install()`` is exercised on a restored copy of the module state: the real
    one has already been installed (or not) by settings.py, and re-installing here
    would shift the clock for the whole suite."""

    def setUp(self):
        from django.utils import timezone as dj

        self._real_now = dj.now
        self._saved = (simclock._OFFSET, simclock._ORIGIN)
        simclock._OFFSET = simclock._ORIGIN = None
        self.addCleanup(self._restore)

    def _restore(self):
        from django.utils import timezone as dj

        dj.now = self._real_now
        simclock._OFFSET, simclock._ORIGIN = self._saved

    def test_without_the_variable_nothing_is_touched(self):
        from django.utils import timezone as dj

        self.assertIsNone(simclock.install(""))
        self.assertIs(dj.now, self._real_now)
        self.assertFalse(simclock.is_active())

    def test_shifts_the_clock(self):
        from django.utils import timezone as dj

        simclock.install("2027-01-31T16:00:00+00:00")
        self.assertTrue(simclock.is_active())
        drift = dj.now() - datetime(2027, 1, 31, 16, tzinfo=dt_timezone.utc)
        self.assertLess(abs(drift), timedelta(seconds=5))

    def test_the_clock_walks(self):
        """Simulated time advances like real time. A STOPPED clock would let no
        market session ever expire and make two consecutive requests
        indistinguishable: you would be looking at a photograph, not an app."""
        from django.utils import timezone as dj

        simclock.install("2027-01-31T16:00:00+00:00")
        first = dj.now()
        # Compared against the system clock rather than by sleeping: the test stays
        # instant and measures the same thing, that the two advance together.
        expected = datetime.now(dt_timezone.utc) + simclock.offset()
        self.assertLess(abs(expected - first), timedelta(seconds=5))
        self.assertGreaterEqual(dj.now(), first)

    def test_installing_twice_does_not_compound_the_offset(self):
        simclock.install("2027-01-31T16:00:00+00:00")
        shift = simclock.offset()
        simclock.install("2030-01-01T00:00:00+00:00")
        self.assertEqual(simclock.offset(), shift)
