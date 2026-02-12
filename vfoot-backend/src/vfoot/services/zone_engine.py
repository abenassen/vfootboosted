from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any


DEFAULT_GRID_COLS = 5
DEFAULT_GRID_ROWS = 4


@dataclass(frozen=True)
class ZoneGridSpec:
    cols: int = DEFAULT_GRID_COLS
    rows: int = DEFAULT_GRID_ROWS


def make_zone_grid(cols: int = DEFAULT_GRID_COLS, rows: int = DEFAULT_GRID_ROWS) -> dict[str, Any]:
    zone_ids: list[str] = []
    for r in range(rows):
        for c in range(cols):
            zone_ids.append(f"z{r:02d}{c:02d}")
    return {
        "cols": cols,
        "rows": rows,
        "zone_ids": zone_ids,
        "meta": {"labeling": "left-to-right top-to-bottom"},
    }


def _u01(seed: str) -> float:
    raw = sha256(seed.encode("utf-8")).hexdigest()[:8]
    return int(raw, 16) / 0xFFFFFFFF


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def build_player_presence_map(player_key: str, grid: dict[str, Any]) -> list[float]:
    """
    Deterministic heatmap-like zone presence with strict normalization sum=1.
    No rigid role assignment: spatial profile emerges from hashed centers.
    """
    cols = int(grid["cols"])
    rows = int(grid["rows"])

    cx = 0.05 + 0.9 * _u01(f"{player_key}:cx")
    cy = 0.05 + 0.9 * _u01(f"{player_key}:cy")
    sx = 0.14 + 0.24 * _u01(f"{player_key}:sx")
    sy = 0.14 + 0.24 * _u01(f"{player_key}:sy")

    values: list[float] = []
    for r in range(rows):
        for c in range(cols):
            x = c / max(1, cols - 1)
            y = r / max(1, rows - 1)
            dx = (x - cx) / sx
            dy = (y - cy) / sy
            base = 2.718281828 ** (-0.5 * (dx * dx + dy * dy))
            n = (_u01(f"{player_key}:{r}:{c}") - 0.5) * 0.08
            values.append(_clamp01(base + n))

    s = sum(values)
    if s <= 0:
        return [1.0 / (cols * rows)] * (cols * rows)
    return [v / s for v in values]


def compute_coverage_preview(
    grid: dict[str, Any],
    roster: list[dict[str, Any]],
    saved_lineup: dict[str, Any],
    gk_separate_slot: bool,
) -> dict[str, Any]:
    n = len(grid["zone_ids"])
    coverage = [0.0] * n
    quality = [0.0] * n

    starters = set(saved_lineup.get("starter_player_ids", []))
    gk = saved_lineup.get("gk_player_id")

    for p in roster:
        if p["player_id"] not in starters:
            continue

        w = 0.7 if gk_separate_slot and gk and p["player_id"] == gk else 1.0
        z = p["estimated_influence"]["zone_map"]["values"]
        q = p["estimated_influence"].get("quality_map", {"values": z})["values"]
        for i in range(n):
            coverage[i] += z[i] * w
            quality[i] += q[i] * w

    max_cov = max(max(coverage), 1e-9)
    max_qual = max(max(quality), 1e-9)
    cov_n = [v / max_cov for v in coverage]
    qual_n = [v / max_qual for v in quality]

    rows = int(grid["rows"])
    cols = int(grid["cols"])
    row_sum = [sum(cov_n[r * cols : (r + 1) * cols]) for r in range(rows)]

    att_rows = max(1, rows // 3)
    mid_rows = max(1, rows // 3)
    att = sum(row_sum[:att_rows])
    mid = sum(row_sum[att_rows : att_rows + mid_rows])
    defi = sum(row_sum[att_rows + mid_rows :])
    total = att + mid + defi + 1e-9

    holes = [grid["zone_ids"][i] for i, v in enumerate(cov_n) if v < 0.18][:6]

    return {
        "team_zone_coverage": {"values": cov_n},
        "team_zone_quality": {"values": qual_n},
        "summary": {
            "def_mid_att": {
                "def": defi / total,
                "mid": mid / total,
                "att": att / total,
            },
            "critical_holes": holes,
        },
    }
