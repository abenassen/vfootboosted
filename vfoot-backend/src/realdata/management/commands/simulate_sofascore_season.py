"""Play a season that has not been played, so the application can be exercised.

Writes SofaScore-shaped payloads into the request cache, then runs the REAL importer
over them (offline: a cached path never touches the network). See
``realdata/services/season_simulator.py`` for what is invented and how.

The three steps are separate on purpose. The cache is written first and kept, so a
re-import after a scoring change costs nothing and reproduces exactly the same
season; the import is the ordinary one, so the mapping cannot drift from the real
scrape; and the match statuses are set last, because they are the one thing the
importer does not own — it reads what happened, not whether the data is settled.

    python manage.py simulate_sofascore_season --season 3 --through 22 \
        --now 2027-01-31T18:35:00+01:00

Idempotent: the same seed and the same instant rebuild the same season. Re-running
after changing ``--now`` alone moves the front of the season without reshuffling
what came before it, because every match draws from a stream keyed on its own
position in the calendar.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction
from django.utils import timezone

from realdata.models import (
    CompetitionSeason,
    Match,
    MatchAppearance,
    MatchDisciplinaryEvent,
    MatchShot,
    PlayerOnPitchInterval,
    PlayerZoneFeature,
    TeamZoneFeature,
)
from realdata.services import season_simulator

# Full time plus the interval and stoppages: the delay after which a kicked-off
# match is treated as over, and the stamp ``finished_at`` gets.
FULL_TIME = timedelta(minutes=105)


class Command(BaseCommand):
    help = "Simulate a Serie A season into the SofaScore cache and import it."

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, required=True,
                            help="CompetitionSeason id to simulate (e.g. 3).")
        parser.add_argument("--through", type=int, required=True,
                            help="Last matchday to play (inclusive).")
        parser.add_argument("--now", type=str, default=None,
                            help="The instant the season is observed from "
                                 "(ISO 8601). Defaults to the current clock, which "
                                 "under VFOOT_FAKE_NOW is the simulated one.")
        parser.add_argument("--live-minute", type=int, default=0,
                            help="Force the minute of matches still in progress; "
                                 "0 derives it from the kick-off.")
        parser.add_argument("--seed", type=int, default=2627)
        parser.add_argument("--headline", type=str, default="",
                            help="Provider id of the match to put in the LAST "
                                 "kick-off slot of its round (the posticipo), so a "
                                 "scenario can choose which match is in progress.")
        parser.add_argument("--year", type=str, default=None,
                            help="Provider year string (default derived, e.g. 26/27).")
        parser.add_argument("--cache-dir", type=str, default=None)
        parser.add_argument("--write-only", action="store_true",
                            help="Write the cache and stop, without importing.")
        parser.add_argument("--import-only", action="store_true",
                            help="Import an already-written cache.")
        parser.add_argument("--fresh", action="store_true",
                            help="Re-ingest every played match, not just the ones "
                                 "whose state has changed. Needed after the "
                                 "generator or the seed changes, because then even "
                                 "a finished match has a different payload.")

    def handle(self, *args, **o):
        season = self._season(o["season"])
        cache_dir = Path(o["cache_dir"] or settings.VFOOT_SOFASCORE_CACHE)
        year = o["year"] or _year_of(season)
        now = _parse(o["now"]) if o["now"] else timezone.now()
        through = int(o["through"])

        self.stdout.write(self.style.NOTICE(
            f"Simulating {season} through matchday {through}\n"
            f"  observed at {now.isoformat()}\n"
            f"  cache       {cache_dir}"))

        plan: dict[str, dict] = {}
        if not o["import_only"]:
            report = season_simulator.write_season_cache(
                competition_season=season, cache_dir=cache_dir,
                through_matchday=through, now=now,
                live_minute=int(o["live_minute"]), seed=int(o["seed"]), year=year,
                headline=str(o["headline"] or ""),
                log=lambda m: self.stdout.write(m))
            plan = report["plan"]
            self.stdout.write(self.style.SUCCESS(
                f"cache written: {report['finished']} finished, {report['live']} live, "
                f"{report['scheduled']} not started, {report['rounds']} rounds, "
                f"{report['heatmaps']} heatmaps, "
                f"{report['kickoffs_assigned']} kick-off slots assigned"))
        if o["write_only"]:
            return
        if not plan:
            plan = self._plan_from_db(season, through, now, int(o["live_minute"]))

        self._apply_calendar(season, through, plan)
        targets = self._targets(season, plan, fresh=bool(o["fresh"]))
        self._purge(season, plan, targets)

        # ONE importer pass, aimed at the matches that actually need it.
        #
        # The obvious version re-ingests the whole season every time, and it is what
        # this did first: correct, and useless for the job the command exists for.
        # Moving the observation instant three hours changes four matches out of two
        # hundred and seventeen, and re-importing the other two hundred and thirteen
        # — a million zone-feature rows — turned a ten-second question into a
        # fifteen-minute one. A FINISHED match is immutable here (it is always played
        # in full and then cut back, so its payload does not depend on the clock), so
        # once it is in it never needs looking at again.
        if targets:
            call_command("import_sofascore", year=year,
                         season_code=season.season.code, cache_dir=str(cache_dir),
                         delay=0.0, include_unfinished=True, no_skip_existing=True,
                         pilot=",".join(targets))
            call_command("import_sofascore_intervals", competition_season=season.id,
                         cache_dir=str(cache_dir))
        else:
            self.stdout.write("  nothing to import: every match is already in the "
                              "state this instant calls for")

        self._settle(season, through, now, plan)

    # -- deciding what to touch --------------------------------------------
    def _plan_from_db(self, season: CompetitionSeason, through: int, now,
                      live_minute: int) -> dict[str, dict]:
        """Rebuild the per-match plan without re-writing the cache (--import-only).

        Only sound once the kick-off slots are in the database, which is true from
        the second run onwards — the first run always writes the cache and gets the
        plan from there.
        """
        plan = {}
        for match in (Match.objects.filter(competition_season=season,
                                           matchday__lte=through)
                      .exclude(kickoff=None)):
            status, clock = _status_at(match.kickoff, now, live_minute)
            plan[str(match.external_id)] = {
                "status": status, "clock": clock,
                "kickoff": match.kickoff.isoformat(),
                # No cache was written, so nothing was played: whatever score the
                # database already holds is the best answer available, and for a
                # live match it is the one the last poll left.
                "home_goals": match.home_goals, "away_goals": match.away_goals}
        return plan

    @transaction.atomic
    def _apply_calendar(self, season: CompetitionSeason, through: int,
                        plan: dict[str, dict]) -> None:
        """Write the assigned kick-off slots, for every simulated match.

        Including the ones that have not kicked off. The importer only visits
        matches it ingests, so relying on it left the evening fixtures of a
        half-played round showing the provider's placeholder time — the round would
        be listed as three matches at 13:00 that were plainly not being played.
        """
        moved = 0
        for match in Match.objects.filter(competition_season=season,
                                          matchday__lte=through):
            entry = plan.get(str(match.external_id))
            if not entry or not entry.get("kickoff"):
                continue
            kickoff = _parse(entry["kickoff"])
            if match.kickoff != kickoff:
                match.kickoff = kickoff
                match.save(update_fields=["kickoff"])
                moved += 1
        if moved:
            self.stdout.write(f"  calendar: {moved} kick-off times updated")

    def _targets(self, season: CompetitionSeason, plan: dict[str, dict],
                 fresh: bool) -> list[str]:
        """Provider ids to ingest: the FINISHED ones, and only where needed.

        A match IN PROGRESS is deliberately not imported, and that is a fidelity
        decision rather than an optimisation. The live pipeline does not import one
        either: ``live_ingest.poll_live`` updates the lifecycle and the score and
        nothing else, and the per-player data arrives at the +15min finalization.
        Importing it here would hand the application a squad sheet and provisional
        statistics that the real cron would not have produced yet — the simulated
        season would look better than the product is, which is the one way a
        simulator can actively mislead.

        Its score still reaches the database, from the plan; see ``_settle``.

        A finished match is ingested only if the database does not already hold it
        as finished with a squad sheet — which, because a finished match's payload
        never changes, means once.
        """
        played = set(MatchAppearance.objects
                     .filter(match__competition_season=season)
                     .values_list("match_id", flat=True).distinct())
        state = {str(m.external_id): (m.id, m.status) for m in
                 Match.objects.filter(competition_season=season)}
        out = []
        for ext, entry in plan.items():
            if entry["status"] != "finished":
                continue
            if fresh:
                out.append(ext)
                continue
            match_id, status = state.get(ext, (None, None))
            if match_id not in played or status != Match.STATUS_FINISHED:
                out.append(ext)
        return out

    @transaction.atomic
    def _purge(self, season: CompetitionSeason, plan: dict[str, dict],
               targets: list[str]) -> None:
        """Clear what the importer will not clear for itself, in two scopes.

        **Appearances, for every match about to be re-ingested.** ``_ingest_match``
        deletes and rewrites the zone features, the shot map and the cards, but
        appearances go through ``update_or_create`` — so a player who was in the
        squad sheet under a previous run and is not in this one keeps his row
        forever. It looks harmless until the generator or the seed changes, and then
        a match quietly carries 50 appearances instead of 46, four of them
        describing a game nobody played.

        **Everything, for matches that are not FINISHED.** Two cases, one rule.
        A match that has not kicked off is never visited by the importer, so
        winding the clock BACK would leave a fixture reading 'scheduled' with a
        shot map attached. A match IN PROGRESS is not imported either (see
        ``_targets``) and must carry no per-player data at all — but if it was
        finished a moment ago in a later scenario, or was imported by an older
        version of this command, it still holds a full squad sheet. Rewinding into
        a live match therefore has to strip it, or the application would show a
        distinta the real cron has not produced yet.
        """
        ext_to_id = {str(m.external_id): m.id for m in
                     Match.objects.filter(competition_season=season)}
        counts: dict[str, int] = {}

        def wipe(model, ids) -> None:
            if not ids:
                return
            deleted, _ = model.objects.filter(match_id__in=ids).delete()
            if deleted:
                counts[model.__name__] = counts.get(model.__name__, 0) + deleted

        wipe(MatchAppearance, [ext_to_id[e] for e in targets if e in ext_to_id])

        not_final = [ext_to_id[e] for e, entry in plan.items()
                     if entry["status"] != "finished" and e in ext_to_id]
        for model in (PlayerZoneFeature, TeamZoneFeature, PlayerOnPitchInterval,
                      MatchDisciplinaryEvent, MatchShot, MatchAppearance):
            wipe(model, not_final)

        if counts:
            self.stdout.write("  cleared: " + ", ".join(
                f"{n} {k}" for k, n in sorted(counts.items())))

    # -- match lifecycle ---------------------------------------------------
    @transaction.atomic
    def _settle(self, season: CompetitionSeason, through: int, now,
                plan: dict[str, dict]) -> None:
        """Set what the importer does not: status, data readiness, kick-off firmness.

        Driven by the PLAN, not inferred from whether appearances exist. That
        mattered as soon as an in-progress match stopped being imported: with no
        squad sheet, an inference from the data would have filed it as 'not started'
        while its own kick-off was an hour in the past.

        ``data_ready`` is the flag a league's conclusion keys on, and it means "the
        provider has stopped changing this match" — not "it is over". Here it is true
        exactly for the finished matches with appearances, which is the honest
        reading: a match still in progress has data that will change, and a match
        nobody has played has none.

        Kick-offs stop being provisional for the simulated stretch only. That is not
        a detail: a provisional kick-off locks no lineup, so leaving the whole season
        confirmed would lock every future matchday at once, and leaving matchday 22
        provisional would leave it fieldable while it is being played.
        """
        played = set(MatchAppearance.objects
                     .filter(match__competition_season=season)
                     .values_list("match_id", flat=True).distinct())
        counts = {"finished": 0, "live": 0, "scheduled": 0}
        for match in Match.objects.filter(competition_season=season):
            simulated = match.matchday is not None and match.matchday <= through
            entry = plan.get(str(match.external_id)) if simulated else None
            state = (entry or {}).get("status", "notstarted")

            if simulated and state == "finished" and match.id in played:
                match.status, match.data_ready = Match.STATUS_FINISHED, True
                match.finished_at = match.kickoff + FULL_TIME
                counts["finished"] += 1
            elif simulated and state == "inprogress":
                # Exactly what a live poll leaves behind: lifecycle and score, no
                # per-player data. The score comes from the plan because nothing
                # imports an in-progress match — see _targets.
                match.status, match.data_ready = Match.STATUS_LIVE, False
                match.finished_at = None
                match.home_goals = entry.get("home_goals")
                match.away_goals = entry.get("away_goals")
                counts["live"] += 1
            else:
                match.status, match.data_ready = Match.STATUS_SCHEDULED, False
                match.finished_at = None
                # A match that has not kicked off has NO SCORE, and saying so is
                # this branch's job because nothing else will: the importer writes
                # the goals and never visits a match it does not ingest, so winding
                # the clock back left three fixtures reading 'scheduled' and
                # '1-0' — the score of a match that, at this instant, has not been
                # played.
                match.home_goals = match.away_goals = None
                counts["scheduled"] += 1
            match.kickoff_provisional = not simulated
            match.data_checked_at = now
            match.save(update_fields=["status", "data_ready", "finished_at",
                                      "home_goals", "away_goals",
                                      "kickoff_provisional", "data_checked_at"])

        self.stdout.write(self.style.SUCCESS(
            f"matches settled: {counts['finished']} finished, {counts['live']} live, "
            f"{counts['scheduled']} scheduled"))

    def _season(self, season_id: int) -> CompetitionSeason:
        try:
            return CompetitionSeason.objects.select_related("season", "competition").get(
                id=season_id)
        except CompetitionSeason.DoesNotExist as exc:
            raise CommandError(f"No CompetitionSeason with id {season_id}.") from exc


def _parse(raw: str) -> datetime:
    value = datetime.fromisoformat(str(raw).strip())
    return value if value.tzinfo else value.replace(tzinfo=dt_timezone.utc)


def _year_of(season: CompetitionSeason) -> str:
    """Season.code ("2026-2027") -> the provider's year string ("26/27")."""
    code = str(season.season.code)
    if "-" in code:
        a, b = code.split("-")
        return f"{a[-2:]}/{b[-2:]}"
    return code
