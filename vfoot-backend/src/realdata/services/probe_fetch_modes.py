"""Probe: once cf_clearance exists, which way of calling the API returns 200?

Earlier probes failed because cf_clearance wasn't set yet. With --headful
--channel chrome the real browser solves the Cloudflare challenge and sets
cf_clearance after a few seconds. So: wait for cf_clearance, THEN try every way
of reaching the API (in-page fetch variants + a direct top-level navigation).

    python probe_fetch_modes.py --headful --channel chrome
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

from sofascore_browser_client import SofaScoreBrowserClient
from sofascore_client import API_BASE, SITE_BASE

TEST_PATH = "/api/v1/event/13980080/lineups"  # a still-missing round-38 match


JS = r"""
async (urls) => {
  const out = [];
  const tries = [
    ['api default creds',  urls.api, {}],
    ['api omit creds',     urls.api, {credentials: 'omit'}],
    ['api include creds',  urls.api, {credentials: 'include'}],
    ['www include creds',  urls.www, {credentials: 'include'}],
  ];
  for (const [label, url, opts] of tries) {
    try {
      const r = await fetch(url, {headers: {'Accept': '*/*'}, ...opts});
      const t = await r.text();
      out.push({label, url, status: r.status, len: t.length, head: t.slice(0, 70)});
    } catch (e) {
      out.push({label, url, status: -1, error: String(e)});
    }
  }
  return out;
}
"""


def _has_clearance(ctx) -> bool:
    return any("clearance" in c["name"].lower() for c in ctx.cookies())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chromium-path", default=None)
    ap.add_argument("--channel", default=None)
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--wait", type=int, default=40,
                    help="Max seconds to wait for cf_clearance.")
    args = ap.parse_args()

    cache = Path("./_probe_fetchmodes_cache")
    if cache.exists():
        shutil.rmtree(cache)

    client = SofaScoreBrowserClient(
        cache, min_delay=1.0, logger=print,
        headless=not args.headful, chromium_path=args.chromium_path,
        channel=args.channel)
    try:
        page = client._ensure_session()
        print(f"  landed: {page.url!r}")

        # Poll for cf_clearance (reloading once midway if it doesn't show).
        deadline = time.monotonic() + args.wait
        reloaded = False
        while not _has_clearance(client._ctx):
            if time.monotonic() > deadline:
                print(f"  !! cf_clearance never appeared in {args.wait}s")
                break
            page.wait_for_timeout(1000)
            if not reloaded and time.monotonic() > deadline - args.wait / 2:
                reloaded = True
                try:
                    page.reload(wait_until="domcontentloaded", timeout=20000)
                except Exception:
                    pass
        if _has_clearance(client._ctx):
            print("  cf_clearance: PRESENT")

        # In-page fetch variants
        results = page.evaluate(JS, {
            "api": API_BASE + TEST_PATH,
            "www": SITE_BASE + TEST_PATH,
        })
        print("\n  in-page fetch results:")
        for r in results:
            tag = "   <<< 200" if r.get("status") == 200 else ""
            if r.get("status", -1) >= 0:
                print(f"    [{r['label']:<18}] status={r['status']} "
                      f"len={r.get('len')} head={r.get('head')!r}{tag}")
            else:
                print(f"    [{r['label']:<18}] ERROR {r.get('error')}")

        # Direct top-level navigation (the original transport)
        try:
            resp = page.goto(API_BASE + TEST_PATH, wait_until="commit",
                             timeout=20000)
            body = page.evaluate("() => document.body ? document.body.innerText.slice(0,70) : ''")
            print(f"\n  direct page.goto(api): status={resp.status if resp else '?'} "
                  f"head={body!r}{'   <<< 200' if resp and resp.status == 200 else ''}")
        except Exception as exc:  # noqa: BLE001
            print(f"\n  direct page.goto(api): ERROR {type(exc).__name__}: {str(exc)[:80]}")

        winners = [r["label"] for r in results if r.get("status") == 200]
        print(f"\n  => in-page winners: {winners or 'NONE'}")
    finally:
        client.close()
        if cache.exists():
            shutil.rmtree(cache)


if __name__ == "__main__":
    main()
