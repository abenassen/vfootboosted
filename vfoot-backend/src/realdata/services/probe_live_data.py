"""Measure SofaScore's live + post-match data availability and stabilisation.

Two questions drive vfoot's in-season behaviour and neither can be answered from a
finished season's cache:
  1. DURING a match, what's already published — lineups, goals/cards (incidents),
     team statistics, shotmap, per-player heatmaps? (-> what a *provisional* live
     fantasy estimate can use.)
  2. AFTER the final whistle, how long until the COMPLETE data we score on
     (shotmap + per-player heatmaps + statistics) is present AND stops changing?
     (-> when a matchday can actually be computed as final.)

SofaScore's publishing policy is the same across competitions, so this can run NOW
on any live football match (World Cup, friendlies…), not just Serie A. It polls the
match's endpoints on an interval, fingerprints each one, and records first-seen and
stable-since timestamps. Output: a compact live line per poll + a JSONL log to
analyse afterwards.

Uses the browser transport's UNCACHED `_raw_get` (the cache would freeze a live
response). USER runs it — it's network.

    # 1) find something live right now:
    python probe_live_data.py --list --headful --channel chrome
    # 2) probe one match through full-time and ~2h beyond:
    python probe_live_data.py --match-id 13950001 --interval 90 \
        --post-final-minutes 120 --log live_probe.jsonl --headful --channel chrome
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from sofascore_browser_client import SofaScoreBrowserClient
from sofascore_client import SofaScoreBlocked


def _fetch(client, path):
    """Uncached GET. Returns (data, None) or (None, 'reason')."""
    try:
        return client._raw_get(path), None
    except SofaScoreBlocked as exc:
        return None, f"blocked:{exc}"
    except Exception as exc:  # noqa: BLE001 - one bad endpoint shouldn't stop the poll
        return None, f"{type(exc).__name__}:{str(exc)[:50]}"


def _metrics(client, mid):
    """Pull every endpoint once; return a dict of presence + size fingerprints."""
    m = {}
    ev, err = _fetch(client, f"/api/v1/event/{mid}")
    event = (ev or {}).get("event", ev) or {}
    st = (event.get("status") or {})
    m["status_type"] = st.get("type")
    m["status_desc"] = st.get("description")
    m["score"] = f"{(event.get('homeScore') or {}).get('current','?')}-" \
                 f"{(event.get('awayScore') or {}).get('current','?')}"
    m["start_ts"] = event.get("startTimestamp")
    m["_event_err"] = err

    lu, err = _fetch(client, f"/api/v1/event/{mid}/lineups")
    sample_pid = None
    if lu:
        players = [p for side in ("home", "away") for p in (lu.get(side) or {}).get("players", [])]
        m["lineups_confirmed"] = bool(lu.get("confirmed"))
        m["lineups_players"] = len(players)
        m["lineups_with_stats"] = sum(1 for p in players if p.get("statistics"))
        starters = [p for p in players if not p.get("substitute")]
        if starters:
            sample_pid = (starters[0].get("player") or {}).get("id")
    else:
        m["lineups_confirmed"] = False
        m["lineups_players"] = 0
        m["lineups_with_stats"] = 0
    m["_lineups_err"] = err

    inc, err = _fetch(client, f"/api/v1/event/{mid}/incidents")
    items = (inc or {}).get("incidents", []) if inc else []
    m["incidents"] = len(items)
    m["goals"] = sum(1 for x in items if x.get("incidentType") == "goal")
    m["cards"] = sum(1 for x in items if x.get("incidentType") == "card")
    m["_incidents_err"] = err

    stat, err = _fetch(client, f"/api/v1/event/{mid}/statistics")
    groups = (stat or {}).get("statistics", []) if stat else []
    m["stats_present"] = bool(groups)
    m["stats_items"] = sum(len(g.get("groups", [])) for g in groups) if groups else 0
    m["_stats_err"] = err

    shot, err = _fetch(client, f"/api/v1/event/{mid}/shotmap")
    m["shots"] = len((shot or {}).get("shotmap", [])) if shot else 0
    m["_shots_err"] = err

    m["sample_pid"] = sample_pid
    if sample_pid:
        hm, err = _fetch(client, f"/api/v1/event/{mid}/player/{sample_pid}/heatmap")
        m["heatmap_points"] = len((hm or {}).get("heatmap", [])) if hm else 0
        m["_heatmap_err"] = err
    else:
        m["heatmap_points"] = 0
        m["_heatmap_err"] = "no-sample-player"
    return m


# the size fingerprints we watch for first-appearance + stabilisation
WATCH = ["lineups_confirmed", "lineups_players", "lineups_with_stats",
         "incidents", "goals", "cards", "stats_present", "stats_items",
         "shots", "heatmap_points"]


def _list_live(client):
    data, err = _fetch(client, "/api/v1/sport/football/events/live")
    if not data:
        print(f"Could not fetch live list: {err}")
        return
    events = data.get("events", [])
    print(f"{len(events)} live football matches:")
    for e in events:
        st = (e.get("status") or {})
        tour = ((e.get("tournament") or {}).get("name", "?"))
        print(f"  id={e.get('id'):<10} {st.get('description',''):<12} "
              f"{(e.get('homeTeam') or {}).get('name','?')} "
              f"{(e.get('homeScore') or {}).get('current','')}-"
              f"{(e.get('awayScore') or {}).get('current','')} "
              f"{(e.get('awayTeam') or {}).get('name','?')}   [{tour}]")


def main() -> None:
    ap = argparse.ArgumentParser(description="Probe SofaScore live/post-match data timing.")
    ap.add_argument("--list", action="store_true", help="List current live matches and exit.")
    ap.add_argument("--match-id", type=int, default=None)
    ap.add_argument("--interval", type=float, default=90.0, help="Seconds between polls.")
    ap.add_argument("--max-hours", type=float, default=5.0)
    ap.add_argument("--post-final-minutes", type=float, default=120.0,
                    help="Keep polling this long after status becomes 'finished'.")
    ap.add_argument("--log", default="live_probe.jsonl")
    ap.add_argument("--cache-dir", default="./live_probe_cache")
    ap.add_argument("--chromium-path", default=None)
    ap.add_argument("--channel", default=None)
    ap.add_argument("--headful", action="store_true")
    args = ap.parse_args()

    client = SofaScoreBrowserClient(
        Path(args.cache_dir), min_delay=0.5, logger=print,
        headless=not args.headful, chromium_path=args.chromium_path, channel=args.channel)

    try:
        if args.list or args.match_id is None:
            _list_live(client)
            if args.match_id is None:
                print("\nPick one and re-run with --match-id <id>.")
            return

        mid = args.match_id
        log = open(args.log, "a", encoding="utf-8")
        first_seen, stable_since, last_val = {}, {}, {}
        t0 = time.time()
        finished_at = None
        poll = 0
        print(f"Probing match {mid}; interval {args.interval}s. Ctrl-C to stop.")
        while True:
            poll += 1
            now = time.time()
            m = _metrics(client, mid)
            # track first-seen (value becomes non-zero/true) + stability (unchanged)
            for k in WATCH:
                v = m.get(k)
                truthy = bool(v) if isinstance(v, bool) else (v not in (0, None))
                if truthy and k not in first_seen:
                    first_seen[k] = now
                if last_val.get(k) != v:
                    stable_since[k] = now
                last_val[k] = v
            rec = {"t": now, "rel_s": round(now - t0), "poll": poll, **m,
                   "stable_s": {k: round(now - stable_since.get(k, now)) for k in WATCH}}
            log.write(json.dumps(rec, ensure_ascii=False) + "\n")
            log.flush()

            hm_stable = round((now - stable_since.get("heatmap_points", now)) / 60)
            sh_stable = round((now - stable_since.get("shots", now)) / 60)
            print(f"[+{rec['rel_s']//60:>3}m] {m['status_type'] or '?':<10} "
                  f"{m['status_desc'] or '':<11} {m['score']:<7} | "
                  f"lu:{'C' if m['lineups_confirmed'] else '-'} p={m['lineups_players']:<2} "
                  f"st={m['lineups_with_stats']:<2} | inc={m['incidents']}"
                  f"(g{m['goals']},c{m['cards']}) | stat={'Y' if m['stats_present'] else '-'}"
                  f"({m['stats_items']}) | shots={m['shots']}(±{sh_stable}m) | "
                  f"hm={m['heatmap_points']}(±{hm_stable}m)")

            if m["status_type"] == "finished" and finished_at is None:
                finished_at = now
                print(f"  -> FULL TIME detected; polling {args.post_final_minutes:.0f} "
                      f"more minutes to catch data stabilisation.")
            if finished_at and (now - finished_at) >= args.post_final_minutes * 60:
                print("  -> post-final window elapsed; stopping.")
                break
            if (now - t0) >= args.max_hours * 3600:
                print("  -> max-hours reached; stopping.")
                break
            time.sleep(args.interval)

        log.close()
        print(f"\nDone. Per-metric first-seen (minutes from probe start):")
        for k in WATCH:
            if k in first_seen:
                print(f"  {k:<20} first @ +{round((first_seen[k]-t0)/60)}m")
        print(f"Full timeline in {Path(args.log).resolve()}")
    except KeyboardInterrupt:
        print("\nInterrupted — partial log kept; re-run --match-id to resume a new session.")
    finally:
        if hasattr(client, "close"):
            client.close()


if __name__ == "__main__":
    main()
