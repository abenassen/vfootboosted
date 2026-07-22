"""Probe: how far along is the provider's calendar for the UPCOMING season?

Answers the pre-season question: are kickoff times CONFIRMED yet, or still the
placeholder the provider ships before slots are assigned? (A round whose fixtures
all share one identical timestamp is not yet scheduled — the same heuristic
``calendar_sync`` uses to set ``Match.kickoff_provisional``, mirrored here so the
probe stays standalone/Django-free.)

Serie A unique-tournament id = 23. Uses the browser transport (passes Cloudflare)
with a THROWAWAY cache so every read is live. Run it yourself (network step):

    cd vfoot-backend/src/realdata/services
    python probe_next_season.py                      # first 6 rounds
    python probe_next_season.py --rounds 38          # whole season
    python probe_next_season.py --headful --channel chrome   # if headless is blocked
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sofascore_browser_client import SofaScoreBrowserClient

TID = 23  # Serie A


def _fmt(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default=None, help='e.g. "chrome"')
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--rounds", type=int, default=6,
                    help="how many rounds to inspect (default 6)")
    ap.add_argument("--year", default=None,
                    help="season label, e.g. '26/27'; default = auto-detect upcoming")
    args = ap.parse_args()

    cache = Path("./_probe_next_season_cache")
    if cache.exists():
        shutil.rmtree(cache)

    client = SofaScoreBrowserClient(
        cache, min_delay=1.0, logger=print,
        headless=not args.headful, channel=args.channel)

    try:
        seasons = client.get_valid_seasons()
        if args.year:
            if args.year not in seasons:
                print(f"\n>>> Season {args.year!r} not listed. Available: {sorted(seasons)}")
                return
            year = args.year
        else:
            upcoming = [y for y in seasons if ("26" in str(y) and "27" in str(y))]
            if not upcoming:
                print("\n>>> No 26/27 season listed yet on SofaScore.")
                return
            year = upcoming[0]
        sid = seasons[year]
        print(f"\n>>> Season {year} (id {sid})")

        rounds_data = client.get(
            f"/api/v1/unique-tournament/{TID}/season/{sid}/rounds")
        rnos = sorted({r.get("round") for r in rounds_data.get("rounds", [])
                       if r.get("round") is not None})
        print(f"    rounds published: {len(rnos)}   currentRound: {rounds_data.get('currentRound')}")

        print(f"\n    Kickoff status, first {min(args.rounds, len(rnos))} rounds")
        print(f"    {'rnd':>4}  {'ev':>3}  {'slots':>5}  {'state':<11}  window")
        confirmed = 0
        inspected = 0
        for rnd in rnos[:args.rounds]:
            data = client.get(
                f"/api/v1/unique-tournament/{TID}/season/{sid}/events/round/{rnd}")
            events = data.get("events", []) or []
            if not events:
                print(f"    {rnd:>4}  {0:>3}  {'-':>5}  {'EMPTY':<11}")
                continue
            inspected += 1
            stamps = sorted({e.get("startTimestamp") for e in events
                             if e.get("startTimestamp")})
            provisional = len(events) > 1 and len(stamps) == 1
            if not provisional:
                confirmed += 1
            state = "PROVISIONAL" if provisional else "confirmed"
            window = (_fmt(stamps[0]) if len(stamps) == 1
                      else f"{_fmt(stamps[0])} -> {_fmt(stamps[-1])}")
            print(f"    {rnd:>4}  {len(events):>3}  {len(stamps):>5}  {state:<11}  {window}")

        print(f"\n>>> {confirmed}/{inspected} inspected rounds have CONFIRMED kickoff slots.")
        if confirmed:
            print("    -> the scheduler can open live windows on those rounds.")
        else:
            print("    -> still placeholders; calendar-sync will pick up the real slots "
                  "as they are published (kickoff_provisional stays True until then).")

        # First round detail: ids are what the scrapers key on.
        if rnos:
            first = client.get(
                f"/api/v1/unique-tournament/{TID}/season/{sid}/events/round/{rnos[0]}")
            print(f"\n    Round {rnos[0]} fixtures:")
            for ev in first.get("events", [])[:10]:
                st = (ev.get("status") or {}).get("type")
                print(f"      id={ev.get('id')}  {_fmt(ev.get('startTimestamp'))}  "
                      f"{st:<11} {ev.get('homeTeam', {}).get('name')} v "
                      f"{ev.get('awayTeam', {}).get('name')}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
