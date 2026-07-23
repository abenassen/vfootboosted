"""Per-match SofaScore fetch — runs INSIDE the egress netns (so it exits via the
pinned Surfshark IP). It is handed a list of match ids (the DB-aware caller
decided which; this worker never touches the DB) and warms their cache.

Exit codes let the root orchestrator react:
  0  = all requested matches fetched (or already cached)
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


def fetch_match(client: SofaScoreClient, mid: int, kind: str) -> None:
    # Live: the evolving, cheap endpoints (no heatmaps mid-match) + the event status
    # itself, so the tick can read lifecycle/score without a heavy pull. Final: the
    # full set incl. per-player heatmaps, which only make sense once the match is over.
    client.get(f"/api/v1/event/{mid}")            # status + score (light)
    stats = client.player_stats_records(mid)
    client.incidents_records(mid)
    if kind == "final":
        client.shots_records(mid)
        for row in stats:
            pid = row.get("id")
            if pid is not None and _minutes(row) > 0:
                client.heatmap(mid, int(pid))


def warm_schedule(client: SofaScoreClient, year: str) -> None:
    # Warms seasons -> rounds -> every round's events: the whole fixture list the
    # calendar sync then reads OFFLINE. One cheap pass; no per-match data.
    client.get_match_dicts(year)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-ids", help="comma-separated match ids (fetch mode)")
    ap.add_argument("--schedule-year", help="season year e.g. 26/27 (schedule mode)")
    ap.add_argument("--kind", choices=["live", "final"], default="final")
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--delay", type=float, default=1.5)
    args = ap.parse_args()

    client = SofaScoreClient(Path(args.cache_dir), min_delay=args.delay,
                             max_retries=1, logger=print)
    try:
        if args.schedule_year:
            warm_schedule(client, args.schedule_year)
            print(f"warmed schedule {args.schedule_year}")
        elif args.match_ids:
            for mid in (int(x) for x in args.match_ids.split(",") if x.strip()):
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
