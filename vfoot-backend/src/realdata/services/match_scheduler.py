"""Match scheduling policy — the pure decision layer the ``tick`` command runs.

Kept separate from the command so it is unit-testable and has no I/O: given the
current time and a set of matches, it decides which scrape actions are due. This
is the DB-driven scheduler at the heart of the semiautomatic pipeline — there
are NO per-match cron entries; the tick simply asks "what is due now?" each run,
which makes it robust to calendar changes (a postponed kickoff just fires later).

Two windows:

* LIVE — from a CONFIRMED kickoff until a generous upper bound, one ROUND every
  ``VFOOT_LIVE_POLL_MINUTES``: status, score and the per-player data, so the votes
  move while the match is being played — without ever promoting it to
  ``data_ready``. Provisional kickoffs are skipped (the slot isn't real yet); a
  match already flagged ``live`` always gets its round, even outside the nominal
  window. Every ``VFOOT_LIVE_HEAVY_EVERY``-th round is also HEAVY: it pulls a
  heatmap per player and with them the positional half of the model. One clock,
  one flag — not two clocks competing to push each other's due time out.
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
    """Minimum gap between two rounds of the SAME live match — the TIME of the
    cadence. Read at call time so it can be retuned (env var) without a code
    change: the knob that fits the pipeline to the machine."""
    return timedelta(minutes=float(getattr(settings, "VFOOT_LIVE_POLL_MINUTES", 2)))


def live_heavy_every() -> int:
    """How many light rounds go by per heavy one — the SHAPE of the cadence, as
    opposed to ``live_poll_interval``'s time.

    Two knobs of different natures, and keeping them apart is what lets the rig run
    at production's shape while compressing its clock (see ``vfoot-sim``). At k=1
    every round is heavy and the distinction disappears altogether, which is exactly
    the behaviour a rig must not hide.
    """
    return max(1, int(getattr(settings, "VFOOT_LIVE_HEAVY_EVERY", 4)))


def live_heavy_interval() -> timedelta:
    """Minimum gap between two HEAVY rounds of the same live match.

    Expressed as k times the light interval rather than counted on the match, which
    costs no column. The trade: a light round skipped because the egress was blocked
    does not postpone the heavy one, so it follows the clock rather than the rounds
    actually made. In practice the difference is a couple of minutes once.
    """
    return live_heavy_every() * live_poll_interval()


# Finalization checkpoints, measured from observed full-time.
FINAL_CHECK_AFTER = timedelta(minutes=15)
FINAL_CONFIRM_AFTER = timedelta(minutes=60)

# Action kinds
STAMP_FT = "stamp_ft"          # first time seen finished -> record finished_at
LIVE_ROUND = "live_round"      # one live round: status, score and the votes
LIVE_HEAVY = "live_heavy"      # the k-th round, which also pulls the heatmaps
FINAL_CHECK = "final_check"    # +15min post-FT scrape (provisional-final)
FINAL_CONFIRM = "final_confirm"  # +1h post-FT scrape -> data_ready


@dataclass
class TickPlan:
    stamp_ft: list[Match] = field(default_factory=list)
    live_round: list[Match] = field(default_factory=list)
    # A SUBSET of live_round, never a separate list of work: the heavy pass is a
    # flag on a round, which is what having one clock means.
    live_heavy: list[Match] = field(default_factory=list)
    final_check: list[Match] = field(default_factory=list)
    final_confirm: list[Match] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.stamp_ft or self.live_round
                    or self.final_check or self.final_confirm)

    def summary(self) -> str:
        return (f"stamp_ft={len(self.stamp_ft)} live_round={len(self.live_round)} "
                f"(heavy={len(self.live_heavy)}) "
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
            # given match gets a round only every VFOOT_LIVE_POLL_MINUTES.
            last = m.data_checked_at
            if last is None or now - last >= live_poll_interval():
                plan.live_round.append(m)
                # ...and every k-th round carries the heavy pass with it. Its own
                # stamp, but no longer its own clock: a heavy pass never happens
                # outside a round, so the two cannot race each other any more.
                imported = m.data_imported_at
                if imported is None or now - imported >= live_heavy_interval():
                    plan.live_heavy.append(m)
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
