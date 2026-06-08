"""Per-player profiles derived from real StatsBomb data, shared by the
simulation engine and the lineup/formation UI.

Everything here is descriptive of a player's *spatial habits* over the available
matches: where they act (footprint), the role that implies (spatially inferred,
no position labels), and how much/often they play (minutes). It is the seed of a
per-matchday predictive model — for now it summarises the season without leakage
concerns (the materialised league is historical)."""

from __future__ import annotations

import re
from collections import defaultdict

from realdata.models import MatchAppearance, PlayerZoneFeature

_ZONE_RE = re.compile(r"^Z_(\d+)_\d+$")


def zone_col(zone_key: str) -> int | None:
    m = _ZONE_RE.match(zone_key)
    return int(m.group(1)) if m else None


def role_from_footprint(footprint: dict[str, float]) -> str:
    """Coarse role inferred from where the player acts (footprint = normalised
    presence over zones, sum=1). GK touch almost only their own box (col-0 share
    high); outfielders separate by the column centre of gravity."""
    col_share: dict[int, float] = defaultdict(float)
    for zone_key, presence in footprint.items():
        col = zone_col(zone_key)
        if col is not None:
            col_share[col] += presence
    if not col_share:
        return "MID"
    avg_col = sum(col * share for col, share in col_share.items())
    if col_share.get(0, 0.0) >= 0.6 or avg_col < 0.5:
        return "GK"
    if avg_col < 1.9:
        return "DEF"
    if avg_col < 2.5:
        return "MID"
    return "ATT"


def average_column(footprint: dict[str, float]) -> float:
    total = 0.0
    for zone_key, presence in footprint.items():
        col = zone_col(zone_key)
        if col is not None:
            total += col * presence
    return round(total, 3)


def player_footprints(player_ids: list[int]) -> dict[int, dict[str, float]]:
    """{player_id: {zone_key: presence_share}} from season touches (sum=1)."""
    raw: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    rows = PlayerZoneFeature.objects.filter(feature_key="touches", player_id__in=player_ids).values_list(
        "player_id", "zone_key", "value"
    )
    for player_id, zone_key, value in rows:
        raw[int(player_id)][str(zone_key)] += float(value or 0.0)
    footprints: dict[int, dict[str, float]] = {}
    for player_id, zones in raw.items():
        total = sum(zones.values())
        if total > 0:
            footprints[player_id] = {z: round(v / total, 5) for z, v in zones.items()}
    return footprints


def player_minutes(player_ids: list[int]) -> dict[int, dict]:
    """{player_id: {appearances, starts, avg_minutes}} over the available matches."""
    agg: dict[int, dict] = defaultdict(lambda: {"appearances": 0, "starts": 0, "minutes": 0})
    rows = MatchAppearance.objects.filter(player_id__in=player_ids).values_list(
        "player_id", "minutes_played", "is_starter"
    )
    for player_id, minutes, is_starter in rows:
        a = agg[int(player_id)]
        a["appearances"] += 1
        a["minutes"] += int(minutes or 0)
        if is_starter:
            a["starts"] += 1
    out: dict[int, dict] = {}
    for player_id, a in agg.items():
        apps = a["appearances"]
        out[player_id] = {
            "appearances": apps,
            "starts": a["starts"],
            "avg_minutes": round(a["minutes"] / apps, 1) if apps else 0.0,
        }
    return out


def minutes_label(avg_minutes: float, appearances: int, total_matches: int) -> str:
    """high / medium / low expectation of being on the pitch."""
    if total_matches <= 0 or appearances == 0:
        return "low"
    play_share = appearances / total_matches
    if play_share >= 0.6 and avg_minutes >= 60:
        return "high"
    if play_share >= 0.3 and avg_minutes >= 30:
        return "medium"
    return "low"


def player_profiles(player_ids: list[int], total_matches: int = 0) -> dict[int, dict]:
    """Full per-player profile: role, footprint, avg column, minutes summary."""
    ids = [int(pid) for pid in player_ids]
    footprints = player_footprints(ids)
    minutes = player_minutes(ids)
    profiles: dict[int, dict] = {}
    for pid in ids:
        fp = footprints.get(pid, {})
        mins = minutes.get(pid, {"appearances": 0, "starts": 0, "avg_minutes": 0.0})
        profiles[pid] = {
            "role": role_from_footprint(fp) if fp else "MID",
            "avg_col": average_column(fp),
            "footprint": fp,
            "appearances": mins["appearances"],
            "starts": mins["starts"],
            "avg_minutes": mins["avg_minutes"],
            "minutes_label": minutes_label(mins["avg_minutes"], mins["appearances"], total_matches),
        }
    return profiles
