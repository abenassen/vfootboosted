"""What the leagues are told while a real match is being played.

Two channels, and they are for opposite situations — the distinction is the whole
design, not a detail of it:

* **the WebSocket nudge** reaches pages that are OPEN. It fires after any import
  that moved anything, carries no data, and its only job is to make the page
  re-read. Cheap enough to send every ten minutes for two hours.
* **the push** reaches people who are NOT looking — the phone in a pocket, the app
  closed. It costs the user's attention every single time, so it is spent only on
  what would make somebody put down what they are doing: **a goal by one of his
  players, a sending-off, and full time**. Never a vote that moved; that would be a
  notification every ten minutes per match, which is the fastest way to have the
  permission revoked for good.

WHO GETS THE PUSH. Whoever FIELDED the player in the matchday being played — read
from the saved lineup, not from the roster. Owning a player you left on the bench
is not a reason to be woken up, and the bench itself is: a benched player who has
come on is scoring for you.

WHY BEFORE/AFTER. The import overwrites; it does not report. So the events have to
be read off the difference between two snapshots of the same match, taken either
side of it. That is also what makes them fire exactly once: the second import sees
the same goal in both snapshots and says nothing.
"""
from __future__ import annotations

import logging

from realdata.models import (
    CARD_RED, CARD_SECOND_YELLOW, Match, MatchAppearance,
    MatchDisciplinaryEvent, Player, PlayerTeamStint,
)
from vfoot.models import (
    FantasyLeague, FantasyMatchday, LeagueMembership, SavedLineupSnapshot,
)
from vfoot.services import push_channel

log = logging.getLogger(__name__)

SENT_OFF = (CARD_RED, CARD_SECOND_YELLOW)

# Where a tapped notification lands: the league home, which is where the section
# with the matches being played is — one tap from every tabellino of the round.
# Not the fixture page directly, because "which fixture" depends on who is reading
# and a notification is composed once for several people.
LIVE_URL = "/home"


# --------------------------------------------------------------------------- #
# The nudge                                                                    #
# --------------------------------------------------------------------------- #
def leagues_following(match: Match):
    """Every league whose reference season is the one this match belongs to.

    A league follows a whole championship, not individual matches: it is the round
    that is being played, and any of its ten matches can move any of its tabellini.
    """
    return FantasyLeague.objects.filter(
        reference_season_id=match.competition_season_id)


def leagues_to_nudge(match: Match) -> set[int]:
    """The league ids that would want to hear about this match changing.

    Collected rather than nudged on the spot: a tick that imports the three matches
    of a Sunday evening would otherwise send three nudges, and every open page would
    re-read the whole calendar three times in eight seconds. The round changed once.
    """
    return set(leagues_following(match).values_list("id", flat=True))


def broadcast_leagues(league_ids) -> int:
    """Send ONE nudge per league. Returns how many went out."""
    from vfoot.services.live_realtime import broadcast_live

    ids = sorted(set(league_ids))
    for league_id in ids:
        broadcast_live(league_id, kind="scores")
    return len(ids)


def broadcast_match(match: Match) -> int:
    """Nudge every league following this match — the single-match convenience."""
    return broadcast_leagues(leagues_to_nudge(match))


# --------------------------------------------------------------------------- #
# Before / after                                                               #
# --------------------------------------------------------------------------- #
def snapshot_events(match: Match) -> dict:
    """{player_id: (goals, sent_off)} as the database holds it RIGHT NOW.

    Taken immediately before an import so the same import's writes can be diffed
    against it. Cheap: two aggregate reads over one match.
    """
    goals = dict(MatchAppearance.objects.filter(match=match)
                 .values_list("player_id", "goals"))
    off = set(MatchDisciplinaryEvent.objects
              .filter(match=match, card_type__in=SENT_OFF)
              .values_list("player_id", flat=True))
    return {pid: (int(goals.get(pid) or 0), pid in off)
            for pid in set(goals) | off}


def _new_events(before: dict, after: dict) -> list[tuple[int, str, int]]:
    """(player_id, kind, count) for what happened between the two snapshots.

    A player absent from ``before`` is a player who had not appeared yet — a
    substitute who has just come on. His goals are new; his cards too.
    """
    out = []
    for pid, (goals, off) in after.items():
        prev_goals, prev_off = before.get(pid, (0, False))
        if goals > prev_goals:
            out.append((pid, "goal", goals - prev_goals))
        if off and not prev_off:
            out.append((pid, "red", 1))
    return out


# --------------------------------------------------------------------------- #
# Who is fielding whom                                                         #
# --------------------------------------------------------------------------- #
def _playing_matchdays(match: Match):
    """The (league, FantasyMatchday) pairs this match feeds, still open.

    A concluded matchday is frozen: whatever happens in a recovery of it is the
    admin's business, not a notification's.
    """
    if match.matchday is None:
        return []
    return [
        (md.league, md) for md in
        FantasyMatchday.objects
        .filter(real_competition_season_id=match.competition_season_id,
                real_matchday=match.matchday)
        .exclude(status=FantasyMatchday.STATUS_CONCLUDED)
        .select_related("league")
    ]


def _managers_fielding(league, md, player_ids: set) -> dict:
    """{player_id: [user, ...]} — who has each player in a saved lineup this round.

    Read from the snapshots directly rather than through ``read_saved_lineup``: that
    one resolves ONE team's lineup for one competition, and here the question is the
    other way round (who, in this whole league, fielded any of these players). A
    league with a cup as well as a championship has several lineups per team and
    every one of them counts — the player is playing for that manager either way.

    ``lineup_id`` is ``team<id>`` or ``team<id>:comp<n>``; the team is its prefix.
    """
    if not player_ids:
        return {}
    users_by_team = {
        mem.team.id: mem.user
        for mem in LeagueMembership.objects.filter(league=league)
        .select_related("user", "team")
        if getattr(mem, "team", None) is not None
    }
    out: dict[int, list] = {}
    for snap in SavedLineupSnapshot.objects.filter(
            league_id=str(league.id), matchday_id=str(md.real_matchday),
            lineup_id__startswith="team"):
        team_id = _team_of_lineup(snap.lineup_id)
        user = users_by_team.get(team_id)
        if user is None:
            continue
        fielded = {int(x) for x in (snap.starter_player_ids or [])}
        fielded |= {int(x) for x in (snap.bench_player_ids or [])}
        if snap.gk_player_id:
            fielded.add(int(snap.gk_player_id))
        for pid in fielded & player_ids:
            bucket = out.setdefault(pid, [])
            if user not in bucket:
                bucket.append(user)
    return out


def _team_of_lineup(lineup_id: str) -> int | None:
    head = str(lineup_id or "").split(":")[0]
    return int(head[4:]) if head[:4] == "team" and head[4:].isdigit() else None


# --------------------------------------------------------------------------- #
# The two announcements                                                        #
# --------------------------------------------------------------------------- #
def announce_events(match: Match, before: dict) -> int:
    """Push the goals and sendings-off that happened since ``before``.

    Returns how many notifications went out. Never raises: this runs inside the
    tick, and a push service having a bad minute must not cost an import.
    """
    try:
        return _announce_events(match, before)
    except Exception:  # noqa: BLE001
        log.exception("Notifiche live fallite per la partita %s", match.id)
        return 0


def _announce_events(match: Match, before: dict) -> int:
    if not push_channel.configured():
        return 0
    events = _new_events(before, snapshot_events(match))
    if not events:
        return 0
    names = dict(Player.objects.filter(id__in=[pid for pid, _k, _n in events])
                 .values_list("id", "full_name"))
    sent = 0
    for league, md in _playing_matchdays(match):
        fielding = _managers_fielding(league, md, {pid for pid, _k, _n in events})
        for pid, kind, count in events:
            name = names.get(pid, str(pid))
            if kind == "goal":
                title = f"⚽ Gol di {name}" + (" (doppietta!)" if count > 1 else "")
                body = f"{_scoreline(match)} · il voto si sta muovendo."
            else:
                title = f"🟥 {name} espulso"
                body = f"{_scoreline(match)} · la sua partita finisce qui."
            for user in fielding.get(pid, []):
                sent += push_channel.send_to_user(
                    user, title=title, body=body, url=LIVE_URL,
                    # One tag per (match, player, kind): a re-send of the same event
                    # replaces the notification on screen instead of stacking a
                    # second copy of it.
                    tag=f"live-{match.id}-{pid}-{kind}")
    return sent


def announce_full_time(match: Match) -> int:
    """Push "the match is over" to whoever had players in it.

    Full time, not the end of the round: it is the instant at which those players'
    votes stop moving, which is the thing the person following his matchday is
    actually waiting for. The end of the round is somebody else's event — the
    admin's — and it already has its own message.
    """
    try:
        return _announce_full_time(match)
    except Exception:  # noqa: BLE001
        log.exception("Notifica di fine partita fallita per %s", match.id)
        return 0


def _announce_full_time(match: Match) -> int:
    if not push_channel.configured():
        return 0
    played = set(MatchAppearance.objects.filter(match=match, minutes_played__gt=0)
                 .values_list("player_id", flat=True))
    if not played:
        # No squad sheet yet (the live import has not run, or was blocked). Fall
        # back to the two clubs' registered players: worse aim, but a full time
        # nobody is told about is worse still.
        played = set(PlayerTeamStint.objects.filter(
            team_season_id__in=[match.home_team_id, match.away_team_id],
            end_date__isnull=True).values_list("player_id", flat=True))
    sent = 0
    for league, md in _playing_matchdays(match):
        fielding = _managers_fielding(league, md, played)
        users = {u.id: u for users in fielding.values() for u in users}
        title = f"Finita: {_scoreline(match)}"
        body = ("I voti dei tuoi giocatori si assestano nell'ora prossima, "
                "poi diventano definitivi.")
        for user in users.values():
            sent += push_channel.send_to_user(
                user, title=title, body=body, url=LIVE_URL, tag=f"ft-{match.id}")
    return sent


def _scoreline(match: Match) -> str:
    home = match.home_team.team.name if match.home_team_id else "?"
    away = match.away_team.team.name if match.away_team_id else "?"
    hg = "-" if match.home_goals is None else match.home_goals
    ag = "-" if match.away_goals is None else match.away_goals
    return f"{home} {hg}-{ag} {away}"
