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
# A real browser UA is REQUIRED — Transfermarkt 403s the default httpx UA. It used
# to be enough: until 13/08/2026 the origin was bare nginx with no challenge at all.
# It is now behind CloudFront + AWS WAF, which challenges by IP reputation (the
# Linode datacenter IP is on the list, our ~42 requests a day never were the
# trigger), so the UA is necessary and no longer sufficient — see TransfermarktBlocked.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Venti secondi bastano largamente a una pagina rosa (il tempo di risposta normale
# e' sotto il secondo); il tetto serve a non restare appesi, non a dare tempo.
REQUEST_TIMEOUT = 20.0
# Codici che il tempo ripara: coda piena e guasti di server. Tutto il resto e' una
# risposta, e una risposta non si ritenta.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
# Attesa fra un tentativo e l'altro, moltiplicata per il numero del tentativo.
RETRY_BACKOFF = 3.0


class TransfermarktBlocked(RuntimeError):
    """The WAF answered instead of the site — a different animal from a bad page.

    IT LOOKS LIKE SUCCESS, which is why it needs a name. The AWS WAF challenge is
    ``202 Accepted`` with an empty body: a 2xx, so ``raise_for_status`` stays
    quiet, the empty HTML parses into zero clubs, and the caller reads "the
    competition has no teams". On 13/08/2026 that is exactly how the poll failed —
    the only reason it did not close five hundred players' stints as departures
    was the separate ``scraped == 0`` guard downstream.

    Raised, never retried: the retry loop is for what time repairs, and a
    reputation verdict on our exit IP is not that. The orchestrator rotates to
    another exit instead.
    """


# Transfermarkt's .com squad table renders DOB as DD/MM/YYYY, e.g. "12/04/1995 (31)".
_DOB_RE = re.compile(r"(\d{2}/\d{2}/\d{4})")
_SPIELER_RE = re.compile(r"/profil/spieler/(\d+)")
_VEREIN_RE = re.compile(r"/verein/(\d+)")


def _raise_if_challenged(r: httpx.Response) -> None:
    """Turn a WAF verdict into an exception before anyone can mistake it for HTML.

    ``x-amzn-waf-action`` is the header AWS WAF explicitly exposes to the client
    (it is listed in ``access-control-expose-headers`` on the very same response),
    so this reads the site's own statement rather than guessing from the body. The
    403 arm covers the older, plainer refusal.
    """
    if r.headers.get("x-amzn-waf-action"):
        raise TransfermarktBlocked(
            f"WAF {r.headers['x-amzn-waf-action']} su {r.request.url} "
            f"(HTTP {r.status_code}, {len(r.content)}b)")
    if r.status_code == 403:
        raise TransfermarktBlocked(f"HTTP 403 su {r.request.url}")


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
                 logger=print, attempts: int = 3) -> None:
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.min_delay = min_delay
        self.jitter = jitter
        self.log = logger
        self.attempts = max(1, attempts)
        self._last = 0.0
        self._client = httpx.Client(headers=HEADERS, timeout=REQUEST_TIMEOUT,
                                    follow_redirects=True)

    def _throttle(self) -> None:
        wait = self.min_delay + random.uniform(0, self.jitter) - (
            time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)

    def _get_html(self, url: str) -> str:
        """GET con ritentativo sui guasti passeggeri.

        PERCHE'. L'11/08/2026 tre club su venti sono andati persi per
        ``ReadTimeout``, e nello stesso giro le richieste RIUSCITE stavano
        rispondendo in 10-15 secondi contro il decimo di secondo abituale: non un
        blocco (ogni risposta arrivata era 200) ma Transfermarkt lento in quella
        finestra, e il tetto fisso ha tagliato i tre piu' lenti. Senza ritentativo
        un singolo timeout costa il club per dodici ore.

        E costa molto piu' del club: un club mancante toglie fiducia alla sua
        fotografia, quindi le partenze di QUELLA rosa non vengono chiuse. Il
        ritentativo e' percio' la cosa piu' economica che tenga insieme il dato.

        Si ritenta solo su cio' che il tempo ripara — timeout, guasti di
        trasporto, 429 e 5xx. Un 404 e' una risposta, non un guasto: ritentarlo
        vuol dire solo aspettare tre volte per la stessa notizia.
        """
        last: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            self._throttle()
            try:
                r = self._client.get(url)
                self._last = time.monotonic()
                _raise_if_challenged(r)
                r.raise_for_status()
                return r.text
            except httpx.HTTPStatusError as exc:
                self._last = time.monotonic()
                if exc.response.status_code not in RETRY_STATUS:
                    raise
                last = exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                # Il timeout non passa da ``_client.get`` con un tempo di risposta,
                # quindi ``_last`` va spostato a mano: senza, il throttle crede che
                # l'ultima richiesta sia vecchia di venti secondi e riparte subito.
                self._last = time.monotonic()
                last = exc
            if attempt < self.attempts:
                pause = RETRY_BACKOFF * attempt + random.uniform(0, self.jitter)
                self.log(f"  ritento fra {pause:.1f}s "
                         f"({attempt}/{self.attempts - 1}): "
                         f"{type(last).__name__} su {url}")
                time.sleep(pause)
        raise last  # type: ignore[misc]  # attempts >= 1, quindi last e' valorizzato

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
    ap.add_argument("--attempts", type=int, default=3,
                    help="Tentativi per pagina sui guasti passeggeri (default 3).")
    args = ap.parse_args()

    out = Path(args.cache_dir) / args.competition / str(args.season)
    out.mkdir(parents=True, exist_ok=True)
    tm = TM(out, min_delay=args.delay, jitter=args.jitter,
            attempts=args.attempts)
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
