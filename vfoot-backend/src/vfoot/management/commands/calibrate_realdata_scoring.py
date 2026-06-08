from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from django.core.management.base import BaseCommand

from realdata.models import Match, SIDE_AWAY, SIDE_HOME
from vfoot.services.realdata_scoring import compute_real_match_zone_duels, starting_player_ids_for_real_match


GOAL_THRESHOLDS = (66.0, 72.0, 78.0, 84.0, 90.0, 96.0)


@dataclass(frozen=True)
class CalibrationRow:
    match_id: int
    raw_home: float
    raw_away: float
    real_home_goals: int
    real_away_goals: int


@dataclass
class CalibrationParams:
    scale: float = 1.0
    offset: float = 8.0
    home_advantage: float = 0.5
    diff_boost: float = 0.25

    def as_dict(self) -> dict[str, float]:
        return {
            "scale": self.scale,
            "offset": self.offset,
            "home_advantage": self.home_advantage,
            "diff_boost": self.diff_boost,
        }

    def clipped(self) -> "CalibrationParams":
        return CalibrationParams(
            scale=min(1.25, max(0.75, self.scale)),
            offset=min(18.0, max(0.0, self.offset)),
            home_advantage=min(2.0, max(-2.0, self.home_advantage)),
            diff_boost=min(3.0, max(0.0, self.diff_boost)),
        )


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


def adjusted_scores(row: CalibrationRow, params: CalibrationParams) -> tuple[float, float]:
    diff = row.raw_home - row.raw_away
    home = row.raw_home * params.scale + params.offset + params.home_advantage + params.diff_boost * diff
    away = row.raw_away * params.scale + params.offset - params.home_advantage - params.diff_boost * diff
    return home, away


def objective(
    rows: list[CalibrationRow],
    params: CalibrationParams,
    *,
    tau: float,
    diff_weight: float,
    sign_weight: float,
    draw_weight: float,
    sign_tau: float,
    regularization: float,
    prior: CalibrationParams,
) -> float:
    if not rows:
        return 0.0
    total = 0.0
    for row in rows:
        adj_home, adj_away = adjusted_scores(row, params)
        pred_home = soft_goals(adj_home, tau)
        pred_away = soft_goals(adj_away, tau)
        goal_loss = (pred_home - row.real_home_goals) ** 2 + (pred_away - row.real_away_goals) ** 2
        diff_loss = ((pred_home - pred_away) - (row.real_home_goals - row.real_away_goals)) ** 2
        real_sign = sign(row.real_home_goals, row.real_away_goals)
        score_diff = adj_home - adj_away
        if real_sign == 0:
            sign_loss = draw_weight * (score_diff / 6.0) ** 2
        else:
            # Smooth hinge/logistic loss. Low when adjusted score diff has the same sign as the real result.
            sign_loss = math.log1p(math.exp(-real_sign * score_diff / sign_tau))
        total += goal_loss + diff_weight * diff_loss + sign_weight * sign_loss

    reg = (
        (params.scale - prior.scale) ** 2
        + ((params.offset - prior.offset) / 6.0) ** 2
        + (params.home_advantage - prior.home_advantage) ** 2
        + (params.diff_boost - prior.diff_boost) ** 2
    )
    return total / len(rows) + regularization * reg


def finite_difference_gradient(
    rows: list[CalibrationRow],
    params: CalibrationParams,
    *,
    tau: float,
    diff_weight: float,
    sign_weight: float,
    draw_weight: float,
    sign_tau: float,
    regularization: float,
    prior: CalibrationParams,
) -> dict[str, float]:
    steps = {
        "scale": 0.002,
        "offset": 0.02,
        "home_advantage": 0.02,
        "diff_boost": 0.02,
    }
    base = params.as_dict()
    grads: dict[str, float] = {}
    for name, step in steps.items():
        plus = base.copy()
        minus = base.copy()
        plus[name] += step
        minus[name] -= step
        p_plus = CalibrationParams(**plus).clipped()
        p_minus = CalibrationParams(**minus).clipped()
        loss_plus = objective(
            rows,
            p_plus,
            tau=tau,
            diff_weight=diff_weight,
            sign_weight=sign_weight,
            draw_weight=draw_weight,
            sign_tau=sign_tau,
            regularization=regularization,
            prior=prior,
        )
        loss_minus = objective(
            rows,
            p_minus,
            tau=tau,
            diff_weight=diff_weight,
            sign_weight=sign_weight,
            draw_weight=draw_weight,
            sign_tau=sign_tau,
            regularization=regularization,
            prior=prior,
        )
        grads[name] = (loss_plus - loss_minus) / (2.0 * step)
    return grads


def metrics(rows: list[CalibrationRow], params: CalibrationParams) -> dict[str, float]:
    if not rows:
        return {
            "matches": 0,
            "goal_mae_per_team": 0.0,
            "wdl_accuracy": 0.0,
            "exact_scoreline_accuracy": 0.0,
            "avg_pred_goals_per_team": 0.0,
            "avg_real_goals_per_team": 0.0,
        }
    total_abs = 0.0
    wdl_hits = 0
    exact_hits = 0
    pred_goal_sum = 0
    real_goal_sum = 0
    soft_abs = 0.0
    soft_wdl_hits = 0
    soft_diff_abs = 0.0
    soft_goal_sum = 0.0
    for row in rows:
        adj_home, adj_away = adjusted_scores(row, params)
        soft_home = soft_goals(adj_home, 1.25)
        soft_away = soft_goals(adj_away, 1.25)
        pred_home = hard_goals(adj_home)
        pred_away = hard_goals(adj_away)
        total_abs += abs(pred_home - row.real_home_goals) + abs(pred_away - row.real_away_goals)
        wdl_hits += int(sign(pred_home, pred_away) == sign(row.real_home_goals, row.real_away_goals))
        soft_wdl_hits += int(sign(soft_home, soft_away) == sign(row.real_home_goals, row.real_away_goals))
        exact_hits += int(pred_home == row.real_home_goals and pred_away == row.real_away_goals)
        pred_goal_sum += pred_home + pred_away
        real_goal_sum += row.real_home_goals + row.real_away_goals
        soft_goal_sum += soft_home + soft_away
        soft_abs += abs(soft_home - row.real_home_goals) + abs(soft_away - row.real_away_goals)
        soft_diff_abs += abs((soft_home - soft_away) - (row.real_home_goals - row.real_away_goals))

    n = len(rows)
    return {
        "matches": n,
        "soft_goal_mae_per_team": soft_abs / (2.0 * n),
        "soft_wdl_accuracy": soft_wdl_hits / n,
        "soft_goal_diff_mae": soft_diff_abs / n,
        "soft_avg_pred_goals_per_team": soft_goal_sum / (2.0 * n),
        "goal_mae_per_team": total_abs / (2.0 * n),
        "wdl_accuracy": wdl_hits / n,
        "exact_scoreline_accuracy": exact_hits / n,
        "avg_pred_goals_per_team": pred_goal_sum / (2.0 * n),
        "avg_real_goals_per_team": real_goal_sum / (2.0 * n),
    }


class Command(BaseCommand):
    help = "Calibrate real-data Vfoot score conversion against historical StatsBomb match results."

    def add_arguments(self, parser):
        parser.add_argument("--epochs", type=int, default=250)
        parser.add_argument("--learning-rate", type=float, default=0.04)
        parser.add_argument("--tau", type=float, default=1.25)
        parser.add_argument("--diff-weight", type=float, default=0.35)
        parser.add_argument("--sign-weight", type=float, default=0.0)
        parser.add_argument("--draw-weight", type=float, default=0.5)
        parser.add_argument("--sign-tau", type=float, default=4.0)
        parser.add_argument("--regularization", type=float, default=0.02)
        parser.add_argument("--validation-mod", type=int, default=5)
        parser.add_argument("--output", type=str, default="calibration/realdata_scoring_v1_conversion.json")
        parser.add_argument("--no-write", action="store_true")

    def handle(self, *args, **options):
        rows = self._load_rows()
        if not rows:
            self.stdout.write(self.style.ERROR("No realdata rows available for calibration."))
            return

        validation_mod = int(options["validation_mod"])
        train_rows = [row for row in rows if row.match_id % validation_mod != 0]
        validation_rows = [row for row in rows if row.match_id % validation_mod == 0]

        prior = CalibrationParams()
        params = CalibrationParams()
        best_params = params
        best_validation_loss = float("inf")

        lr = float(options["learning_rate"])
        tau = float(options["tau"])
        diff_weight = float(options["diff_weight"])
        sign_weight = float(options["sign_weight"])
        draw_weight = float(options["draw_weight"])
        sign_tau = float(options["sign_tau"])
        regularization = float(options["regularization"])
        epochs = int(options["epochs"])

        adam_m = {name: 0.0 for name in params.as_dict()}
        adam_v = {name: 0.0 for name in params.as_dict()}
        beta1 = 0.9
        beta2 = 0.999
        eps = 1e-8

        for epoch in range(1, epochs + 1):
            grads = finite_difference_gradient(
                train_rows,
                params,
                tau=tau,
                diff_weight=diff_weight,
                sign_weight=sign_weight,
                draw_weight=draw_weight,
                sign_tau=sign_tau,
                regularization=regularization,
                prior=prior,
            )
            values = params.as_dict()
            for name, grad in grads.items():
                adam_m[name] = beta1 * adam_m[name] + (1.0 - beta1) * grad
                adam_v[name] = beta2 * adam_v[name] + (1.0 - beta2) * grad * grad
                m_hat = adam_m[name] / (1.0 - beta1**epoch)
                v_hat = adam_v[name] / (1.0 - beta2**epoch)
                values[name] -= lr * m_hat / (math.sqrt(v_hat) + eps)
            params = CalibrationParams(**values).clipped()

            validation_loss = objective(
                validation_rows,
                params,
                tau=tau,
                diff_weight=diff_weight,
                sign_weight=sign_weight,
                draw_weight=draw_weight,
                sign_tau=sign_tau,
                regularization=regularization,
                prior=prior,
            )
            if validation_loss < best_validation_loss:
                best_validation_loss = validation_loss
                best_params = CalibrationParams(**params.as_dict())

            if epoch == 1 or epoch % 25 == 0 or epoch == epochs:
                train_loss = objective(
                    train_rows,
                    params,
                    tau=tau,
                    diff_weight=diff_weight,
                    sign_weight=sign_weight,
                    draw_weight=draw_weight,
                    sign_tau=sign_tau,
                    regularization=regularization,
                    prior=prior,
                )
                self.stdout.write(
                    f"epoch={epoch} train_loss={train_loss:.4f} "
                    f"validation_loss={validation_loss:.4f} params={params.as_dict()}"
                )

        result = {
            "formula_version": "realdata_scoring_v1_conversion_gd",
            "goal_thresholds": list(GOAL_THRESHOLDS),
            "soft_goal_tau": tau,
            "loss": {
                "diff_weight": diff_weight,
                "draw_weight": draw_weight,
                "regularization": regularization,
                "sign_tau": sign_tau,
                "sign_weight": sign_weight,
                "validation_mod": validation_mod,
            },
            "params": best_params.as_dict(),
            "metrics": {
                "train": metrics(train_rows, best_params),
                "validation": metrics(validation_rows, best_params),
                "all": metrics(rows, best_params),
            },
        }

        self.stdout.write(self.style.SUCCESS("Best calibrated params:"))
        self.stdout.write(json.dumps(result, indent=2, sort_keys=True))

        if not options["no_write"]:
            out_path = Path(options["output"])
            if not out_path.is_absolute():
                out_path = Path.cwd().parent / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote {out_path}"))

    def _load_rows(self) -> list[CalibrationRow]:
        rows: list[CalibrationRow] = []
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
            home_player_ids = starting_player_ids_for_real_match(match, SIDE_HOME)
            away_player_ids = starting_player_ids_for_real_match(match, SIDE_AWAY)
            if len(home_player_ids) < 8 or len(away_player_ids) < 8:
                continue
            payload = compute_real_match_zone_duels(
                match=match,
                home_player_ids=home_player_ids[:11],
                away_player_ids=away_player_ids[:11],
            )
            rows.append(
                CalibrationRow(
                    match_id=match.id,
                    raw_home=float(payload["score"]["home_total"]),
                    raw_away=float(payload["score"]["away_total"]),
                    real_home_goals=int(match.home_goals or 0),
                    real_away_goals=int(match.away_goals or 0),
                )
            )
        return rows
