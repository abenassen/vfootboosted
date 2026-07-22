"""Targeted probe: is curl_cffi being stopped by a Cloudflare managed challenge?

Run on the Pi (same machine/IP where the warmer gets blocked):

    pip install curl_cffi
    python probe_cloudflare.py

It makes ONE raw curl_cffi request to a light SofaScore API endpoint and
inspects the response. Two predictions of the "managed challenge" diagnosis:

  (1) the 403 body is the Cloudflare challenge HTML (not JSON), with a
      `cf-mitigated: challenge` header and markers like "Just a moment".
  (2) replaying the SAME request with the browser's `cf_clearance` cookie +
      matching User-Agent turns it into 200 JSON.

To test (2), copy from the browser (DevTools on sofascore.com):
  - the `cf_clearance` cookie value  (Application -> Cookies)
  - the exact User-Agent             (console: navigator.userAgent)
and pass them via env vars:

    CF_CLEARANCE='<value>' CF_UA='<exact UA string>' python probe_cloudflare.py
"""

from __future__ import annotations

import os

from curl_cffi import requests as cffi

API = "https://api.sofascore.com/api/v1/unique-tournament/23/seasons"
SITE = "https://www.sofascore.com"

CHALLENGE_MARKERS = [
    "just a moment",
    "challenge-platform",
    "cf-challenge",
    "__cf_chl",
    "enable javascript and cookies",
    "cf_chl_opt",
]

INTERESTING_HEADERS = [
    "server", "cf-ray", "cf-mitigated", "content-type",
    "retry-after", "cf-cache-status",
]


def classify(resp) -> str:
    body = (resp.text or "")
    low = body.lower()
    hits = [m for m in CHALLENGE_MARKERS if m in low]
    if resp.status_code == 200:
        try:
            resp.json()
            return "OK_JSON (200, valid JSON — request passed)"
        except Exception:
            return "200 but NOT json (unexpected)"
    if hits:
        return f"CLOUDFLARE_CHALLENGE (markers: {', '.join(hits)})"
    if resp.status_code == 403:
        return "403 but no challenge markers (could be a hard block / WAF rule)"
    return f"other ({resp.status_code})"


def show(title: str, resp) -> None:
    print(f"\n=== {title} ===")
    print(f"status: {resp.status_code}")
    for h in INTERESTING_HEADERS:
        v = resp.headers.get(h)
        if v:
            print(f"  {h}: {v}")
    body = resp.text or ""
    print(f"body length: {len(body)}")
    print("body[:600]:")
    print(body[:600])
    print(f"--> verdict: {classify(resp)}")


def main() -> None:
    headers = {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": SITE + "/",
        "Origin": SITE,
    }

    # (1) plain curl_cffi, exactly like the warmer does it
    s = cffi.Session()
    r1 = s.get(API, headers=headers, impersonate="chrome", timeout=20)
    show("PROBE 1: plain curl_cffi (as the warmer)", r1)

    # (2) same request + browser's cf_clearance cookie & matching UA
    clearance = os.environ.get("CF_CLEARANCE")
    ua = os.environ.get("CF_UA")
    if clearance and ua:
        h2 = dict(headers)
        h2["User-Agent"] = ua
        r2 = s.get(API, headers=h2, cookies={"cf_clearance": clearance},
                   impersonate="chrome", timeout=20)
        show("PROBE 2: curl_cffi + browser cf_clearance + matching UA", r2)
        print("\n--- CONCLUSION ---")
        v1, v2 = classify(r1), classify(r2)
        if v1.startswith("CLOUDFLARE_CHALLENGE") and v2.startswith("OK_JSON"):
            print("CONFIRMED: managed challenge. curl_cffi alone is challenged;"
                  " the browser's cf_clearance unblocks it. IP is fine.")
        elif v1.startswith("OK_JSON"):
            print("curl_cffi ALREADY passes now — the earlier block has lifted.")
        else:
            print(f"Inconclusive: probe1={v1!r}, probe2={v2!r}. See bodies above.")
    else:
        print("\n(Set CF_CLEARANCE and CF_UA env vars to run PROBE 2 — the"
              " definitive cookie-injection test.)")


if __name__ == "__main__":
    main()
