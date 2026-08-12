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
    """Every real matchday that has KICKED OFF — its first confirmed kickoff is past.

    This is the "the round has begun" fact: it is what makes a live tabellino exist
    and what stops a competition from being planned onto that matchday. Whether a
    manager may still touch his lineup is a different question, because under the
    per-player deadline he may — see ``closed_matchdays``.
    """
    now = now or timezone.now()
    return {md for md, first in matchday_locks(competition_season_id).items() if first <= now}


def matchday_last_kickoffs(competition_season_id: int) -> dict[int, object]:
    """{real_matchday: LAST confirmed kickoff}, the mirror of ``matchday_locks``.

    Under the per-player deadline this is when a round finally closes: the moment
    the last club takes the pitch there is nobody left to decide about.
    """
    from django.db.models import Max

    rows = (
        Match.objects.filter(
            competition_season_id=competition_season_id,
            kickoff_provisional=False,
            kickoff__isnull=False,
            matchday__isnull=False,
        )
        .exclude(status__in=[Match.STATUS_POSTPONED, Match.STATUS_CANCELLED])
        .values("matchday")
        .annotate(last=Max("kickoff"))
        .values_list("matchday", "last")
    )
    return {int(md): last for md, last in rows}


def closed_matchdays(league, now=None) -> set[int]:
    """Real matchdays this league's managers can no longer touch AT ALL.

    The one function every "can he still field a team" question should ask, because
    it is the only one that knows the league's deadline:

    * no deadline (a league replayed over a finished season) — nothing is ever closed;
    * ``matchday`` — closed at the first kickoff, the whole XI at once;
    * ``player`` — closed only at the LAST kickoff. In between the round is *partly*
      locked, which is not the same thing and is exactly what used to have no way of
      being said: ``locked_matchdays`` would have shut the page on a manager who
      still had a Monday-night striker to decide about.
    """
    from vfoot.models import FantasyLeague

    csid = league.reference_season_id
    if csid is None or not league.enforce_lineup_deadline:
        return set()
    now = now or timezone.now()
    if league.lineup_lock_mode == FantasyLeague.LOCK_PLAYER:
        return {md for md, last in matchday_last_kickoffs(csid).items() if last <= now}
    return locked_matchdays(csid, now)


def player_lock_times(competition_season_id: int, real_matchday: int) -> dict[int, object]:
    """{team_season_id: confirmed kickoff of that club's match in this round}.

    Keyed on the club and not on the player: a lineup holds twenty-five players from
    ten clubs, and the deadline is a property of the club's fixture. A postponed
    match does not lock anybody — ``matchday_fixtures_by_team`` already prefers the
    replay row, so the club's deadline moves to the recovery, which is the right
    answer for a manager who has to decide about a player nobody is going to play.
    """
    from vfoot.services.match_resolver import matchday_fixtures_by_team

    out: dict[int, object] = {}
    for ts_id, m in matchday_fixtures_by_team(competition_season_id, real_matchday).items():
        if m.kickoff is None or m.kickoff_provisional:
            continue
        if m.status in (Match.STATUS_POSTPONED, Match.STATUS_CANCELLED):
            continue
        out[ts_id] = m.kickoff
    return out


def locked_players(league, real_matchday: int, player_ids, now=None) -> set[int]:
    """Of these players, the ones already frozen for this matchday.

    Empty under the matchday-wide deadline: there the lineup locks as a block and
    naming individual players would be misleading. Under the per-player deadline it
    is the set whose clubs have taken the pitch.
    """
    from vfoot.models import FantasyLeague
    from realdata.models import PlayerTeamStint

    csid = league.reference_season_id
    if (csid is None
            or not league.enforce_lineup_deadline
            or league.lineup_lock_mode != FantasyLeague.LOCK_PLAYER):
        return set()
    player_ids = list(player_ids)
    if not player_ids:
        return set()
    now = now or timezone.now()
    kicked = {ts_id for ts_id, k in player_lock_times(csid, real_matchday).items() if k <= now}
    if not kicked:
        return set()
    return {
        pid
        for pid, ts_id in PlayerTeamStint.objects.filter(
            player_id__in=player_ids,
            team_season__competition_season_id=csid,
            end_date__isnull=True,
        ).values_list("player_id", "team_season_id")
        if ts_id in kicked
    }


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

    "Still" is the league's own deadline, not a universal one: under the per-player
    lock a round that kicked off on Saturday is the round to field until the last
    club takes the pitch on Monday, and sending the manager forward to the next one
    would hide the eight players he could still move.
    """
    from vfoot.models import FantasyLeague

    now = now or timezone.now()
    per_player = (league.enforce_lineup_deadline
                  and league.lineup_lock_mode == FantasyLeague.LOCK_PLAYER)
    locks: dict[int, dict[int, object]] = {}
    for md in league_matchdays(league):
        csid = md.real_competition_season_id
        if csid not in locks:
            locks[csid] = (matchday_last_kickoffs(csid) if per_player
                           else matchday_locks(csid))
        deadline = locks[csid].get(md.real_matchday)
        if deadline is None or deadline > now:
            return md.real_matchday
    return None


def playing_matchday(league, now=None) -> int | None:
    """The real matchday with a match ON THE PITCH right now, or None between rounds.

    A postponed shell is skipped: it has been moved out of its window and its
    replay is a separate row with its own kickoff — which correctly makes the
    matchday 'playing' again on the day of the recovery.

    A match already promoted to ``data_ready`` is skipped too, and that one is not
    an optimisation: the time window is 3 hours from kick-off, while the data
    settles at +1h from full time, i.e. around +2h45. So for the quarter of an hour
    between the two the round was BOTH 'being played' and 'complete', and the home
    said "la giornata 22 e' finita, puoi calcolare i punteggi" directly above "si
    gioca la giornata 22" — every single round, not only in the simulator. The
    window bounds when we start looking; what ends a round is its data settling.
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
            data_ready=False,
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
# The season itself: is there still football to be played in it?               #
# --------------------------------------------------------------------------- #
def open_season_ids() -> set[int]:
    """The CompetitionSeasons a league can still be tied to: those with at least
    one match left to play, plus those whose calendar we do not have yet.

    A league lives ON a championship — its rosters, its listone and its own
    calendar all hang off it — so binding one to a season that is over produces a
    league that can never play a single round. The reference season is immutable
    once set, so this has to be caught at the only moment it can be: the choice.

    "Left to play" is read off the CALENDAR (a scheduled or live match) and not
    off a date: the season's own start/end dates are optional in the schema and
    are in fact empty for every season we hold, while the fixture list is the
    thing the sync keeps fresh. A season with NO matches at all is open too — it
    is next year's edition, minted by ``probe_next_season`` before its calendar
    is published, which is precisely the one a league is being created for in
    August. Postponed-and-never-replayed fixtures do not keep a season alive:
    they outlive the last round by design and would make every past season read
    as still running.
    """
    from realdata.models import CompetitionSeason

    with_calendar = set(Match.objects.values_list("competition_season_id", flat=True).distinct())
    still_to_play = set(
        Match.objects.filter(status__in=(Match.STATUS_SCHEDULED, Match.STATUS_LIVE))
        .values_list("competition_season_id", flat=True)
        .distinct()
    )
    all_ids = set(CompetitionSeason.objects.values_list("id", flat=True))
    return still_to_play | (all_ids - with_calendar)


def season_is_open(competition_season_id: int) -> bool:
    """``open_season_ids`` for a single season."""
    return competition_season_id in open_season_ids()


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
