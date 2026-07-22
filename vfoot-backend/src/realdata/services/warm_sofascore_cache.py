"""Standalone SofaScore cache warmer (no Django) — meant to run on a Pi.

Fills the on-disk request cache so the heavy network scraping can run on a
separate always-on machine, decoupled from the database.

Deploy: copy THIS file and ``sofascore_client.py`` into the same folder on the
Pi, then::

    pip install curl_cffi
    python warm_sofascore_cache.py --year 25/26 --cache-dir ./sofascore_cache

It is resumable (cached requests return instantly) and stops cleanly if
SofaScore blocks — just re-run to continue. When done, rsync the cache dir to
the laptop's ``historical-data/serie-a/sofascore/cache/`` and run
``manage.py import_sofascore --year 25/26`` there: it reads the cache offline
and writes the DB locally.
"""

from __future__ import annotations

import argparse
from pathlib import Path

# Same-directory imports: keep this file next to sofascore_client.py and
# sofascore_browser_client.py.
from sofascore_client import SofaScoreClient, SofaScoreBlocked
from sofascore_browser_client import SofaScoreBrowserClient


def _minutes(row: dict) -> int:
    try:
        return int(float(row.get("minutesPlayed") or 0))
    except (TypeError, ValueError):
        return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Warm the SofaScore request cache.")
    ap.add_argument("--year", default="25/26", help="SofaScore season year, e.g. 25/26")
    ap.add_argument("--cache-dir", default="./sofascore_cache")
    ap.add_argument("--delay", type=float, default=2.0,
                    help="Seconds before every uncached request (throttle).")
    ap.add_argument("--limit", type=int, default=None,
                    help="Stop after warming N matches (testing).")
    ap.add_argument("--skip-ids-file", default=None,
                    help="File of match ids (whitespace/comma separated) to skip "
                         "— e.g. matches already in the laptop DB.")
    ap.add_argument("--transport", choices=["browser", "curl"], default="browser",
                    help="browser = real Chromium via Playwright (passes the TLS "
                         "block); curl = curl_cffi (now flagged by SofaScore).")
    ap.add_argument("--chromium-path", default=None,
                    help="Path to a system Chromium if Playwright's bundled one "
                         "won't run (e.g. /usr/bin/chromium on 32-bit OS).")
    ap.add_argument("--channel", default=None,
                    help='Browser channel, e.g. "chrome" to drive real Google '
                         "Chrome instead of Playwright's bundled Chromium.")
    ap.add_argument("--headful", action="store_true",
                    help="Show the browser window (debugging; needs a display).")
    args = ap.parse_args()

    if args.transport == "browser":
        client = SofaScoreBrowserClient(
            Path(args.cache_dir), min_delay=args.delay, logger=print,
            headless=not args.headful, chromium_path=args.chromium_path,
            channel=args.channel)
    else:
        client = SofaScoreClient(Path(args.cache_dir), min_delay=args.delay, logger=print)

    try:
        _warm(client, args)
    finally:
        if hasattr(client, "close"):
            client.close()


def _warm(client, args) -> None:
    skip_ids: set[int] = set()
    if args.skip_ids_file:
        text = Path(args.skip_ids_file).read_text()
        skip_ids = {int(tok) for tok in text.replace(",", " ").split() if tok.strip().isdigit()}
        print(f"Skipping {len(skip_ids)} match ids already done (from {args.skip_ids_file}).")

    events = client.get_match_dicts(args.year)
    finished = [e for e in events
                if (e.get("status") or {}).get("type") == "finished"]
    print(f"{len(finished)} finished matches to warm (of {len(events)} in schedule).")

    warmed = 0
    skipped = 0
    for event in finished:
        if args.limit is not None and warmed >= args.limit:
            print(f"Reached --limit {args.limit}; stopping.")
            break
        match_id = int(event["id"])
        if match_id in skip_ids:
            skipped += 1
            continue
        home = (event.get("homeTeam") or {}).get("name")
        away = (event.get("awayTeam") or {}).get("name")
        try:
            stats = client.player_stats_records(match_id)
            client.shots_records(match_id)
            incidents = client.incidents_records(match_id)  # goals/cards/subs
            heatmaps = 0
            for row in stats:
                pid = row.get("id")
                if pid is not None and _minutes(row) > 0:
                    client.heatmap(match_id, int(pid))
                    heatmaps += 1
            print(f"  warmed {match_id} {home} v {away}: players={len(stats)} "
                  f"heatmaps={heatmaps} incidents={len(incidents)}")
        except SofaScoreBlocked as exc:
            print(f"  !! blocked ({exc}); stopping. Re-run to resume from cache.")
            break
        except Exception as exc:  # noqa: BLE001 - skip one bad match, keep going
            print(f"  !! match {match_id} failed: {type(exc).__name__}: {exc}")
        warmed += 1

    print(f"Done. Warmed {warmed} matches (skipped {skipped}) "
          f"into {Path(args.cache_dir).resolve()}")


if __name__ == "__main__":
    main()
