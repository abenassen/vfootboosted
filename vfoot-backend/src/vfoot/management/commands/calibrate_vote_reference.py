"""Freeze the per-role vote calibration from a COMPLETED season.

The voto puro centres each role on 6 by z-scoring against its peers' mean and
spread. Computed from the running season those move as results arrive, so a 6 in
September would not equal a 6 in May and matchday 1 would have no scale at all.
This calibrates them ONCE, on a finished season, and writes them to a versioned
file the scorer reads forever after (see services/vote_reference.py).

Run it when the season used for calibration is complete, and again whenever the
weights change — never during a season in progress.

    python manage.py calibrate_vote_reference --season 2
    python manage.py calibrate_vote_reference --season 2 --dry-run
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from realdata.models import CompetitionSeason, Match
from vfoot.services.classic_pagella import compute_role_averages
from vfoot.services.classic_rating import (
    build_feature_scales, build_reference, clear_scales_cache,
    reference_population_keyed,
)
from vfoot.services import goal_impact as gi
from vfoot.services import goal_impact_calibration as gic
from vfoot.services.vote_reference import (
    REFERENCE_PATH, clear_cache, save, weights_fingerprint,
)


class Command(BaseCommand):
    help = "Freeze the per-role voto-puro reference from a completed season."

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, required=True,
                            help="CompetitionSeason to calibrate on (a COMPLETED one).")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        cs = CompetitionSeason.objects.filter(id=o["season"]).first()
        if cs is None:
            raise CommandError(f"No CompetitionSeason id={o['season']}")

        total = Match.objects.filter(competition_season=cs).count()
        finished = Match.objects.filter(competition_season=cs,
                                        status=Match.STATUS_FINISHED).count()
        if finished < total:
            self.stdout.write(self.style.WARNING(
                f"Attenzione: {finished}/{total} partite concluse. La reference "
                "andrebbe calibrata su una stagione FINITA, non in corso."))

        # ORDER MATTERS. The per-feature spreads come first, because both the role
        # reference and the explanation's role averages are computed FROM the index,
        # and the index cannot be computed before the standardisation is fixed. They
        # are passed explicitly rather than read back from the file, which at this
        # point still holds the previous calibration.
        scales = build_feature_scales(cs.id)
        reference = build_reference(cs.id, scales=scales)
        averages = compute_role_averages(cs.id, scales=scales)
        if not reference:
            raise CommandError("Nessun dato: impossibile calibrare.")

        self.stdout.write(f"Calibrazione su '{cs}' ({finished} partite):")
        for role in ("POR", "DIF", "CEN", "ATT"):
            r = reference.get(role)
            if r:
                self.stdout.write(f"   {role}: media {r['mean']:.3f}  "
                                  f"dev.std {r['std']:.3f}  (n={r['n']})")
        for chan, sc in sorted(scales.items()):
            self.stdout.write(f"   scale {chan}: {len(sc)} feature standardizzate")
        # --- IMPATTO DEI GOL -------------------------------------------------
        # Dopo la reference e non prima: la banda si risolve contro quanto vale
        # GIA' una marcatura senza il credito del gol, e quel residuo si misura
        # con l'indice nuovo, che senza la reference non produce voti.
        timelines, skipped = gic.season_timelines(cs.id)
        xp = gi.build_xp_table(timelines)
        self.stdout.write(f"impatto gol: {len(timelines)} partite riconciliate"
                          + (f" ({skipped} scartate: cronologia dei gol incoerente"
                             " col risultato)" if skipped else "")
                          + f", {len(xp)} stati campionati")
        imps = gic.season_importances(cs.id, xp)
        population = [(k, role) for k, role, _f, _m, _e
                      in reference_population_keyed(cs.id)]
        pop_keys = {k for k, _r in population}
        scoring = {k: v for k, v in imps.items() if k in pop_keys}
        residual = self._residual_mean(cs.id, reference, scales, scoring)
        band, p95 = gic.solve_band(imps, scoring, residual)
        means = gic.role_mean_credit(population, imps, band, p95)
        self.stdout.write(
            f"   marcature nella popolazione: {len(scoring)}   "
            f"residuo sga+volume {residual:+.4f}   bersaglio "
            f"{gic.TARGET_TOTAL_25_26:+.4f}")
        self.stdout.write(f"   banda {band}  p95 {p95}  medie di ruolo {means}")
        goal_impact = {"xp": xp, "band": list(band), "p95": p95,
                       "role_mean_credit": means}

        self.stdout.write(f"fingerprint pesi: {weights_fingerprint()}")

        if o["dry_run"]:
            self.stdout.write("[dry-run] nulla scritto")
            return
        save(reference, averages, season_id=cs.id, feature_scales=scales,
             goal_impact=goal_impact)
        clear_cache()
        clear_scales_cache()
        self.stdout.write(self.style.SUCCESS(f"Scritto {REFERENCE_PATH}"))

    def _residual_mean(self, cs_id, reference, scales, scoring):
        """Quanto vale una marcatura SENZA il credito del gol: l'sga e il volume
        del tiro che l'ha prodotta, col modello nuovo.

        Si misura per differenza — il voto con quei gol meno il voto senza — e non
        sommando delle voci, perche' la compressione non e' additiva e una somma di
        contributi non e' il salto che il voto fa davvero.
        """
        import copy
        import statistics as st

        from realdata.models import MatchShot
        from vfoot.services.classic_rating import (
            _raw_vote_from_index, index_for_role, reference_population_keyed,
        )

        shots = {}
        for s in MatchShot.objects.filter(
                match__competition_season_id=cs_id, is_goal=True).values(
                "match_id", "player_id", "xg", "xgot"):
            shots.setdefault((s["match_id"], s["player_id"]), []).append(s)

        def without_goals(feats, goals):
            t = copy.deepcopy(feats)
            for g in goals:
                t["shots"] = (t.get("shots") or 0) - 1
                t["xg_shots"] = (t.get("xg_shots") or 0.0) - g["xg"]
                t["xg_on_target"] = (t.get("xg_on_target") or 0.0) - g["xgot"]
                t["shots_on_target"] = (t.get("shots_on_target") or 0) - 1
                t["shots_goal"] = (t.get("shots_goal") or 0) - 1
            return t

        deltas = []
        for key, role, feats, mins, exp in reference_population_keyed(cs_id):
            goals = shots.get(key)
            if key not in scoring or not goals:
                continue
            chan = scales.get("gk" if role == "POR" else "outfield")
            a = _raw_vote_from_index(index_for_role(role, feats, mins, exp, chan),
                                     role, mins, reference)
            b = _raw_vote_from_index(
                index_for_role(role, without_goals(feats, goals), mins, exp, chan),
                role, mins, reference)
            deltas.append(a - b)
        return st.fmean(deltas) if deltas else 0.0
