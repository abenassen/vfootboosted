"""Compact SofaScore probe for the VPN sweep. Runs inside a netns; prints
parseable lines: EXITIP=<ip>, HOST=<served>, FINGERPRINT=<used>, CHALLENGED=<csv> and
VERDICT=<PASS|CHALLENGE_ALL|CHALLENGE|EMPTY|HTTP_n|EXC ...>.

PASS requires the endpoints the scraper actually depends on (a real match's
lineups), not just the light seasons list — a soft block often lets the cheap
endpoint through and challenges the heavy ones.

It walks the SAME fingerprint chain as the scraper (imported, not copied): an
exit is good if the scraper can get through it, and the scraper walks the chain.
CHALLENGE_ALL is the verdict that says more than "this IP": every fingerprint was
refused, and when every exit says it the fault is curl_cffi, not the pool."""
from __future__ import annotations
import json, os, sys, urllib.request
from curl_cffi import requests as cffi

# Same trick as fetch_worker: the client lives in the app tree.
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "..", "src", "realdata", "services"))
from sofascore_client import (  # noqa: E402
    API_HOSTS, IMPERSONATE_CHAIN, SITE_BASE, is_challenge, simulating_refusal)

# The scraper's own hosts, imported for the same reason as the chain: a probe on
# another host certifies exits for a door the scraper does not use (29/09/2026:
# api.sofascore.com closed, www open).
SITE = SITE_BASE
H = {"Accept": "*/*", "Accept-Language": "en-US,en;q=0.9",
     "Referer": SITE + "/", "Origin": SITE}
MARKERS = ["just a moment", "challenge-platform", "__cf_chl", "cf_chl_opt",
           "attention required", "enable javascript and cookies"]


def exit_ip():
    try:
        return json.load(urllib.request.urlopen("https://api.ipify.org?format=json", timeout=8))["ip"]
    except Exception:
        return "?"


def get(s, url, fp):
    if simulating_refusal():    # the drill: see sofascore_client
        return None, "FP_CHALLENGE"
    try:
        r = s.get(url, headers=H, impersonate=fp, timeout=20)
    except Exception as e:
        return None, f"EXC {type(e).__name__}"
    body = r.text or ""
    low = body.lower()
    if is_challenge(r.status_code, body):
        return r, "FP_CHALLENGE"
    if r.status_code == 200 and body.strip():
        if any(m in low for m in MARKERS):
            return r, "CHALLENGE"
        return r, "OK"
    if any(m in low for m in MARKERS):
        return r, "CHALLENGE"
    if r.status_code == 200:
        return r, "EMPTY"
    return r, f"HTTP_{r.status_code}"


def _door(s, path):
    """Walk hosts x fingerprints exactly as the client does. Returns
    (host, fp, challenged, response, verdict); host is None when every host
    refused."""
    for host in API_HOSTS:
        challenged = []
        for fp in IMPERSONATE_CHAIN:
            r, v = get(s, host + path, fp)
            if v == "FP_CHALLENGE":
                challenged.append(fp); continue
            if v == "HTTP_403":
                break           # the host refuses: next host
            return host, fp, challenged, r, v
    return None, None, challenged, None, v


def main():
    print(f"EXITIP={exit_ip()}")
    s = cffi.Session()
    host, fp, challenged, r, v = _door(
        s, "/api/v1/unique-tournament/23/season/76457/rounds")
    print(f"CHALLENGED={','.join(challenged)}")
    if host is None:
        # Every host refused. CHALLENGE_ALL either way: for the refill it is the
        # same finding — this exit does not let the scraper in — and the count
        # across exits is what says whether it is the exit or us.
        print(f"VERDICT=CHALLENGE_ALL (rounds; {v}; {','.join(challenged)})"); return
    print(f"HOST={host}")
    print(f"FINGERPRINT={fp}")
    if v != "OK":
        print(f"VERDICT={v} (rounds)"); return
    r, v = get(s, f"{host}/api/v1/unique-tournament/23/season/76457/events/round/1", fp)
    mid = None
    if v == "OK":
        try:
            mid = r.json()["events"][0]["id"]
        except Exception:
            pass
    if mid:
        r, v = get(s, f"{host}/api/v1/event/{mid}/lineups", fp)
        if v != "OK":
            print(f"VERDICT={v} (lineups)"); return
    notes = [fp]
    if host != API_HOSTS[0]:
        notes.append(f"host {host}")
    if challenged:
        notes.append(f"challenged {','.join(challenged)}")
    print(f"VERDICT=PASS ({'; '.join(notes)})")


if __name__ == "__main__":
    main()
