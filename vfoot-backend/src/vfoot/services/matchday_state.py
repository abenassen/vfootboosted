"""The two clocks of a league, kept apart on purpose.

A league answers two questions that look like one and are not:

* **what is being played** — which round can still be fielded, which one is on the
  pitch right now, when the lineups lock. This is a fact of the real calendar. It
  must never wait for anyone: a distracted admin who forgets to close matchday 16
  cannot be allowed to stop the managers of matchday 18 from fielding a team.
* **what has been counted** — which round has been scored, and therefore what the
  table says. This is the league's ledger, it belongs to the admin, and it is
  allowed to run late.

When the admin is punctual the two coincide and nobody notices. When they diverge
the divergence is itself the thing worth showing ("si gioca la 18, il registro è
fermo alla 16") — which is why they are computed separately here instead of being
derived from one another, as they were when a single "current matchday" pointer
had to answer both.

Everything in this module is DERIVED from the calendar and the ledger rows; the
only stored state is ``FantasyMatchday.status``.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from realdata.models import Match
from vfoot.models import FantasyMatchday

# How long a match occupies the pitch. Used to answer "is a match being played
# right now" from the CALENDAR alone, without depending on a live poller having
# flipped a status: a definition that needs the poller can get stuck forever if
# the poller is down, and "the market is frozen forever" is exactly the class of
# failure this module exists to avoid.
MATCH_WINDOW = timedelta(hours=3)


# --------------------------------------------------------------------------- #
# The real calendar: what is being played.                                     #
# --------------------------------------------------------------------------- #
def lineup_lock_at(competition_season_id: int, real_matchday: int):
    """When lineups for this real matchday lock: its first CONFIRMED kickoff.

    A provisional kickoff (the provider still shipping one placeholder timestamp
    for the whole round) does not lock anything — the slot is not known yet.
    Returns None when the round has no confirmed kickoff at all, which reads as
    "not locked".
    """
    return (
        Match.objects.filter(
            competition_season_id=competition_season_id,
            matchday=real_matchday,
            kickoff_provisional=False,
            kickoff__isnull=False,
        )
        .order_by("kickoff")
        .values_list("kickoff", flat=True)
        .first()
    )


def is_locked(competition_season_id: int, real_matchday: int, now=None) -> bool:
    lock = lineup_lock_at(competition_season_id, real_matchday)
    return lock is not None and lock <= (now or timezone.now())


def matchday_locks(competition_season_id: int) -> dict[int, object]:
    """{real_matchday: first confirmed kickoff} for a whole season, in one query.

    The per-matchday lookup costs a query each, which a calendar of 38 rounds turns
    into 38 — this is the same answer for the whole season at once.
    """
    from django.db.models import Min

    rows = (
        Match.objects.filter(
            competition_season_id=competition_season_id,
            kickoff_provisional=False,
            kickoff__isnull=False,
            matchday__isnull=False,
        )
        .values("matchday")
        .annotate(first=Min("kickoff"))
        .values_list("matchday", "first")
    )
    return {int(md): first for md, first in rows}


def locked_matchdays(competition_season_id: int, now=None) -> set[int]:
    """Every real matchday whose lineups have already locked."""
    now = now or timezone.now()
    return {md for md, first in matchday_locks(competition_season_id).items() if first <= now}


def league_matchdays(league):
    """The league's ledger rows, in calendar order."""
    return list(
        FantasyMatchday.objects.filter(league=league).order_by("real_matchday", "id")
    )


def next_fieldable_matchday(league, now=None) -> int | None:
    """The earliest real matchday whose lineups can still be set.

    This — not the ledger pointer — is what the "Formazione" shortcut must follow.
    Reading it from the ledger is what used to send a manager to a matchday played
    weeks ago while hiding the one he could actually still field.
    """
    now = now or timezone.now()
    locks: dict[int, dict[int, object]] = {}
    for md in league_matchdays(league):
        csid = md.real_competition_season_id
        if csid not in locks:
            locks[csid] = matchday_locks(csid)
        first = locks[csid].get(md.real_matchday)
        if first is None or first > now:
            return md.real_matchday
    return None


def playing_matchday(league, now=None) -> int | None:
    """The real matchday with a match ON THE PITCH right now, or None between rounds.

    A postponed shell is skipped: it has been moved out of its window and its
    replay is a separate row with its own kickoff — which correctly makes the
    matchday 'playing' again on the day of the recovery.
    """
    now = now or timezone.now()
    cs = league.reference_season
    if cs is None:
        return None
    row = (
        Match.objects.filter(
            competition_season_id=cs.id,
            kickoff__lte=now,
            kickoff__gt=now - MATCH_WINDOW,
            matchday__isnull=False,
        )
        .exclude(status__in=[Match.STATUS_POSTPONED, Match.STATUS_CANCELLED])
        .order_by("kickoff")
        .values_list("matchday", flat=True)
        .first()
    )
    return int(row) if row is not None else None


def is_matchday_in_progress(league, now=None) -> bool:
    """True while the reference championship is physically being played.

    The market's settlement freeze keys on THIS and never on the conclusions: a
    freeze that waited for an admin to close a matchday would let a forgetful one
    freeze the market for good.
    """
    return playing_matchday(league, now) is not None


# --------------------------------------------------------------------------- #
# The ledger: what has been counted.                                           #
# --------------------------------------------------------------------------- #
def ledger_matchday(league):
    """The matchday the league is due to score next: the earliest that is neither
    concluded nor parked as awaiting. None when the ledger is up to date."""
    return (
        FantasyMatchday.objects.filter(league=league, status=FantasyMatchday.STATUS_PLANNED)
        .order_by("real_matchday", "id")
        .first()
    )


def awaiting_matchdays(league) -> list:
    """Matchdays parked by the admin, waiting for a postponed match to be played."""
    return list(
        FantasyMatchday.objects.filter(league=league, status=FantasyMatchday.STATUS_AWAITING)
        .order_by("real_matchday", "id")
    )


def conclusion_queue(league) -> list:
    """Everything the admin owes the league, oldest first.

    An awaiting matchday belongs here as soon as its recovery has been played, and
    the ledger pointer as soon as its round is complete — plus every round behind
    them, because arrears are the normal shape of a forgotten conclusion and the
    admin should see them as ONE queue rather than discovering them one at a time.
    """
    from vfoot.api.league_views import _real_matchday_stats  # local: avoids a cycle

    out = []
    for md in league_matchdays(league):
        if md.status == FantasyMatchday.STATUS_CONCLUDED:
            continue
        stats = _real_matchday_stats(md.real_competition_season_id, md.real_matchday, league)
        if stats["is_completed"]:
            out.append(md)
    return out


def can_conclude(league, md) -> tuple[bool, str]:
    """May this matchday be concluded now? (allowed, reason-if-not).

    In order, with one exception that is the point of the awaiting state: a parked
    matchday may be concluded whenever its recovery has been played, without first
    having to close everything that has happened since.
    """
    if md.status == FantasyMatchday.STATUS_CONCLUDED:
        return False, "La giornata è già conclusa."
    if md.status == FantasyMatchday.STATUS_AWAITING:
        return True, ""
    pointer = ledger_matchday(league)
    if pointer is not None and pointer.id != md.id:
        return False, (
            f"Concludi le giornate in ordine — la prima da chiudere è la "
            f"{pointer.real_matchday}."
        )
    return True, ""
