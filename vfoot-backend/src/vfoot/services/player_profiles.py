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


def player_footprints(player_ids: list[int], as_of_matchday: int | None = None) -> dict[int, dict[str, float]]:
    """{player_id: {zone_key: presence_share}} from touches (sum=1). When
    as_of_matchday is given, only matches BEFORE it count (no leakage: you set a
    lineup for matchday N knowing only matchdays < N)."""
    qs = PlayerZoneFeature.objects.filter(feature_key="touches", player_id__in=player_ids)
    if as_of_matchday is not None:
        qs = qs.filter(match__matchday__lt=as_of_matchday)
    raw: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for player_id, zone_key, value in qs.values_list("player_id", "zone_key", "value"):
        raw[int(player_id)][str(zone_key)] += float(value or 0.0)
    footprints: dict[int, dict[str, float]] = {}
    for player_id, zones in raw.items():
        total = sum(zones.values())
        if total > 0:
            footprints[player_id] = {z: round(v / total, 5) for z, v in zones.items()}
    return footprints


def player_minutes(player_ids: list[int], as_of_matchday: int | None = None,
                   competition_season_id: int | None = None) -> dict[int, dict]:
    """{player_id: {appearances, starts, avg_minutes}} over the available matches
    (only those before as_of_matchday when given, and of one season when given)."""
    agg: dict[int, dict] = defaultdict(lambda: {"appearances": 0, "starts": 0, "minutes": 0})
    qs = MatchAppearance.objects.filter(player_id__in=player_ids)
    if competition_season_id is not None:
        qs = qs.filter(match__competition_season_id=competition_season_id)
    if as_of_matchday is not None:
        qs = qs.filter(match__matchday__lt=as_of_matchday)
    rows = qs.values_list("player_id", "minutes_played", "is_starter")
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
    """high / medium / low expectation of being on the pitch, or 'unknown' when we
    have no games to judge from (typically pre-season): claiming a player is rarely
    used when nobody has played yet would be plainly wrong."""
    if appearances == 0:
        return "unknown"
    if total_matches <= 0:
        return "unknown"
    play_share = appearances / total_matches
    if play_share >= 0.6 and avg_minutes >= 60:
        return "high"
    if play_share >= 0.3 and avg_minutes >= 30:
        return "medium"
    return "low"


def player_form(
    player_ids: list[int],
    params: dict[str, float],
    scales: dict[str, float],
    as_of_matchday: int | None = None,
    window: int = 6,
) -> dict[int, float]:
    """Expected per-match contribution from RECENT form: the calibration-weighted
    net value (Σ param·value/scale over zones & features) of each player's last
    `window` matchdays before the cutoff, averaged per match. Errors carry their
    negative weight, so a sloppy spell drags the number down."""
    qs = PlayerZoneFeature.objects.filter(player_id__in=player_ids)
    if as_of_matchday is not None:
        qs = qs.filter(match__matchday__lt=as_of_matchday, match__matchday__gte=as_of_matchday - window)
    per_player_match: dict[tuple[int, int], float] = defaultdict(float)
    for player_id, match_id, feature_key, value in qs.values_list(
        "player_id", "match_id", "feature_key", "value"
    ):
        w = params.get(feature_key)
        s = scales.get(feature_key)
        if w and s:
            per_player_match[(int(player_id), int(match_id))] += w * (float(value or 0.0) / s)
    by_player: dict[int, list[float]] = defaultdict(list)
    for (pid, _mid), contribution in per_player_match.items():
        by_player[pid].append(contribution)
    return {pid: round(sum(cs) / len(cs), 3) for pid, cs in by_player.items() if cs}


def player_profiles(
    player_ids: list[int],
    total_matches: int = 0,
    as_of_matchday: int | None = None,
    params: dict[str, float] | None = None,
    scales: dict[str, float] | None = None,
    competition_season_id: int | None = None,
) -> dict[int, dict]:
    """Full per-player profile: role, footprint, avg column, minutes summary, and
    (when params/scales given) recent-form expected contribution. With
    as_of_matchday everything is computed from matches before that matchday only."""
    ids = [int(pid) for pid in player_ids]
    footprints = player_footprints(ids, as_of_matchday=as_of_matchday)
    minutes = player_minutes(ids, as_of_matchday=as_of_matchday,
                             competition_season_id=competition_season_id)
    form = (
        player_form(ids, params, scales, as_of_matchday=as_of_matchday)
        if params and scales
        else {}
    )
    denom = (as_of_matchday - 1) if as_of_matchday is not None else total_matches
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
            "minutes_label": minutes_label(mins["avg_minutes"], mins["appearances"], denom),
            "form": form.get(pid, 0.0),
        }
    return profiles
