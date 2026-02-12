from __future__ import annotations

from hashlib import sha256
from typing import Any

DUEL_BONUS_RATE = 0.10


def _u01(seed: str) -> float:
    raw = sha256(seed.encode("utf-8")).hexdigest()[:8]
    return int(raw, 16) / 0xFFFFFFFF


def _overcrowding_renormalize(values: list[float]) -> list[float]:
    """
    Anti-exploit rule: if total zone presence > 1, normalize and discard excess.
    """
    s = sum(values)
    if s <= 1.0:
        return values
    if s <= 0:
        return values
    return [v / s for v in values]


def _player_rating(player_id: str) -> tuple[float, float]:
    # deterministic ratings in realistic ranges
    pure_vote = 5.3 + 2.1 * _u01(f"{player_id}:pure")
    fantavote = pure_vote + (2.0 * _u01(f"{player_id}:fv") - 1.0) * 0.8
    return pure_vote, fantavote


def _build_team_zone_scores(team: dict[str, Any], zone_count: int) -> tuple[list[float], list[float], dict[int, list[dict[str, Any]]]]:
    pure_scores = [0.0] * zone_count
    base_fv_scores = [0.0] * zone_count
    contributors: dict[int, list[dict[str, Any]]] = {i: [] for i in range(zone_count)}

    players = team["players"]
    for zi in range(zone_count):
        zone_presences = [p["estimated_influence"]["zone_map"]["values"][zi] for p in players]
        norm = _overcrowding_renormalize(zone_presences)

        for i, p in enumerate(players):
            pure_vote, fantavote = _player_rating(p["player_id"])
            contrib_presence = norm[i]
            pure_scores[zi] += contrib_presence * pure_vote
            base = contrib_presence * fantavote
            base_fv_scores[zi] += base
            contributors[zi].append(
                {
                    "player_id": p["player_id"],
                    "name": p["name"],
                    "contrib": round(base, 3),
                }
            )

    return pure_scores, base_fv_scores, contributors


def compute_match_zone_duels(
    match_id: str,
    league_id: str,
    matchday_id: str,
    grid: dict[str, Any],
    home_team: dict[str, Any],
    away_team: dict[str, Any],
) -> dict[str, Any]:
    zone_ids = grid["zone_ids"]
    zcount = len(zone_ids)

    home_pure, home_base, home_contrib = _build_team_zone_scores(home_team, zcount)
    away_pure, away_base, away_contrib = _build_team_zone_scores(away_team, zcount)

    zone_results: list[dict[str, Any]] = []
    winner_map: list[str] = []
    points_map: list[float] = []
    margin_map: list[float] = []
    key_factor_map: list[str] = []

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

        macro_scores = {
            "possession": {"home": round(hp, 3), "away": round(ap, 3), "swing": round(hp - ap, 3)},
            "quality": {"home": round(hb, 3), "away": round(ab, 3), "swing": round(hb - ab, 3)},
        }
        key_factor = "zone_duel_pure_vote"

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
                "macro_scores": macro_scores,
                "key_factor": key_factor,
                "top_contributors": {
                    "home": sorted(home_contrib[zi], key=lambda x: x["contrib"], reverse=True)[:2],
                    "away": sorted(away_contrib[zi], key=lambda x: x["contrib"], reverse=True)[:2],
                },
                "explain_stats": {
                    "duel": [
                        {"label": "Pure vote", "home": round(hp, 3), "away": round(ap, 3)},
                        {"label": "Base fantavote", "home": round(hb, 3), "away": round(ab, 3)},
                    ]
                },
            }
        )

        winner_map.append(winner)
        points_map.append(round(abs(swing), 3))
        margin_map.append(round(margin, 3))
        key_factor_map.append(key_factor)

    decisive = sorted(zone_results, key=lambda z: abs(z["points"]["swing"]), reverse=True)[:3]
    decisive_ids = [z["zone_id"] for z in decisive]

    cols = int(grid["cols"])
    by_flank = {
        "left": {"swing": round(sum(z["points"]["swing"] for i, z in enumerate(zone_results) if (i % cols) == 0), 3)},
        "center": {"swing": round(sum(z["points"]["swing"] for i, z in enumerate(zone_results) if 0 < (i % cols) < cols - 1), 3)},
        "right": {"swing": round(sum(z["points"]["swing"] for i, z in enumerate(zone_results) if (i % cols) == cols - 1), 3)},
    }

    rows = int(grid["rows"])
    def row_band(r: int) -> str:
        if r < max(1, rows // 3):
            return "att"
        if r < max(2, (2 * rows) // 3):
            return "mid"
        return "def"

    by_height = {
        "def": {"swing": 0.0},
        "mid": {"swing": 0.0},
        "att": {"swing": 0.0},
    }
    for i, z in enumerate(zone_results):
        r = i // cols
        by_height[row_band(r)]["swing"] += z["points"]["swing"]
    for k in by_height:
        by_height[k]["swing"] = round(by_height[k]["swing"], 3)

    home_total = round(sum(z["points"]["home"] for z in zone_results), 3)
    away_total = round(sum(z["points"]["away"] for z in zone_results), 3)

    return {
        "match": {
            "match_id": match_id,
            "league_id": league_id,
            "matchday_id": matchday_id,
            "status": "finished",
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
                    "text": f"Decisive zones: {', '.join(decisive_ids)}",
                    "zone_group": "decisive",
                    "swing": round(home_total - away_total, 3),
                }
            ],
            "decisive_zones": decisive_ids,
        },
        "zone_results": zone_results,
        "zone_maps": {
            "winner_map": {"values": winner_map},
            "points_map": {"values": points_map},
            "margin_map": {"values": margin_map},
            "key_factor_map": {"values": key_factor_map},
        },
        "line_summaries": {
            "by_flank": by_flank,
            "by_height": by_height,
        },
    }
