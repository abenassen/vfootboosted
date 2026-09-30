"""Browser transport for SofaScore — real Chromium TLS via Playwright.

SofaScore blocks at the TLS-fingerprint level: after ~1k requests it flags
``curl_cffi``'s JA3 (every Chrome impersonation target gets a 403
``{"reason":"challenge"}``), while real Chrome from the SAME IP passes. So the
robust transport is a headless Chromium — its TLS handshake is genuine Chrome,
indistinguishable from the millions of real users SofaScore can't block.

This subclasses ``SofaScoreClient`` and overrides ONLY the transport
(``_ensure_session`` + ``_raw_get``); the cache / throttle / backoff / resume
logic in the parent's ``get()`` is reused unchanged. So a Pi-warmed cache is
still imported offline on the laptop exactly as before.

Install on the Pi (64-bit Raspberry Pi OS):

    pip install playwright
    playwright install chromium
    sudo playwright install-deps      # system libs; needs sudo

If the bundled Chromium won't run (e.g. 32-bit OS), install the system browser
(``sudo apt install chromium``) and pass ``--chromium-path /usr/bin/chromium``.
"""

from __future__ import annotations

import json
import time

# Works both as a Django package module (realdata.services.*) and as a standalone
# script run from this directory (the probe_*.py helpers, the egress worker).
# When the standalone module is ALREADY loaded it wins: the egress worker catches
# ``sofascore_client.SofaScoreBlocked``, and the same class imported under the
# package name would be a different class it cannot catch — a browser block would
# surface as an unexpected error and the orchestrator would not rotate.
import sys

if "sofascore_client" in sys.modules:
    from sofascore_client import (
        API_BASE,
        SofaScoreBlocked,
        SofaScoreClient,
        SofaScoreError,
        SITE_BASE,
    )
else:
    try:
        from realdata.services.sofascore_client import (
            API_BASE,
            SofaScoreBlocked,
            SofaScoreClient,
            SofaScoreError,
            SITE_BASE,
        )
    except ModuleNotFoundError:
        from sofascore_client import (
            API_BASE,
            SofaScoreBlocked,
            SofaScoreClient,
            SofaScoreError,
            SITE_BASE,
        )

# Where the page SITS while we fetch. The requests are in-page ``fetch()`` calls,
# and all they need from the page is its ORIGIN (www.sofascore.com: cookies, no
# CORS) — any page of the site gives that. The home is needed once, because its
# own JavaScript is what produces the ``x-requested-with`` token; after that,
# staying on it costs a quarter of the Linode's only CPU for as long as the page
# lives (measured 30/09/2026: 7.6 s of CPU every 30 s on the home, 0.2 s here), and
# on a cold run the requests queued behind its loading took 23 s for four. So:
# token from the home, then here.
LIGHT_PAGE = SITE_BASE + "/robots.txt"
# Nothing the token depends on: scripts must run, the rest is weight. Measured
# with the move to LIGHT_PAGE: a cold run from ~28 s and ~15 s of CPU to ~6 s and
# ~5 s.
_SKIPPED = ("image", "font", "media", "stylesheet")

# A normal desktop Chrome UA (no "HeadlessChrome" token).
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")


class SofaScoreBrowserClient(SofaScoreClient):
    def __init__(self, cache_dir, *, headless: bool = True,
                 chromium_path: str | None = None,
                 channel: str | None = None, **kwargs) -> None:
        super().__init__(cache_dir, **kwargs)
        self._headless = headless
        self._chromium_path = chromium_path
        self._channel = channel  # e.g. "chrome" to drive real Google Chrome
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None
        # SofaScore signs every API request with an `x-requested-with` header
        # (a short build token, e.g. "725c6f"). Without it the API returns
        # 403 {"reason":"challenge"} even with a real browser + cookies. We
        # capture the live value off the site's own requests and replay it.
        self._xrw: str | None = None

    # -- transport overrides --------------------------------------------

    def _ensure_session(self):
        if self._page is not None:
            return self._page
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - depends on env
            raise SofaScoreError(
                "playwright is not installed. Run: pip install playwright && "
                "playwright install chromium") from exc

        self._pw = sync_playwright().start()
        launch_kwargs = {
            "headless": self._headless,
            "args": ["--disable-blink-features=AutomationControlled",
                     "--no-sandbox"],
        }
        if self._chromium_path:
            launch_kwargs["executable_path"] = self._chromium_path
        if self._channel:
            launch_kwargs["channel"] = self._channel
        self._browser = self._pw.chromium.launch(**launch_kwargs)
        self._ctx = self._browser.new_context(
            user_agent=_UA,
            locale="en-US",
            viewport={"width": 1280, "height": 800},
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": SITE_BASE + "/",
            },
        )
        self._ctx.route("**/*", lambda route: route.abort()
                        if route.request.resource_type in _SKIPPED
                        else route.continue_())
        self._page = self._ctx.new_page()
        # Capture the x-requested-with token from the site's own /api/v1/ XHRs.
        def _grab_xrw(req):
            try:
                if "/api/v1/" in req.url and "sofascore.com" in req.url:
                    v = req.headers.get("x-requested-with")
                    if v:
                        self._xrw = v
            except Exception:  # noqa: BLE001 - listener must never throw
                pass
        self._page.on("request", _grab_xrw)
        self._capture_token()
        return self._page

    def _capture_token(self) -> None:
        """Load the site so its own JS fires API calls, then read the token."""
        try:
            self._page.goto(SITE_BASE + "/", wait_until="domcontentloaded",
                            timeout=int(self._timeout * 1000))
        except Exception as exc:  # noqa: BLE001 - warm-up is best-effort
            self._log(f"  (warm-up nav failed, continuing: {type(exc).__name__})")
        # The homepage fires several /api/v1/ XHRs within a second or two.
        for _ in range(80):
            if self._xrw:
                break
            self._page.wait_for_timeout(250)
        if self._xrw:
            self._log(f"  captured x-requested-with token: {self._xrw}")
        else:
            self._log("  !! could not capture x-requested-with token "
                      "(site made no API calls?) — requests will likely 403")
        try:
            self._page.goto(LIGHT_PAGE, wait_until="domcontentloaded",
                            timeout=int(self._timeout * 1000))
        except Exception as exc:  # noqa: BLE001 - the home still works, just heavier
            self._log(f"  (could not move to {LIGHT_PAGE}: {type(exc).__name__})")

    def _raw_get(self, path: str):
        page = self._ensure_session()
        from playwright.sync_api import Error as PWError

        # SofaScore moved its data API from api.sofascore.com to the SAME-ORIGIN
        # www.sofascore.com/api/v1/... and now requires the x-requested-with
        # token header. So issue an in-page fetch from the www document (cookies
        # flow automatically, no CORS) carrying the captured token.
        if not self._xrw:
            self._capture_token()
        if "sofascore.com" not in (page.url or ""):
            try:
                page.goto(SITE_BASE + "/", wait_until="domcontentloaded",
                          timeout=int(self._timeout * 1000))
            except PWError as exc:
                self._last_request = time.monotonic()
                raise SofaScoreBlocked(f"site nav error: {str(exc)[:80]}") from exc

        try:
            result = page.evaluate(
                """async ({url, xrw}) => {
                    try {
                        const headers = {'Accept': 'application/json, text/plain, */*'};
                        if (xrw) headers['x-requested-with'] = xrw;
                        // no-store: SofaScore allows 10 s of caching (60 on a
                        // round), and a browser that answers from its own cache
                        // would hand back a live match as it was a moment ago.
                        const r = await fetch(url, {headers, cache: 'no-store'});
                        const body = await r.text();
                        return {status: r.status, body: body};
                    } catch (e) {
                        return {status: -1, body: String(e)};
                    }
                }""",
                {"url": SITE_BASE + path, "xrw": self._xrw},
            )
        except PWError as exc:
            self._last_request = time.monotonic()
            raise SofaScoreBlocked(f"evaluate error: {str(exc)[:80]}") from exc
        self._last_request = time.monotonic()

        status = int(result.get("status", -1))
        body = result.get("body") or ""
        if status == -1:
            raise SofaScoreBlocked(f"fetch failed: {body[:60]}")
        if status == 404:
            return None
        if status != 200:
            # token may have rotated (new site build) — force a re-capture so
            # the parent's retry picks up a fresh one.
            if status == 403:
                self._xrw = None
            raise SofaScoreBlocked(f"HTTP {status}")
        if not body.strip():
            raise SofaScoreBlocked("empty body (soft block)")
        try:
            return json.loads(body)
        except Exception as exc:  # noqa: BLE001 - challenge pages aren't JSON
            raise SofaScoreBlocked(f"non-JSON body: {str(exc)[:60]}") from exc

    # -- lifecycle ------------------------------------------------------

    def close(self) -> None:
        for obj, meth in ((self._page, "close"), (self._ctx, "close"),
                          (self._browser, "close"), (self._pw, "stop")):
            try:
                if obj is not None:
                    getattr(obj, meth)()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
        self._page = self._ctx = self._browser = self._pw = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
