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
from vfoot.services.classic_rating import build_minute_curves, flatten_minute_curves
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
        parser.add_argument("--no-flatten", action="store_true",
                            help="non correggere le curve dei minuti sul residuo "
                                 "esterno (v. flatten_minute_curves)")
        parser.add_argument("--external-dir", default=None,
                            help="cartella degli xlsx del giudice; default: "
                                 "data_fantacalcio/<stagione>")

    def _external_votes(self, cs, directory=None) -> dict:
        """{"<giornata>:<player_id>": voto} dal foglio del giudice.

        Riusa il lettore di ``compare_external_votes`` invece di riscriverlo: il
        formato del foglio e l'aggancio dei nomi sono gia' un problema risolto una
        volta, e risolverlo due volte vuol dire vederlo divergere.
        """
        import glob
        import re
        from pathlib import Path
        from django.conf import settings
        from realdata.services.identity import norm_name
        from vfoot.management.commands.compare_external_votes import (
            Command as Ext, _club_key)

        ext = Ext()
        base = directory or str(Path(settings.VFOOT_DATA_DIR) / "data_fantacalcio"
                                / str(cs).split()[-1])
        files = sorted(glob.glob(f"{base}/*.xlsx"))
        if not files:
            return {}
        team_map = ext._our_team_index(cs.id)
        pidx = ext._our_player_index(cs.id)
        gd_re = re.compile(r"Giornata_(\d+)")
        out = {}
        for f in files:
            mm = gd_re.search(f)
            if not mm:
                continue
            gd = int(mm.group(1))
            for e in ext._parse_file(f, "Fantacalcio"):
                team = team_map.get(_club_key(e["team"] or ""))
                if not team or e["voto"] is None:
                    continue
                surn = norm_name(e["nome"]).split()[-1] if e["nome"] else ""
                cands = pidx.get((team, surn), [])
                if len(cands) == 1:
                    out[f"{gd}:{cands[0]}"] = e["voto"]
        return out

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
        # Le curve indice-vs-minuti, DOPO la reference perche' ci si appoggiano
        # (le medie di ruolo restano quelle) e prima di scriverla: v.
        # classic_rating.build_minute_curves.
        build_minute_curves(cs.id, reference, scales=scales)
        if not reference:
            raise CommandError("Nessun dato: impossibile calibrare.")

        # LA CURVA DEI MINUTI SI TARA, NON SI OSSERVA E BASTA. Misurata sul solo
        # indice fa il suo mestiere male fra i 46 e i 70 minuti, dove il 95% delle
        # presenze sono titolari SOSTITUITI: per loro il poco minutaggio non e' una
        # circostanza da perdonare ma la conseguenza di aver giocato male, e la
        # curva li perdona lo stesso. Si corregge sul residuo contro un giudizio
        # esterno (v. classic_rating.flatten_minute_curves).
        #
        # I FOGLI SONO UN INGRESSO DI CALIBRAZIONE, NON UNA DIPENDENZA DEL MODELLO:
        # quel che finisce nel file e' una curva come le sigma e i centri, e nessuno
        # a valle sa da dove viene. E non si sta copiando il giudizio sul MERITO —
        # per quello il modello diverge apposta — ma si usa un metro esterno per una
        # cosa che merito non e': quanto pesi aver giocato sessanta minuti invece di
        # novanta.
        if not o["no_flatten"]:
            external = self._external_votes(cs, o["external_dir"])
            if not external:
                self.stdout.write(self.style.WARNING(
                    "   curve dei minuti NON corrette: nessun voto esterno trovato. "
                    "La calibrazione e' valida ma l'inclinazione per fascia resta."))
            else:
                residuo = flatten_minute_curves(cs.id, reference, external)
                if residuo:
                    peggio = max(residuo.items(), key=lambda kv: abs(kv[1]))
                    self.stdout.write(
                        f"   curve dei minuti corrette su {len(external)} voti esterni: "
                        f"residuo massimo {peggio[1]:+.3f} al {peggio[0]}'")

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
        # L'ASSIST, sulla stessa importanza e con la stessa disciplina: banda
        # risolta contro il credito medio di prima, media di ruolo da sottrarre.
        a_imps = gic.season_assist_importances(cs.id, xp)
        a_scoring = {k: v for k, v in a_imps.items() if k in pop_keys}
        a_band = gic.solve_assist_band(a_imps, a_scoring)
        a_means = gic.role_mean_credit(population, a_imps, a_band, p95)
        self.stdout.write(
            f"   assist agganciati a un gol: {len(a_imps)} presenze   "
            f"banda {a_band}   medie di ruolo {a_means}")
        flat_imps = [i for v in imps.values() for i in v if i is not None]
        mean_imp = round(sum(flat_imps) / len(flat_imps), 4) if flat_imps else 0.0
        goal_impact = {"xp": xp, "band": list(band), "p95": p95,
                       "role_mean_credit": means,
                       "assist_band": list(a_band),
                       "role_mean_assist_credit": a_means,
                       # per la ricaduta degli assist non agganciati
                       "mean_importance": mean_imp}

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
