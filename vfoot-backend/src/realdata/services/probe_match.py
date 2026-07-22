"""Probe 2: does curl_cffi pass the data API if we send the browser's headers?

Replays the exact lineups request the browser made, via curl_cffi, with the
full mobile-Chrome header set (UA, sec-ch-ua, sec-fetch-*). NO ad cookies — we
established those are third-party junk, not a SofaScore token.

Tries several impersonate targets so we can see if a fresher Chrome fingerprint
is what's needed. Run on the Pi:

    python probe_match.py

Optionally inject the browser's raw Cookie header to rule cookies in/out:

    COOKIES='_ga=...; __gads=...' python probe_match.py
"""

from __future__ import annotations

import os

from curl_cffi import requests as cffi

URL = "https://api.sofascore.com/api/v1/event/13981430/lineups"

# Exactly what the browser sent (minus if-none-match, so we get a full body).
HEADERS = {
    "accept": "*/*",
    "accept-language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "referer": "https://www.sofascore.com/",
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?1",
    "sec-ch-ua-platform": '"Android"',
    "user-agent": ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/148.0.0.0 Mobile Safari/537.36"),
}

# Newest first — the one that matches the live browser (148) is what we want.
TARGETS = ["chrome", "chrome131", "chrome124", "chrome120", "chrome116"]


def verdict(resp) -> str:
    if resp.status_code == 200:
        try:
            resp.json()
            return "PASS (200 JSON)"
        except Exception:
            return "200 non-JSON"
    body = (resp.text or "")[:120]
    return f"BLOCKED ({resp.status_code}) {body}"


def main() -> None:
    headers = dict(HEADERS)
    cookies = os.environ.get("COOKIES")
    if cookies:
        headers["cookie"] = cookies
        print("(sending the browser Cookie header too)")

    s = cffi.Session()
    for target in TARGETS:
        try:
            r = s.get(URL, headers=headers, impersonate=target, timeout=20)
        except Exception as exc:  # target not supported by this curl_cffi build
            print(f"impersonate={target:10s} -> n/a ({type(exc).__name__}: {str(exc)[:50]})")
            continue
        print(f"impersonate={target:10s} -> {verdict(r)}")


if __name__ == "__main__":
    main()
