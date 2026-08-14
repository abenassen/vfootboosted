"""Compact Transfermarkt probe for the VPN sweep — the twin of sofa_probe_netns.py.

Runs inside a netns; prints two parseable lines:
    EXITIP=<ip>   and   VERDICT=<PASS|CHALLENGE|EMPTY|THIN|HTTP_n|EXC ...>

It borrows the REAL scraper's client and headers instead of rolling its own, so
the verdict measures what the scrape will actually get — TLS fingerprint, header
order and all. A probe that passes where the scraper fails is worse than no probe:
it fills the pool with IPs that only work for the probe.

PASS requires the heavy half too. The competition page must list the clubs AND one
club's squad page must yield a real roster: a soft block can serve the cheap page
and challenge the squad pages, which is where every player lives.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

# The scraper lives in the app tree; make it importable whether this file sits in
# the repo's egress/ dir or beside a deployed copy. Same trick as fetch_worker.py.
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "..", "src", "realdata", "services"))
from bs4 import BeautifulSoup                                        # noqa: E402
from scrape_transfermarkt_squads import (                            # noqa: E402
    BASE, HEADERS, REQUEST_TIMEOUT, TransfermarktBlocked, _raise_if_challenged,
)
import httpx                                                         # noqa: E402

_VEREIN_RE = re.compile(r"/verein/(\d+)")
_SPIELER_RE = re.compile(r"/profil/spieler/(\d+)")
# Serie A has twenty clubs and squads run 25-40. Well under either and the page
# came back "successful" but hollow, which is a block wearing a 200.
MIN_CLUBS = 18
MIN_PLAYERS = 15


def exit_ip() -> str:
    try:
        return json.load(urllib.request.urlopen(
            "https://api.ipify.org?format=json", timeout=8))["ip"]
    except Exception:                                                # noqa: BLE001
        return "?"


def get(client: httpx.Client, url: str):
    try:
        r = client.get(url)
        _raise_if_challenged(r)
    except TransfermarktBlocked:
        return None, "CHALLENGE"
    except Exception as e:                                           # noqa: BLE001
        return None, f"EXC {type(e).__name__}"
    if r.status_code != 200:
        return None, f"HTTP_{r.status_code}"
    if not (r.text or "").strip():
        return None, "EMPTY"
    return BeautifulSoup(r.text, "lxml"), "OK"


def main() -> None:
    season = sys.argv[1] if len(sys.argv) > 1 else "2026"
    print(f"EXITIP={exit_ip()}")
    with httpx.Client(headers=HEADERS, timeout=REQUEST_TIMEOUT,
                      follow_redirects=True) as c:
        soup, v = get(c, f"{BASE}/-/startseite/wettbewerb/IT1?saison_id={season}")
        if v != "OK":
            print(f"VERDICT={v} (competition)"); return
        clubs: dict[str, str] = {}
        for a in soup.select("table.items td.hauptlink a[href*='/verein/']"):
            href = a.get("href", "")
            m = _VEREIN_RE.search(href)
            if m and a.get_text(strip=True):
                clubs.setdefault(m.group(1), href.strip("/").split("/")[0])
        if len(clubs) < MIN_CLUBS:
            print(f"VERDICT=THIN ({len(clubs)} clubs)"); return

        cid, slug = next(iter(clubs.items()))
        soup, v = get(c, f"{BASE}/{slug}/kader/verein/{cid}/saison_id/{season}/plus/1")
        if v != "OK":
            print(f"VERDICT={v} (squad)"); return
        n = 0
        for tr in soup.select("table.items > tbody > tr"):
            link = tr.select_one("a[href*='/profil/spieler/']")
            if link and _SPIELER_RE.search(link.get("href", "") or ""):
                n += 1
        if n < MIN_PLAYERS:
            print(f"VERDICT=THIN ({len(clubs)} clubs, {n} players)"); return
        print(f"VERDICT=PASS ({len(clubs)} clubs, {n} players)")


if __name__ == "__main__":
    main()
