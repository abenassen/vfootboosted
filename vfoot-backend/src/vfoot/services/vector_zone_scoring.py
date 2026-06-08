"""Vector zone-duel scoring — the single source of truth for the math.

Both the historical-league simulation and (in a later phase) the real
DB-backed match-detail endpoint should compute scores through this service, so
the numbers and the explainable breakdown never diverge.

Model recap (calibration `vector_zone_duel_v1`):

    For each zone the two teams have a feature vector (sum of their players'
    StatsBomb event features in that zone). Each feature is divided by a fixed
    per-feature scale, weighted by a learned param, and the home-minus-away
    difference is summed into the zone margin:

        zone_margin = Σ_f  param_f · (home_f - away_f) / scale_f

    The match margin is the MEAN of zone margins over every zone where either
    team had presence. It is then boosted (gameplay-only spread) and mapped to a
    score:

        team_score = base ± home_advantage ± score_scale · (boost · mean_margin)

    Because the margin is linear in the feature vectors, each player's
    contribution to a zone is well defined:

        contribution(player, zone) = Σ_f param_f · feature_f(player, zone) / scale_f

    Summing contributions of a team's players in a zone reproduces that team's
    side of the zone margin, so attribution is exact, not heuristic.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

ZoneVectors = Mapping[str, Mapping[str, float]]


def load_calibration(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _player_zone_contributions(
    player_vectors: ZoneVectors,
    features: list[str],
    scales: dict[str, float],
    params: dict[str, float],
) -> dict[str, float]:
    """Signed contribution of one player to each zone margin (their own side)."""
    out: dict[str, float] = {}
    for zone_key, vec in player_vectors.items():
        c = 0.0
        for f in features:
            v = float(vec.get(f, 0.0))
            if v:
                c += params[f] * (v / scales[f])
        if abs(c) > 1e-12:
            out[zone_key] = c
    return out


def score_zone_duel(
    home_vectors: ZoneVectors,
    away_vectors: ZoneVectors,
    calibration: Mapping[str, Any],
    *,
    home_players: Iterable[Mapping[str, Any]] | None = None,
    away_players: Iterable[Mapping[str, Any]] | None = None,
    fantasy_home_advantage: float = 0.0,
    fantasy_margin_boost: float = 1.0,
) -> dict[str, Any]:
    """Compute the full, explainable zone-duel result.

    ``home_players``/``away_players`` are optional iterables of
    ``{"player_id", "name", "vectors": {zone: {feature: value}}}`` used for
    per-player attribution; pass them to get the player breakdowns.
    """
    features = list(calibration["features"])
    scales = {k: max(1e-9, float(v)) for k, v in calibration["feature_scales"].items()}
    params = {k: float(v) for k, v in calibration["params"].items()}
    base = params["base"]
    score_scale = params["score_scale"]

    zone_keys = sorted(set(home_vectors) | set(away_vectors))

    # Per-player contribution maps, keyed by player, for fast per-zone lookup.
    def build_players(players):
        result = []
        if not players:
            return result
        for p in players:
            contribs = _player_zone_contributions(p.get("vectors", {}), features, scales, params)
            total = sum(contribs.values())
            result.append(
                {
                    "player_id": p.get("player_id"),
                    "name": p.get("name"),
                    "total": round(total, 5),
                    "zones": {z: round(c, 5) for z, c in contribs.items()},
                }
            )
        result.sort(key=lambda r: abs(r["total"]), reverse=True)
        return result

    home_player_rows = build_players(home_players)
    away_player_rows = build_players(away_players)

    def players_in_zone(rows, zone_key):
        out = [
            {"player_id": r["player_id"], "name": r["name"], "contribution": r["zones"][zone_key]}
            for r in rows
            if zone_key in r["zones"]
        ]
        out.sort(key=lambda r: abs(r["contribution"]), reverse=True)
        return out

    zones = []
    total_margin = 0.0
    for zone_key in zone_keys:
        margin = 0.0
        feats = []
        hv = home_vectors.get(zone_key, {})
        av = away_vectors.get(zone_key, {})
        for f in features:
            h_raw = float(hv.get(f, 0.0))
            a_raw = float(av.get(f, 0.0))
            swing = params[f] * ((h_raw / scales[f]) - (a_raw / scales[f]))
            margin += swing
            if h_raw or a_raw:
                feats.append(
                    {
                        "feature": f,
                        "home": round(h_raw, 3),
                        "away": round(a_raw, 3),
                        "swing": round(swing, 5),
                    }
                )
        total_margin += margin
        zones.append(
            {
                "zone_key": zone_key,
                "margin": round(margin, 5),
                "winner": "home" if margin > 0 else "away" if margin < 0 else "draw",
                "features": sorted(feats, key=lambda r: abs(r["swing"]), reverse=True),
                "home_players": players_in_zone(home_player_rows, zone_key),
                "away_players": players_in_zone(away_player_rows, zone_key),
            }
        )

    mean_margin = total_margin / len(zone_keys) if zone_keys else 0.0
    boosted = fantasy_margin_boost * mean_margin
    home_score = base + fantasy_home_advantage + score_scale * boosted
    away_score = base - fantasy_home_advantage - score_scale * boosted

    return {
        "total_margin": round(mean_margin, 6),
        "boosted_margin": round(boosted, 6),
        "home_score": home_score,
        "away_score": away_score,
        "score_build": {
            "base": round(base, 3),
            "score_scale": round(score_scale, 3),
            "fantasy_margin_boost": round(fantasy_margin_boost, 3),
            "fantasy_home_advantage": round(fantasy_home_advantage, 3),
            "zone_count": len(zone_keys),
        },
        "zones": zones,
        "home_player_totals": home_player_rows,
        "away_player_totals": away_player_rows,
    }
