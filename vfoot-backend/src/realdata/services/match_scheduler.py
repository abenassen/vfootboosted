"""Match scheduling policy — the pure decision layer the ``tick`` command runs.

Kept separate from the command so it is unit-testable and has no I/O: given the
current time and a set of matches, it decides which scrape actions are due. This
is the DB-driven scheduler at the heart of the semiautomatic pipeline — there
are NO per-match cron entries; the tick simply asks "what is due now?" each run,
which makes it robust to calendar changes (a postponed kickoff just fires later).

Two windows:

* LIVE — from a CONFIRMED kickoff until a generous upper bound, poll the live
  match (provisional score/events). Provisional kickoffs are skipped (the slot
  isn't real yet); a match already flagged ``live`` is always polled as a
  fallback even outside the nominal window. Inside this same window, and on its
  own slower clock, the FULL per-player data is imported so the votes move while
  the match is being played — without ever promoting it to ``data_ready``.
* FINALIZATION — measured from the observed full-time (``finished_at``): a first
  scrape at +15 min (data is usually settled by then) and a confirmation at
  +1 h that promotes the match to ``data_ready``. Between +15 and +1 h the tick
  keeps re-scraping so any late revision is caught before confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.conf import settings

from realdata.models import Match

# Generous upper bound after kickoff for the live-poll window (90' + halftime +
# stoppage + margin). The window only bounds when we START/STOP polling; actual
# full-time is detected from the provider status, not from this number.
LIVE_POLL_WINDOW = timedelta(minutes=135)

def live_poll_interval() -> timedelta:
    """Minimum gap between two scrapes of the SAME live match. Read at call time so
    the cadence can be retuned (env var) without a code change — the knob that fits
    the pipeline to the machine."""
    return timedelta(minutes=float(getattr(settings, "VFOOT_LIVE_POLL_MINUTES", 2)))


def live_import_interval() -> timedelta:
    """Minimum gap between two FULL imports of the same live match — its own cadence,
    slower than the light poll's on purpose.

    Ten minutes is the rhythm at which a performance actually changes, and it divides
    the writing by five compared to polling's two. The two windows are the same; only
    how often each fires inside it differs.
    """
    return timedelta(minutes=float(getattr(settings, "VFOOT_LIVE_IMPORT_MINUTES", 10)))


# Finalization checkpoints, measured from observed full-time.
FINAL_CHECK_AFTER = timedelta(minutes=15)
FINAL_CONFIRM_AFTER = timedelta(minutes=60)

# Action kinds
STAMP_FT = "stamp_ft"          # first time seen finished -> record finished_at
LIVE_POLL = "live_poll"        # scrape the in-progress match
LIVE_IMPORT = "live_import"    # full per-player import WITHOUT promoting the match
FINAL_CHECK = "final_check"    # +15min post-FT scrape (provisional-final)
FINAL_CONFIRM = "final_confirm"  # +1h post-FT scrape -> data_ready


@dataclass
class TickPlan:
    stamp_ft: list[Match] = field(default_factory=list)
    live_poll: list[Match] = field(default_factory=list)
    live_import: list[Match] = field(default_factory=list)
    final_check: list[Match] = field(default_factory=list)
    final_confirm: list[Match] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.stamp_ft or self.live_poll or self.live_import
                    or self.final_check or self.final_confirm)

    def summary(self) -> str:
        return (f"stamp_ft={len(self.stamp_ft)} live_poll={len(self.live_poll)} "
                f"live_import={len(self.live_import)} "
                f"final_check={len(self.final_check)} "
                f"final_confirm={len(self.final_confirm)}")


def _in_live_window(match: Match, now: datetime) -> bool:
    if match.status == Match.STATUS_LIVE:
        return True  # already live: always poll, even outside the nominal window
    if match.status != Match.STATUS_SCHEDULED:
        return False
    if match.kickoff is None or match.kickoff_provisional:
        return False  # no confirmed slot yet
    return match.kickoff <= now < match.kickoff + LIVE_POLL_WINDOW


def plan_tick(now: datetime, matches) -> TickPlan:
    """Classify each match into the action(s) due at ``now``."""
    plan = TickPlan()
    for m in matches:
        # A finished match we've never stamped: record full-time now, then it
        # enters the finalization schedule on subsequent ticks.
        if m.status == Match.STATUS_FINISHED and m.finished_at is None:
            plan.stamp_ft.append(m)
            continue

        if _in_live_window(m, now):
            # Honour the per-match cadence: the tick may fire every minute, but a
            # given match is re-scraped only every VFOOT_LIVE_POLL_MINUTES.
            last = m.data_checked_at
            if last is None or now - last >= live_poll_interval():
                plan.live_poll.append(m)
            # The full import rides the same window on its own, slower clock. Its own
            # stamp too: sharing data_checked_at with the poll above would mean the
            # poll, firing five times as often, kept pushing the import's next due
            # time out and it would never come round.
            imported = m.data_imported_at
            if imported is None or now - imported >= live_import_interval():
                plan.live_import.append(m)
            continue

        if (m.status == Match.STATUS_FINISHED and not m.data_ready
                and m.finished_at is not None):
            if now >= m.finished_at + FINAL_CONFIRM_AFTER:
                plan.final_confirm.append(m)
            elif now >= m.finished_at + FINAL_CHECK_AFTER:
                plan.final_check.append(m)

    return plan


def candidate_matches():
    """Matches worth considering each tick: on a syncable real season, not yet
    finalized. Bounds the per-tick queryset."""
    return (Match.objects
            .filter(status__in=[Match.STATUS_SCHEDULED, Match.STATUS_LIVE,
                                Match.STATUS_FINISHED],
                    data_ready=False)
            .exclude(competition_season__external_id="")
            .select_related("competition_season", "home_team__team",
                            "away_team__team"))
