"""Put the whole application into a named, reproducible state at a given instant.

One command instead of three, and — the part that matters — one that can be run
again tomorrow, or after a database reset, or with the clock moved on three hours,
and land somewhere you can reason about. It drives the two simulators and then
tells you the clock to observe the result from:

    manage.py simulate_scenario                       # the default scenario
    manage.py simulate_scenario --at 2027-01-31T21:30:00+01:00
    manage.py simulate_scenario --list

WHAT REPRODUCIBLE MEANS HERE, PRECISELY
---------------------------------------
Same scenario and same instant -> byte-identical season. Same scenario and a LATER
instant -> the same season with more of it played: the matches behind are untouched
down to the scorers, and a match in progress carries on from where it was rather
than being re-rolled. That is a property of the generator, not of this command
(each fixture draws from a stream keyed on its own provider id, and a match is
always played in full and then cut back to the minute being watched), and it is
what makes "advance the clock and watch the live pipeline work" a meaningful test
instead of a new random season each time.

Moving the instant BACKWARDS works too, and is the case worth naming because it is
the one that silently rots: matches that have un-happened have their data erased,
and league matchdays that are no longer behind the front are reopened. A scenario
is a state, not a high-water mark.

THE CLOCK IS NOT SET BY THIS COMMAND
------------------------------------
It prints the value and stops, deliberately. ``VFOOT_FAKE_NOW`` is read by
settings.py at process start, so it belongs to whoever launches the server; a
command that appeared to set it would be setting it for a process that is about to
exit. See vfoot/simclock.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from realdata.models import CompetitionSeason, Match
from vfoot.models import FantasyLeague, FantasyMatchday
from vfoot.services import matchday_state


@dataclass(frozen=True)
class Scenario:
    """A state worth being able to return to."""
    name: str
    description: str
    season_id: int
    league_id: int
    through: int
    at: str
    seed: int = 2627


SCENARIOS = {
    s.name: s for s in (
        Scenario(
            name="g22-live",
            description=(
                "Serie A 2026-27, Sunday afternoon of matchday 22: six matches "
                "played, one in progress, three still to come. The league's ledger "
                "is at 21, the round being played is 22, the fieldable one is 23 — "
                "the two clocks visibly apart."),
            season_id=3, league_id=62, through=22,
            at="2027-01-31T18:35:00+01:00",
        ),
        Scenario(
            name="g22-pre",
            description=(
                "The same season on the Saturday, before a ball is kicked in "
                "matchday 22: the only instant at which the round is both current "
                "and still fieldable by everyone (see the Modello 1 deadline)."),
            season_id=3, league_id=62, through=22,
            at="2027-01-30T14:00:00+01:00",
        ),
        Scenario(
            name="g22-done",
            description=(
                "Monday: matchday 22 fully played and NOT yet concluded by the "
                "admin. Exercises the conclusion queue, the nudge, and a ledger "
                "one round behind a completed calendar."),
            season_id=3, league_id=62, through=22,
            at="2027-02-01T10:00:00+01:00",
        ),
    )
}
DEFAULT_SCENARIO = "g22-live"


class Command(BaseCommand):
    help = "Rebuild a reproducible application state (simulated season + league)."

    def add_arguments(self, parser):
        parser.add_argument("--scenario", default=DEFAULT_SCENARIO,
                            help=f"Named scenario (default: {DEFAULT_SCENARIO}).")
        parser.add_argument("--at", default=None,
                            help="Override the instant to rebuild the state at.")
        parser.add_argument("--seed", type=int, default=None)
        parser.add_argument("--list", action="store_true",
                            help="Describe the scenarios and exit.")
        parser.add_argument("--skip-season", action="store_true",
                            help="Leave the championship alone and only re-run the "
                                 "league (fast, when only the fantasy side changed).")
        parser.add_argument("--fresh", action="store_true",
                            help="Re-ingest the whole championship instead of only "
                                 "what this instant changes. Needed after the "
                                 "generator or the seed changes; slow (minutes).")
        parser.add_argument("--check", action="store_true",
                            help="Rebuild nothing; just report the current state.")

    def handle(self, *args, **o):
        if o["list"]:
            for s in SCENARIOS.values():
                self.stdout.write(self.style.MIGRATE_HEADING(f"{s.name}"))
                self.stdout.write(f"    {s.description}")
                self.stdout.write(f"    season {s.season_id}, league {s.league_id}, "
                                  f"through matchday {s.through}, at {s.at}\n")
            return

        scenario = SCENARIOS.get(o["scenario"])
        if scenario is None:
            raise CommandError(
                f"Unknown scenario {o['scenario']!r}. Known: "
                f"{', '.join(sorted(SCENARIOS))}. Use --list to see what they are.")
        at = _parse(o["at"]) if o["at"] else _parse(scenario.at)
        seed = o["seed"] if o["seed"] is not None else scenario.seed

        if o["check"]:
            self._report(scenario, at)
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"scenario {scenario.name} @ {at.isoformat()}"))
        self.stdout.write(f"  {scenario.description}")

        if not o["skip_season"]:
            call_command("simulate_sofascore_season", season=scenario.season_id,
                         through=scenario.through, now=at.isoformat(), seed=seed,
                         fresh=bool(o["fresh"]))
        # Everything the calendar has finished is concludable; the round still being
        # played is not. Derived from the clock rather than passed in, so a scenario
        # is defined by ITS INSTANT alone and cannot drift out of step with itself.
        # ``redo`` is not optional here. Rebuilding a scenario re-runs the
        # championship, and every fantasy score is DERIVED from it: leaving the
        # matchdays that were already concluded alone would keep tabellini computed
        # from performances that no longer exist — a league whose table cannot be
        # reproduced from the season under it, which is the one thing a scenario
        # must not be.
        call_command("advance_fantasy_league", league=scenario.league_id,
                     through=scenario.through,
                     conclude_through=self._last_complete(scenario, at),
                     seed=seed + 1, redo=True)

        self._report(scenario, at)
        self.stdout.write(self.style.SUCCESS(
            "\nObserve it with:\n"
            f'    $env:VFOOT_FAKE_NOW = "{scenario.at if not o["at"] else at.isoformat()}"\n'
            "    .\\vfoot-dev.ps1 restart"))

    def _last_complete(self, scenario: Scenario, at) -> int:
        """The highest matchday whose real matches have ALL kicked off and ended.

        A matchday is concludable when the calendar is done with it, not when the
        admin gets round to it — that separation is the league's two clocks, and
        deriving this from the fixtures keeps the scenario honest at any instant.
        """
        last = 0
        rounds: dict[int, list] = {}
        for md, kickoff in (Match.objects
                            .filter(competition_season_id=scenario.season_id,
                                    matchday__lte=scenario.through)
                            .exclude(kickoff=None)
                            .values_list("matchday", "kickoff")):
            rounds.setdefault(int(md), []).append(kickoff)
        for md in sorted(rounds):
            done = all((at - k).total_seconds() / 60.0 >= 105 for k in rounds[md])
            if done:
                last = md
        return last

    def _report(self, scenario: Scenario, at) -> None:
        season = CompetitionSeason.objects.filter(id=scenario.season_id).first()
        league = FantasyLeague.objects.filter(id=scenario.league_id).first()
        if season is None or league is None:
            raise CommandError("Scenario points at a season or league that is gone.")

        counts = {row["status"]: row["n"] for row in
                  Match.objects.filter(competition_season=season)
                  .values("status").annotate(n=Count("id"))}
        self.stdout.write("\n  championship: "
                          + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
        live = (Match.objects.filter(competition_season=season, status=Match.STATUS_LIVE)
                .select_related("home_team__team", "away_team__team"))
        for m in live:
            self.stdout.write(f"    in progress: {m.home_team.team} {m.home_goals}-"
                              f"{m.away_goals} {m.away_team.team}")

        ledger = matchday_state.league_matchdays(league)
        concluded = sum(1 for md in ledger
                        if md.status == FantasyMatchday.STATUS_CONCLUDED)
        pointer = matchday_state.ledger_matchday(league)
        self.stdout.write(
            f"  league '{league.name}': {concluded}/{len(ledger)} matchdays concluded"
            f" · ledger at {pointer.real_matchday if pointer else 'up to date'}"
            f" · being played {matchday_state.playing_matchday(league, now=at)}"
            f" · fieldable {matchday_state.next_fieldable_matchday(league, now=at)}")


def _parse(raw: str) -> datetime:
    value = datetime.fromisoformat(str(raw).strip())
    return value if value.tzinfo else value.replace(tzinfo=dt_timezone.utc)
