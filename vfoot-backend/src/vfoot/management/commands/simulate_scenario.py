"""Put the whole application into a named, reproducible state at a given instant.

One command instead of three, and — the part that matters — one that can be run
again tomorrow, or after a database reset, or with the clock moved on three hours,
and land somewhere you can reason about. It drives the two simulators and then
tells you the clock to observe the result from:

    manage.py simulate_scenario                       # the default scenario
    manage.py simulate_scenario --scenario fine-stagione
    manage.py simulate_scenario --at 2027-01-31T21:30:00+01:00
    manage.py simulate_scenario --list

A SCENARIO IS TWO CLOCKS, NOT ONE
---------------------------------
The calendar's and the ledger's. Most scenarios only need to name the first: what
has been concluded follows from what has been played, and deriving it is what
keeps them from drifting out of step with themselves. But the end of a season is
precisely the state where the two come apart on purpose — every match played, and
the last round still waiting for someone to press Concludi, because that press is
what ends the competitions and hands out the honours. ``conclude_through`` is how
a scenario says so, and ``fine-stagione`` is the one that does.

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
from vfoot.models import FantasyFixture, FantasyLeague, FantasyMatchday
from vfoot.services import honours, matchday_state
from vfoot.services.competition_prizes import competition_fixtures


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
    # Provider id of the match to move to the LAST kick-off slot of its round, so a
    # scenario can name the match that should be in progress rather than accepting
    # whichever fixture sorts first. See season_simulator._order_fixtures.
    headline: str = ""
    # The league by NAME as well as by id. An id is not portable: it is minted by
    # whichever database seeded the league, so a scenario written on one machine
    # pointed at a different league (or at nothing) on the next — and the symptom
    # was not "league 62 is the wrong one" but "every squad failed to field a legal
    # XI", which reads like a bug in the fielding. Resolved by name first, and
    # SEEDED under that name when it is not there, so a scenario is reproducible
    # from an empty database. Empty name => id only, the old behaviour.
    league_name: str = ""
    league_rounds: int = 3   # snake-drafted cycles of 9 rounds each, when seeding
    # Whether the seeded league also runs the two cups. Off by default because a
    # scenario about a Sunday afternoon does not need them and they cost seeding
    # time; on for the one scenario that is ABOUT competitions ending, where a
    # championship on its own would show a single trophy and no bracket.
    league_cup: bool = False
    # How many played-out rounds the LEDGER is left short of the calendar: the
    # admin who has not clicked yet. Counted in ROUNDS rather than given as a
    # matchday number because a scenario must not depend on the shape of the
    # league it lands in — the demo league seeded from empty ends on real matchday
    # 36, the one already on this machine on 38, and "leave the last one to be
    # concluded" is the same request in both. Zero (the default) means the ledger
    # keeps up with the calendar, which is what every other scenario wants.
    pending_conclusions: int = 0


# The league every scenario plays in. One name, shared, because the scenarios
# differ by INSTANT and by nothing else — and because a name survives a database
# reset in a way an id does not.
#
# Shared including by ``fine-stagione``, which needs a bigger league than the
# others (four cycles and the cups, so that the calendar ends WITH the season):
# seeding it under a name of its own would have been tidier and wrong. A scenario
# is a state of THE league being played in, and one that quietly moved you to a
# league of its own would show you the end of a season that was not the one you
# had been watching all afternoon.
LEAGUE = "Lega Live · Serie A 2026/27"

# Chi gestisce la squadra #1 e amministra la lega, quando non si dice altro. Lo
# stesso predefinito di ``seed_classic_demo_league``, ripetuto qui perche' e' la
# CHIAVE con cui la lega viene ritrovata: se i due valori divergessero, un avvio
# non troverebbe la lega seminata dall'altro e ne farebbe una seconda.
DEFAULT_OWNER = "andrea"

# Quante giornate reali copre un ciclo di semina. Sta qui perche' e' il cambio fra
# le due unita' che i due comandi usano: lo scenario conta in CICLI, la coppa e' fissata
# a GIORNATE REALI, e senza la conversione le due cose si scoprono incompatibili solo
# a semina avviata.
ROUNDS_PER_CYCLE = 9

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
            league_name=LEAGUE,
        ),
        Scenario(
            name="g22-pre",
            description=(
                "The same season on the Saturday, before a ball is kicked in "
                "matchday 22: the only instant at which the round is both current "
                "and still fieldable by everyone (see the Modello 1 deadline)."),
            season_id=3, league_id=62, through=22,
            at="2027-01-30T14:00:00+01:00",
            league_name=LEAGUE,
        ),
        Scenario(
            name="napoli-inter",
            description=(
                "Sunday night, matchday 22: nine matches played and Napoli-Inter in "
                "progress at about the half hour. The scenario for watching the live "
                "pipeline work — the votes of the two squads move every ten minutes, "
                "the rest of the round is already settled, and the league's tabellini "
                "are half final and half provisional."),
            season_id=3, league_id=0, through=22,
            at="2027-01-31T21:15:00+01:00",
            headline="16283209",   # SSC Napoli vs Inter, moved to the last slot
            league_name=LEAGUE,
        ),
        Scenario(
            name="g22-done",
            description=(
                "Monday: matchday 22 fully played and NOT yet concluded by the "
                "admin. Exercises the conclusion queue, the nudge, and a ledger "
                "one round behind a completed calendar."),
            season_id=3, league_id=62, through=22,
            at="2027-02-01T10:00:00+01:00",
            league_name=LEAGUE,
        ),
        Scenario(
            name="fine-stagione",
            description=(
                "Sunday night, the last matchday of Serie A just whistled off: the "
                "championship is over, all 380 matches played, and every competition "
                "of the league has run out of football. What is left is the LEDGER — "
                "the final round is played and NOT concluded, so the title, the cup "
                "and every honour they decide are still to be handed out. The "
                "scenario for the last click, the one that is not like the others."),
            season_id=3, league_id=62, through=38,
            # Dopo l'ULTIMO fischio, non dopo il primo: l'ultima giornata e'
            # sparpagliata sul fine settimana come tutte le altre (ROUND_SLOTS),
            # e l'ultimo slot e' la domenica alle 20:45. Un istante del sabato
            # sera dava uno scenario di fine stagione con nove partite ancora da
            # giocare — che e' esattamente cio' che questo scenario non e'.
            at="2027-05-30T23:30:00+02:00",
            # LA STESSA LEGA degli altri scenari: e' quella su cui si prova, e uno
            # scenario che si fabbrica una lega sua manda a vedere la fine di una
            # stagione che non e' quella che si stava giocando. Da una banca dati
            # vuota si semina, e li' serve la forma piena — quattro cicli, cosi'
            # che il campionato finisca CON la stagione, e le coppe, senza le
            # quali "tutte le competizioni finite" e' una competizione sola.
            league_name=LEAGUE,
            league_rounds=4,
            league_cup=True,
            pending_conclusions=1,
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
        parser.add_argument("--owner", default=DEFAULT_OWNER,
                            help=f"Which user manages team #1 and administers the "
                                 f"league (default: {DEFAULT_OWNER}). A league is "
                                 f"identified by name AND owner, so two owners get "
                                 f"two leagues rather than one ambiguous name.")
        # Tri-state on purpose: None means "whatever the scenario says", which is
        # what every existing invocation means and must keep meaning.
        parser.add_argument("--cup", dest="cup", action="store_true", default=None,
                            help="Seed the two cups as well as the championship, "
                                 "whatever the scenario's default. Three competitions "
                                 "instead of one, for testing what a league looks "
                                 "like with a bracket and a group stage in it.")
        parser.add_argument("--no-cup", dest="cup", action="store_false",
                            help="Championship only, whatever the scenario's default.")

    def handle(self, *args, **o):
        if o["list"]:
            for s in SCENARIOS.values():
                self.stdout.write(self.style.MIGRATE_HEADING(f"{s.name}"))
                self.stdout.write(f"    {s.description}")
                self.stdout.write(
                    f"    season {s.season_id}, "
                    f"league {s.league_name or s.league_id}, "
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
            self._report(scenario, self._league(scenario, create=False,
                                                owner=o["owner"]), at)
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"scenario {scenario.name} @ {at.isoformat()}"))
        self.stdout.write(f"  {scenario.description}")

        if not o["skip_season"]:
            call_command("simulate_sofascore_season", season=scenario.season_id,
                         through=scenario.through, now=at.isoformat(), seed=seed,
                         headline=scenario.headline, fresh=bool(o["fresh"]))
        league = self._league(scenario, create=True, owner=o["owner"], cup=o["cup"])
        # Everything the calendar has finished is concludable; the round still being
        # played is not. Derived from the clock rather than passed in, so a scenario
        # is defined by ITS INSTANT alone and cannot drift out of step with itself —
        # unless it names ``conclude_through``, which is how a scenario says "the
        # football is over, the admin has not clicked yet". That is a state the
        # clock cannot express, because it is not about the calendar at all.
        # ``redo`` is not optional here. Rebuilding a scenario re-runs the
        # championship, and every fantasy score is DERIVED from it: leaving the
        # matchdays that were already concluded alone would keep tabellini computed
        # from performances that no longer exist — a league whose table cannot be
        # reproduced from the season under it, which is the one thing a scenario
        # must not be.
        call_command("advance_fantasy_league", league=league.id,
                     through=scenario.through,
                     conclude_through=self._conclude_through(scenario, league, at),
                     seed=seed + 1, redo=True)

        self._report(scenario, league, at)
        self.stdout.write(self.style.SUCCESS(
            "\nObserve it with:\n"
            f'    $env:VFOOT_FAKE_NOW = "{scenario.at if not o["at"] else at.isoformat()}"\n'
            "    .\\vfoot-dev.ps1 restart"))

    def _league(self, scenario: Scenario, *, create: bool,
                owner: str = DEFAULT_OWNER, cup: bool | None = None) -> FantasyLeague:
        """The league this scenario plays in, by (name, owner) and then by id.

        By NAME first because an id belongs to the database that minted it, and a
        scenario is supposed to survive a reset. Seeded when it is not there, which
        is what makes the whole scenario reproducible from an empty database — and
        idempotent, so the second run costs nothing.

        And by OWNER as well as by name, because that is the pair the seeder is
        idempotent on: it wipes and rebuilds `name + owner`. Matching on the name
        alone meant a second owner produced a SECOND league under the same name,
        after which this lookup picked whichever sorted first — so `--owner mario`
        seeded Mario's league and then handed you Andrea's, with nothing on screen
        saying the two were different leagues.

        The check is not just "does a league exist": it must be classic, on THIS
        season, with rosters. Without the last one every squad silently fails to
        field a legal XI, and nothing in the output says the league was the problem.
        """
        found = None
        if scenario.league_name:
            found = FantasyLeague.objects.filter(
                name=scenario.league_name, owner__username=owner).first()
        # The id fallback is the pre-name behaviour, kept for a league that predates
        # all of this — and it knows nothing about owners. So it applies only when
        # no particular owner was asked for: with `--owner mario` it could hand back
        # a league belonging to someone else, which is the exact confusion the pair
        # above exists to end. Asking for an owner means asking for THAT owner.
        if found is None and scenario.league_id and owner == DEFAULT_OWNER:
            found = FantasyLeague.objects.filter(id=scenario.league_id).first()
        if found is not None and self._usable(found, scenario, cup):
            return found
        if not create or not scenario.league_name:
            raise CommandError(
                f"No usable league for scenario {scenario.name!r} owned by "
                f"{owner!r}: it needs a CLASSIC league on season "
                f"{scenario.season_id} with rosters. "
                + (f"Found {found.id!r} but it does not qualify. "
                   if found is not None else "")
                + "Seed one with `manage.py seed_classic_demo_league "
                  f"--competition-season {scenario.season_id} --owner {owner}`.")

        want_cup = scenario.league_cup if cup is None else cup
        cycles = self._cycles_for(scenario, want_cup)
        self.stdout.write(self.style.NOTICE(
            f"  seeding the league '{scenario.league_name}' for {owner} "
            f"({'championship + cups' if want_cup else 'championship only'}, "
            f"{cycles} cycles)…"))
        if cycles > scenario.league_rounds:
            # Said out loud: the league you get is LONGER than this scenario's, and
            # that is a visible difference — more rounds on the calendar — not an
            # implementation detail. Better read here than noticed later as "why
            # does this league run to matchday 36".
            self.stdout.write(
                f"    (the cups' last round is a real matchday the calendar has to "
                f"reach, so {scenario.league_rounds} cycles became {cycles} — "
                f"{ROUNDS_PER_CYCLE * cycles} matchdays)")
        call_command("seed_classic_demo_league",
                     league_name=scenario.league_name,
                     competition_season=scenario.season_id,
                     cycles=cycles,
                     owner=owner,
                     no_cup=not want_cup)
        league = FantasyLeague.objects.filter(
            name=scenario.league_name, owner__username=owner).first()
        if league is None or not self._usable(league, scenario, cup):
            raise CommandError(
                f"Seeding '{scenario.league_name}' for {owner} did not produce a "
                f"usable league.")
        return league

    @staticmethod
    def _usable(league: FantasyLeague, scenario: Scenario,
                cup: bool | None = None) -> bool:
        from vfoot.models import CompetitionPrize, FantasyRosterSlot

        if not (league.mode == FantasyLeague.MODE_CLASSIC
                and league.reference_season_id == scenario.season_id
                and FantasyRosterSlot.objects.filter(
                    team__league=league, released_at__isnull=True).exists()):
            return False
        # A scenario about trophies needs a league that has some to give: one
        # seeded before the prizes existed passes every other test and then ends
        # its season awarding nothing, which reads as "the honours are broken"
        # rather than "this league was built by an older command". Re-seeding is
        # the cheap half of the build, so the doubt is resolved by rebuilding.
        #
        # Judged on the cups ASKED FOR, not on the scenario's default: `--cup` on a
        # league seeded without them found it perfectly usable and handed it back
        # unchanged, so the flag did nothing and said nothing. Wanting cups where
        # there are none is a reason to re-seed, which is exactly what returning
        # False here does.
        if (scenario.league_cup if cup is None else cup) and \
                not CompetitionPrize.objects.filter(
                    competition__league=league).exists():
            return False
        return True

    @staticmethod
    def _cycles_for(scenario: Scenario, want_cup: bool) -> int:
        """Cycles to seed: enough for the calendar to reach the cup's last round.

        The cup is pinned to REAL matchdays (24, 30, 36) while the league's calendar
        is only as long as its cycles make it — nine rounds each. Ask for cups on a
        three-cycle scenario and the calendar stops at 27, so the semi-final looks
        for matchday 30 and the seed dies with `KeyError: 30`, five minutes into a
        build, pointing at a dictionary lookup rather than at the mismatch.
        """
        from vfoot.management.commands.seed_classic_demo_league import CUP_ROUNDS

        if not want_cup:
            return scenario.league_rounds
        needed = -(-max(rm for _, rm in CUP_ROUNDS) // ROUNDS_PER_CYCLE)
        return max(scenario.league_rounds, needed)

    def _conclude_through(self, scenario: Scenario, league: FantasyLeague, at) -> int:
        """The last round the ledger has counted: everything the calendar has
        finished, minus the rounds this scenario leaves to be concluded by hand.

        Counted BACKWARDS FROM THE END of the league's own rounds, not by naming a
        matchday. The two things a scenario would have to know to name one — where
        the league's calendar ends, and whether it has a round on every real
        matchday — are properties of the league it lands in, and a scenario that
        depended on them would be right on this database and wrong on the next.
        """
        last_complete = self._last_complete(scenario, at)
        if not scenario.pending_conclusions:
            return last_complete
        rounds = [md.real_matchday for md in matchday_state.league_matchdays(league)
                  if md.real_matchday <= last_complete]
        left = len(rounds) - scenario.pending_conclusions
        # 0 means "nothing has been concluded", which is the honest answer when the
        # league has fewer played rounds than the scenario wants left open.
        return rounds[left - 1] if left > 0 else 0

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

    def _report(self, scenario: Scenario, league: FantasyLeague, at) -> None:
        season = CompetitionSeason.objects.filter(id=scenario.season_id).first()
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

        # The competitions, said in the two states that matter: already settled, and
        # played-out but still waiting for a conclusion. The second is the whole
        # point of the end-of-season scenario, and a report that only counted
        # matchdays could not tell it from "there is nothing left to do".
        for comp in league.competitions.prefetch_related("prizes").order_by("id"):
            fixtures = competition_fixtures(comp)
            played = sum(1 for fx in fixtures
                         if fx.status == FantasyFixture.STATUS_FINISHED)
            prizes = list(comp.prizes.all())
            won = honours.prize_winners(comp)
            if not honours.is_complete(comp, fixtures):
                state = f"still running, {played}/{len(fixtures)} fixtures counted"
            elif all(won.get(p.id) for p in prizes):
                state = "over, honours awarded"
            else:
                state = (f"over, {sum(1 for p in prizes if not won.get(p.id))} "
                         f"honours STILL TO AWARD")
            self.stdout.write(f"    {comp.name}: {state} "
                              f"· prizes at stake: {len(prizes)}")


def _parse(raw: str) -> datetime:
    value = datetime.fromisoformat(str(raw).strip())
    return value if value.tzinfo else value.replace(tzinfo=dt_timezone.utc)
