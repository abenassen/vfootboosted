"""What a WARM actually fetches, and why it has to fetch it again.

The fetching half of the pipeline had no test at all: the rig replaces it wholesale
(``egress_sim`` writes the payloads instead of downloading them), so everything
downstream was exercised and this was not. That is how the cache trap survived —
the simulated provider overwrites its files on every warm, the real client returns
whatever is already on disk, and only production would have shown the difference:
a live match frozen at the minute of its first fetch, with every tick reporting
success.

No network here either, but the seam is one layer lower: the real client with its
wire replaced, so cache, throttle and retry are the ones that ship.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "egress"))
import fetch_worker  # noqa: E402

MID = 16283209
OTHER = 162832099  # deliberately starts with the same digits


def _lineups(n: int = 3) -> dict:
    def entry(pid):
        return {"player": {"id": pid, "name": f"P{pid}"}, "substitute": False,
                "statistics": {"minutesPlayed": 90, "touches": 10}}
    return {"home": {"players": [entry(i) for i in range(1, n + 1)]},
            "away": {"players": []}}


class _Wire(fetch_worker.SofaScoreClient):
    """The real client, with only the network replaced."""

    def __init__(self, cache_dir, **kw):
        kw.setdefault("min_delay", 0.0)
        kw.setdefault("jitter", 0.0)
        super().__init__(cache_dir, **kw)
        self.requested: list[str] = []

    def _raw_get(self, path: str):
        self.requested.append(path)
        if path.endswith("/lineups"):
            return _lineups()
        if path.endswith("/shotmap"):
            return {"shotmap": []}
        if path.endswith("/incidents"):
            return {"incidents": []}
        if path.endswith("/heatmap"):
            return {"heatmap": [{"x": 50, "y": 50}]}
        if path.endswith("/seasons"):
            return {"seasons": [{"year": "26/27", "id": 95836}]}
        if path.endswith("/rounds"):
            return {"rounds": [{"round": 1}, {"round": 2}]}
        if "/events/round/" in path:
            return {"events": [{"id": MID}]}
        return {"event": {"id": MID}}


class _Base(SimpleTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = Path(tmp.name)
        self.clients: list[_Wire] = []

    def _run(self, *argv) -> int:
        """One warm, as the orchestrator invokes it."""
        def build(cache_dir, **kw):
            c = _Wire(cache_dir, **kw)
            self.clients.append(c)
            return c

        with mock.patch.object(sys, "argv",
                               ["fetch_worker", "--cache-dir", str(self.cache),
                                "--delay", "0", *argv]), \
             mock.patch.object(fetch_worker, "SofaScoreClient", build):
            return fetch_worker.main()

    def _files(self) -> set[str]:
        return {p.name for p in self.cache.glob("*.json")}

    def _last_requests(self) -> list[str]:
        return self.clients[-1].requested


class WhatAWarmFetchesTests(_Base):
    def test_a_light_warm_is_four_requests(self):
        """The four a vote is made of, and not one heatmap."""
        self.assertEqual(self._run("--match-ids", str(MID), "--kind", "live"), 0)
        self.assertEqual(len(self._last_requests()), 4)
        self.assertEqual([p for p in self._last_requests() if "heatmap" in p], [])

    def test_a_heavy_warm_adds_one_heatmap_per_player_who_played(self):
        self.assertEqual(self._run("--match-ids", str(MID), "--kind", "final"), 0)
        self.assertEqual(len(self._last_requests()), 4 + 3)
        self.assertEqual(len([p for p in self._last_requests() if "heatmap" in p]), 3)


class AWarmDoesNotServeTheLastWarmTests(_Base):
    """The trap this file exists for: the client's cache never expires, so a second
    warm of the same match answered with the first warm's bytes and looked fine."""

    def test_the_second_warm_fetches_again(self):
        self._run("--match-ids", str(MID), "--kind", "live")
        self._run("--match-ids", str(MID), "--kind", "live")
        self.assertEqual(len(self._last_requests()), 4,
                         "il secondo scaldamento ha servito i byte del primo: "
                         "in produzione la partita si congela al primo minuto")

    def test_the_heavy_warm_refetches_the_heatmaps_too(self):
        self._run("--match-ids", str(MID), "--kind", "final")
        self._run("--match-ids", str(MID), "--kind", "final")
        self.assertEqual(len(self._last_requests()), 4 + 3)

    def test_resume_is_what_keeps_them(self):
        """The retry after a block: the same warm continuing on another IP, which
        must not pay again for what it already got."""
        self._run("--match-ids", str(MID), "--kind", "final")
        self._run("--match-ids", str(MID), "--kind", "final", "--resume")
        self.assertEqual(self._last_requests(), [])

    def test_only_this_match_is_dropped(self):
        self._run("--match-ids", str(OTHER), "--kind", "final")
        prima = self._files()
        self._run("--match-ids", str(MID), "--kind", "final")
        self.assertTrue(prima.issubset(self._files()),
                        "un id piu' lungo che comincia con le stesse cifre "
                        "non deve essere toccato")

    def test_a_match_warm_leaves_the_calendar_alone(self):
        (self.cache / "api_v1_unique-tournament_23_seasons.json").write_text("{}")
        self._run("--match-ids", str(MID), "--kind", "live")
        self.assertIn("api_v1_unique-tournament_23_seasons.json", self._files())

    def test_a_schedule_warm_refetches_the_fixture_list(self):
        """Fixtures move — postponements, kickoff changes — so the calendar sync
        reading a frozen round file would never see them."""
        self.assertEqual(self._run("--schedule-year", "26/27"), 0)
        primo = len(self._last_requests())
        self.assertEqual(self._run("--schedule-year", "26/27"), 0)
        self.assertEqual(len(self._last_requests()), primo)
        self.assertIn("/api/v1/unique-tournament/23/seasons", self._last_requests())

    def test_a_stale_seasons_index_is_not_served_back(self):
        """It is the index that says which files belong to the season, so serving
        an old one back would make the purge miss its own target."""
        (self.cache / "api_v1_unique-tournament_23_seasons.json").write_text(
            json.dumps({"seasons": []}))            # una stagione che non c'e'
        self.assertEqual(self._run("--schedule-year", "26/27"), 0)

    def test_a_schedule_warm_leaves_the_OTHER_seasons_alone(self):
        """The hazard in the obvious implementation: this cache also holds the
        seasons already scraped — a 13k-request pull on a dev machine — under the
        same prefix. Refreshing one must not take the others with it."""
        vecchia = self.cache / "api_v1_unique-tournament_23_season_76457_events_round_5.json"
        vecchia.write_text(json.dumps({"events": []}))
        self.assertEqual(self._run("--schedule-year", "26/27"), 0)
        self.assertTrue(vecchia.exists(),
                        "la 25/26 gia' scaricata e' stata cancellata per aggiornare la 26/27")
