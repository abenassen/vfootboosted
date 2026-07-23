"""Diagnostic probe: can THIS machine reach Transfermarkt like a browser?

The polling design hinges on one open question (ROADMAP §1): SofaScore 403s the
Linode datacenter IP, but Transfermarkt's squad scraper is a plain browser-UA GET
with no JS/TLS challenge — so it *might* work from Linode where SofaScore doesn't.
Before building a polling cadence on top of it, we have to actually check.

This script depends on nothing but ``httpx`` (no Django, no DB) so it can be
copied to the Linode box and run standalone:

    python3 probe_transfermarkt.py

It hits the two request shapes the real scraper uses — the competition page and
one squad page — and reports, for each: HTTP status, byte size, whether the
squad table (``table.items``) is actually present, any Cloudflare / challenge
fingerprints, and the exit IP as TM sees it. Run it from the laptop AND from
Linode and diff the two: same status + real table on both => scraping from Linode
is fine; a 403 or challenge only on Linode => the datacenter IP is the problem.
"""

from __future__ import annotations

import sys

import httpx

BASE = "https://www.transfermarkt.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# The two URL shapes the scraper uses: a competition page and a squad page. The
# squad URL below is Juventus 25/26 — a stable, always-populated roster.
URLS = {
    "competition": f"{BASE}/-/startseite/wettbewerb/IT1?saison_id=2025",
    "squad": f"{BASE}/juventus-turin/kader/verein/506/saison_id/2025/plus/1",
}

# Substrings that betray an anti-bot interstitial instead of the real page.
CHALLENGE_MARKERS = [
    "Just a moment",
    "cf-browser-verification",
    "cf_chl",
    "challenge-platform",
    "Attention Required",
    "captcha",
    "Access denied",
    "__cf_bm",
]


def _exit_ip(client: httpx.Client) -> str:
    try:
        r = client.get("https://api.ipify.org", timeout=10.0)
        return r.text.strip()
    except Exception as exc:  # noqa: BLE001
        return f"(unknown: {type(exc).__name__})"


def probe(name: str, url: str, client: httpx.Client) -> bool:
    print(f"\n=== {name}: {url}")
    try:
        r = client.get(url)
    except Exception as exc:  # noqa: BLE001
        print(f"  REQUEST FAILED: {type(exc).__name__}: {exc}")
        return False
    body = r.text
    low = body.lower()
    has_table = "table.items" in body or 'class="items"' in body
    hits = [m for m in CHALLENGE_MARKERS if m.lower() in low]
    server = r.headers.get("server", "")
    set_cookie = r.headers.get("set-cookie", "")
    print(f"  status      : {r.status_code}")
    print(f"  bytes       : {len(body)}")
    print(f"  server hdr  : {server}")
    print(f"  squad table : {'YES' if has_table else 'no'}")
    print(f"  challenge   : {hits if hits else 'none'}")
    if "cf" in server.lower() or "__cf" in set_cookie:
        print(f"  cloudflare  : set-cookie={set_cookie[:120]!r}")
    ok = r.status_code == 200 and has_table and not hits
    print(f"  -> {'OK' if ok else 'BLOCKED / DEGRADED'}")
    return ok


def main() -> int:
    with httpx.Client(headers=HEADERS, timeout=20.0, follow_redirects=True) as c:
        print(f"exit IP as TM sees it: {_exit_ip(c)}")
        results = {name: probe(name, url, c) for name, url in URLS.items()}
    ok = all(results.values())
    print(f"\nVERDICT: {'reachable from here' if ok else 'BLOCKED / degraded from here'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
