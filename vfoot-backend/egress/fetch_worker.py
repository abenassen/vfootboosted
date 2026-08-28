"""Per-match SofaScore fetch — runs INSIDE the egress netns (so it exits via the
pinned Surfshark IP). It is handed a list of match ids (the DB-aware caller
decided which; this worker never touches the DB) and warms their cache.

A WARM DROPS WHAT IT IS ABOUT TO REWRITE, FIRST. That is the whole difference
between this side and the reading side, and it is not an optimisation — it is the
only thing that makes a live match live. ``SofaScoreClient`` caches on disk with no
expiry: a path already on disk is returned WITHOUT a request. That is exactly right
for the app, which reads what this worker just left there, and exactly wrong here,
where a second warm of the same match would return the first warm's bytes for the
rest of the evening. The score would freeze at the minute of the first fetch, the
votes with it, and every tick would go on reporting success — no error anywhere.

``--resume`` turns the purge off, and has ONE caller: the orchestrator, when it
rotates to another IP after a block. That retry is the same warm continuing, so it
must not re-pay for the twenty heatmaps it already got.

Exit codes let the root orchestrator react:
  0  = all requested matches fetched
  3  = SofaScore blocked this IP  -> orchestrator should rotate to another IP
  1  = other error

  python fetch_worker.py --match-ids 123,456 --kind final --cache-dir /var/cache/sofa
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# sofascore_client lives in the app tree (src/realdata/services); make it importable
# whether this worker sits next to a copy (the /root test dir) or in the repo's
# egress/ dir. Python already put THIS dir on sys.path[0]; add the services dir too.
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "..", "src", "realdata", "services"))
from sofascore_client import SofaScoreClient, SofaScoreBlocked  # noqa: E402


def _minutes(row: dict) -> int:
    try:
        return int(float(row.get("minutesPlayed") or 0))
    except (TypeError, ValueError):
        return 0


def fetch_probable(client: SofaScoreClient, mid: int) -> None:
    """UNA richiesta: la distinta, che prima del calcio d'inizio e' la formazione
    PREVISTA (``confirmed: false``).

    E' il giro piu' economico che esista qui dentro, ed e' voluto: le probabili
    valgono meno dei voti e non devono poter costare quanto loro. Nessun evento,
    nessun tabellino, nessuna heatmap — solo il foglio squadra.
    """
    client.get(f"/api/v1/event/{mid}/lineups")


def fetch_match(client: SofaScoreClient, mid: int, kind: str) -> None:
    # Four requests, and they are everything a vote needs: the event (status, score
    # and the fixture the importer resolves from), the squad sheet, the incidents,
    # and the shot map. What 'final' adds is the POSITIONAL half — a heatmap per
    # player, some twenty-two more requests — which is the whole reason the two
    # kinds exist and why the heavy one is rationed to every k-th round.
    client.get(f"/api/v1/event/{mid}")
    stats = client.player_stats_records(mid)
    client.incidents_records(mid)
    client.shots_records(mid)
    if kind == "final":
        for row in stats:
            pid = row.get("id")
            if pid is not None and _minutes(row) > 0:
                client.heatmap(mid, int(pid))


def warm_schedule(client: SofaScoreClient, year: str, cache_dir: Path, *,
                  rounds: list[int] | None = None, resume: bool = False) -> None:
    """Warm a season's fixture list: the schedule the calendar sync reads OFFLINE.
    No per-match data.

    ``rounds`` limits it to those matchdays — one request each instead of all
    thirty-eight, which is what lets the sync run every hour on a match day
    instead of four times a day. ``None`` warms the whole season.

    Dropped in two steps rather than by one wide glob, and the reason is a hazard
    rather than tidiness: this cache also holds the SEASONS ALREADY SCRAPED (a
    13k-request pull on a dev machine), and they live under the same
    ``unique-tournament`` prefix. Wiping the prefix to refresh one season would
    take the others with it. So: drop the seasons index, re-read it, and only then
    drop what is about to be re-read OF THE SEASON BEING WARMED — and, with
    ``rounds``, only the rounds actually being re-read. Dropping the other
    thirty-four would leave the offline side unable to answer for them until some
    later full pass, which is a worse cache than no narrowing at all.
    """
    if not resume:
        purge(cache_dir.glob("api_v1_unique-tournament_*_seasons.json"))
    season_id = client.get_valid_seasons().get(year)
    if not resume and season_id:
        # The fixture list moves — postponements, kickoff changes — so a warm has
        # to actually re-read it, or the calendar sync never sees them.
        base = f"api_v1_unique-tournament_*_season_{season_id}"
        if rounds is None:
            purge(cache_dir.glob(f"{base}_*.json"))
        else:
            for rnd in rounds:
                purge(cache_dir.glob(f"{base}_events_round_{rnd}.json"))
    if rounds is None:
        client.get_match_dicts(year)
    else:
        for rnd in rounds:
            client.get_round_events(year, rnd)


def match_entries(cache_dir: Path, match_ids: list[int]):
    """The cache files a match warm is about to rewrite.

    Matched by name rather than by asking the client, because the heatmap paths are
    not knowable until the squad sheet has been fetched — and by then the stale copy
    would already have been served. ``api_v1_event_{mid}`` and
    ``api_v1_event_{mid}_...`` are exactly this match's entries: a longer id that
    starts with the same digits does not match either pattern.
    """
    for mid in match_ids:
        yield from cache_dir.glob(f"api_v1_event_{mid}.json")
        yield from cache_dir.glob(f"api_v1_event_{mid}_*.json")


def probable_entries(cache_dir: Path, match_ids: list[int]):
    """La sola distinta di ogni partita — quello che il giro 'probable' riscrive."""
    for mid in match_ids:
        yield from cache_dir.glob(f"api_v1_event_{mid}_lineups.json")


def purge(paths) -> int:
    """Drop those entries, so the fetch that follows is a fetch. Returns how many."""
    dropped = 0
    for path in paths:
        path.unlink(missing_ok=True)
        dropped += 1
    return dropped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-ids", help="comma-separated match ids (fetch mode)")
    ap.add_argument("--schedule-year", help="season year e.g. 26/27 (schedule mode)")
    ap.add_argument("--rounds", help="comma-separated rounds to warm (schedule "
                                     "mode); default = the whole season")
    ap.add_argument("--kind", choices=["live", "final", "probable"], default="final")
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--resume", action="store_true",
                    help="keep what is already cached instead of re-fetching it. "
                         "For a retry on another IP after a block — the same warm "
                         "continuing, which must not pay twice.")
    args = ap.parse_args()

    cache_dir = Path(args.cache_dir)
    ids = [int(x) for x in (args.match_ids or "").split(",") if x.strip()]
    rounds = ([int(x) for x in args.rounds.split(",") if x.strip()]
              if args.rounds else None)
    client = SofaScoreClient(cache_dir, min_delay=args.delay,
                             max_retries=1, logger=print)
    try:
        if args.schedule_year:
            # Drops as it goes: which files belong to this season is not knowable
            # before the seasons index has been re-read. See warm_schedule.
            warm_schedule(client, args.schedule_year, cache_dir,
                          rounds=rounds, resume=args.resume)
            print(f"warmed schedule {args.schedule_year}"
                  + (f" rounds={rounds}" if rounds else " (whole season)"))
        elif ids:
            if not args.resume:
                # Il giro 'probable' butta SOLO la distinta. Buttare anche il resto
                # sarebbe scorretto due volte: getterebbe dati che nessuno sta per
                # riscrivere (l'evento, il tabellino), e li getterebbe a favore del
                # giro meno importante che c'e' qui dentro.
                stale = (probable_entries(cache_dir, ids) if args.kind == "probable"
                         else match_entries(cache_dir, ids))
                print(f"purged {purge(stale)} stale entries")
            for mid in ids:
                if args.kind == "probable":
                    fetch_probable(client, mid)
                else:
                    fetch_match(client, mid, args.kind)
                print(f"fetched {mid} ({args.kind})")
        else:
            print("ERROR: need --match-ids or --schedule-year")
            return 1
    except SofaScoreBlocked as exc:
        print(f"BLOCKED: {exc}")
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
