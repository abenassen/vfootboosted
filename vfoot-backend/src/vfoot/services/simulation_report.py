"""Read-only access layer for the historical Vfoot league dry-run artifact.

The historical league simulation (``simulate_historical_vfoot_league``) writes a
self-contained JSON report. This module loads that artifact, assigns stable
fixture ids, and computes a few aggregate distributions so the frontend can
browse the simulated season without re-running the engine.

The artifact is intentionally not materialized into the persistent fantasy
tables; this layer keeps it strictly read-only.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from functools import lru_cache
from typing import Any

from django.conf import settings

DEFAULT_REPORT_RELATIVE = "calibration/historical_vfoot_league_dry_run.json"


def _report_path() -> str:
    """Resolve the dry-run artifact path relative to the backend root."""
    # settings.BASE_DIR points at vfoot-backend/src; the calibration dir lives
    # one level up at vfoot-backend/calibration.
    base = os.path.dirname(str(settings.BASE_DIR))
    return os.path.join(base, DEFAULT_REPORT_RELATIVE)


@lru_cache(maxsize=1)
def _load_raw(path: str, mtime: float) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_report() -> dict[str, Any]:
    """Load the artifact, transparently reloading when the file changes.

    The lru_cache is keyed on (path, mtime) so regenerating the report invalidates
    the cache without a server restart.
    """
    path = _report_path()
    if not os.path.exists(path):
        raise FileNotFoundError(
            "Historical Vfoot league dry-run artifact not found. "
            "Generate it with: python manage.py simulate_historical_vfoot_league"
        )
    mtime = os.path.getmtime(path)
    return _load_raw(path, mtime)


def _result(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if away_goals > home_goals:
        return "away"
    return "draw"


def _fixtures_with_ids(report: dict[str, Any]) -> list[dict[str, Any]]:
    fixtures = report.get("fixtures", [])
    enriched = []
    for idx, fx in enumerate(fixtures):
        item = dict(fx)
        item["fixture_id"] = idx
        item["result"] = _result(fx.get("home_goals", 0), fx.get("away_goals", 0))
        enriched.append(item)
    return enriched


def _distributions(fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    results = Counter()
    scorelines = Counter()
    scores: list[float] = []
    for fx in fixtures:
        results[fx["result"]] += 1
        scorelines[f"{fx.get('home_goals', 0)}-{fx.get('away_goals', 0)}"] += 1
        scores.append(float(fx.get("home_score", 0.0)))
        scores.append(float(fx.get("away_score", 0.0)))

    top_scorelines = [
        {"scoreline": k, "count": v}
        for k, v in scorelines.most_common(8)
    ]
    score_range = None
    if scores:
        score_range = {
            "min": round(min(scores), 3),
            "avg": round(sum(scores) / len(scores), 3),
            "max": round(max(scores), 3),
        }
    return {
        "results": {
            "home_wins": results.get("home", 0),
            "draws": results.get("draw", 0),
            "away_wins": results.get("away", 0),
        },
        "top_scorelines": top_scorelines,
        "score_range": score_range,
        "total_fixtures": len(fixtures),
    }


def build_overview() -> dict[str, Any]:
    report = load_report()
    fixtures = _fixtures_with_ids(report)
    return {
        "version": report.get("version"),
        "player_pool_size": report.get("player_pool_size"),
        "config": report.get("config", {}),
        "teams": report.get("teams", []),
        "standings": report.get("standings", []),
        "notes": report.get("notes", []),
        "distributions": _distributions(fixtures),
        "rounds": sorted({fx.get("fantasy_round") for fx in fixtures if fx.get("fantasy_round")}),
    }


def _fixture_summary(fx: dict[str, Any]) -> dict[str, Any]:
    return {
        "fixture_id": fx["fixture_id"],
        "fantasy_round": fx.get("fantasy_round"),
        "real_matchday": fx.get("real_matchday"),
        "home_team": fx.get("home_team"),
        "away_team": fx.get("away_team"),
        "home_score": fx.get("home_score"),
        "away_score": fx.get("away_score"),
        "home_goals": fx.get("home_goals"),
        "away_goals": fx.get("away_goals"),
        "result": fx["result"],
    }


def build_fixture_list() -> list[dict[str, Any]]:
    fixtures = _fixtures_with_ids(load_report())
    return [_fixture_summary(fx) for fx in fixtures]


def build_fixture_detail(fixture_id: int) -> dict[str, Any] | None:
    fixtures = _fixtures_with_ids(load_report())
    if fixture_id < 0 or fixture_id >= len(fixtures):
        return None
    return fixtures[fixture_id]
