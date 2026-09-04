"""Automatic, regularised tuning of the goalkeeper vote channel.

This is the keeper counterpart of the movement ``vote_tuning`` bank.  A candidate
always rebuilds the GK reference and the post-vote minute flattening before it is
scored.  The fitter is deliberately a development tool: it returns a proposal and
never changes ``classic_rating``.
"""
from __future__ import annotations

import math

import numpy as np

from realdata.models import Match, Player
from vfoot.services import classic_rating as cr


def pearson(actual: np.ndarray, target: np.ndarray) -> float:
    actual, target = np.asarray(actual, float), np.asarray(target, float)
    if actual.size < 2 or actual.std() == 0 or target.std() == 0:
        return float("nan")
    return float(np.corrcoef(actual, target)[0, 1])


class GoalkeeperBench:
    """A frozen matrix of keeper appearances, independent of candidate weights."""

    def __init__(self, season_id: int):
        self.season_id = season_id
        self.keys = list(cr.GK_WEIGHTS)
        self.w0 = np.array([cr.GK_WEIGHTS[k] for k in self.keys], dtype=float)
        self.scales = cr.feature_scales(gk=True)

        population, pop_minutes = [], []
        for role, totals, minutes, _exposure in cr._reference_population(season_id):
            if role == Player.ROLE_GK:
                population.append(self.vector(totals, minutes))
                pop_minutes.append(minutes)
        if len(population) < 2:
            raise ValueError("servono almeno due presenze POR nella reference")
        self.population = np.asarray(population, dtype=float)
        self.population_minutes = np.asarray(pop_minutes, dtype=float)

        # The post-vote curve is learned from every rated keeper appearance, not
        # just the >=20' reference population (same distinction as the movement
        # bank).  It is populated once; only the index changes with the weights.
        mids = list(Match.objects.filter(competition_season_id=season_id)
                    .values_list("id", flat=True))
        totals = cr._per_match_player_totals(mids)
        minutes = cr._minutes_map(mids)
        roles = cr.current_role_map(only_declared=True)
        val_z, val_minutes = [], []
        for (mid, pid), feats in totals.items():
            if roles.get(pid) != Player.ROLE_GK:
                continue
            mins = minutes.get((mid, pid), 0)
            if mins <= 0 or not cr.is_rated(mins, feats):
                continue
            val_z.append(self.vector(feats, mins)); val_minutes.append(mins)
        self.curve_z = np.asarray(val_z, dtype=float)
        self.curve_minutes = np.asarray(val_minutes, dtype=float)

    def vector(self, totals: dict, minutes: int) -> np.ndarray:
        values = cr.raw_feature_values(totals, minutes, gk=True)
        return np.array([cr.scored_z(k, values.get(k, 0.0), self.scales)
                         for k in self.keys], dtype=float)

    @staticmethod
    def _reference(population_z: np.ndarray, weights: np.ndarray) -> dict:
        index = population_z @ weights
        return {"mean": float(index.mean()), "std": float(index.std()) or 1.0,
                "n": int(len(index))}

    def _minute_curve(self, weights: np.ndarray) -> dict[int, float]:
        if not len(self.curve_z):
            return {}
        index = self.curve_z @ weights
        out = {}
        for minute in range(1, 130):
            mask = np.abs(self.curve_minutes - minute) <= cr.MINUTE_CURVE_WINDOW
            if int(mask.sum()) >= cr.MINUTE_CURVE_MIN_N:
                out[minute] = float(index[mask].mean())
        return out

    def _raw(self, weights: np.ndarray, z: np.ndarray, minutes: np.ndarray,
             ref: dict, minute_conditioning: float, shrinkage: float,
             curve: dict[int, float] | None = None) -> np.ndarray:
        index = z @ weights
        curve = curve or {}
        shifts = np.array([minute_conditioning *
                           (curve.get(int(m), ref["mean"]) - ref["mean"])
                           for m in minutes])
        evidence = minutes / (minutes + shrinkage)
        raw = (cr.vote_center_for(Player.ROLE_GK) + cr.GK_SPREAD_K * evidence
               * ((index - ref["mean"] - shifts) / ref["std"]))
        return np.clip(raw, cr.VOTE_MIN, cr.VOTE_MAX)

    def _flatten(self, base: np.ndarray, target: np.ndarray, minutes: np.ndarray,
                 ref: dict, minute_conditioning: float, shrinkage: float,
                 strength: float) -> dict[int, float]:
        """Post-vote correction, identical in form to ``appiattisci``.

        Residuals use the half-point vote grid, as the production calibration does.
        ``strength`` is an explicit hyperparameter so the sparse GK sample can keep
        the correction close to zero if it does not replicate out of sample.
        """
        if strength <= 0 or minute_conditioning <= 0:
            return {}
        residual = np.round(base * 2.0) / 2.0 - target
        out = {}
        for minute in range(1, 100):
            mask = np.abs(minutes - minute) <= cr.MINUTE_CURVE_WINDOW
            if int(mask.sum()) < cr.MINUTE_CURVE_MIN_N:
                continue
            w = minute / (minute + shrinkage)
            out[minute] = (strength * float(residual[mask].mean()) * ref["std"]
                           / (cr.GK_SPREAD_K * w * minute_conditioning))
        return out

    def predict(self, weights: np.ndarray, z: np.ndarray, minutes: np.ndarray,
                target: np.ndarray | None = None, minute_conditioning: float = 0.0,
                shrinkage: float = cr.SHRINKAGE_MINUTES,
                flatten_strength: float = 1.0) -> np.ndarray:
        ref = self._reference(self.population, weights)
        curve = self._minute_curve(weights)
        base = self._raw(weights, z, minutes, ref, minute_conditioning, shrinkage, curve)
        if target is not None:
            corrections = self._flatten(base, target, minutes, ref,
                                        minute_conditioning, shrinkage, flatten_strength)
            curve = {**curve, **corrections}
        return self._raw(weights, z, minutes, ref, minute_conditioning, shrinkage, curve)

    def calibrated_predict(self, weights: np.ndarray, z_cal: np.ndarray,
                           minutes_cal: np.ndarray, target_cal: np.ndarray,
                           z_eval: np.ndarray, minutes_eval: np.ndarray,
                           minute_conditioning: float, shrinkage: float,
                           flatten_strength: float) -> np.ndarray:
        """Predict a split using flattening learned on calibration data.

        Keeping the residual correction on the calibration side is essential: using
        evaluation votes to build it would make a seemingly impressive correlation
        a target leak.
        """
        ref = self._reference(self.population, weights)
        curve = self._minute_curve(weights)
        base_cal = self._raw(weights, z_cal, minutes_cal, ref,
                             minute_conditioning, shrinkage, curve)
        curve.update(self._flatten(base_cal, target_cal, minutes_cal, ref,
                                   minute_conditioning, shrinkage, flatten_strength))
        return self._raw(weights, z_eval, minutes_eval, ref,
                         minute_conditioning, shrinkage, curve)

    def objective(self, weights: np.ndarray, z: np.ndarray, minutes: np.ndarray,
                  target: np.ndarray, minute_conditioning: float,
                  shrinkage: float, flatten_strength: float,
                  regularization: float) -> tuple[float, float, float]:
        pred = self.predict(weights, z, minutes, target, minute_conditioning,
                            shrinkage, flatten_strength)
        corr = pearson(pred, target)
        if math.isnan(corr):
            return 1e6, corr, float("inf")
        scale = np.maximum(np.abs(self.w0), 0.10)
        drift = float(np.mean(((weights - self.w0) / scale) ** 2))
        return -corr + regularization * drift, corr, drift

    def fit_weights(self, z: np.ndarray, minutes: np.ndarray, target: np.ndarray,
                    minute_conditioning: float, shrinkage: float,
                    flatten_strength: float, regularization: float) -> dict:
        """Optimise only the weights while all hyperparameters are fixed."""
        try:
            from scipy.optimize import minimize
        except ImportError as exc:
            raise RuntimeError("serve scipy per l'ottimizzazione dei portieri") from exc
        bounds = [(0.0, None) if w >= 0 else (None, 0.0) for w in self.w0]
        result = minimize(
            lambda w: self.objective(w, z, minutes, target, minute_conditioning,
                                     shrinkage, flatten_strength, regularization)[0],
            self.w0, method="L-BFGS-B", bounds=bounds,
            options={"maxiter": 1500, "ftol": 1e-12})
        loss, corr, drift = self.objective(
            result.x, z, minutes, target, minute_conditioning, shrinkage,
            flatten_strength, regularization)
        return {"weights": result.x, "loss": loss, "correlation": corr,
                "drift": drift, "success": bool(result.success),
                "message": str(result.message)}

    def alternating_fit(self, z: np.ndarray, minutes: np.ndarray, target: np.ndarray,
                        regularization: float = 0.10,
                        conditioning_grid=(0.0, 0.25, 0.5, 0.75, 1.0),
                        shrinkage_grid=(15.0, 25.0, 35.0),
                        flatten_grid=(0.0, 0.5, 1.0), rounds: int = 2) -> dict:
        """Alternate weight optimisation and hyperparameter selection."""
        current = (0.0, float(cr.SHRINKAGE_MINUTES), 0.0)
        weights = self.w0.copy()
        history = []
        for _round in range(max(1, rounds)):
            fitted = self.fit_weights(z, minutes, target, *current, regularization)
            weights = fitted["weights"]
            candidates = []
            for conditioning in conditioning_grid:
                for shrinkage in shrinkage_grid:
                    for flatten in flatten_grid:
                        loss, corr, drift = self.objective(
                            weights, z, minutes, target, conditioning, shrinkage,
                            flatten, regularization)
                        candidates.append((loss, conditioning, shrinkage, flatten,
                                           corr, drift))
            best = min(candidates, key=lambda row: row[0])
            current = best[1:4]
            history.append({"round": _round + 1,
                            "weights": {"values": {k: float(fitted["weights"][i])
                                                       for i, k in enumerate(self.keys)},
                                        "correlation": fitted["correlation"],
                                        "drift": fitted["drift"],
                                        "loss": fitted["loss"]},
                            "best_hyperparameters": {
                                "minute_conditioning": current[0],
                                "shrinkage_minutes": current[1],
                                "flatten_strength": current[2]},
                            "correlation": best[4], "drift": best[5]})
        fitted = self.fit_weights(z, minutes, target, *current, regularization)
        return {"weights": {k: float(fitted["weights"][i])
                             for i, k in enumerate(self.keys)},
                "hyperparameters": {"minute_conditioning": current[0],
                                     "shrinkage_minutes": current[1],
                                     "flatten_strength": current[2]},
                "candidate": {"correlation": fitted["correlation"],
                               "drift": fitted["drift"], "loss": fitted["loss"]},
                "history": history, "success": fitted["success"],
                "message": fitted["message"], "regularization": regularization,
                "n": int(len(target))}


def bootstrap_delta(baseline: np.ndarray, candidate: np.ndarray, target: np.ndarray,
                    *, seed: int = 0, n: int = 2000) -> dict:
    """Paired bootstrap for correlation improvement (not a causal p-value)."""
    rng = np.random.default_rng(seed)
    deltas = np.empty(n)
    idx = np.arange(len(target))
    for i in range(n):
        sample = rng.choice(idx, size=len(idx), replace=True)
        deltas[i] = pearson(candidate[sample], target[sample]) - pearson(
            baseline[sample], target[sample])
    lo, hi = np.quantile(deltas, [0.025, 0.975])
    return {"delta": float(pearson(candidate, target) - pearson(baseline, target)),
            "ci95": [float(lo), float(hi)],
            "p_nonpositive": float(np.mean(deltas <= 0)), "resamples": n}
