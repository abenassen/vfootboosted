"""Scrape current squad rosters (name + date of birth) from Transfermarkt.

Transfermarkt is the authoritative source for transfers, so its *current* squads
are the freshness benchmark we test SofaScore's rosters against. Unlike SofaScore
it has NO anti-bot layer — a plain HTTPS GET with a browser User-Agent works — so
this is a light ~21-request pass (1 competition page + one squad page per club).

It does NOT touch the DB. It writes one JSON file per club into the cache dir;
the offline ``manage.py match_transfermarkt`` command then reconciles those rosters
against the SofaScore ``Player`` rows by (name, date-of-birth).

    python scrape_transfermarkt_squads.py \
        --competition IT1 --season 2025 \
        --cache-dir /…/historical-data/serie-a/transfermarkt

``--competition`` is the Transfermarkt competition code (Serie A = IT1, Premier
League = GB1, La Liga = ES1, Bundesliga = L1, Ligue 1 = FR1) — so the same script
extends to other leagues. ``--season`` is the start year (2025 = season 25/26).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

BASE = "https://www.transfermarkt.com"
# A real browser UA is REQUIRED — Transfermarkt 403s the default httpx UA, but it
# has no JS/TLS challenge beyond that, so this is all it takes.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Transfermarkt's .com squad table renders DOB as DD/MM/YYYY, e.g. "12/04/1995 (31)".
_DOB_RE = re.compile(r"(\d{2}/\d{2}/\d{4})")
_SPIELER_RE = re.compile(r"/profil/spieler/(\d+)")
_VEREIN_RE = re.compile(r"/verein/(\d+)")


def _parse_dob(text: str) -> str | None:
    """First 'DD/MM/YYYY' in the row (the DOB cell) -> ISO '1995-04-12', or None."""
    m = _DOB_RE.search(text)
    if not m:
        return None
    try:
        from datetime import datetime
        return datetime.strptime(m.group(1), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


class TM:
    def __init__(self, cache_dir: Path, *, min_delay: float, jitter: float,
                 logger=print) -> None:
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.min_delay = min_delay
        self.jitter = jitter
        self.log = logger
        self._last = 0.0
        self._client = httpx.Client(headers=HEADERS, timeout=20.0,
                                    follow_redirects=True)

    def _throttle(self) -> None:
        wait = self.min_delay + random.uniform(0, self.jitter) - (
            time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)

    def _get_html(self, url: str) -> str:
        self._throttle()
        r = self._client.get(url)
        self._last = time.monotonic()
        r.raise_for_status()
        return r.text

    def clubs(self, competition: str, season: int) -> list[dict[str, Any]]:
        """[{id, name, slug, url}] for every club in the competition+season."""
        url = (f"{BASE}/-/startseite/wettbewerb/{competition}"
               f"?saison_id={season}")
        soup = BeautifulSoup(self._get_html(url), "lxml")
        seen: dict[str, dict[str, Any]] = {}
        for a in soup.select("table.items td.hauptlink a[href*='/verein/']"):
            href = a.get("href", "")
            mid = _VEREIN_RE.search(href)
            name = a.get_text(strip=True)
            if not mid or not name:
                continue
            cid = mid.group(1)
            slug = href.strip("/").split("/")[0]
            seen.setdefault(cid, {
                "id": cid, "name": name, "slug": slug,
                "url": f"{BASE}/{slug}/kader/verein/{cid}/saison_id/{season}/plus/1",
            })
        return list(seen.values())

    def squad(self, club: dict[str, Any]) -> list[dict[str, Any]]:
        """Detailed roster rows for one club: name, dob, position, shirt, value."""
        soup = BeautifulSoup(self._get_html(club["url"]), "lxml")
        players: list[dict[str, Any]] = []
        for tr in soup.select("table.items > tbody > tr"):
            link = tr.select_one("a[href*='/profil/spieler/']")
            if not link:
                continue
            pid_m = _SPIELER_RE.search(link.get("href", ""))
            name = link.get_text(strip=True)
            if not pid_m or not name:
                continue
            row_text = tr.get_text(" ", strip=True)
            shirt_el = tr.select_one("td.rueckennummer")
            pos_el = tr.select_one("td.posrela tr + tr td")
            val_el = tr.select_one("td.rechts.hauptlink")
            nat = [img.get("title") for img in tr.select("img.flaggenrahmen")
                   if img.get("title")]
            players.append({
                "tm_id": pid_m.group(1),
                "name": name,
                "dob": _parse_dob(row_text),
                "shirt": (shirt_el.get_text(strip=True) if shirt_el else None),
                "position": (pos_el.get_text(strip=True) if pos_el else None),
                "nationality": nat,
                "market_value": (val_el.get_text(strip=True) if val_el else None),
            })
        return players

    def close(self) -> None:
        self._client.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Scrape Transfermarkt squad rosters.")
    ap.add_argument("--competition", default="IT1",
                    help="TM competition code (Serie A=IT1, PL=GB1, LaLiga=ES1).")
    ap.add_argument("--season", type=int, default=2025,
                    help="Season start year (2025 = 25/26).")
    ap.add_argument("--cache-dir", default="./transfermarkt_cache")
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--jitter", type=float, default=1.5)
    ap.add_argument("--limit", type=int, default=None, help="Max clubs (debug).")
    args = ap.parse_args()

    out = Path(args.cache_dir) / args.competition / str(args.season)
    out.mkdir(parents=True, exist_ok=True)
    tm = TM(out, min_delay=args.delay, jitter=args.jitter)
    try:
        clubs = tm.clubs(args.competition, args.season)
        print(f"{len(clubs)} clubs in {args.competition} {args.season}.")
        total = 0
        for i, club in enumerate(clubs, 1):
            if args.limit and i > args.limit:
                break
            f = out / f"club_{club['id']}.json"
            if f.exists():
                roster = json.loads(f.read_text())["players"]
                print(f"  [{i}/{len(clubs)}] {club['name']}: cached "
                      f"({len(roster)} players)")
                total += len(roster)
                continue
            try:
                roster = tm.squad(club)
            except Exception as exc:  # noqa: BLE001 - skip one bad club, keep going
                print(f"  [{i}/{len(clubs)}] {club['name']}: FAILED "
                      f"{type(exc).__name__}: {exc}")
                continue
            with_dob = sum(1 for p in roster if p["dob"])
            tmp = f.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(
                {"club": club, "players": roster}, ensure_ascii=False, indent=2))
            tmp.replace(f)
            total += len(roster)
            print(f"  [{i}/{len(clubs)}] {club['name']}: {len(roster)} players "
                  f"({with_dob} with DOB)")
        print(f"Done. {total} players across {len(clubs)} clubs "
              f"into {out.resolve()}")
    finally:
        tm.close()


if __name__ == "__main__":
    main()
