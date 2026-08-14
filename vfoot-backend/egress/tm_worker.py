"""ONE Transfermarkt page — runs INSIDE the egress netns, so it exits via the
pinned Surfshark IP. The twin of fetch_worker.py, with one deliberate difference:
this worker fetches a SINGLE page per invocation and the orchestrator loops.

WHY ONE PAGE. The pages are spaced a minute or two apart to protect the shared
VPN exit, so a whole scrape spans half an hour. A worker that fetched all twenty
clubs in one call would hold the netns for that entire half hour, and the tick —
which needs the same namespace every sixty seconds — would starve through the
live window. Splitting it lets the orchestrator drop the tunnel between pages, so
the wait costs nothing to anyone else.

It does NOT touch the DB. It writes the same files the in-process scraper wrote,
which is what lets the Django import on the other side stay unchanged:

    clubs.json        the competition's club list  (--mode clubs)
    club_<id>.json    {"club": ..., "players": [...]}  (--mode squad)

Exit codes let the root orchestrator react:
  0 = page fetched and written
  3 = Transfermarkt blocked this IP  -> orchestrator demotes it and rotates
  1 = other error (a real 404, a parse failure) -> not an IP problem

  python tm_worker.py --mode clubs --competition IT1 --season 2026 --out DIR
  python tm_worker.py --mode squad --club '<json>' --season 2026 --out DIR
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "..", "src", "realdata", "services"))
from scrape_transfermarkt_squads import TM, TransfermarktBlocked   # noqa: E402


def _write(path: Path, payload) -> None:
    """Rename into place: the orchestrator may die between pages (a rotation, a
    kill), and a half-written club file would import as a half squad — which reads
    as a dozen departures rather than as the crash it was."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["clubs", "squad"], required=True)
    ap.add_argument("--competition", default="IT1")
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--out", required=True, help="cache dir to write into")
    ap.add_argument("--club", help="the club dict as JSON (--mode squad)")
    ap.add_argument("--attempts", type=int, default=3)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    # min_delay=0: the ORCHESTRATOR owns the spacing, and it spaces by minutes.
    # Throttling again in here would only add to a gap that is already generous,
    # while holding the tunnel open for the extra seconds.
    tm = TM(out, min_delay=0, jitter=0, attempts=args.attempts,
            logger=lambda *_: None)
    try:
        if args.mode == "clubs":
            clubs = tm.clubs(args.competition, args.season)
            _write(out / "clubs.json", clubs)
            print(f"{len(clubs)} club elencati")
            return 0 if clubs else 1

        club = json.loads(args.club or "{}")
        if not club.get("id"):
            print("--club senza id", file=sys.stderr); return 1
        roster = tm.squad(club)
        _write(out / f"club_{club['id']}.json",
               {"club": club, "players": roster})
        with_dob = sum(1 for p in roster if p.get("dob"))
        print(f"{len(roster)} giocatori ({with_dob} con data di nascita)")
        return 0
    except TransfermarktBlocked as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:                                     # noqa: BLE001
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        tm.close()


if __name__ == "__main__":
    sys.exit(main())
