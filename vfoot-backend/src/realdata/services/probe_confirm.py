"""Confirm the full recipe: www base + cf_clearance + captured x-requested-with.

The site signs every API request with an `x-requested-with` header (e.g.
"725c6f"). We capture that value live from the site's own requests, then issue
our synthetic same-origin fetches WITH it. If shotmap/heatmap (which the site
never fetched, so no browser-cache shortcut) now return 200, the recipe is
proven.

    python probe_confirm.py --headful --channel chrome
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

from sofascore_browser_client import SofaScoreBrowserClient

BASE = "https://www.sofascore.com"
MATCH = 13980080
MATCH_URL = f"{BASE}/football/match/fiorentina-atalanta/LdbsTdb#id:{MATCH}"

JS = r"""
async ({base, mid, xrw}) => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const get = async (path) => {
    try {
      const r = await fetch(base + path,
        {headers: {'Accept': '*/*', 'x-requested-with': xrw}});
      const t = await r.text();
      let j = null; try { j = JSON.parse(t); } catch (e) {}
      return {status: r.status, len: t.length, json: j};
    } catch (e) { return {status: -1, error: String(e)}; }
  };
  const out = {};
  out.lineups = await get(`/api/v1/event/${mid}/lineups`); await sleep(2500);
  out.shotmap = await get(`/api/v1/event/${mid}/shotmap`); await sleep(2500);
  let pid = null;
  try { pid = out.lineups.json.home.players[0].player.id; } catch (e) {}
  out.pid = pid;
  if (pid) out.heatmap = await get(`/api/v1/event/${mid}/player/${pid}/heatmap`);
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
    ap.add_argument("--wait", type=int, default=50)
    args = ap.parse_args()

    cache = Path("./_probe_confirm_cache")
    if cache.exists():
        shutil.rmtree(cache)

    client = SofaScoreBrowserClient(
        cache, min_delay=1.0, logger=print,
        headless=not args.headful, chromium_path=args.chromium_path,
        channel=args.channel)

    captured = {"xrw": None}

    try:
        client._ensure_session()
        pg = client._page

        def on_request(req):
            if "/api/v1/" in req.url and "www.sofascore.com" in req.url:
                try:
                    v = req.headers.get("x-requested-with")
                except Exception:
                    v = None
                if v:
                    captured["xrw"] = v
        pg.on("request", on_request)

        try:
            pg.goto(MATCH_URL, wait_until="domcontentloaded", timeout=25000)
        except Exception as exc:  # noqa: BLE001
            print(f"  (match nav issue: {exc})")

        deadline = time.monotonic() + args.wait
        i = 0
        while (not _has_clearance(client._ctx) or not captured["xrw"]) \
                and time.monotonic() < deadline:
            i += 1
            try:
                pg.mouse.move(200 + i * 17 % 600, 200 + i * 23 % 400)
                pg.mouse.wheel(0, 300)
                if i % 3 == 0:
                    for label in ("Lineups", "Formazioni", "Player statistics"):
                        try:
                            pg.get_by_text(label, exact=False).first.click(timeout=1500)
                            break
                        except Exception:
                            pass
            except Exception:
                pass
            pg.wait_for_timeout(1500)

        print(f"  cf_clearance: {'PRESENT' if _has_clearance(client._ctx) else 'ABSENT'}")
        print(f"  captured x-requested-with: {captured['xrw']!r}")
        if not captured["xrw"]:
            print("  (no x-requested-with captured — can't test the signed fetch)")
            return

        res = pg.evaluate(JS, {"base": BASE, "mid": MATCH, "xrw": captured["xrw"]})

        def show(name, r):
            if not r:
                print(f"  {name:<8} (skipped)"); return
            if r.get("status", -1) < 0:
                print(f"  {name:<8} ERROR {r.get('error')}"); return
            j = r.get("json")
            extra = ""
            if name == "lineups" and isinstance(j, dict):
                extra = f" players home={len((j.get('home') or {}).get('players') or [])}"
            if name == "shotmap" and isinstance(j, dict):
                extra = f" shots={len(j.get('shotmap') or [])}"
            if name == "heatmap" and isinstance(j, dict):
                extra = f" points={len(j.get('heatmap') or [])}"
            tag = "  <<< OK" if r.get("status") == 200 else ""
            print(f"  {name:<8} status={r['status']} len={r['len']}{extra}{tag}")

        print()
        show("lineups", res.get("lineups"))
        show("shotmap", res.get("shotmap"))
        print(f"  picked player id: {res.get('pid')}")
        show("heatmap", res.get("heatmap"))
    finally:
        client.close()
        if cache.exists():
            shutil.rmtree(cache)


if __name__ == "__main__":
    main()
