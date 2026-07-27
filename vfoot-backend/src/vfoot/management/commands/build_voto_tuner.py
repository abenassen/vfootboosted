"""Build the interactive voto-puro weight tuner spreadsheet.

    python manage.py build_voto_tuner                 # -> <repo>/voto_puro_tuner.xlsx
    python manage.py build_voto_tuner --season 2 --cases 24 --out /path/file.xlsx

An analyst opens the sheet and edits the WEIGHTS (Tuner!C): the voto puro of every
selected case recomputes live via spreadsheet formulas (μ/σ per role are rebuilt
from a stored covariance matrix, so no Python round-trip). It replaces a pile of
throwaway scripts — hence a real, versioned command rather than a temp file.

Design notes:
  * features = the deployed outfield vector (TOTAL + PER90 + defensive exposure)
    plus the shot-outcome detail (post/goal/save/miss/block, weight 0) so the
    SGA_Pali paradigm can be reconstructed by hand from the weights.
  * the √ compression toggle applies √ ONLY to PER90 features; TOTAL/exposure/shot
    detail stay linear (integer counts stay integer, xG/xGOT stay linear).
  * cases are chosen for DISCREPANCY with fantacalcio, and deliberately span
    scorers and heavy defeats — fantacalcio ties the base vote to the result, our
    voto puro does not, and that is exactly where they part ways.
"""
from __future__ import annotations

import glob
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import openpyxl
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter as col
from openpyxl.worksheet.datavalidation import DataValidation

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import vfoot.services.classic_rating as cr
from realdata.models import Match, MatchAppearance, Player, Team
from vfoot.management.commands.voto_puro_discrepancies import Command as DiscCmd

OUT_ROLES = ["DIF", "CEN", "ATT"]
SHOTMAP = {"post": "shots_post", "goal": "shots_goal", "save": "shots_saved",
           "miss": "shots_off", "block": "shots_blocked"}
# Provider stats we ingest but do not weight — shown at weight 0 for inspection.
# (crosses_completed / dribbles_attempted are now weighted; possession_lost was
# dropped as 79% redundant with the errors_* it overlaps — see PER90_WEIGHTS.)
# big_chance_created/missed were dropped (goal now weighted via shots_goal) — they're
# TOTAL events, not shown here (UNUSED is treated as PER90); re-add to TOTAL_WEIGHTS.
UNUSED = ["tackles", "possession_lost"]
# Emblematic cases to always show, tagged by disagreement type:
#   "DISAC. 2x"    — we disagree with BOTH fantacalcio and SofaScore. Scorers who
#                    also wasted chances: the goal is our +3 bonus, not the base
#                    vote, and both benchmarks apply a scoring halo we don't.
#   "DISAC. fanta" — we disagree with fantacalcio but SofaScore AGREES with us:
#                    individual merit in a team defeat vs fanta's collective punishment.
FORCED = [
    (1072, 11, "DISAC. 2x"),     # Delprato (DIF) 1 gol, 2 big chance mancate
    (1101, 36, "DISAC. 2x"),     # Malen (ATT) 2 gol ma sprechi
    (768, 11, "DISAC. 2x"),      # Berardi (CEN) 2 gol
    (1188, 10, "DISAC. 2x"),     # Castro (ATT) 2 gol
    (934, 28, "DISAC. 2x"),      # Bowie (ATT) 1 gol
    (740, 29, "DISAC. 2x"),      # Simeone (ATT) 1 gol
    (1002, 25, "DISAC. 2x"),     # Loyola (CEN) 1 gol + rigore concesso
    (926, 37, "DISAC. fanta"),   # Edmundsson (DIF) SofaScore 9.1 conferma noi
    (907, 21, "DISAC. fanta"),   # Koopmeiners (CEN)
    (1160, 33, "DISAC. fanta"),  # Buongiorno (DIF)
]

TEAL = "1F5C53"; YEL = "FFF2CC"
CF_GREEN = ("C6EFCE", "006100"); CF_YEL = ("FFEB9C", "9C6500"); CF_RED = ("FFC7CE", "9C0006")


class Command(BaseCommand):
    help = "Build the interactive voto-puro weight tuner spreadsheet."

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, default=2)
        parser.add_argument("--cases", type=int, default=24,
                            help="Target number of case columns (emblematic + Statistico "
                                 "discrepancies + fillers).")
        parser.add_argument("--dir", default=None,
                            help="Folder with the external fantacalcio .xlsx sheets.")
        parser.add_argument("--out", default=None,
                            help="Output path (default <repo>/voto_puro_tuner.xlsx).")

    def handle(self, *args, **o):
        cs = o["season"]
        out = o["out"] or str(Path(__file__).resolve().parents[5] / "voto_puro_tuner.xlsx")
        ddir = o["dir"] or str(Path(settings.VFOOT_DATA_DIR) / "data_fantacalcio" / "2025-2026")
        files = sorted(glob.glob(f"{ddir}/*.xlsx"))
        if not files:
            raise CommandError(f"No fantacalcio .xlsx in {ddir}")

        # ---- feature set (deployed + shot detail) ----
        TOTAL = list(cr.TOTAL_WEIGHTS)
        PER90 = list(cr.PER90_WEIGHTS) + UNUSED
        # shots_post / shots_blocked are now WEIGHTED TOTAL features (their values
        # arrive via _per_match_player_totals); only the UNWEIGHTED shot outcomes go
        # here, shown at weight 0 for inspection — else they'd be double-counted.
        SHOTDET = [f for f in SHOTMAP.values() if f not in cr.TOTAL_WEIGHTS]
        FEATS = TOTAL + PER90 + ["_exposure"] + SHOTDET
        nF = len(FEATS)
        is_p90 = {f: (f in PER90) for f in FEATS}
        # √ on PER90 and on the √-TOTAL features (shots_goal: diminishing returns).
        sqmask = np.array([is_p90[f] or f in cr.SQRT_TOTAL_FEATURES for f in FEATS])
        curw = {**cr.TOTAL_WEIGHTS, **cr.PER90_WEIGHTS}

        def w_of(f):
            return -cr.DEF_EXPOSURE_WEIGHT if f == "_exposure" else curw.get(f, 0.0)

        # ---- per-match data ----
        mids = list(Match.objects.filter(competition_season_id=cs).values_list("id", flat=True))
        md_of = {m.id: m.matchday for m in Match.objects.filter(competition_season_id=cs)}
        # _per_match_player_totals already merges the shot-outcome detail (post/goal/
        # save/miss/block), with own goals excluded from shots_goal — so no manual
        # re-injection here (it would re-count own goals as goals scored).
        totals = cr._per_match_player_totals(mids)
        minutes = cr._minutes_map(mids)
        expo = cr.defensive_exposure(mids, minutes)
        gd_on_map = cr.on_pitch_goal_difference(mids, minutes)

        roles = {p: r for p, r in cr.current_role_map().items() if r}
        teamname = {t.id: t.name for t in Team.objects.all()}
        # match result + player side (for margin / heavy-loss selection)
        mgoals = {m.id: (m.home_goals, m.away_goals)
                  for m in Match.objects.filter(competition_season_id=cs)}
        side_of = dict(MatchAppearance.objects.filter(match__competition_season_id=cs)
                       .values_list("id", "side")) if False else {}
        side_of = {(a["match_id"], a["player_id"]): a["side"]
                   for a in MatchAppearance.objects
                   .filter(match__competition_season_id=cs)
                   .values("match_id", "player_id", "side")}

        def scaledraw(tot, m, ex, role):
            sc = 90.0 / max(m, cr.EXTRAP_FLOOR_MINUTES)
            v = []
            for f in FEATS:
                if f == "_exposure":
                    v.append(ex if role == "DIF" else 0.0)
                elif is_p90[f]:
                    v.append(tot.get(f, 0.0) * sc)
                else:
                    v.append(tot.get(f, 0.0))
            return np.array(v)

        def sqrtv(M):
            return np.where(sqmask, np.sign(M) * np.sqrt(np.abs(M)), M)

        # ---- population -> per-role mean/cov (raw + selective-√) ----
        pop = defaultdict(list)
        gp2mp = {}
        for (mid, pid), tot in totals.items():
            role = roles.get(pid)
            if role not in OUT_ROLES:
                continue
            m = minutes.get((mid, pid), 0)
            gp2mp[(md_of.get(mid), pid)] = (mid, pid)
            if m < cr.MIN_MINUTES_REFERENCE or not cr.is_rated(m, tot):
                continue
            pop[role].append(scaledraw(tot, m, expo.get((mid, pid), 0.0), role))
        STATS = {}
        for role in OUT_ROLES:
            R = np.array(pop[role]); Sq = sqrtv(R)
            STATS[role] = {"mean_raw": R.mean(0), "cov_raw": np.cov(R.T),
                           "mean_sqrt": Sq.mean(0), "cov_sqrt": np.cov(Sq.T)}

        # ---- discrepancy rows (reuses the external-sheet parsing) ----
        rows = DiscCmd().discrepancy_rows(cs, files)
        name = {p.id: (p.short_name or p.full_name) for p in Player.objects.all()}

        def margin(gd, pid):
            mp = gp2mp.get((gd, pid))
            if not mp:
                return 0
            mid, _ = mp
            hg, ag = mgoals.get(mid, (0, 0))
            return (hg - ag) if side_of.get((mid, pid)) == "home" else (ag - hg)

        cand = []
        for r in rows:
            if (r["minutes"] or 0) < 60 or r["role"] not in OUT_ROLES:
                continue
            # need our vote and at least one external benchmark to compare against
            if (r["gd"], r["pid"]) not in gp2mp or r["our"] is None:
                continue
            if r["fanta"] is None and r["statistico"] is None:
                continue
            r = {**r,
                 "absd": abs(r["our"] - r["fanta"]) if r["fanta"] is not None else 0.0,
                 "absd_stat": (abs(r["our"] - r["statistico"])
                               if r["statistico"] is not None else None),
                 "margin": margin(r["gd"], r["pid"])}
            cand.append(r)

        # ---- case selection (dedup by player) ----
        sel, seen = [], set()

        def take(r, tipo):
            if r["pid"] in seen:
                return False
            sel.append({**r, "tipo": tipo}); seen.add(r["pid"]); return True

        by_key = {(r["gd"], r["pid"]): r for r in cand}
        for pid, gd, tag in FORCED:                              # emblematic cases
            r = by_key.get((gd, pid))
            if r:
                take(r, tag)
        # THE STRANGE-VOTE HUNT: biggest gaps vs the Statistico base vote. Statistico
        # is the goal-stripped algorithmic grade, so a large gap here is a pure
        # performance-read disagreement — exactly the votes to sanity-check.
        n = 0
        for r in sorted([x for x in cand if x["absd_stat"] is not None],
                        key=lambda x: -x["absd_stat"]):
            if take(r, "DISAC. stat"):
                n += 1
            if n >= 10:
                break
        # scorers with a base-vote discrepancy
        n = 0
        for r in sorted([x for x in cand if x["goals"]], key=lambda x: -x["absd"]):
            if take(r, "GOL"):
                n += 1
            if n >= 5:
                break
        # heavy defeat, we are high, fanta is low: the result-correlation gap
        n = 0
        for r in sorted([x for x in cand if x["margin"] <= -3 and x["our"] >= 6.5
                         and x["fanta"] <= 5.5], key=lambda x: -x["our"]):
            if take(r, "KO netto"):
                n += 1
            if n >= 4:
                break
        # top discrepancy per role
        for role in OUT_ROLES:
            n = 0
            for r in sorted([x for x in cand if x["role"] == role], key=lambda x: -x["absd"]):
                if take(r, "OUTLIER"):
                    n += 1
                if n >= 2:
                    break
        # a couple of good-agreement anchors per role (sanity)
        for role in OUT_ROLES:
            n = 0
            for r in sorted([x for x in cand if x["role"] == role and x["absd"] <= 0.3
                             and 5.6 <= x["our"] <= 7.6], key=lambda x: x["absd"]):
                if take(r, "buono"):
                    n += 1
                if n >= 1:
                    break
        sel = sel[:o["cases"]]

        casedata = []
        for r in sel:
            gd, pid = r["gd"], r["pid"]
            mid, _ = gp2mp[(gd, pid)]; tot = totals[(mid, pid)]; m = minutes[(mid, pid)]
            role = roles[pid]; sd = scaledraw(tot, m, expo.get((mid, pid), 0.0), role)
            M = Match.objects.get(id=mid)
            res = f"gd{gd}: {teamname.get(M.home_team_id,'?')} {M.home_goals}-{M.away_goals} {teamname.get(M.away_team_id,'?')}"
            if r["goals"]:
                res += f" · {r['goals']}⚽"
            casedata.append({"name": name.get(pid, str(pid)), "tipo": r["tipo"], "role": role,
                             "min": m, "match": res, "goals": r["goals"], "raw": sd,
                             "sqrt": sqrtv(sd), "fanta": r["fanta"], "stat": r["statistico"],
                             "sofa": r["sofa"], "our": r["our"],
                             "expl": r.get("explanation_text", ""),
                             # weight-independent inputs to the post-adjustment layer
                             "gd_on": gd_on_map.get((mid, pid), 0),
                             "red_adj": round(cr.red_card_adjustments(mid).get(pid, 0.0)
                                              + cr.own_goal_adjustments(mid).get(pid, 0.0), 3)})
        casedata.sort(key=lambda c: (OUT_ROLES.index(c["role"]), c["tipo"], c["name"]))

        # ---- the discrepancy ledger: top gaps vs Statistico, with our text ----
        expl_rows, seen_e = [], set()
        for r in sorted([x for x in cand if x["absd_stat"] is not None],
                        key=lambda x: -x["absd_stat"]):
            if r["pid"] in seen_e:
                continue
            seen_e.add(r["pid"])
            mid, _ = gp2mp[(r["gd"], r["pid"])]
            M = Match.objects.get(id=mid)
            expl_rows.append({
                "name": name.get(r["pid"], str(r["pid"])), "role": r["role"], "gd": r["gd"],
                "match": (f"{teamname.get(M.home_team_id,'?')} {M.home_goals}-{M.away_goals} "
                          f"{teamname.get(M.away_team_id,'?')}"),
                "goals": r["goals"], "assists": r["assists"],
                "our": r["our"], "stat": r["statistico"], "fanta": r["fanta"],
                "delta": round(r["our"] - r["statistico"], 1),
                "expl": r.get("explanation_text", "") or "(nessuna voce sopra soglia)"})
            if len(expl_rows) >= 30:
                break

        self._build_xlsx(out, FEATS, nF, is_p90, w_of, STATS, casedata, expl_rows)
        self.stdout.write(self.style.SUCCESS(
            f"scritto {out} | casi: {len(casedata)} "
            f"(gol: {sum(1 for c in casedata if c['goals'])}, "
            f"KO netto: {sum(1 for c in casedata if c['tipo']=='KO netto')})"))

    # ------------------------------------------------------------------
    def _build_xlsx(self, out, FEATS, nF, is_p90, w_of, STATS, casedata, expl_rows=()):
        wb = openpyxl.Workbook()
        fillh = PatternFill("solid", fgColor=TEAL); yel = PatternFill("solid", fgColor=YEL)

        # ---- ref: means as COLUMNS + covariance blocks ----
        ref = wb.create_sheet("ref")
        meancol = {}
        for ci, (role, k) in enumerate([(r, k) for r in OUT_ROLES for k in ("raw", "sqrt")]):
            c = 2 + ci; meancol[(role, k)] = col(c)
            ref.cell(1, c, f"{role}_{k}")
            for i, v in enumerate(STATS[role]["mean_" + k]):
                ref.cell(2 + i, c, float(v))
        covpos = {}; rr = nF + 4
        for role in OUT_ROLES:
            for k in ("raw", "sqrt"):
                covpos[(role, k)] = rr; C = STATS[role]["cov_" + k]
                for i in range(nF):
                    for j in range(nF):
                        ref.cell(rr, 2 + j, float(C[i, j]))
                    rr += 1
                rr += 1

        def meanrng(role, k):
            return f"ref!${meancol[(role,k)]}$2:${meancol[(role,k)]}${1+nF}"

        def covrng(role, k):
            p = covpos[(role, k)]
            return f"ref!$B${p}:${col(1+nF)}${p+nF-1}"

        # ---- calc: w_outer + mu/sigma ----
        calc = wb.create_sheet("calc")
        for i in range(nF):
            for j in range(nF):
                calc.cell(2 + i, 2 + j, f"=Tuner!$C${7+i}*Tuner!$C${7+j}")
        wouter = f"calc!$B$2:${col(1+nF)}${1+nF}"; wvec = f"Tuner!$C$7:$C${6+nF}"
        murow = {}; rr = nF + 4
        for role in OUT_ROLES:
            calc.cell(rr, 1, role)
            calc.cell(rr, 2, f"=SUMPRODUCT({wvec},{meanrng(role,'raw')})")
            calc.cell(rr, 3, f"=SUMPRODUCT({wvec},{meanrng(role,'sqrt')})")
            calc.cell(rr, 4, f"=SQRT(SUMPRODUCT({covrng(role,'raw')},{wouter}))")
            calc.cell(rr, 5, f"=SQRT(SUMPRODUCT({covrng(role,'sqrt')},{wouter}))")
            murow[role] = rr; rr += 1

        # ---- cases: feature vectors + highlight + per-role mean/var/σ ----
        cs = wb.create_sheet("cases")

        def zfill(v, mean, var):
            if var <= 0:
                return None
            z = (v - mean) / (var ** 0.5)
            if z >= 2: return PatternFill("solid", fgColor="ED7D31")
            if z >= 1: return PatternFill("solid", fgColor="FFD966")
            if z <= -2: return PatternFill("solid", fgColor="2E75B6")
            if z <= -1: return PatternFill("solid", fgColor="9DC3E6")
            return None
        for ci, c in enumerate(casedata):
            S = STATS[c["role"]]
            for i in range(nF):
                rc = cs.cell(2 + i, 2 + ci, float(c["raw"][i])); rc.number_format = "0.00"
                f = zfill(c["raw"][i], S["mean_raw"][i], S["cov_raw"][i, i])
                if f: rc.fill = f
                qc = cs.cell(2 + nF + 2 + i, 2 + ci, float(c["sqrt"][i])); qc.number_format = "0.00"
                f2 = zfill(c["sqrt"][i], S["mean_sqrt"][i], S["cov_sqrt"][i, i])
                if f2: qc.fill = f2

        def craw(ci): return f"cases!${col(2+ci)}$2:${col(2+ci)}${1+nF}"
        def csq(ci): return f"cases!${col(2+ci)}${2+nF+2}:${col(2+ci)}${1+2*nF+2}"
        cs["A1"] = "RAW block v (per-90 scaled)"; cs.cell(nF + 3, 1, "SQRT block v")
        for i, f in enumerate(FEATS):
            cs.cell(2 + i, 1, f); cs.cell(nF + 4 + i, 1, f)
        for ci, c in enumerate(casedata):
            cs.cell(1, 2 + ci, c["name"]).font = Font(bold=True)
            cs.cell(nF + 3, 2 + ci, c["name"]).font = Font(bold=True)
        base = 2 + len(casedata) + 1
        for j, role in enumerate(OUT_ROLES):
            mc = base + 3 * j; vc = mc + 1; sc = mc + 2
            for hr in (1, nF + 3):
                cs.cell(hr, mc, f"{role} media").font = Font(bold=True, color=TEAL)
                cs.cell(hr, vc, f"{role} var").font = Font(bold=True, color=TEAL)
                cs.cell(hr, sc, f"{role} σ").font = Font(bold=True, color=TEAL)
            for i in range(nF):
                vr = STATS[role]["cov_raw"][i, i]; vs = STATS[role]["cov_sqrt"][i, i]
                cs.cell(2 + i, mc, round(float(STATS[role]["mean_raw"][i]), 3))
                cs.cell(2 + i, vc, round(float(vr), 4)); cs.cell(2 + i, sc, round(float(vr) ** 0.5, 3))
                cs.cell(nF + 4 + i, mc, round(float(STATS[role]["mean_sqrt"][i]), 3))
                cs.cell(nF + 4 + i, vc, round(float(vs), 4)); cs.cell(nF + 4 + i, sc, round(float(vs) ** 0.5, 3))
        cs.cell(2 * nF + 6, 1, "Evidenziazione (vs media del RUOLO del caso): ambra=+1σ "
                "arancio=+2σ (alto); azzurro=-1σ blu=-2σ (basso). Colonne a destra: "
                "media/var/σ per ruolo.").font = Font(italic=True, size=9)
        cs.column_dimensions["A"].width = 22
        for ci in range(len(casedata)):
            cs.column_dimensions[col(2 + ci)].width = 11
        for j in range(9):
            cs.column_dimensions[col(base + j)].width = 10

        # ---- Tuner ----
        tun = wb.create_sheet("Tuner"); wb.move_sheet("Tuner", -(len(wb.sheetnames) - 1))
        tun["A1"] = "VOTO PURO — tuner dei pesi"; tun["A1"].font = Font(bold=True, size=14)
        tun["A2"] = ("Edita i PESI (col C, celle gialle) e K mitigazione (B5). Interruttore "
                     "RAW/SQRT in B4. Il VOTO FINALE (riga 24) si colora: verde=accordo, "
                     "giallo=borderline, rosso=outlier.")
        tun["A3"] = ("Pipeline: voto base = 6+0.8·(min/(min+25))·(indice−media)/σ in [3,10]; "
                     "poi + mitigazione risultato (solo divergenze, cap ±1) + red/autogol; "
                     "poi clamp [3,10] e arrotondamento 0.5. gd_on e red/autogol sono FISSI "
                     "(non dipendono dai pesi). SQRT applica √ alle PER90 e a shots_goal "
                     "(rendimento decrescente sui gol multipli).")
        tun["A4"] = "compressione:"; tun["B4"] = "SQRT"; tun["B4"].font = Font(bold=True); tun["B4"].fill = yel
        dv = DataValidation(type="list", formula1='"RAW,SQRT"'); tun.add_data_validation(dv); dv.add(tun["B4"])
        tun["A5"] = "K mitigazione:"; tun["B5"] = cr.RESULT_MITIGATION_K
        tun["C5"] = "base sc/vitt:"; tun["D5"] = cr.RESULT_MITIGATION_BASE
        for cell in ("B5", "D5"):
            tun[cell].font = Font(bold=True); tun[cell].fill = yel
            tun[cell].number_format = "0.00"
        tun["A6"] = "feature"; tun["B6"] = "tipo"; tun["C6"] = "PESO"
        for cc in ("A6", "B6", "C6"):
            tun[cc].font = Font(bold=True, color="FFFFFF"); tun[cc].fill = fillh
        for i, f in enumerate(FEATS):
            tun.cell(7 + i, 1, f)
            tun.cell(7 + i, 2, "PER90" if is_p90[f] else ("EXPOS" if f == "_exposure" else "TOT"))
            wc = tun.cell(7 + i, 3, round(w_of(f), 3)); wc.fill = yel; wc.number_format = "0.000"
        TOG = "Tuner!$B$4"; KM = "Tuner!$B$5"; BB = "Tuner!$D$5"; c0 = 5
        rowlab = [(7, "giocatore"), (8, "TIPO"), (9, "ruolo"), (10, "partita (gd, risultato, gol)"),
                  (11, "minuti"), (12, "fanta"), (13, "statistico"), (14, "sofascore"),
                  (15, "nostro(attuale)"), (16, "indice"), (17, "media INDICE ruolo"),
                  (18, "sigma INDICE ruolo"), (19, "gd_on (in campo)"), (20, "red/autogol (fisso)"),
                  (21, "voto base"), (22, "mitigazione"), (24, "VOTO FINALE (live)")]
        for rr2, lab in rowlab:
            tun.cell(rr2, c0, lab).font = Font(bold=True, size=9)
        for ci, c in enumerate(casedata):
            cc = c0 + 1 + ci; L = col(cc); mr = murow[c["role"]]
            tun.cell(7, cc, c["name"]).font = Font(bold=True)
            _tipo_fill = {"buono": "C9E7DF", "DISAC. 2x": "F8CBAD",
                          "DISAC. fanta": "FFE699"}.get(c["tipo"], "F7ECDD")
            tun.cell(8, cc, c["tipo"]).fill = PatternFill("solid", fgColor=_tipo_fill)
            tun.cell(9, cc, c["role"]); tun.cell(10, cc, c["match"]); tun.cell(11, cc, c["min"])
            tun.cell(12, cc, c["fanta"]); tun.cell(13, cc, c["stat"] if c["stat"] is not None else "-")
            tun.cell(14, cc, c["sofa"] if c["sofa"] is not None else "-"); tun.cell(15, cc, c["our"])
            tun.cell(16, cc, f'=IF({TOG}="SQRT",SUMPRODUCT({wvec},{csq(ci)}),SUMPRODUCT({wvec},{craw(ci)}))')
            tun.cell(17, cc, f'=IF({TOG}="SQRT",calc!$C${mr},calc!$B${mr})')
            tun.cell(18, cc, f'=IF({TOG}="SQRT",calc!$E${mr},calc!$D${mr})')
            tun.cell(19, cc, c["gd_on"])
            tun.cell(20, cc, c["red_adj"])
            # voto base (clamp [3,10], pre-arrotondamento)
            tun.cell(21, cc, f'=MAX(3,MIN(10,6+0.8*({L}11/({L}11+25))*(({L}16-{L}17)/{L}18)))')
            # mitigazione: solo divergenze, gravità = base + K·|gd_on|, cap ±1.
            #   sconfitta (gd_on<0): voto alto scende di (voto-6)·(base+K·|gd_on|)
            #   vittoria  (gd_on>0): voto basso sale di (6-voto)·(base+K·gd_on)
            tun.cell(22, cc,
                     f'=MAX(-1,MIN(1,IF({L}19<0,-MAX(0,{L}21-6)*({BB}+{KM}*(-{L}19)),'
                     f'IF({L}19>0,MAX(0,6-{L}21)*({BB}+{KM}*{L}19),0))))')
            # voto finale = clamp(base + mitigazione + red_adj), arrotondato a 0.5
            tun.cell(24, cc, f'=ROUND(MAX(3,MIN(10,{L}21+{L}22+{L}20))*2)/2')
            tun.cell(24, cc).font = Font(bold=True, size=12)
            for rr in (16, 17, 18, 20, 21, 22):
                tun.cell(rr, cc).number_format = "0.000"
            tun.cell(24, cc).number_format = "0.0"
            for rr in (12, 13, 14, 15):
                if isinstance(tun.cell(rr, cc).value, (int, float)):
                    tun.cell(rr, cc).number_format = "0.0"
            tun.column_dimensions[col(cc)].width = 13
        # conditional colour on the FINAL voto row vs fanta/statistico
        first = col(c0 + 1); last = col(c0 + len(casedata)); rng = f"{first}24:{last}24"
        D = f"MIN(ABS({first}24-{first}12),IF(ISNUMBER({first}13),ABS({first}24-{first}13),99))"
        for cond, (bg, fg) in ((f"{D}<=0.75", CF_GREEN), (f"AND({D}>0.75,{D}<=1.5)", CF_YEL), (f"{D}>1.5", CF_RED)):
            tun.conditional_formatting.add(rng, FormulaRule(
                formula=[cond], fill=PatternFill("solid", fgColor=bg),
                font=Font(bold=True, size=12, color=fg)))
        tun["E26"] = ("NOTE: 'media/sigma INDICE ruolo' sono media e dev.std dell'INDICE (somma pesata) "
                      "tra i giocatori del ruolo → cambiano coi pesi. gd_on e red_adj sono FISSI. "
                      "'nostro(attuale)' (riga 15) è il deployato e dovrebbe ≈ VOTO FINALE (riga 24).")
        tun["E27"] = ("TIPO: 'DISAC. 2x'=disaccordo con fanta E SofaScore (marcatori "
                      "che sprecano: il gol è bonus +3, non voto base; loro fanno l'alone-gol, "
                      "noi no); 'DISAC. fanta'=disaccordo con fanta ma SofaScore ci dà ragione "
                      "(merito individuale in sconfitta vs punizione collettiva); "
                      "GOL=marcatore, 'KO netto'=sconfitta ≥3 gol, OUTLIER, buono=accordo.")
        tun["E28"] = ("Mitigazione: solo divergenze (voto>6 in sconfitta → giù; voto<6 in vittoria → su), "
                      "gravità = base + K·|gd_on|, cap ±1. K in B5, 'base sc/vitt' (contributo "
                      "discreto sconfitta/vittoria, oltre i gol) in D5. SGA_Pali: xgOT−xg + palo.")
        for a in ("E26", "E27", "E28"):
            tun[a].font = Font(italic=True, size=9)
        tun.column_dimensions["A"].width = 21; tun.column_dimensions["C"].width = 8
        tun.column_dimensions["E"].width = 19

        # ---- medie (readable per-feature role means) ----
        med = wb.create_sheet("medie")
        med["A1"] = "Medie per-FEATURE per ruolo (FISSE)."; med["A1"].font = Font(bold=True)
        for j, h in enumerate(["feature", "DIF raw", "CEN raw", "ATT raw", "DIF sqrt", "CEN sqrt", "ATT sqrt"]):
            hc = med.cell(3, 1 + j, h); hc.font = Font(bold=True, color="FFFFFF"); hc.fill = fillh
        for i, f in enumerate(FEATS):
            med.cell(4 + i, 1, f)
            for jr, role in enumerate(OUT_ROLES):
                med.cell(4 + i, 2 + jr, round(float(STATS[role]["mean_raw"][i]), 3))
                med.cell(4 + i, 5 + jr, round(float(STATS[role]["mean_sqrt"][i]), 3))
        med.column_dimensions["A"].width = 21

        # ---- spiegazioni: the strange-vote ledger with our generated text ----
        if expl_rows:
            sp = wb.create_sheet("spiegazioni")
            wb.move_sheet("spiegazioni", -(len(wb.sheetnames) - 2))  # right after Tuner
            sp["A1"] = ("Voti più lontani dallo STATISTICO (voto fanta senza bonus/malus), "
                        "con la spiegazione testuale che genera il nostro sistema.")
            sp["A1"].font = Font(bold=True, size=12)
            sp["A2"] = ("Lo Statistico toglie i gol dal voto, quindi un Δ grande = pura "
                        "divergenza sulla LETTURA della prestazione. 'nostro' è il voto puro "
                        "deployato (mitigazione + drop-prestazione da espulsione/autogol già "
                        "dentro). ATTENZIONE alle righe con 'Espulso.'/'Autogol.' nella "
                        "spiegazione: lì il Δ è GONFIATO, perché lo Statistico mette tutta la "
                        "penalità nel voto base mentre noi ci aggiungiamo il malus -1/-2 a "
                        "livello di FANTAVOTO (non qui). Leggi la spiegazione e giudica.")
            sp["A2"].font = Font(italic=True, size=9)
            heads = ["giocatore", "ruolo", "gd", "partita", "gol", "assist",
                     "nostro", "statistico", "fanta", "Δ ns−stat", "spiegazione"]
            for j, h in enumerate(heads):
                hc = sp.cell(4, 1 + j, h)
                hc.font = Font(bold=True, color="FFFFFF"); hc.fill = fillh
            for i, e in enumerate(expl_rows):
                r = 5 + i
                sp.cell(r, 1, e["name"]).font = Font(bold=True)
                sp.cell(r, 2, e["role"]); sp.cell(r, 3, e["gd"]); sp.cell(r, 4, e["match"])
                sp.cell(r, 5, e["goals"] or ""); sp.cell(r, 6, e["assists"] or "")
                sp.cell(r, 7, e["our"]).number_format = "0.0"
                sp.cell(r, 8, e["stat"]).number_format = "0.0"
                sp.cell(r, 9, e["fanta"] if e["fanta"] is not None else "-")
                dc = sp.cell(r, 10, e["delta"]); dc.number_format = "+0.0;-0.0"
                dc.font = Font(bold=True)
                ad = abs(e["delta"])
                fg = (CF_RED if ad >= 2 else (CF_YEL if ad >= 1.5 else CF_GREEN))
                dc.fill = PatternFill("solid", fgColor=fg[0]); dc.font = Font(bold=True, color=fg[1])
                tc = sp.cell(r, 11, e["expl"]); tc.alignment = Alignment(wrap_text=True, vertical="top")
            widths = {"A": 18, "B": 6, "C": 5, "D": 26, "E": 5, "F": 6,
                      "G": 8, "H": 9, "I": 7, "J": 10, "K": 88}
            for c, w in widths.items():
                sp.column_dimensions[c].width = w
            sp.freeze_panes = "A5"

        if "Sheet" in wb.sheetnames:
            wb.remove(wb["Sheet"])
        wb.save(out)
