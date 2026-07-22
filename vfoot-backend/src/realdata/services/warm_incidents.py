"""Lightweight top-up: fetch ONLY the /incidents endpoint for every finished match.

The original warmer pulled lineups/shotmap/heatmap but not incidents — yet cards
(yellow/red) live ONLY in incidents, alongside goals (scorer+assist), subs,
penalties and VAR. Incidents is ONE request per match (~380 total) vs the ~13k
per-player heatmap requests, so this is a quick supplementary pass over an
existing cache. Resumable and stop-clean on block, exactly like warm_sofascore_cache.

    python warm_incidents.py --year 25/26 \
        --cache-dir /…/historical-data/serie-a/sofascore/cache \
        --transport browser --headful --channel chrome
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sofascore_client import SofaScoreClient, SofaScoreBlocked
from sofascore_browser_client import SofaScoreBrowserClient


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch only /incidents for the season.")
    ap.add_argument("--year", default="25/26")
    ap.add_argument("--cache-dir", default="./sofascore_cache")
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--transport", choices=["browser", "curl"], default="browser")
    ap.add_argument("--chromium-path", default=None)
    ap.add_argument("--channel", default=None)
    ap.add_argument("--headful", action="store_true")
    args = ap.parse_args()

    if args.transport == "browser":
        client = SofaScoreBrowserClient(
            Path(args.cache_dir), min_delay=args.delay, logger=print,
            headless=not args.headful, chromium_path=args.chromium_path,
            channel=args.channel)
    else:
        client = SofaScoreClient(Path(args.cache_dir), min_delay=args.delay, logger=print)

    try:
        events = client.get_match_dicts(args.year)
        finished = [e for e in events
                    if (e.get("status") or {}).get("type") == "finished"]
        print(f"{len(finished)} finished matches; fetching incidents (cached = instant).")

        done = 0
        with_cards = 0
        for i, event in enumerate(finished, 1):
            if args.limit is not None and done >= args.limit:
                print(f"Reached --limit {args.limit}; stopping.")
                break
            mid = int(event["id"])
            home = (event.get("homeTeam") or {}).get("name")
            away = (event.get("awayTeam") or {}).get("name")
            try:
                inc = client.incidents_records(mid)
            except SofaScoreBlocked as exc:
                print(f"  !! blocked ({exc}); stopping. Re-run to resume from cache.")
                break
            except Exception as exc:  # noqa: BLE001 - skip one bad match, keep going
                print(f"  !! match {mid} failed: {type(exc).__name__}: {exc}")
                continue
            cards = sum(1 for x in inc if x.get("incidentType") == "card")
            if cards:
                with_cards += 1
            print(f"  [{i}/{len(finished)}] {mid} {home} v {away}: "
                  f"incidents={len(inc)} cards={cards}")
            done += 1

        print(f"Done. {done} matches fetched ({with_cards} had cards) "
              f"into {Path(args.cache_dir).resolve()}")
    finally:
        if hasattr(client, "close"):
            client.close()


if __name__ == "__main__":
    main()
