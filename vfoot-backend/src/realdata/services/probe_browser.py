"""Probe 3: does the headless browser transport pass SofaScore's TLS block?

Uses a THROWAWAY empty cache dir so the request is always live (the real
warmer cache is untouched), then fetches one known endpoint via
``SofaScoreBrowserClient``. This isolates the transport: no schedule fetch, no
reuse of already-cached matches — just "does real Chromium get the JSON".

Run on the Pi (after `pip install playwright && playwright install chromium`):

    python probe_browser.py
    python probe_browser.py --chromium-path /usr/bin/chromium   # 32-bit fallback
    python probe_browser.py --headful                           # needs a display
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from sofascore_browser_client import SofaScoreBrowserClient
from sofascore_client import SofaScoreBlocked

# event 13980080 (Fiorentina v Atalanta, round 38) — one of the 59 still-missing
# matches, so this is a live, representative fetch.
TEST_MATCH = 13980080


def main() -> None:
    ap = argparse.ArgumentParser(description="Probe the browser transport.")
    ap.add_argument("--chromium-path", default=None)
    ap.add_argument("--channel", default=None,
                    help='e.g. "chrome" to drive the real Google Chrome binary.')
    ap.add_argument("--headful", action="store_true")
    args = ap.parse_args()

    cache = Path("./_probe_browser_cache")
    if cache.exists():
        shutil.rmtree(cache)  # ensure a live fetch, not a cached read

    client = SofaScoreBrowserClient(
        cache, min_delay=1.0, logger=print,
        headless=not args.headful, chromium_path=args.chromium_path,
        channel=args.channel)
    try:
        # Trigger the warm-up (site load + challenge) and inspect the cookies
        # the anti-bot left us — a clearance cookie means the JS challenge solved.
        client._ensure_session()
        names = sorted(c["name"] for c in client._ctx.cookies())
        clearance = [n for n in names
                     if any(k in n.lower() for k in ("datadome", "clearance", "_cf", "challenge"))]
        print(f"  cookies after warm-up ({len(names)}): {names}")
        print(f"  likely anti-bot clearance cookie(s): {clearance or 'NONE'}")
        # Is the page we landed on the real site or a Cloudflare challenge wall?
        try:
            title = client._page.title()
            content = (client._page.content() or "").lower()
            challenge = any(k in content for k in
                            ("just a moment", "checking your browser",
                             "cf-challenge", "challenge-platform", "enable javascript"))
            print(f"  landed page: url={client._page.url!r} title={title!r}")
            print(f"  looks like a Cloudflare challenge wall: {challenge}")
        except Exception as exc:  # noqa: BLE001
            print(f"  (couldn't introspect page: {type(exc).__name__}: {exc})")

        print(f"\nFetching lineups for event {TEST_MATCH} via browser...")
        players = client.player_stats_records(TEST_MATCH)
        shots = client.shots_records(TEST_MATCH)
        # also exercise a per-player heatmap (the highest-volume endpoint type)
        hm_pts = None
        pid = next((p.get("id") for p in players if p.get("id")), None)
        if pid is not None:
            hm_pts = len(client.heatmap(TEST_MATCH, int(pid)))
        print(f"\n  PASS: {len(players)} player records, {len(shots)} shots, "
              f"heatmap points for pid {pid}: {hm_pts}.")
        if players:
            print(f"  sample: {players[0].get('name')} "
                  f"({players[0].get('side')}) — keys: {len(players[0])}")
        print("\n=> Browser transport WORKS. Safe to run the full warmer with "
              "--transport browser.")
    except SofaScoreBlocked as exc:
        print(f"\n  BLOCKED: {exc}")
        print("\n=> Even the headless browser is challenged. Try --headful, or "
              "tell Claude — we add stealth / use the real browser profile.")
    finally:
        client.close()
        if cache.exists():
            shutil.rmtree(cache)


if __name__ == "__main__":
    main()
