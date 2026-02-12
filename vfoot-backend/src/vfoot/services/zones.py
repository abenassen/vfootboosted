# vfoot/services/zones.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from django.db import transaction
from django.db.models import QuerySet

from realdata.models import Match, MatchAppearance
from vfoot.models import (
    HeatmapGrid,
    PlayerZonePresence,
    Zone,
    ZoneDuel,
    ZoneSet,
)


@dataclass(frozen=True)
class GridSpec:
    nx: int
    ny: int


def generate_grid_zones(nx: int, ny: int) -> List[dict]:
    """
    Generate normalized bbox zones for a grid partition.
    Coordinates are normalized to [0,1], origin at top-left.
    """
    if nx <= 0 or ny <= 0:
        raise ValueError("nx and ny must be positive.")

    zones: List[dict] = []
    dx = 1.0 / nx
    dy = 1.0 / ny

    for row in range(ny):
        for col in range(nx):
            x0 = col * dx
            y0 = row * dy
            x1 = (col + 1) * dx
            y1 = (row + 1) * dy
            zones.append(
                {
                    "code": f"Z_{col}_{row}",
                    "row": row,
                    "col": col,
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                }
            )
    return zones


@transaction.atomic
def materialize_grid_zoneset(zoneset: ZoneSet) -> int:
    """
    Create Zone rows for a ZoneSet of kind 'grid' using zoneset.params {"nx":..,"ny":..}.
    Returns the number of created zones.
    """
    if zoneset.kind != ZoneSet.KIND_GRID:
        raise ValueError("ZoneSet is not of kind 'grid'.")

    nx = int(zoneset.params.get("nx", 0))
    ny = int(zoneset.params.get("ny", 0))
    if nx <= 0 or ny <= 0:
        raise ValueError("ZoneSet params must include positive nx, ny.")

    # Ensure idempotency: delete existing zones for this zoneset and recreate
    zoneset.zones.all().delete()

    zone_dicts = generate_grid_zones(nx=nx, ny=ny)
    zone_objs = [
        Zone(
            zone_set=zoneset,
            code=z["code"],
            row=z["row"],
            col=z["col"],
            x0=z["x0"],
            y0=z["y0"],
            x1=z["x1"],
            y1=z["y1"],
        )
        for z in zone_dicts
    ]
    Zone.objects.bulk_create(zone_objs, batch_size=500)
    return len(zone_objs)


def _infer_grid_spec(zones: QuerySet[Zone]) -> GridSpec:
    """
    Infer grid dimensions from Zone rows that have row/col.
    """
    max_row = zones.aggregate(models_max=models.Max("row"))["models_max"]
    max_col = zones.aggregate(models_max=models.Max("col"))["models_max"]
    if max_row is None or max_col is None:
        raise ValueError("Zones do not have row/col; cannot infer grid spec.")
    return GridSpec(nx=int(max_col) + 1, ny=int(max_row) + 1)


def _grid_zone_lookup(zones: Iterable[Zone], nx: int, ny: int) -> Dict[Tuple[int, int], Zone]:
    """
    Build a lookup (col,row) -> Zone for grid zones.
    """
    lookup: Dict[Tuple[int, int], Zone] = {}
    for z in zones:
        if z.col is None or z.row is None:
            raise ValueError("Grid zones must have col and row set.")
        lookup[(int(z.col), int(z.row))] = z
    if len(lookup) != nx * ny:
        # Not necessarily fatal, but in beta it's better to be strict.
        raise ValueError("ZoneSet zones are incomplete for the expected grid.")
    return lookup


def _zone_for_cell_center_grid(
    cx: float, cy: float, nx: int, ny: int, lookup: Dict[Tuple[int, int], Zone]
) -> Zone:
    """
    Map a cell center to the corresponding grid zone via integer binning.
    """
    # Clamp inside [0, 1)
    cx = min(max(cx, 0.0), 0.999999)
    cy = min(max(cy, 0.0), 0.999999)
    col = int(cx * nx)
    row = int(cy * ny)
    return lookup[(col, row)]


@transaction.atomic
def compute_zone_presences_for_match(match: Match, zoneset: ZoneSet) -> int:
    """
    Compute PlayerZonePresence for all appearances of a match and a given ZoneSet.
    Currently optimized for grid ZoneSets; for polygons you can extend later.

    Returns the number of (match,player,zone) rows written.
    """
    zones = Zone.objects.filter(zone_set=zoneset).order_by("row", "col", "code")
    if not zones.exists():
        raise ValueError("ZoneSet has no zones materialized. Run materialization first.")

    if zoneset.kind != ZoneSet.KIND_GRID:
        # For future: use bbox / polygon hit-testing.
        raise NotImplementedError("Only grid zonesets are supported in beta.")

    nx = int(zoneset.params.get("nx"))
    ny = int(zoneset.params.get("ny"))
    lookup = _grid_zone_lookup(zones, nx=nx, ny=ny)

    # Remove old presences for this match and zoneset (zoneset is implied by Zone FK)
    PlayerZonePresence.objects.filter(match=match, zone__zone_set=zoneset).delete()

    appearances = (
        MatchAppearance.objects.filter(match=match)
        .select_related("player")
        .prefetch_related("heatmap")
    )

    rows_to_create: List[PlayerZonePresence] = []

    for app in appearances:
        # Heatmap is optional at this stage: skip if missing.
        try:
            heatmap = app.heatmap  # OneToOne
        except HeatmapGrid.DoesNotExist:
            continue

        w = int(heatmap.grid_w)
        h = int(heatmap.grid_h)
        values = heatmap.values

        if not isinstance(values, list) or len(values) != w * h:
            raise ValueError(f"HeatmapGrid values length mismatch for appearance={app.id}")

        total = float(sum(values))
        if total <= 0:
            # No activity recorded -> skip or create zeros (skip keeps DB smaller)
            continue

        # Accumulate per zone
        zone_sums: Dict[int, float] = {}  # zone_id -> sum
        for iy in range(h):
            cy = (iy + 0.5) / h
            for ix in range(w):
                cx = (ix + 0.5) / w
                z = _zone_for_cell_center_grid(cx, cy, nx=nx, ny=ny, lookup=lookup)
                v = float(values[iy * w + ix])
                zone_sums[z.id] = zone_sums.get(z.id, 0.0) + v

        # Normalize to presence in [0,1]
        for zone_id, s in zone_sums.items():
            presence = s / total
            rows_to_create.append(
                PlayerZonePresence(
                    match=match,
                    player=app.player,
                    zone_id=zone_id,
                    presence=presence,
                    # activity_score is optional; for now store total normalized to 1.0
                    activity_score=0.0,
                )
            )

    PlayerZonePresence.objects.bulk_create(rows_to_create, batch_size=2000)
    return len(rows_to_create)


@transaction.atomic
def compute_zone_duels_for_match(match: Match, zoneset: ZoneSet) -> int:
    """
    Compute ZoneDuel for a match by aggregating PlayerZonePresence.
    home_score/away_score are simple sums of presences for now (beta).
    You can later weight by performance metrics or 'activity_score'.

    Returns number of ZoneDuel rows written.
    """
    zones = Zone.objects.filter(zone_set=zoneset)
    if not zones.exists():
        raise ValueError("ZoneSet has no zones materialized.")

    # Delete existing duels for this match and zoneset
    ZoneDuel.objects.filter(match=match, zone__zone_set=zoneset).delete()

    # Build a map player -> side for this match (home/away)
    side_by_player_id: Dict[int, str] = dict(
        MatchAppearance.objects.filter(match=match).values_list("player_id", "side")
    )

    presences = (
        PlayerZonePresence.objects.filter(match=match, zone__zone_set=zoneset)
        .select_related("zone")
        .values("player_id", "zone_id", "presence")
    )

    home_sum: Dict[int, float] = {}
    away_sum: Dict[int, float] = {}

    for p in presences:
        pid = int(p["player_id"])
        zid = int(p["zone_id"])
        val = float(p["presence"])
        side = side_by_player_id.get(pid)
        if side == "home":
            home_sum[zid] = home_sum.get(zid, 0.0) + val
        elif side == "away":
            away_sum[zid] = away_sum.get(zid, 0.0) + val
        else:
            # If a presence exists but we can't find side, ignore (shouldn't happen)
            continue

    duels: List[ZoneDuel] = []
    for z in zones:
        hs = home_sum.get(z.id, 0.0)
        aws = away_sum.get(z.id, 0.0)

        if hs > aws:
            winner = "home"
        elif aws > hs:
            winner = "away"
        else:
            winner = "draw"

        intensity = 0.0
        denom = hs + aws
        if denom > 0:
            intensity = min(1.0, abs(hs - aws) / denom)

        duels.append(
            ZoneDuel(
                match=match,
                zone=z,
                home_score=hs,
                away_score=aws,
                winner=winner,
                intensity=intensity,
            )
        )

    ZoneDuel.objects.bulk_create(duels, batch_size=500)
    return len(duels)

