"""Probe: sniff the site's OWN api.sofascore.com DATA calls on a match page.

Navigate to a real match page so the site fires its lineups/statistics/heatmap
XHRs, then report every /api/v1/ response grouped by host+status, and dump the
successful api.sofascore.com DATA calls (url + request headers) so we can see
exactly what makes them pass — and whether the site's own data calls even
succeed anymore.

    python probe_sniff.py --headful --channel chrome
"""

from __future__ import annotations

import argparse
import shutil
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from sofascore_browser_client import SofaScoreBrowserClient

MATCH_URL = ("https://www.sofascore.com/football/match/"
             "fiorentina-atalanta/LdbsTdb#id:13980080")
DATA_HOST = "www.sofascore.com"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chromium-path", default=None)
    ap.add_argument("--channel", default=None)
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--seconds", type=int, default=18)
    args = ap.parse_args()

    cache = Path("./_probe_sniff_cache")
    if cache.exists():
        shutil.rmtree(cache)

    client = SofaScoreBrowserClient(
        cache, min_delay=1.0, logger=print,
        headless=not args.headful, chromium_path=args.chromium_path,
        channel=args.channel)

    seen = []  # (host, status, url, request_headers)
    by_host_status = Counter()

    try:
        client._ensure_session()
        pg = client._page

        def on_response(resp):
            url = resp.url
            if "/api/v1/" not in url:
                return
            host = urlsplit(url).netloc
            try:
                status = resp.status
            except Exception:
                status = "?"
            by_host_status[(host, status)] += 1
            try:
                req_headers = dict(resp.request.headers)
            except Exception:
                req_headers = {}
            seen.append((host, status, url, req_headers))

        pg.on("response", on_response)

        print(f"\n  Navigating the match page, listening {args.seconds}s...")
        try:
            pg.goto(MATCH_URL, wait_until="domcontentloaded", timeout=25000)
        except Exception as exc:  # noqa: BLE001
            print(f"  (match nav issue: {exc})")
        # try to open the Lineups tab so those endpoints fire
        for label in ("Lineups", "Formazioni", "Player statistics", "Statistiche"):
            try:
                pg.get_by_text(label, exact=False).first.click(timeout=2500)
                pg.wait_for_timeout(1500)
            except Exception:
                pass
        pg.wait_for_timeout(args.seconds * 1000)

        print("\n  /api/v1/ responses by host+status:")
        for (host, status), n in sorted(by_host_status.items()):
            print(f"    {host:<22} {status}  x{n}")

        data_ok = [s for s in seen if s[0] == DATA_HOST and s[1] == 200]
        data_bad = [s for s in seen if s[0] == DATA_HOST and s[1] != 200]
        print(f"\n  {DATA_HOST}: {len(data_ok)} OK, {len(data_bad)} non-200")

        if data_ok:
            print("\n  >>> SUCCESSFUL data calls the SITE made (sample up to 8):")
            for host, status, url, h in data_ok[:8]:
                print(f"      200  {url}")
            # prefer an /event/ call as the representative one to dump fully
            rep = next((s for s in data_ok if "/event/" in s[2]), data_ok[0])
            host, status, url, h = rep
            print(f"\n  ALL request headers of: {url}")
            for k in sorted(h):
                v = h[k]
                if k.lower() == "cookie":
                    names = [c.split("=")[0].strip() for c in v.split(";")]
                    print(f"        cookie: ({len(names)} cookies) {sorted(names)}")
                else:
                    print(f"        {k}: {v}")
        else:
            print("  !! Even the site's own data calls are NOT 200.")
            if data_bad:
                host, status, url, h = data_bad[0]
                print(f"  sample: status={status} {url}")

        names = sorted(c["name"] for c in client._ctx.cookies())
        clearance = [n for n in names if "clearance" in n.lower()]
        print(f"\n  cf_clearance cookie(s): {clearance or 'NONE'}")
    finally:
        client.close()
        if cache.exists():
            shutil.rmtree(cache)


if __name__ == "__main__":
    main()
