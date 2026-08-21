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


def closed_matchdays(league, now=None, team=None) -> set[int]:
    """Real matchdays this league's managers can no longer touch AT ALL.

    The one function every "can he still field a team" question should ask, because
    it is the only one that knows the league's deadline:

    * no deadline (a league replayed over a finished season) — nothing is ever closed;
    * ``matchday`` — closed at the first kickoff, the whole XI at once;
    * ``own`` — closed at the first kickoff of one of the TEAM's players, so the
      answer is per team. Without a team — the calendar, the league views, the
      admin — it answers with the LATEST deadline any team could have, i.e. the
      round's last kickoff: a round must never read as closed while somebody can
      still field. With a team it is that team's own deadline (``team_deadline``).
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
    if league.lineup_lock_mode == FantasyLeague.LOCK_OWN:
        if team is None:
            return {md for md, last in matchday_last_kickoffs(csid).items() if last <= now}
        # A team's deadline is never earlier than the round's first kickoff, so
        # rounds that have not begun are skipped without a query each.
        return {md for md, first in matchday_locks(csid).items()
                if first <= now and is_closed_for(league, md, team, now)}
    return locked_matchdays(csid, now)


def is_closed_for(league, real_matchday: int, team, now=None) -> bool:
    """``closed_matchdays`` for ONE matchday and ONE team, without computing the
    whole season: what the save endpoint and the lineup repair actually ask."""
    from vfoot.models import FantasyLeague

    csid = league.reference_season_id
    if csid is None or not league.enforce_lineup_deadline:
        return False
    now = now or timezone.now()
    if league.lineup_lock_mode == FantasyLeague.LOCK_OWN:
        deadline, _ = team_deadline(league, team, real_matchday)
        return deadline is not None and deadline <= now
    return real_matchday in closed_matchdays(league, now)


def team_deadline(league, team, real_matchday: int):
    """Under the ``own`` deadline: when THIS team's lineup for this round closes.

    Returns ``(kickoff, match)`` — the earliest confirmed kickoff among the clubs of
    the team's players, and the match that sets it — or ``(None, None)`` when the
    league has no reference season, no deadline, or the round has no confirmed
    kickoff yet. Postponements are handled by ``player_lock_times``: a club whose
    match moved binds at the recovery, not at the original slot.

    WHICH players. Everyone owned now, PLUS everyone who was owned at the moment
    his club kicked off. The second half is not a nicety — it is what makes the
    deadline a deadline:

    * the market settles between one match of the round and the next (its freeze
      is the three hours of a match, not the whole weekend). Counting only the
      current roster, selling a man who took a 4.5 on Friday would move the
      deadline to Saturday, reopen the lineup, and let the repair swap him for
      somebody who plays on Sunday: a known vote erased. He was yours when his
      match began, so he still binds you.
    * conversely, buying on Saturday a man who played on Friday closes the lineup
      at his Friday kickoff rather than letting his known vote into it. Harsh, and
      self-inflicted — and the alternative is a market in known votes.

    So once a team's round is closed it stays closed, whatever the roster does.
    A player sold BEFORE his kickoff was not yours when it mattered and does not
    bind. ``acquired_at`` / ``released_at`` on the roster contract are the record.
    """
    from vfoot.models import FantasyLeague

    if (league.reference_season_id is None
            or not league.enforce_lineup_deadline
            or league.lineup_lock_mode != FantasyLeague.LOCK_OWN):
        return None, None
    return team_first_kickoff(league, team, real_matchday)


def team_first_kickoff(league, team, real_matchday: int):
    """``(kickoff, match)`` of the first match of the round involving one of the
    team's players — the computation behind ``team_deadline``, without the mode
    check. Under the per-player deadline it is the instant from which the manager
    knows something about his own team, i.e. the clock of the defender-count rule.
    ``(None, None)`` without a reference season or a confirmed kickoff."""
    from vfoot.models import FantasyRosterSlot
    from vfoot.services.match_resolver import matchday_fixtures_by_team
    from realdata.models import PlayerTeamStint

    csid = league.reference_season_id
    if csid is None:
        return None, None
    slots = list(
        FantasyRosterSlot.objects.filter(team_id=getattr(team, "id", team))
        .values_list("player_id", "acquired_at", "released_at")
    )
    if not slots:
        # No contract, ever: there is nothing to compute a deadline from, and the
        # conservative answer is the league-wide one — the round's first kickoff.
        m = (Match.objects.filter(competition_season_id=csid, matchday=real_matchday,
                                  kickoff_provisional=False, kickoff__isnull=False)
             .select_related("home_team__team", "away_team__team")
             .order_by("kickoff").first())
        return (m.kickoff, m) if m is not None else (None, None)
    stint = dict(
        PlayerTeamStint.objects.filter(
            player_id__in={pid for pid, _, _ in slots},
            team_season__competition_season_id=csid,
            end_date__isnull=True,
        ).values_list("player_id", "team_season_id")
    )
    fixtures = matchday_fixtures_by_team(csid, real_matchday)
    best, best_match = None, None
    for pid, acquired_at, released_at in slots:
        m = fixtures.get(stint.get(pid))
        if m is None or m.kickoff is None or m.kickoff_provisional:
            continue
        if m.status in (Match.STATUS_POSTPONED, Match.STATUS_CANCELLED):
            continue
        k = m.kickoff
        if released_at is not None and not (
                (acquired_at is None or acquired_at <= k) and k < released_at):
            continue        # gone before his match began: not yours when it mattered
        if best is None or k < best:
            best, best_match = k, m
    return best, best_match

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


def next_fieldable_matchday(league, now=None, team=None) -> int | None:
    """The earliest real matchday whose lineups can still be set.

    This — not the ledger pointer — is what the "Formazione" shortcut must follow.
    Reading it from the ledger is what used to send a manager to a matchday played
    weeks ago while hiding the one he could actually still field.

    "Still" is the league's own deadline, not a universal one: under the per-player
    lock a round that kicked off on Saturday is the round to field until the last
    club takes the pitch on Monday, and sending the manager forward to the next one
    would hide the eight players he could still move. Under the ``own`` deadline it
    is the TEAM's: pass one to get his answer, none to get the latest any team
    could have (``closed_matchdays``).
    """
    from vfoot.models import FantasyLeague

    now = now or timezone.now()
    mode = league.lineup_lock_mode if league.enforce_lineup_deadline else None
    if mode == FantasyLeague.LOCK_OWN and team is not None:
        for md in league_matchdays(league):
            if not is_closed_for(league, md.real_matchday, team, now):
                return md.real_matchday
        return None
    per_player = mode in (FantasyLeague.LOCK_PLAYER, FantasyLeague.LOCK_OWN)
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


# How far apart two matches of the SAME round can be and still be "the same
# weekend". A round runs Friday to Monday, a midweek one Tuesday to Thursday; a
# recovery played weeks later is a match of that round but not of that weekend,
# and must not keep the round on the pitch in between.
ROUND_SPAN = timedelta(days=5)


def playing_matchday(league, now=None) -> int | None:
    """The real matchday being PLAYED right now, or None between rounds.

    A round is on the pitch from its first kickoff until its last match of the
    weekend has settled — the gaps between one match and the next INCLUDED. It used
    to be "a match is on the pitch", three hours from a kickoff, and that made the
    market settle on Saturday morning between Friday's match and Saturday's: a round
    is one thing, not a string of three-hour windows.

    Per match, "over" is ``data_ready`` OR the three-hour window elapsed, whichever
    comes first — the window so that a poller that is down cannot freeze the market
    for good, the flag so that the quarter of an hour between full time and the
    data settling does not read as both 'being played' and 'complete'.

    A postponed shell is skipped: it has been moved out of its window and its replay
    is a separate row with its own kickoff — which correctly makes the matchday
    'playing' again on the day of the recovery, and only then (``ROUND_SPAN``).
    """
    now = now or timezone.now()
    cs = league.reference_season
    if cs is None:
        return None
    rows = list(
        Match.objects.filter(
            competition_season_id=cs.id,
            matchday__isnull=False,
            kickoff__isnull=False,
            kickoff_provisional=False,
            kickoff__gt=now - ROUND_SPAN - MATCH_WINDOW,
            kickoff__lte=now + ROUND_SPAN,
        )
        .exclude(status__in=[Match.STATUS_POSTPONED, Match.STATUS_CANCELLED])
        .values_list("matchday", "kickoff", "data_ready")
    )
    by_md: dict[int, list] = {}
    for md, k, ready in rows:
        by_md.setdefault(int(md), []).append((k, ready))
    playing = []
    for md, ms in by_md.items():
        started = [(k, ready) for k, ready in ms if k <= now]
        if not started:
            continue
        # A match still on the pitch, by either reading.
        if any(not ready and now < k + MATCH_WINDOW for k, ready in started):
            playing.append(md)
            continue
        # Between two matches of the same weekend: the last one that has begun
        # and a later one that is due within the span of a round.
        last_started = max(k for k, _ in started)
        if any(now < k <= last_started + ROUND_SPAN for k, _ in ms):
            playing.append(md)
    return min(playing) if playing else None


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
