from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from django.core.management.base import BaseCommand

from realdata.models import Match, PlayerZoneFeature, SIDE_AWAY, SIDE_HOME
from vfoot.services.duel_engine import DUEL_BONUS_RATE
from vfoot.services.realdata_scoring import (
    BASE_ZONE_RATING,
    MAX_ZONE_RATING,
    MIN_ZONE_RATING,
    PRESENCE_FEATURE_WEIGHTS,
    QUALITY_FEATURE_WEIGHTS,
    statsbomb_zone_to_contract,
    starting_player_ids_for_real_match,
)
from vfoot.services.zone_engine import make_zone_grid


GOAL_THRESHOLDS = (66.0, 72.0, 78.0, 84.0, 90.0, 96.0)

FEATURE_GROUPS = {
    "passing": {"passes_completed"},
    "progression": {"progressive_passes_completed", "progressive_carries"},
    "chance_creation": {"key_passes", "passes_into_box"},
    "shooting": {"shots", "xg_shots", "touches_in_box"},
    "duels": {"duels_won"},
    "defending": {"ball_recoveries", "interceptions", "blocks", "clearances"},
    "pressure": {"pressures"},
    "errors": {"errors_bad_passes", "errors_dispossessed", "errors_fouls_committed", "errors_miscontrols"},
}


@dataclass(frozen=True)
class PlayerSample:
    player_id: int
    side: str
    presence: list[float]
    grouped_quality: dict[str, list[float]]


@dataclass(frozen=True)
class MatchSample:
    match_id: int
    home_players: tuple[PlayerSample, ...]
    away_players: tuple[PlayerSample, ...]
    real_home_goals: int
    real_away_goals: int


@dataclass
class FeatureParams:
    passing: float = 1.0
    progression: float = 1.0
    chance_creation: float = 1.0
    shooting: float = 1.0
    duels: float = 1.0
    defending: float = 1.0
    pressure: float = 1.0
    errors: float = 1.0
    scale: float = 0.9763180661691573
    offset: float = 7.98300181688761
    home_advantage: float = 0.773751176674608

    def as_dict(self) -> dict[str, float]:
        return {
            "passing": self.passing,
            "progression": self.progression,
            "chance_creation": self.chance_creation,
            "shooting": self.shooting,
            "duels": self.duels,
            "defending": self.defending,
            "pressure": self.pressure,
            "errors": self.errors,
            "scale": self.scale,
            "offset": self.offset,
            "home_advantage": self.home_advantage,
        }

    def clipped(self) -> "FeatureParams":
        values = self.as_dict()
        for group in FEATURE_GROUPS:
            values[group] = min(4.0, max(0.0, values[group]))
        values["scale"] = min(1.25, max(0.75, values["scale"]))
        values["offset"] = min(18.0, max(0.0, values["offset"]))
        values["home_advantage"] = min(2.5, max(-2.5, values["home_advantage"]))
        return FeatureParams(**values)


def hard_goals(score: float) -> int:
    if score < 66.0:
        return 0
    return math.floor((score - 66.0) / 6.0) + 1


def sign(a: float, b: float) -> int:
    if a > b:
        return 1
    if a < b:
        return -1
    return 0


def sigmoid(x: float) -> float:
    if x >= 40:
        return 1.0
    if x <= -40:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def soft_goals(score: float, tau: float) -> float:
    return sum(sigmoid((score - threshold) / tau) for threshold in GOAL_THRESHOLDS)


def _normalise(values: list[float]) -> list[float]:
    total = sum(max(0.0, value) for value in values)
    if total <= 0.0:
        return values
    return [max(0.0, value) / total for value in values]


def _overcrowding_renormalize(values: list[float]) -> list[float]:
    total = sum(values)
    if total <= 1.0 or total <= 0.0:
        return values
    return [value / total for value in values]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _feature_group(feature_key: str) -> str | None:
    for group, keys in FEATURE_GROUPS.items():
        if feature_key in keys:
            return group
    return None


def _team_scores(players: tuple[PlayerSample, ...], params: FeatureParams, zone_count: int) -> tuple[list[float], list[float]]:
    pure_scores = [0.0] * zone_count
    player_pure_votes: list[float] = []
    player_zone_ratings: list[list[float]] = []

    multipliers = params.as_dict()
    for player in players:
        ratings: list[float] = []
        for zi in range(zone_count):
            quality = 0.0
            for group in FEATURE_GROUPS:
                quality += player.grouped_quality[group][zi] * multipliers[group]
            ratings.append(_clamp(BASE_ZONE_RATING + quality, MIN_ZONE_RATING, MAX_ZONE_RATING))
        player_zone_ratings.append(ratings)
        player_pure_votes.append(sum(player.presence[zi] * ratings[zi] for zi in range(zone_count)))

    base_scores = [0.0] * zone_count
    for zi in range(zone_count):
        zone_presences = _overcrowding_renormalize([player.presence[zi] for player in players])
        for pi, presence in enumerate(zone_presences):
            pure_scores[zi] += presence * player_zone_ratings[pi][zi]
            base_scores[zi] += presence * player_pure_votes[pi]
    return pure_scores, base_scores


def raw_match_score(sample: MatchSample, params: FeatureParams, zone_count: int) -> tuple[float, float]:
    home_pure, home_base = _team_scores(sample.home_players, params, zone_count)
    away_pure, away_base = _team_scores(sample.away_players, params, zone_count)

    home_total = 0.0
    away_total = 0.0
    for zi in range(zone_count):
        if abs(home_pure[zi] - away_pure[zi]) < 1e-9:
            home_total += home_base[zi]
            away_total += away_base[zi]
        elif home_pure[zi] > away_pure[zi]:
            home_total += home_base[zi] * (1.0 + DUEL_BONUS_RATE)
            away_total += away_base[zi] * (1.0 - DUEL_BONUS_RATE)
        else:
            home_total += home_base[zi] * (1.0 - DUEL_BONUS_RATE)
            away_total += away_base[zi] * (1.0 + DUEL_BONUS_RATE)
    return home_total, away_total


def adjusted_scores(sample: MatchSample, params: FeatureParams, zone_count: int) -> tuple[float, float]:
    raw_home, raw_away = raw_match_score(sample, params, zone_count)
    home = raw_home * params.scale + params.offset + params.home_advantage
    away = raw_away * params.scale + params.offset - params.home_advantage
    return home, away


def objective(
    samples: list[MatchSample],
    params: FeatureParams,
    *,
    zone_count: int,
    tau: float,
    diff_weight: float,
    sign_weight: float,
    draw_weight: float,
    sign_tau: float,
    regularization: float,
    prior: FeatureParams,
) -> float:
    if not samples:
        return 0.0
    total = 0.0
    for sample in samples:
        adj_home, adj_away = adjusted_scores(sample, params, zone_count)
        pred_home = soft_goals(adj_home, tau)
        pred_away = soft_goals(adj_away, tau)
        goal_loss = (pred_home - sample.real_home_goals) ** 2 + (pred_away - sample.real_away_goals) ** 2
        diff_loss = ((pred_home - pred_away) - (sample.real_home_goals - sample.real_away_goals)) ** 2
        real_sign = sign(sample.real_home_goals, sample.real_away_goals)
        score_diff = adj_home - adj_away
        if real_sign == 0:
            sign_loss = draw_weight * (score_diff / 6.0) ** 2
        else:
            sign_loss = math.log1p(math.exp(-real_sign * score_diff / sign_tau))
        total += goal_loss + diff_weight * diff_loss + sign_weight * sign_loss

    p = params.as_dict()
    q = prior.as_dict()
    reg = 0.0
    for group in FEATURE_GROUPS:
        reg += (p[group] - q[group]) ** 2
    reg += (p["scale"] - q["scale"]) ** 2
    reg += ((p["offset"] - q["offset"]) / 6.0) ** 2
    reg += (p["home_advantage"] - q["home_advantage"]) ** 2
    return total / len(samples) + regularization * reg


def finite_difference_gradient(samples: list[MatchSample], params: FeatureParams, **kwargs) -> dict[str, float]:
    steps = {
        "passing": 0.02,
        "progression": 0.02,
        "chance_creation": 0.02,
        "shooting": 0.02,
        "duels": 0.02,
        "defending": 0.02,
        "pressure": 0.02,
        "errors": 0.02,
        "scale": 0.002,
        "offset": 0.02,
        "home_advantage": 0.02,
    }
    base = params.as_dict()
    grads: dict[str, float] = {}
    for name, step in steps.items():
        plus = base.copy()
        minus = base.copy()
        plus[name] += step
        minus[name] -= step
        loss_plus = objective(samples, FeatureParams(**plus).clipped(), **kwargs)
        loss_minus = objective(samples, FeatureParams(**minus).clipped(), **kwargs)
        grads[name] = (loss_plus - loss_minus) / (2.0 * step)
    return grads


def spsa_gradient(
    samples: list[MatchSample],
    params: FeatureParams,
    *,
    rng: random.Random,
    perturbation: float,
    **kwargs,
) -> dict[str, float]:
    names = list(params.as_dict())
    base = params.as_dict()
    delta = {name: (1.0 if rng.random() >= 0.5 else -1.0) for name in names}
    scales = {
        "scale": 0.08,
        "offset": 2.0,
        "home_advantage": 1.0,
    }
    for group in FEATURE_GROUPS:
        scales[group] = 1.0

    plus = base.copy()
    minus = base.copy()
    for name in names:
        step = perturbation * scales[name] * delta[name]
        plus[name] += step
        minus[name] -= step

    loss_plus = objective(samples, FeatureParams(**plus).clipped(), **kwargs)
    loss_minus = objective(samples, FeatureParams(**minus).clipped(), **kwargs)

    grads: dict[str, float] = {}
    for name in names:
        grads[name] = (loss_plus - loss_minus) / (2.0 * perturbation * scales[name] * delta[name])
    return grads


def metrics(samples: list[MatchSample], params: FeatureParams, zone_count: int) -> dict[str, float]:
    if not samples:
        return {"matches": 0}
    total_abs = 0.0
    wdl_hits = 0
    exact_hits = 0
    pred_goal_sum = 0
    real_goal_sum = 0
    raw_sign_hits = 0
    soft_abs = 0.0
    soft_wdl_hits = 0
    soft_diff_abs = 0.0
    soft_goal_sum = 0.0
    for sample in samples:
        raw_home, raw_away = raw_match_score(sample, params, zone_count)
        adj_home = raw_home * params.scale + params.offset + params.home_advantage
        adj_away = raw_away * params.scale + params.offset - params.home_advantage
        soft_home = soft_goals(adj_home, 1.25)
        soft_away = soft_goals(adj_away, 1.25)
        pred_home = hard_goals(adj_home)
        pred_away = hard_goals(adj_away)
        total_abs += abs(pred_home - sample.real_home_goals) + abs(pred_away - sample.real_away_goals)
        wdl_hits += int(sign(pred_home, pred_away) == sign(sample.real_home_goals, sample.real_away_goals))
        soft_wdl_hits += int(sign(soft_home, soft_away) == sign(sample.real_home_goals, sample.real_away_goals))
        raw_sign_hits += int(sign(raw_home, raw_away) == sign(sample.real_home_goals, sample.real_away_goals))
        exact_hits += int(pred_home == sample.real_home_goals and pred_away == sample.real_away_goals)
        pred_goal_sum += pred_home + pred_away
        real_goal_sum += sample.real_home_goals + sample.real_away_goals
        soft_goal_sum += soft_home + soft_away
        soft_abs += abs(soft_home - sample.real_home_goals) + abs(soft_away - sample.real_away_goals)
        soft_diff_abs += abs((soft_home - soft_away) - (sample.real_home_goals - sample.real_away_goals))
    n = len(samples)
    return {
        "matches": n,
        "soft_goal_mae_per_team": soft_abs / (2.0 * n),
        "soft_wdl_accuracy": soft_wdl_hits / n,
        "soft_goal_diff_mae": soft_diff_abs / n,
        "soft_avg_pred_goals_per_team": soft_goal_sum / (2.0 * n),
        "goal_mae_per_team": total_abs / (2.0 * n),
        "wdl_accuracy": wdl_hits / n,
        "raw_score_sign_accuracy": raw_sign_hits / n,
        "exact_scoreline_accuracy": exact_hits / n,
        "avg_pred_goals_per_team": pred_goal_sum / (2.0 * n),
        "avg_real_goals_per_team": real_goal_sum / (2.0 * n),
    }


class Command(BaseCommand):
    help = "Calibrate grouped StatsBomb quality-feature weights for real-data Vfoot scoring."

    def add_arguments(self, parser):
        parser.add_argument("--epochs", type=int, default=120)
        parser.add_argument("--learning-rate", type=float, default=0.03)
        parser.add_argument("--tau", type=float, default=1.25)
        parser.add_argument("--diff-weight", type=float, default=0.35)
        parser.add_argument("--sign-weight", type=float, default=1.0)
        parser.add_argument("--draw-weight", type=float, default=0.5)
        parser.add_argument("--sign-tau", type=float, default=4.0)
        parser.add_argument("--regularization", type=float, default=0.08)
        parser.add_argument("--validation-mod", type=int, default=5)
        parser.add_argument("--optimizer", choices=["spsa", "finite-diff"], default="spsa")
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--perturbation", type=float, default=0.08)
        parser.add_argument("--output", type=str, default="calibration/realdata_scoring_v1_feature_groups.json")
        parser.add_argument("--no-write", action="store_true")

    def handle(self, *args, **options):
        zone_ids = list(make_zone_grid()["zone_ids"])
        zone_index = {zone_id: idx for idx, zone_id in enumerate(zone_ids)}
        samples = self._load_samples(zone_index)
        if not samples:
            self.stdout.write(self.style.ERROR("No samples available."))
            return

        validation_mod = int(options["validation_mod"])
        train_samples = [sample for sample in samples if sample.match_id % validation_mod != 0]
        validation_samples = [sample for sample in samples if sample.match_id % validation_mod == 0]

        prior = FeatureParams()
        params = FeatureParams()
        best_params = FeatureParams(**params.as_dict())
        best_validation_loss = float("inf")

        kwargs = {
            "zone_count": len(zone_ids),
            "tau": float(options["tau"]),
            "diff_weight": float(options["diff_weight"]),
            "sign_weight": float(options["sign_weight"]),
            "draw_weight": float(options["draw_weight"]),
            "sign_tau": float(options["sign_tau"]),
            "regularization": float(options["regularization"]),
            "prior": prior,
        }
        lr = float(options["learning_rate"])
        epochs = int(options["epochs"])
        adam_m = {name: 0.0 for name in params.as_dict()}
        adam_v = {name: 0.0 for name in params.as_dict()}
        beta1 = 0.9
        beta2 = 0.999
        eps = 1e-8
        rng = random.Random(int(options["seed"]))
        optimizer = str(options["optimizer"])
        perturbation = float(options["perturbation"])

        self.stdout.write(f"samples={len(samples)} train={len(train_samples)} validation={len(validation_samples)}")
        self.stdout.write(f"initial_metrics={json.dumps(metrics(samples, params, len(zone_ids)), sort_keys=True)}")

        for epoch in range(1, epochs + 1):
            if optimizer == "finite-diff":
                grads = finite_difference_gradient(train_samples, params, **kwargs)
            else:
                grads = spsa_gradient(
                    train_samples,
                    params,
                    rng=rng,
                    perturbation=perturbation / math.sqrt(epoch),
                    **kwargs,
                )
            values = params.as_dict()
            for name, grad in grads.items():
                adam_m[name] = beta1 * adam_m[name] + (1.0 - beta1) * grad
                adam_v[name] = beta2 * adam_v[name] + (1.0 - beta2) * grad * grad
                m_hat = adam_m[name] / (1.0 - beta1**epoch)
                v_hat = adam_v[name] / (1.0 - beta2**epoch)
                values[name] -= lr * m_hat / (math.sqrt(v_hat) + eps)
            params = FeatureParams(**values).clipped()

            validation_loss = objective(validation_samples, params, **kwargs)
            if validation_loss < best_validation_loss:
                best_validation_loss = validation_loss
                best_params = FeatureParams(**params.as_dict())

            if epoch == 1 or epoch % 20 == 0 or epoch == epochs:
                train_loss = objective(train_samples, params, **kwargs)
                self.stdout.write(
                    f"epoch={epoch} train_loss={train_loss:.4f} validation_loss={validation_loss:.4f} "
                    f"params={params.as_dict()}"
                )

        result = {
            "formula_version": "realdata_scoring_v1_feature_groups_gd",
            "feature_groups": {group: sorted(keys) for group, keys in FEATURE_GROUPS.items()},
            "loss": {
                "diff_weight": kwargs["diff_weight"],
                "draw_weight": kwargs["draw_weight"],
                "regularization": kwargs["regularization"],
                "sign_tau": kwargs["sign_tau"],
                "sign_weight": kwargs["sign_weight"],
                "tau": kwargs["tau"],
                "validation_mod": validation_mod,
                "optimizer": optimizer,
            },
            "params": best_params.as_dict(),
            "metrics": {
                "train": metrics(train_samples, best_params, len(zone_ids)),
                "validation": metrics(validation_samples, best_params, len(zone_ids)),
                "all": metrics(samples, best_params, len(zone_ids)),
            },
        }
        self.stdout.write(self.style.SUCCESS(json.dumps(result, indent=2, sort_keys=True)))

        if not options["no_write"]:
            out_path = Path(options["output"])
            if not out_path.is_absolute():
                out_path = Path.cwd().parent / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote {out_path}"))

    def _load_samples(self, zone_index: dict[str, int]) -> list[MatchSample]:
        zone_count = len(zone_index)
        samples: list[MatchSample] = []
        matches = (
            Match.objects.filter(
                player_zone_features__feature_key="touches",
                home_goals__isnull=False,
                away_goals__isnull=False,
            )
            .distinct()
            .order_by("id")
        )
        for match in matches:
            home_ids = list(starting_player_ids_for_real_match(match, SIDE_HOME)[:11])
            away_ids = list(starting_player_ids_for_real_match(match, SIDE_AWAY)[:11])
            if len(home_ids) < 8 or len(away_ids) < 8:
                continue
            players = self._load_players(match, set(home_ids + away_ids), zone_index, zone_count)
            home_players = tuple(player for player in players if player.player_id in home_ids)
            away_players = tuple(player for player in players if player.player_id in away_ids)
            if len(home_players) < 8 or len(away_players) < 8:
                continue
            samples.append(
                MatchSample(
                    match_id=match.id,
                    home_players=home_players,
                    away_players=away_players,
                    real_home_goals=int(match.home_goals or 0),
                    real_away_goals=int(match.away_goals or 0),
                )
            )
        return samples

    def _load_players(
        self,
        match: Match,
        player_ids: set[int],
        zone_index: dict[str, int],
        zone_count: int,
    ) -> list[PlayerSample]:
        rows = PlayerZoneFeature.objects.filter(match=match, player_id__in=player_ids).values(
            "player_id",
            "team_side",
            "zone_key",
            "feature_key",
            "value",
        )
        presence_volume: dict[int, list[float]] = defaultdict(lambda: [0.0] * zone_count)
        grouped_quality: dict[int, dict[str, list[float]]] = defaultdict(
            lambda: {group: [0.0] * zone_count for group in FEATURE_GROUPS}
        )
        sides: dict[int, str] = {}
        for row in rows:
            player_id = int(row["player_id"])
            zone_id = statsbomb_zone_to_contract(str(row["zone_key"]))
            if zone_id not in zone_index:
                continue
            zi = zone_index[zone_id]
            feature_key = str(row["feature_key"])
            value = float(row["value"] or 0.0)
            sides[player_id] = str(row["team_side"])
            presence_volume[player_id][zi] += value * PRESENCE_FEATURE_WEIGHTS.get(feature_key, 0.0)
            group = _feature_group(feature_key)
            if group:
                grouped_quality[player_id][group][zi] += value * QUALITY_FEATURE_WEIGHTS.get(feature_key, 0.0)

        players: list[PlayerSample] = []
        for player_id in player_ids:
            presence = _normalise(presence_volume[player_id])
            if sum(presence) <= 0.0:
                continue
            players.append(
                PlayerSample(
                    player_id=player_id,
                    side=sides.get(player_id, ""),
                    presence=presence,
                    grouped_quality=grouped_quality[player_id],
                )
            )
        return players
