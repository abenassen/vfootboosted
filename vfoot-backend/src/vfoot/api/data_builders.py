from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from realdata.models import Player
from vfoot.models import SavedLineupSnapshot
from vfoot.services.zone_engine import build_player_presence_map, compute_coverage_preview, make_zone_grid


def _u01(seed: str) -> float:
    raw = sha256(seed.encode("utf-8")).hexdigest()[:8]
    return int(raw, 16) / 0xFFFFFFFF


def _minutes_expectation(player_id: str) -> dict[str, Any]:
    v = _u01(f"{player_id}:minutes")
    if v > 0.7:
        return {"value": 0.85, "label": "high"}
    if v > 0.35:
        return {"value": 0.55, "label": "medium"}
    return {"value": 0.25, "label": "low"}


def _quality_map(zone_map: list[float], player_id: str, price: int) -> list[float]:
    weighted = [z * (0.5 + price / 30.0) * (0.8 + 0.4 * _u01(f"{player_id}:q:{i}")) for i, z in enumerate(zone_map)]
    s = sum(weighted)
    if s <= 0:
        return zone_map
    return [w / s for w in weighted]


def build_roster(grid: dict[str, Any], size: int = 20) -> list[dict[str, Any]]:
    db_players = list(Player.objects.all().order_by("id")[:size])

    players: list[dict[str, Any]] = []
    if db_players:
        base_ids = [str(p.id) for p in db_players]
        names = [p.short_name or p.full_name for p in db_players]
    else:
        base_ids = [str(100 + i) for i in range(size)]
        names = [f"Giocatore {i+1}" for i in range(size)]

    for i in range(min(size, len(base_ids))):
        pid = f"P{base_ids[i]}"
        zone_map = build_player_presence_map(pid, grid)
        price = int(round(4 + _u01(f"{pid}:price") * 20))
        players.append(
            {
                "player_id": pid,
                "name": names[i],
                "real_team": f"Team {(i % 10) + 1}",
                "price": price,
                "status": {
                    "injury": None,
                    "suspension": False,
                    "minutes_expectation": _minutes_expectation(pid),
                },
                "estimated_influence": {
                    "zone_map": {"values": zone_map},
                    "quality_map": {"values": _quality_map(zone_map, pid, price)},
                    "provenance": {
                        "source": "vfoot-backend synthetic heatmap",
                        "confidence": round(0.55 + 0.35 * _u01(f"{pid}:confidence"), 3),
                        "notes": "Deterministic placeholder until real match heatmap ingestion is connected.",
                    },
                },
            }
        )

    return players


def default_saved_lineup(roster: list[dict[str, Any]]) -> dict[str, Any]:
    starters = [p["player_id"] for p in roster[:11]]
    bench = [p["player_id"] for p in roster[11:16]]
    return {
        "lineup_id": "LU-DEFAULT",
        "gk_player_id": starters[0] if starters else None,
        "starter_player_ids": starters,
        "bench_player_ids": bench,
        "starter_backups": [],
        "ui_hints": {"last_saved_at": datetime.now(timezone.utc).isoformat()},
    }


def load_saved_lineup(league_id: str, matchday_id: str, roster: list[dict[str, Any]]) -> dict[str, Any]:
    saved = (
        SavedLineupSnapshot.objects.filter(league_id=league_id, matchday_id=matchday_id)
        .order_by("-saved_at")
        .first()
    )
    if not saved:
        return default_saved_lineup(roster)

    return {
        "lineup_id": saved.lineup_id,
        "gk_player_id": saved.gk_player_id,
        "starter_player_ids": saved.starter_player_ids,
        "bench_player_ids": saved.bench_player_ids,
        "starter_backups": saved.starter_backups,
        "ui_hints": {"last_saved_at": saved.saved_at.isoformat()},
    }


def build_lineup_context(league_id: str, matchday_id: str) -> dict[str, Any]:
    grid = make_zone_grid()
    roster = build_roster(grid)
    saved_lineup = load_saved_lineup(league_id, matchday_id, roster)

    rules = {
        "starters_count": 11,
        "bench_count": 5,
        "gk_separate_slot": True,
        "allow_any_substitution": True,
    }

    coverage = compute_coverage_preview(grid, roster, saved_lineup, rules["gk_separate_slot"])

    return {
        "league": {"id": league_id, "name": "Vfoot League"},
        "matchday": {
            "id": matchday_id,
            "name": f"Matchday {matchday_id}",
            "deadline": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        },
        "rules": rules,
        "zone_grid": grid,
        "squad": {
            "team_id": "T12",
            "name": "Casa FC",
            "colors": {"primary": "#0f172a", "secondary": "#38bdf8"},
        },
        "roster": roster,
        "saved_lineup": saved_lineup,
        "coverage_preview": coverage,
        "provenance": {
            "source": "vfoot-backend",
            "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "confidence": 0.7,
        },
    }
