from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from django.core.management.base import BaseCommand

from realdata.models import Match, SIDE_AWAY, SIDE_HOME, TeamZoneFeature
from vfoot.services.vector_zone_scoring import mirror_zone


FEATURES = (
    "xg_shots",
    "shots",
    "touches_in_box",
    "key_passes",
    "passes_into_box",
    "progressive_passes_completed",
    "progressive_carries",
    "ball_recoveries",
    "interceptions",
    "pressures",
    "clearances",
    "errors_bad_passes",
    "errors_dispossessed",
    "errors_fouls_committed",
    "errors_miscontrols",
)

ERROR_FEATURES = {
    "errors_bad_passes",
    "errors_dispossessed",
    "errors_fouls_committed",
    "errors_miscontrols",
}

GOAL_THRESHOLDS = (66.0, 72.0, 78.0, 84.0, 90.0, 96.0)


@dataclass(frozen=True)
class VectorZoneSample:
    match_id: int
    zones_home: tuple[tuple[float, ...], ...]
    zones_away: tuple[tuple[float, ...], ...]
    real_home_goals: int
    real_away_goals: int


@dataclass
class VectorParams:
    base: float = 66.0
    score_scale: float = 8.0
    home_advantage: float = 0.25
    # Per-zone saturation: zone_out = K * tanh(margin / K). Small K -> winning a
    # zone matters more than dominating it (positioning-sensitive); large K ->
    # near-linear (positioning-agnostic). Calibrated as a free parameter.
    saturation_k: float = 0.5
    xg_shots: float = 1.0
    shots: float = 0.2
    touches_in_box: float = 0.1
    key_passes: float = 0.2
    passes_into_box: float = 0.15
    progressive_passes_completed: float = 0.1
    progressive_carries: float = 0.1
    ball_recoveries: float = 0.05
    interceptions: float = 0.05
    pressures: float = 0.02
    clearances: float = 0.0
    errors_bad_passes: float = -0.05
    errors_dispossessed: float = -0.1
    errors_fouls_committed: float = -0.05
    errors_miscontrols: float = -0.08

    def as_dict(self) -> dict[str, float]:
        out = {
            "base": self.base,
            "score_scale": self.score_scale,
            "home_advantage": self.home_advantage,
            "saturation_k": self.saturation_k,
        }
        for feature in FEATURES:
            out[feature] = getattr(self, feature)
        return out

    def clipped(self) -> "VectorParams":
        values = self.as_dict()
        values["base"] = min(76.0, max(56.0, values["base"]))
        values["score_scale"] = min(25.0, max(0.5, values["score_scale"]))
        values["home_advantage"] = min(3.0, max(-3.0, values["home_advantage"]))
        values["saturation_k"] = min(5.0, max(0.1, values["saturation_k"]))
        for feature in FEATURES:
            if feature in ERROR_FEATURES:
                values[feature] = min(0.0, max(-4.0, values[feature]))
            else:
                values[feature] = min(4.0, max(0.0, values[feature]))
        return VectorParams(**values)


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


def vector_scores(sample: VectorZoneSample, params: VectorParams) -> tuple[float, float]:
    weights = [getattr(params, feature) for feature in FEATURES]
    k = max(1e-6, params.saturation_k)
    total = 0.0
    n = 0
    # sample.zones_away is already mirrored at load time, so zip pairs a home
    # zone with the opponent's defensive (mirrored) zone — a specular duel.
    for home_vec, away_vec in zip(sample.zones_home, sample.zones_away):
        margin = sum(weights[i] * (home_vec[i] - away_vec[i]) for i in range(len(FEATURES)))
        total += k * math.tanh(margin / k)  # saturating per-zone outcome
        n += 1
    total_margin = total / max(1, n)
    home = params.base + params.home_advantage + params.score_scale * total_margin
    away = params.base - params.home_advantage - params.score_scale * total_margin
    return home, away


def objective(
    samples: list[VectorZoneSample],
    params: VectorParams,
    *,
    tau: float,
    sign_weight: float,
    diff_weight: float,
    draw_weight: float,
    sign_tau: float,
    regularization: float,
    prior: VectorParams,
) -> float:
    if not samples:
        return 0.0
    total = 0.0
    for sample in samples:
        home_score, away_score = vector_scores(sample, params)
        pred_home = soft_goals(home_score, tau)
        pred_away = soft_goals(away_score, tau)
        goal_loss = (pred_home - sample.real_home_goals) ** 2 + (pred_away - sample.real_away_goals) ** 2
        diff_loss = ((pred_home - pred_away) - (sample.real_home_goals - sample.real_away_goals)) ** 2
        real_sign = sign(sample.real_home_goals, sample.real_away_goals)
        score_diff = home_score - away_score
        if real_sign == 0:
            sign_loss = draw_weight * (score_diff / 6.0) ** 2
        else:
            sign_loss = math.log1p(math.exp(-real_sign * score_diff / sign_tau))
        total += goal_loss + diff_weight * diff_loss + sign_weight * sign_loss

    p = params.as_dict()
    q = prior.as_dict()
    reg = 0.0
    for key, value in p.items():
        scale = 6.0 if key in {"base", "score_scale"} else 1.0
        reg += ((value - q[key]) / scale) ** 2
    return total / len(samples) + regularization * reg


def spsa_gradient(samples: list[VectorZoneSample], params: VectorParams, *, rng: random.Random, perturbation: float, **kwargs) -> dict[str, float]:
    names = list(params.as_dict())
    base = params.as_dict()
    delta = {name: (1.0 if rng.random() >= 0.5 else -1.0) for name in names}
    scales = {name: 1.0 for name in names}
    scales["base"] = 4.0
    scales["score_scale"] = 4.0
    scales["home_advantage"] = 1.0

    plus = base.copy()
    minus = base.copy()
    for name in names:
        step = perturbation * scales[name] * delta[name]
        plus[name] += step
        minus[name] -= step

    loss_plus = objective(samples, VectorParams(**plus).clipped(), **kwargs)
    loss_minus = objective(samples, VectorParams(**minus).clipped(), **kwargs)
    return {
        name: (loss_plus - loss_minus) / (2.0 * perturbation * scales[name] * delta[name])
        for name in names
    }


def metrics(samples: list[VectorZoneSample], params: VectorParams, tau: float) -> dict[str, float]:
    if not samples:
        return {"matches": 0}
    soft_abs = 0.0
    soft_wdl = 0
    soft_diff_abs = 0.0
    soft_goal_sum = 0.0
    real_goal_sum = 0
    for sample in samples:
        home_score, away_score = vector_scores(sample, params)
        pred_home = soft_goals(home_score, tau)
        pred_away = soft_goals(away_score, tau)
        soft_abs += abs(pred_home - sample.real_home_goals) + abs(pred_away - sample.real_away_goals)
        soft_diff_abs += abs((pred_home - pred_away) - (sample.real_home_goals - sample.real_away_goals))
        soft_wdl += int(sign(pred_home, pred_away) == sign(sample.real_home_goals, sample.real_away_goals))
        soft_goal_sum += pred_home + pred_away
        real_goal_sum += sample.real_home_goals + sample.real_away_goals
    n = len(samples)
    return {
        "matches": n,
        "soft_goal_mae_per_team": soft_abs / (2.0 * n),
        "soft_wdl_accuracy": soft_wdl / n,
        "soft_goal_diff_mae": soft_diff_abs / n,
        "soft_avg_pred_goals_per_team": soft_goal_sum / (2.0 * n),
        "avg_real_goals_per_team": real_goal_sum / (2.0 * n),
    }


class Command(BaseCommand):
    help = "Calibrate an experimental vector-based zone duel model from TeamZoneFeature."

    def add_arguments(self, parser):
        parser.add_argument("--epochs", type=int, default=300)
        parser.add_argument("--learning-rate", type=float, default=0.025)
        parser.add_argument("--perturbation", type=float, default=0.08)
        parser.add_argument("--tau", type=float, default=1.25)
        parser.add_argument("--sign-weight", type=float, default=6.0)
        parser.add_argument("--diff-weight", type=float, default=1.0)
        parser.add_argument("--draw-weight", type=float, default=0.5)
        parser.add_argument("--sign-tau", type=float, default=4.0)
        parser.add_argument("--regularization", type=float, default=0.03)
        parser.add_argument("--validation-mod", type=int, default=5)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--output", type=str, default="calibration/vector_zone_duel_v1.json")
        parser.add_argument("--no-write", action="store_true")

    def handle(self, *args, **options):
        samples, feature_scales = self._load_samples()
        validation_mod = int(options["validation_mod"])
        train = [sample for sample in samples if sample.match_id % validation_mod != 0]
        validation = [sample for sample in samples if sample.match_id % validation_mod == 0]

        prior = VectorParams()
        params = VectorParams()
        best_params = VectorParams(**params.as_dict())
        best_validation_loss = float("inf")
        tau = float(options["tau"])
        kwargs = {
            "tau": tau,
            "sign_weight": float(options["sign_weight"]),
            "diff_weight": float(options["diff_weight"]),
            "draw_weight": float(options["draw_weight"]),
            "sign_tau": float(options["sign_tau"]),
            "regularization": float(options["regularization"]),
            "prior": prior,
        }

        self.stdout.write(f"samples={len(samples)} train={len(train)} validation={len(validation)}")
        self.stdout.write(f"feature_scales={json.dumps(feature_scales, sort_keys=True)}")
        self.stdout.write(f"initial_metrics={json.dumps(metrics(samples, params, tau), sort_keys=True)}")

        lr = float(options["learning_rate"])
        epochs = int(options["epochs"])
        rng = random.Random(int(options["seed"]))
        adam_m = {name: 0.0 for name in params.as_dict()}
        adam_v = {name: 0.0 for name in params.as_dict()}
        beta1 = 0.9
        beta2 = 0.999
        eps = 1e-8

        for epoch in range(1, epochs + 1):
            grads = spsa_gradient(
                train,
                params,
                rng=rng,
                perturbation=float(options["perturbation"]) / math.sqrt(epoch),
                **kwargs,
            )
            values = params.as_dict()
            for name, grad in grads.items():
                adam_m[name] = beta1 * adam_m[name] + (1.0 - beta1) * grad
                adam_v[name] = beta2 * adam_v[name] + (1.0 - beta2) * grad * grad
                m_hat = adam_m[name] / (1.0 - beta1**epoch)
                v_hat = adam_v[name] / (1.0 - beta2**epoch)
                values[name] -= lr * m_hat / (math.sqrt(v_hat) + eps)
            params = VectorParams(**values).clipped()

            validation_loss = objective(validation, params, **kwargs)
            if validation_loss < best_validation_loss:
                best_validation_loss = validation_loss
                best_params = VectorParams(**params.as_dict())
            if epoch == 1 or epoch % 50 == 0 or epoch == epochs:
                train_loss = objective(train, params, **kwargs)
                self.stdout.write(
                    f"epoch={epoch} train_loss={train_loss:.4f} validation_loss={validation_loss:.4f} "
                    f"params={params.as_dict()}"
                )

        result = {
            "formula_version": "vector_zone_duel_v2_specular_saturating",
            "features": list(FEATURES),
            "feature_scales": feature_scales,
            "loss": {
                **{k: v for k, v in kwargs.items() if k != "prior"},
                "validation_mod": validation_mod,
            },
            "params": best_params.as_dict(),
            "metrics": {
                "train": metrics(train, best_params, tau),
                "validation": metrics(validation, best_params, tau),
                "all": metrics(samples, best_params, tau),
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

    def _load_samples(self) -> tuple[list[VectorZoneSample], dict[str, float]]:
        raw: dict[int, dict[str, dict[str, dict[str, float]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
        )
        match_goals: dict[int, tuple[int, int]] = {}
        for match in Match.objects.filter(home_goals__isnull=False, away_goals__isnull=False).only("id", "home_goals", "away_goals"):
            match_goals[match.id] = (int(match.home_goals or 0), int(match.away_goals or 0))

        for match_id, side, zone_key, feature_key, value in TeamZoneFeature.objects.filter(
            match_id__in=match_goals,
            feature_key__in=FEATURES,
        ).values_list("match_id", "team_side", "zone_key", "feature_key", "value"):
            raw[int(match_id)][str(zone_key)][str(side)][str(feature_key)] += float(value or 0.0)

        max_values = {feature: 1e-9 for feature in FEATURES}
        for zones in raw.values():
            for sides in zones.values():
                for side in (SIDE_HOME, SIDE_AWAY):
                    for feature in FEATURES:
                        max_values[feature] = max(max_values[feature], sides[side][feature])

        zone_keys = sorted({zone for zones in raw.values() for zone in zones})
        samples: list[VectorZoneSample] = []
        for match_id, zones in raw.items():
            home_vectors = []
            away_vectors = []
            for zone_key in zone_keys:
                home_sides = zones[zone_key]
                # Away contribution to this physical zone comes from its mirrored
                # (opponent-frame) zone, so the duel is specular.
                away_sides = zones[mirror_zone(zone_key)]
                home_vectors.append(tuple(home_sides[SIDE_HOME][feature] / max_values[feature] for feature in FEATURES))
                away_vectors.append(tuple(away_sides[SIDE_AWAY][feature] / max_values[feature] for feature in FEATURES))
            home_goals, away_goals = match_goals[match_id]
            samples.append(
                VectorZoneSample(
                    match_id=match_id,
                    zones_home=tuple(home_vectors),
                    zones_away=tuple(away_vectors),
                    real_home_goals=home_goals,
                    real_away_goals=away_goals,
                )
            )
        samples.sort(key=lambda sample: sample.match_id)
        return samples, max_values

