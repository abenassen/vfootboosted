"""Controlled SofaScore API client (curl_cffi) for high-volume batch pulls.

SofaScore blocks plain HTTP at the TLS-fingerprint (JA3/Cloudflare) level, so
this client uses ``curl_cffi`` with Chrome impersonation. Unlike a browser-based
scraper it gives us full control of the request rate, which is what a
~13k-request season pull needs to avoid getting rate-blocked:

* a throttle BEFORE EVERY request (the per-player heatmap calls included),
* an on-disk cache keyed per endpoint, so a re-run resumes mid-match and never
  re-fetches a response,
* retry with exponential backoff when a response comes back empty / non-JSON
  (Cloudflare's soft block) or 5xx,
* after retries are exhausted it raises ``SofaScoreBlocked`` so the caller can
  STOP cleanly (re-run later resumes from cache) instead of cascading failures.

Install the optional dep yourself: ``pip install curl_cffi``.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any

SERIE_A_UNIQUE_TOURNAMENT_ID = 23
API_BASE = "https://api.sofascore.com"
SITE_BASE = "https://www.sofascore.com"

_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": SITE_BASE + "/",
    "Origin": SITE_BASE,
}


class SofaScoreError(RuntimeError):
    """Generic client error."""


class SofaScoreBlocked(SofaScoreError):
    """Raised when SofaScore keeps refusing — signal to stop the batch."""


class SofaScoreClient:
    def __init__(
        self,
        cache_dir: Path,
        *,
        min_delay: float = 1.5,
        jitter: float = 1.0,
        max_retries: int = 7,
        impersonate: str = "chrome",
        timeout: float = 20.0,
        tournament_id: int = SERIE_A_UNIQUE_TOURNAMENT_ID,
        logger=None,
    ) -> None:
        # curl_cffi is imported lazily on the first real network request, so a
        # fully-cached run (e.g. importing on the laptop from a Pi-warmed cache)
        # needs neither the dependency nor network access.
        self._session = None
        self._impersonate = impersonate
        self._timeout = timeout
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._min_delay = min_delay
        self._jitter = jitter
        self._max_retries = max_retries
        self._tid = tournament_id
        self._log = logger or (lambda msg: None)
        self._last_request = 0.0

    # -- low level -------------------------------------------------------

    def _cache_path(self, path: str) -> Path:
        safe = path.strip("/").replace("/", "_")
        return self._cache_dir / f"{safe}.json"

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        wait = self._min_delay + random.uniform(0.0, self._jitter) - elapsed
        if wait > 0:
            time.sleep(wait)

    def _ensure_session(self):
        if self._session is None:
            try:
                from curl_cffi import requests as cffi_requests  # lazy, optional
            except ImportError as exc:  # pragma: no cover - depends on env
                raise SofaScoreError(
                    "curl_cffi is not installed. Run: pip install curl_cffi") from exc
            self._session = cffi_requests.Session()
        return self._session

    def _raw_get(self, path: str) -> Any:
        resp = self._ensure_session().get(API_BASE + path, headers=_HEADERS,
                                          impersonate=self._impersonate, timeout=self._timeout)
        self._last_request = time.monotonic()
        if resp.status_code == 404:
            return None  # legitimately absent (e.g. a match with no shotmap)
        if resp.status_code != 200:
            raise SofaScoreBlocked(f"HTTP {resp.status_code}")
        text = resp.text or ""
        if not text.strip():
            raise SofaScoreBlocked("empty body (soft block)")
        try:
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - blocked pages aren't JSON
            raise SofaScoreBlocked(f"non-JSON body: {str(exc)[:60]}") from exc

    def get(self, path: str) -> Any:
        """Fetch ``path`` with cache, throttle, and retry/backoff.

        Returns decoded JSON (or ``None`` for a 404). Raises ``SofaScoreBlocked``
        after exhausting retries so the batch can stop and resume later.
        """
        cache_path = self._cache_path(path)
        if cache_path.exists():
            with cache_path.open("r", encoding="utf-8") as fh:
                return json.load(fh)

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            self._throttle()
            try:
                data = self._raw_get(path)
            except SofaScoreBlocked as exc:
                last_exc = exc
                # Cloudflare rate-blocks are time-based (often 15-60 min). Be
                # patient enough to ride one out within a single unattended run.
                backoff = min(600.0, 20.0 * (2 ** attempt)) + random.uniform(0, 5)
                self._log(f"  blocked on {path} ({exc}); backoff {backoff:.0f}s "
                          f"[{attempt + 1}/{self._max_retries}]")
                time.sleep(backoff)
                continue
            tmp = cache_path.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(data, fh)
            tmp.replace(cache_path)
            return data
        raise SofaScoreBlocked(f"giving up on {path} after {self._max_retries} tries: {last_exc}")

    # -- season / schedule ----------------------------------------------

    def get_valid_seasons(self) -> dict[str, int]:
        data = self.get(f"/api/v1/unique-tournament/{self._tid}/seasons")
        return {str(s.get("year")): int(s.get("id")) for s in data.get("seasons", [])}

    def _season_id_for_year(self, year: str) -> int:
        seasons = self.get_valid_seasons()
        if year not in seasons:
            raise SofaScoreError(f"Year {year!r} not in valid seasons: {sorted(seasons)}")
        return seasons[year]

    def get_match_dicts(self, year: str) -> list[dict[str, Any]]:
        """All event dicts for the season (raw SofaScore shape), via rounds."""
        season_id = self._season_id_for_year(year)
        rounds_data = self.get(
            f"/api/v1/unique-tournament/{self._tid}/season/{season_id}/rounds")
        rounds = sorted({r.get("round") for r in rounds_data.get("rounds", [])
                         if r.get("round") is not None})
        events: list[dict[str, Any]] = []
        for rnd in rounds:
            data = self.get(
                f"/api/v1/unique-tournament/{self._tid}/season/{season_id}"
                f"/events/round/{rnd}")
            events.extend(data.get("events", []))
        return events

    # -- per-match data --------------------------------------------------

    def player_stats_records(self, match_id: int) -> list[dict[str, Any]]:
        """Flattened per-player records: player fields + stat keys + side."""
        data = self.get(f"/api/v1/event/{match_id}/lineups")
        if not data:
            return []
        records: list[dict[str, Any]] = []
        for side_key in ("home", "away"):
            team = data.get(side_key) or {}
            for entry in team.get("players", []):
                stats = entry.get("statistics") or {}
                if not stats:
                    continue
                player = entry.get("player") or {}
                rec = {**player, **stats}
                rec["side"] = side_key
                rec["substitute"] = entry.get("substitute")
                rec["position"] = entry.get("position") or player.get("position")
                records.append(rec)
        return records

    def shots_records(self, match_id: int) -> list[dict[str, Any]]:
        data = self.get(f"/api/v1/event/{match_id}/shotmap")
        if not data:
            return []
        return data.get("shotmap", [])

    def incidents_records(self, match_id: int) -> list[dict[str, Any]]:
        """Match incidents: goals (scorer+assist), cards, subs, penalties, VAR.

        These are NOT in the /lineups statistics — cards in particular live only
        here. One request per match (cheap vs the per-player heatmaps).
        """
        data = self.get(f"/api/v1/event/{match_id}/incidents")
        if not data:
            return []
        return data.get("incidents", [])

    def heatmap(self, match_id: int, player_id: int) -> list[dict[str, Any]]:
        data = self.get(f"/api/v1/event/{match_id}/player/{player_id}/heatmap")
        if not data:
            return []
        return data.get("heatmap", [])
