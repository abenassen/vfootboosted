"""Fit the goalkeeper channel to Fantacalcio.it Statistico without overfitting it.

This command only writes a JSON proposal.  Applying a proposal still requires the
normal reviewed edit of ``GK_TOTAL_WEIGHTS`` / ``GK_PER90_WEIGHTS`` followed by
``calibrate_vote_reference``.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from realdata.models import Match
from vfoot.management.commands.voto_puro_discrepancies import Command as Discrepancies
from vfoot.services import classic_rating as cr
from vfoot.services.goalkeeper_tuning import GoalkeeperBench, bootstrap_delta, pearson


class Command(BaseCommand):
    help = "Propone pesi POR regolarizzati verso il modello in produzione."

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, default=2)
        parser.add_argument("--dir", default=None,
                            help="Cartella dei fogli Fantacalcio 2025-26.")
        parser.add_argument("--regularization", type=float, default=0.10,
                            help="λ della distanza quadratica relativa dai pesi deployati.")
        parser.add_argument("--out", default="/tmp/goalkeeper_weight_proposal.json")

    def handle(self, *args, **options):
        season = options["season"]
        directory = options["dir"] or str(
            Path(settings.VFOOT_DATA_DIR) / "data_fantacalcio" / "2025-2026")
        files = sorted(glob.glob(f"{directory}/*.xlsx"))
        if not files:
            raise CommandError(f"Nessun foglio .xlsx in {directory}")

        bench = GoalkeeperBench(season)
        by_md_pid = {}
        mids = list(Match.objects.filter(competition_season_id=season)
                    .values_list("id", "matchday"))
        for mid, md in mids:
            # A player can only have one real match in a matchday; the key is the
            # same identity used by voto_puro_discrepancies to match Statistico.
            by_md_pid[mid] = md
        totals = cr._per_match_player_totals([mid for mid, _ in mids])
        minutes = cr._minutes_map([mid for mid, _ in mids])

        rows = Discrepancies().discrepancy_rows(season, files)
        vectors, mins, targets, matchdays = [], [], [], []
        for row in rows:
            if row["role"] != "POR" or row["statistico"] is None or (row["minutes"] or 0) < 60:
                continue
            candidates = [(mid, pid) for (mid, pid) in totals
                          if pid == row["pid"] and by_md_pid.get(mid) == row["gd"]]
            if len(candidates) != 1:
                continue
            mid, pid = candidates[0]
            vectors.append(bench.vector(totals[(mid, pid)], minutes[(mid, pid)]))
            mins.append(minutes[(mid, pid)])
            targets.append(float(row["statistico"]))
            matchdays.append(row["gd"])
        if len(targets) < 20:
            raise CommandError(f"Solo {len(targets)} portieri appaiati con Statistico (minimo 20)")

        z = np.asarray(vectors, dtype=float)
        mins = np.asarray(mins, dtype=float)
        targets = np.asarray(targets, dtype=float)
        matchdays = np.asarray(matchdays, dtype=int)
        # Temporal holdout: fit on the first 75% of matchdays and report the last
        # quarter untouched.  The final proposal is still refit on all observations
        # after the hyperparameters have been chosen on the training side.
        split = int(np.quantile(np.unique(matchdays), 0.75, method="lower"))
        train = matchdays <= split
        test = ~train
        if test.sum() < 20:
            raise CommandError("holdout temporale troppo piccolo")
        fit_train = bench.alternating_fit(
            z[train], mins[train], targets[train], options["regularization"])
        hp = fit_train["hyperparameters"]
        wt_train = np.array([fit_train["weights"][key] for key in bench.keys])
        base_test = bench.predict(bench.w0, z[test], mins[test])
        cand_test = bench.calibrated_predict(
            wt_train, z[train], mins[train], targets[train], z[test], mins[test],
            hp["minute_conditioning"], hp["shrinkage_minutes"], hp["flatten_strength"])
        # Refit on the complete season only after the holdout measurement.
        proposal = bench.alternating_fit(
            z, mins, targets, options["regularization"])
        wt = np.array([proposal["weights"][key] for key in bench.keys])
        base_full = bench.predict(bench.w0, z, mins)
        cand_full = bench.predict(
            wt, z, mins, targets, proposal["hyperparameters"]["minute_conditioning"],
            proposal["hyperparameters"]["shrinkage_minutes"],
            proposal["hyperparameters"]["flatten_strength"])
        proposal["baseline"] = {
            "correlation": float(pearson(base_full, targets)),
            "holdout_correlation": float(pearson(base_test, targets[test])),
        }
        proposal["candidate"]["holdout_correlation"] = float(
            pearson(cand_test, targets[test]))
        proposal["significance"] = {
            "full": bootstrap_delta(base_full, cand_full, targets),
            "holdout": bootstrap_delta(base_test, cand_test, targets[test]),
            "holdout_matchdays": {"train_through": split,
                                   "test_from": int(matchdays[test].min()),
                                   "test_to": int(matchdays[test].max()),
                                   "n_train": int(train.sum()), "n_test": int(test.sum())},
        }
        proposal["weight_changes"] = {
            key: {"production": float(bench.w0[i]), "candidate": float(wt[i]),
                  "delta": float(wt[i] - bench.w0[i]),
                  "relative_delta": (float((wt[i] - bench.w0[i]) / bench.w0[i])
                                     if bench.w0[i] else None),
                  "standardised_drift": float(((wt[i] - bench.w0[i]) /
                                                max(abs(bench.w0[i]), 0.10)) ** 2)}
            for i, key in enumerate(bench.keys)}
        proposal["training_fit"] = {
            "hyperparameters": fit_train["hyperparameters"],
            "weights": fit_train["weights"],
            "candidate": fit_train["candidate"],
        }
        proposal["weight_stability"] = {
            key: {"train": float(fit_train["weights"][key]),
                  "full": float(proposal["weights"][key]),
                  "train_full_delta": float(proposal["weights"][key]
                                              - fit_train["weights"][key])}
            for key in bench.keys}
        proposal.update({"season": season, "target": "Fantacalcio Statistico",
                         "method": "alternating weights/hyperparameters + post-vote flattening + regularised relative L2",
                         "applied": False})
        out = Path(options["out"])
        out.write_text(json.dumps(proposal, indent=2, sort_keys=True) + "\n")
        self.stdout.write(self.style.SUCCESS(
            "POR: n={n}, corr {old:.4f} → {new:.4f}, drift={drift:.4f}; proposta: {out}".format(
                n=proposal["n"], old=proposal["baseline"]["correlation"],
                new=proposal["candidate"]["correlation"],
                drift=proposal["candidate"]["drift"], out=out)))
