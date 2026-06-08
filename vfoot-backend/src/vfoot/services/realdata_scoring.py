from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.db.models import QuerySet

from realdata.models import Match, PlayerZoneFeature
from vfoot.services.duel_engine import DUEL_BONUS_RATE
from vfoot.services.zone_engine import make_zone_grid


PRESENCE_FEATURE_WEIGHTS = {
    "touches": 1.0,
    "pressures": 0.35,
    "ball_recoveries": 0.50,
    "interceptions": 0.50,
    "blocks": 0.40,
    "clearances": 0.30,
}

QUALITY_FEATURE_WEIGHTS = {
    "passes_completed": 0.015,
    "progressive_passes_completed": 0.060,
    "progressive_carries": 0.050,
    "key_passes": 0.120,
    "passes_into_box": 0.070,
    "shots": 0.060,
    "xg_shots": 0.800,
    "touches_in_box": 0.020,
    "duels_won": 0.060,
    "ball_recoveries": 0.050,
    "interceptions": 0.070,
    "blocks": 0.050,
    "clearances": 0.025,
    "pressures": 0.015,
    "errors_bad_passes": -0.025,
    "errors_dispossessed": -0.060,
    "errors_fouls_committed": -0.040,
    "errors_miscontrols": -0.050,
}

BASE_ZONE_RATING = 5.50
MIN_ZONE_RATING = 4.00
MAX_ZONE_RATING = 8.50


@dataclass(frozen=True)
class PlayerRealZoneProfile:
    player_id: int
    name: str
    side: str
    presence: dict[str, float]
    zone_rating: dict[str, float]
    total_presence_volume: float
    pure_vote: float
    fantavote: float


def statsbomb_zone_to_contract(zone_key: str) -> str:
    """Convert StatsBomb import zone key Z_col_row to API grid key zrowcol."""
    try:
        _, col, row = zone_key.split("_")
        return f"z{int(row):02d}{int(col):02d}"
    except (TypeError, ValueError):
        return zone_key


def contract_zone_to_statsbomb(zone_id: str) -> str:
    """Convert API grid key zrowcol to StatsBomb import zone key Z_col_row."""
    if not zone_id.startswith("z") or len(zone_id) != 5:
        return zone_id
    row = int(zone_id[1:3])
    col = int(zone_id[3:5])
    return f"Z_{col}_{row}"


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _empty_zone_values(zone_ids: Iterable[str]) -> dict[str, float]:
    return {zone_id: 0.0 for zone_id in zone_ids}


def _normalise(values: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, v) for v in values.values())
    if total <= 0:
        return values
    return {k: max(0.0, v) / total for k, v in values.items()}


def _overcrowding_renormalize(values: list[float]) -> list[float]:
    total = sum(values)
    if total <= 1.0 or total <= 0.0:
        return values
    return [v / total for v in values]


def build_player_real_zone_profile(
    *,
    match: Match,
    player_id: int,
    zone_ids: list[str] | None = None,
) -> PlayerRealZoneProfile | None:
    grid = make_zone_grid()
    zone_ids = zone_ids or list(grid["zone_ids"])
    contract_zone_ids = set(zone_ids)

    rows = list(
        PlayerZoneFeature.objects.filter(match=match, player_id=player_id)
        .select_related("player")
        .values("player_id", "player__short_name", "player__full_name", "team_side", "zone_key", "feature_key", "value")
    )
    if not rows:
        return None

    name = rows[0]["player__short_name"] or rows[0]["player__full_name"] or str(player_id)
    side = rows[0]["team_side"]
    presence_volume = _empty_zone_values(zone_ids)
    quality_raw = _empty_zone_values(zone_ids)

    for row in rows:
        zone_id = statsbomb_zone_to_contract(str(row["zone_key"]))
        if zone_id not in contract_zone_ids:
            continue
        feature_key = str(row["feature_key"])
        value = float(row["value"] or 0.0)
        presence_volume[zone_id] += value * PRESENCE_FEATURE_WEIGHTS.get(feature_key, 0.0)
        quality_raw[zone_id] += value * QUALITY_FEATURE_WEIGHTS.get(feature_key, 0.0)

    presence = _normalise(presence_volume)
    if sum(presence.values()) <= 0:
        return None

    zone_rating = {
        zone_id: _clamp(BASE_ZONE_RATING + quality_raw[zone_id], MIN_ZONE_RATING, MAX_ZONE_RATING)
        for zone_id in zone_ids
    }
    pure_vote = sum(presence[z] * zone_rating[z] for z in zone_ids)

    # First playable baseline: fantavote equals provider-derived pure vote.
    # Goal/card fantasy modifiers can be layered later when a calibrated vote model exists.
    fantavote = pure_vote

    return PlayerRealZoneProfile(
        player_id=player_id,
        name=name,
        side=side,
        presence=presence,
        zone_rating=zone_rating,
        total_presence_volume=sum(presence_volume.values()),
        pure_vote=pure_vote,
        fantavote=fantavote,
    )


def build_real_match_profiles(match: Match, player_ids: Iterable[int]) -> list[PlayerRealZoneProfile]:
    zone_ids = list(make_zone_grid()["zone_ids"])
    profiles: list[PlayerRealZoneProfile] = []
    for player_id in player_ids:
        profile = build_player_real_zone_profile(match=match, player_id=int(player_id), zone_ids=zone_ids)
        if profile is not None:
            profiles.append(profile)
    return profiles


def _team_zone_scores(
    profiles: list[PlayerRealZoneProfile],
    zone_ids: list[str],
) -> tuple[list[float], list[float], dict[str, list[dict[str, float | int | str]]]]:
    pure_scores = [0.0] * len(zone_ids)
    base_scores = [0.0] * len(zone_ids)
    contributors: dict[str, list[dict[str, float | int | str]]] = {zone_id: [] for zone_id in zone_ids}

    for zi, zone_id in enumerate(zone_ids):
        zone_presences = [p.presence.get(zone_id, 0.0) for p in profiles]
        norm_presences = _overcrowding_renormalize(zone_presences)
        for idx, profile in enumerate(profiles):
            presence = norm_presences[idx]
            rating = profile.zone_rating.get(zone_id, BASE_ZONE_RATING)
            pure = presence * rating
            base = presence * profile.fantavote
            pure_scores[zi] += pure
            base_scores[zi] += base
            if base > 0:
                contributors[zone_id].append(
                    {
                        "player_id": profile.player_id,
                        "name": profile.name,
                        "contrib": round(base, 3),
                    }
                )
    return pure_scores, base_scores, contributors


def compute_real_match_zone_duels(
    *,
    match: Match,
    home_player_ids: Iterable[int],
    away_player_ids: Iterable[int],
    league_id: str = "realdata",
    matchday_id: str | None = None,
) -> dict:
    grid = make_zone_grid()
    zone_ids = list(grid["zone_ids"])
    home_profiles = build_real_match_profiles(match, home_player_ids)
    away_profiles = build_real_match_profiles(match, away_player_ids)

    home_pure, home_base, home_contrib = _team_zone_scores(home_profiles, zone_ids)
    away_pure, away_base, away_contrib = _team_zone_scores(away_profiles, zone_ids)

    zone_results = []
    winner_map = []
    points_map = []
    margin_map = []
    key_factor_map = []

    for zi, zone_id in enumerate(zone_ids):
        hp = home_pure[zi]
        ap = away_pure[zi]
        if abs(hp - ap) < 1e-9:
            winner = "draw"
        else:
            winner = "home" if hp > ap else "away"

        hb = home_base[zi]
        ab = away_base[zi]
        if winner == "home":
            home_points = hb * (1.0 + DUEL_BONUS_RATE)
            away_points = ab * (1.0 - DUEL_BONUS_RATE)
        elif winner == "away":
            home_points = hb * (1.0 - DUEL_BONUS_RATE)
            away_points = ab * (1.0 + DUEL_BONUS_RATE)
        else:
            home_points = hb
            away_points = ab

        swing = home_points - away_points
        margin = abs(hp - ap)
        key_factor = "statsbomb_event_quality"

        zone_results.append(
            {
                "zone_id": zone_id,
                "winner": winner,
                "points": {
                    "home": round(home_points, 3),
                    "away": round(away_points, 3),
                    "swing": round(swing, 3),
                },
                "margin": round(margin, 3),
                "macro_scores": {
                    "presence_quality": {"home": round(hp, 3), "away": round(ap, 3), "swing": round(hp - ap, 3)},
                    "base_vote": {"home": round(hb, 3), "away": round(ab, 3), "swing": round(hb - ab, 3)},
                },
                "key_factor": key_factor,
                "top_contributors": {
                    "home": sorted(home_contrib[zone_id], key=lambda x: float(x["contrib"]), reverse=True)[:2],
                    "away": sorted(away_contrib[zone_id], key=lambda x: float(x["contrib"]), reverse=True)[:2],
                },
            }
        )
        winner_map.append(winner)
        points_map.append(round(abs(swing), 3))
        margin_map.append(round(margin, 3))
        key_factor_map.append(key_factor)

    home_total = round(sum(z["points"]["home"] for z in zone_results), 3)
    away_total = round(sum(z["points"]["away"] for z in zone_results), 3)
    decisive = sorted(zone_results, key=lambda z: abs(z["points"]["swing"]), reverse=True)[:3]

    return {
        "match": {
            "match_id": str(match.id),
            "league_id": league_id,
            "matchday_id": matchday_id or str(match.matchday or ""),
            "status": "finished",
            "source_real_match_id": match.id,
            "source_external_id": match.external_id,
        },
        "score": {
            "home_total": home_total,
            "away_total": away_total,
            "breakdown": {
                "zones_total": {"home": home_total, "away": away_total},
                "base_total": {"home": round(sum(home_base), 3), "away": round(sum(away_base), 3)},
            },
        },
        "story": {
            "takeaways": [
                {
                    "text": "Decisive zones: " + ", ".join(z["zone_id"] for z in decisive),
                    "zone_group": "decisive",
                    "swing": round(home_total - away_total, 3),
                }
            ],
            "decisive_zones": [z["zone_id"] for z in decisive],
        },
        "zone_grid": grid,
        "zone_results": zone_results,
        "zone_maps": {
            "winner_map": {"values": winner_map},
            "points_map": {"values": points_map},
            "margin_map": {"values": margin_map},
            "key_factor_map": {"values": key_factor_map},
        },
        "provenance": {
            "source": "statsbomb feature tables",
            "formula_version": "realdata_scoring_v1",
            "home_profiles": len(home_profiles),
            "away_profiles": len(away_profiles),
        },
    }


def starting_player_ids_for_real_match(match: Match, side: str, limit: int = 11) -> list[int]:
    qs: QuerySet = match.appearances.filter(side=side).order_by("-is_starter", "-minutes_played", "id")
    return list(qs.values_list("player_id", flat=True)[:limit])

