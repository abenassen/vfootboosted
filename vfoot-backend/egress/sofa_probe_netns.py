"""Compact SofaScore probe for the VPN sweep. Runs inside a netns; prints two
parseable lines: EXITIP=<ip>  and  VERDICT=<PASS|CHALLENGE|EMPTY|HTTP_n|EXC ...>.

PASS requires the endpoints the scraper actually depends on (a real match's
lineups), not just the light seasons list — a soft block often lets the cheap
endpoint through and challenges the heavy ones."""
from __future__ import annotations
import json, urllib.request
from curl_cffi import requests as cffi

API = "https://api.sofascore.com"
SITE = "https://www.sofascore.com"
H = {"Accept": "*/*", "Accept-Language": "en-US,en;q=0.9",
     "Referer": SITE + "/", "Origin": SITE}
MARKERS = ["just a moment", "challenge-platform", "__cf_chl", "cf_chl_opt",
           "attention required", "enable javascript and cookies"]


def exit_ip():
    try:
        return json.load(urllib.request.urlopen("https://api.ipify.org?format=json", timeout=8))["ip"]
    except Exception:
        return "?"


def get(s, url):
    try:
        r = s.get(url, headers=H, impersonate="chrome", timeout=20)
    except Exception as e:
        return None, f"EXC {type(e).__name__}"
    body = r.text or ""
    low = body.lower()
    if r.status_code == 200 and body.strip():
        if any(m in low for m in MARKERS):
            return r, "CHALLENGE"
        return r, "OK"
    if any(m in low for m in MARKERS):
        return r, "CHALLENGE"
    if r.status_code == 200:
        return r, "EMPTY"
    return r, f"HTTP_{r.status_code}"


def main():
    print(f"EXITIP={exit_ip()}")
    s = cffi.Session()
    r, v = get(s, f"{API}/api/v1/unique-tournament/23/season/76457/rounds")
    if v != "OK":
        print(f"VERDICT={v} (rounds)"); return
    r, v = get(s, f"{API}/api/v1/unique-tournament/23/season/76457/events/round/1")
    mid = None
    if v == "OK":
        try:
            mid = r.json()["events"][0]["id"]
        except Exception:
            pass
    if mid:
        r, v = get(s, f"{API}/api/v1/event/{mid}/lineups")
        if v != "OK":
            print(f"VERDICT={v} (lineups)"); return
    print("VERDICT=PASS")


if __name__ == "__main__":
    main()
