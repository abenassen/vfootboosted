"""A fake SofaScore, on the other side of the egress seam.

WHAT THIS REPLACES, AND WHY THERE
---------------------------------
The live pipeline is already split in two by ``egress_client``: one side crosses a
privilege boundary to FETCH bytes into the request cache, the other reads that
cache offline. Every decision — which matches are due, how often to poll, when
full time counts as observed, when a match is promoted to ``data_ready`` — lives on
the reading side and never touches the network.

So a simulated championship does not need a simulated pipeline. It needs a
simulated PROVIDER: something that, asked to warm a match, writes the payload that
SofaScore would be serving for that match *at this moment*. Everything downstream —
``tick``, ``match_scheduler``, ``live_ingest``, the adapter, the voto puro — then
runs exactly as it does in production, against invented bytes.

That is the difference between testing the live pipeline and testing a
reconstruction of it. Regenerating the whole season at a later instant produces the
same rows, and proves nothing about the state machine that is supposed to produce
them: it never polls, never observes a full time, never promotes anything.

HOW "NOW" GETS IN
-----------------
The payload is generated for the CURRENT minute of the match, taken from
``timezone.now()`` — which under ``VFOOT_FAKE_NOW`` is the simulated clock, and
which walks. Poll the same match two minutes later and you get two more minutes of
football: the same match, further on, because the generator always plays the full
ninety and cuts back to the minute being watched.

WIRING
------
``egress_client.run_egress`` dispatches here when ``VFOOT_EGRESS_SIMULATED`` is on.
Nothing else changes, and with the flag off this module is never imported.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from django.utils import timezone

from realdata.models import CompetitionSeason, Match
from realdata.services import season_simulator as sim

# Parsed out of the wrapper's argv, which is the contract egress_client already
# speaks. Keeping that contract means the simulated and the real provider are
# interchangeable without the caller knowing which it got.
FETCH = "fetch"
SCHEDULE = "schedule"


def run(args: list[str]) -> bool:
    """Serve one egress request by generating it. True iff something was written."""
    if not args:
        return False
    kind, options = args[0], _options(args[1:])
    cache_dir = Path(options.get("cache-dir") or "")
    if not cache_dir:
        return False
    if kind == SCHEDULE:
        return _schedule(cache_dir, options.get("year", ""))
    if kind == FETCH:
        ids = [i for i in (options.get("match-ids") or "").split(",") if i]
        return _matches(cache_dir, ids, options.get("kind", "live"))
    return False


def _options(rest: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in range(0, len(rest) - 1, 2):
        if rest[i].startswith("--"):
            out[rest[i][2:]] = rest[i + 1]
    return out


# --------------------------------------------------------------------------- #
# The two things the egress knows how to warm                                  #
# --------------------------------------------------------------------------- #
def _schedule(cache_dir: Path, year: str) -> bool:
    """The season's fixture list.

    Laid down once by the scenario builder and stable afterwards, so this only
    confirms it is there rather than re-deriving identical bytes on every
    finalization. What DOES change — a match's status and score — is written by the
    match warm, into this same file; see ``_refresh_round_entry`` for why that
    matters more than it looks.
    """
    season = _season_for_year(year)
    if season is None:
        return False
    rounds = cache_dir / (f"api_v1_unique-tournament_{sim.SERIE_A_TOURNAMENT_ID}"
                          f"_season_{season.external_id}_rounds.json")
    return rounds.exists()


def _season_for_year(year: str) -> CompetitionSeason | None:
    """'26/27' -> the CompetitionSeason, via the same mapping the adapter uses."""
    from realdata.services.sofascore_adapter import season_code_from_year

    return (CompetitionSeason.objects
            .filter(season__code=season_code_from_year(year))
            .exclude(external_id="").order_by("-id").first())


def _refresh_round_entry(cache_dir: Path, match: Match, status: str, played) -> None:
    """Update this match's entry in its round's event list.

    Not decoration. ``ingest_sofascore_season`` resolves a match from the SCHEDULE,
    and skips anything the schedule does not call finished — so a match that has
    just ended in the live feed but is still 'inprogress' in the round file is
    silently passed over, and the finalization that was supposed to import it
    imports nothing while reporting success. A real provider updates both; so does
    this one.
    """
    path = (f"/api/v1/unique-tournament/{sim.SERIE_A_TOURNAMENT_ID}"
            f"/season/{match.competition_season.external_id}"
            f"/events/round/{match.matchday}")
    target = cache_dir / (path.strip("/").replace("/", "_") + ".json")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for event in payload.get("events", []):
        if str(event.get("id")) != str(match.external_id):
            continue
        event["status"] = {"type": status}
        event["homeScore"] = {"current": played.home_goals if played else None}
        event["awayScore"] = {"current": played.away_goals if played else None}
        if match.kickoff:
            event["startTimestamp"] = int(match.kickoff.timestamp())
        sim._write(cache_dir, path, payload)
        return


def _matches(cache_dir: Path, external_ids: list[str], kind: str) -> bool:
    """Warm these matches AS THEY STAND NOW.

    ``kind`` is the caller's intent, not a different match, and it splits exactly
    where the real fetch worker splits it: both kinds write the event, the squad
    sheet, the incidents and the shot map — the four a vote is made of — and only
    'final' adds the per-player heatmaps. Writing them on every round would be
    correct and would quietly erase the difference the rig exists to show.
    """
    now = timezone.now()
    written = 0
    for match in (Match.objects.filter(external_id__in=external_ids)
                  .select_related("competition_season", "home_team__team",
                                  "away_team__team")):
        state = _state_of(match, now)
        if state is None:
            continue
        status, clock, teams, pool = state
        # Played ONCE per warm, even though two payloads come out of it: the light
        # event needs the score at this minute, which is not knowable without
        # playing the match, so the expensive part would be paid twice for nothing.
        played = None
        if status != "notstarted":
            played = sim.simulate_match(
                teams[match.home_team_id], teams[match.away_team_id],
                int(match.matchday or 1), pool,
                random.Random(f"{_seed_of()}:{match.external_id}"), clock=clock)
        _write_event(cache_dir, match, status, played)
        _refresh_round_entry(cache_dir, match, status, played)
        if played is not None:
            _write_match_data(cache_dir, match.external_id, played)
            if kind == "final" or status == "finished":
                _write_heatmaps(cache_dir, match.external_id, played)
        written += 1
    return written > 0


def _team_entry(team_season) -> dict:
    team = team_season.team
    return {"id": int(team.external_id), "name": team.name,
            "shortName": team.short_name or team.name}


def _write_event(cache_dir: Path, match: Match, status: str, played) -> None:
    """The single-match ``/event/{id}``: lifecycle, score, and the fixture itself.

    The score is the score AT THIS MINUTE, which is why the match is played out and
    cut back rather than read off a stored final result.

    The teams and the round are here because the real endpoint carries them, and
    because the live import now resolves a match FROM THIS PAYLOAD instead of from
    the calendar (see ``sofascore_adapter._event_by_id``). Serving the reduced dict
    a live poll happens to be satisfied with would send the rig down the fallback
    path at every import — measuring, silently, a route production does not take.
    """
    payload = {"event": {
        "id": int(match.external_id),
        "status": {"type": status},
        "startTimestamp": int(match.kickoff.timestamp()) if match.kickoff else None,
        "homeScore": {"current": played.home_goals if played else None},
        "awayScore": {"current": played.away_goals if played else None},
        "homeTeam": _team_entry(match.home_team),
        "awayTeam": _team_entry(match.away_team),
        "roundInfo": {"round": match.matchday},
    }}
    sim._write(cache_dir, f"/api/v1/event/{match.external_id}", payload)


def _write_match_data(cache_dir: Path, mid: str, played) -> None:
    """Lineups, shot map and incidents: three requests, and the totals a vote is
    made of. Written on every round, light or heavy."""
    sim._write(cache_dir, f"/api/v1/event/{mid}/lineups", played.lineups)
    sim._write(cache_dir, f"/api/v1/event/{mid}/shotmap", {"shotmap": played.shotmap})
    sim._write(cache_dir, f"/api/v1/event/{mid}/incidents",
               {"incidents": played.incidents})


def _write_heatmaps(cache_dir: Path, mid: str, played) -> None:
    """One per player, and the expensive half of the fetch: WHERE each of them was.
    Only a heavy round asks for these."""
    for pid, points in played.heatmaps.items():
        sim._write(cache_dir, f"/api/v1/event/{mid}/player/{pid}/heatmap",
                   {"heatmap": points})


# --------------------------------------------------------------------------- #
# Context, built once per process                                              #
# --------------------------------------------------------------------------- #
_CONTEXT: dict[int, tuple] = {}


def _state_of(match: Match, now):
    """(status, clock, squads, donor pool) for a match, or None if it is not ours.

    The squads and the donor pool are expensive to build (a query over every stint
    and eleven thousand appearances) and never change during a run, so they are
    cached per season for the life of the process. A tick is a short-lived process;
    a long-lived one polling every two minutes would otherwise rebuild them all day.
    """
    if match.kickoff is None:
        return None
    status, clock = sim.status_at(match.kickoff, now)
    season_id = match.competition_season_id
    if season_id not in _CONTEXT:
        cs = CompetitionSeason.objects.get(id=season_id)
        _CONTEXT[season_id] = (sim.load_squads(season_id),
                               sim.DonorPool.load(sim._donor_season_id(cs)))
    teams, pool = _CONTEXT[season_id]
    return status, clock, teams, pool


def _seed_of() -> int:
    """The scenario seed. Read from settings so a match warmed by a poll is the
    SAME match the scenario builder wrote, not a second one that happens to involve
    the same two teams."""
    from django.conf import settings

    return int(getattr(settings, "VFOOT_SIM_SEED", 2627))
