"""SofaScore probe for the BROWSER pool. Runs inside a netns; prints EXITIP=<ip>
and VERDICT=<PASS (browser)|BLOCKED ...|EXC ...>, like the curl probe.

A pool of its own because the question is different: an exit the browser gets
through is no evidence that curl does, and the other way round. This one is only
asked for when curl is refused everywhere (sofascore_egress.refill_browser_pool),
because every probe boots a Chromium: ten seconds and ~200 MB on the Linode.

Same endpoints as the curl probe — the rounds, a round's events, a real match's
lineups — through the same client the fallback worker uses."""
from __future__ import annotations
import json, os, sys, tempfile, urllib.request
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "..", "src", "realdata", "services"))
from sofascore_client import SofaScoreBlocked, SofaScoreError  # noqa: E402
from sofascore_browser_client import SofaScoreBrowserClient  # noqa: E402

SEASON = "/api/v1/unique-tournament/23/season/76457"


def exit_ip():
    try:
        return json.load(urllib.request.urlopen("https://api.ipify.org?format=json", timeout=8))["ip"]
    except Exception:
        return "?"


def main():
    print(f"EXITIP={exit_ip()}")
    with tempfile.TemporaryDirectory() as tmp, \
            SofaScoreBrowserClient(Path(tmp), min_delay=0.5, jitter=0.5,
                                   max_retries=1) as c:
        try:
            c.get(f"{SEASON}/rounds")
            events = (c.get(f"{SEASON}/events/round/1") or {}).get("events") or []
            if events:
                c.get(f"/api/v1/event/{events[0]['id']}/lineups")
        except SofaScoreBlocked as exc:
            print(f"VERDICT=BLOCKED ({str(exc)[:80]})"); return
        except SofaScoreError as exc:
            # No playwright, no Chromium: not this exit's fault, and not a PASS.
            print(f"VERDICT=UNAVAILABLE ({str(exc)[:80]})"); return
        except Exception as exc:  # noqa: BLE001 - a crashed browser is not a pass
            print(f"VERDICT=EXC {type(exc).__name__}"); return
    print("VERDICT=PASS (browser)")


if __name__ == "__main__":
    main()
