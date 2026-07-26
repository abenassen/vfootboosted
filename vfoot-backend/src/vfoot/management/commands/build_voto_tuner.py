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
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import openpyxl
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter as col
from openpyxl.worksheet.datavalidation import DataValidation

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import vfoot.services.classic_rating as cr
from realdata.models import Match, MatchAppearance, MatchShot, Player, Team
from vfoot.management.commands.voto_puro_discrepancies import Command as DiscCmd

OUT_ROLES = ["DIF", "CEN", "ATT"]
SHOTMAP = {"post": "shots_post", "goal": "shots_goal", "save": "shots_saved",
           "miss": "shots_off", "block": "shots_blocked"}
# Provider stats we ingest but do not weight — shown at weight 0 for inspection.
# (crosses_completed / dribbles_attempted are now weighted; possession_lost was
# dropped as 79% redundant with the errors_* it overlaps — see PER90_WEIGHTS.)
UNUSED = ["tackles", "possession_lost"]
# forced cases we have analysed and want to keep visible: (player_id, matchday)
# Baschirotto, Leão, Troilo, Ismajli, David.
FORCED = [(1323, 14), (1123, 26), (1070, 22), (1271, 17), (913, 18)]

TEAL = "1F5C53"; YEL = "FFF2CC"
CF_GREEN = ("C6EFCE", "006100"); CF_YEL = ("FFEB9C", "9C6500"); CF_RED = ("FFC7CE", "9C0006")


class Command(BaseCommand):
    help = "Build the interactive voto-puro weight tuner spreadsheet."

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, default=2)
        parser.add_argument("--cases", type=int, default=24,
                            help="Target number of case columns.")
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
        SHOTDET = list(SHOTMAP.values())
        FEATS = TOTAL + PER90 + ["_exposure"] + SHOTDET
        nF = len(FEATS)
        is_p90 = {f: (f in PER90) for f in FEATS}
        sqmask = np.array([is_p90[f] for f in FEATS])  # √ only on PER90
        curw = {**cr.TOTAL_WEIGHTS, **cr.PER90_WEIGHTS}

        def w_of(f):
            return -cr.DEF_EXPOSURE_WEIGHT if f == "_exposure" else curw.get(f, 0.0)

        # ---- per-match data ----
        mids = list(Match.objects.filter(competition_season_id=cs).values_list("id", flat=True))
        md_of = {m.id: m.matchday for m in Match.objects.filter(competition_season_id=cs)}
        totals = cr._per_match_player_totals(mids)
        minutes = cr._minutes_map(mids)
        expo = cr.defensive_exposure(mids, minutes)
        # inject shot-outcome detail from the event-level shotmap
        shd = defaultdict(Counter)
        for mid, pid, st in (MatchShot.objects.filter(match_id__in=mids)
                             .values_list("match_id", "player_id", "shot_type")):
            if st in SHOTMAP:
                shd[(mid, pid)][SHOTMAP[st]] += 1
        for key, tot in totals.items():
            c = shd.get(key, {})
            for f in SHOTDET:
                tot[f] = float(c.get(f, 0))

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
            if (r["gd"], r["pid"]) not in gp2mp or r["fanta"] is None or r["our"] is None:
                continue
            r = {**r, "absd": abs(r["our"] - r["fanta"]),
                 "margin": margin(r["gd"], r["pid"])}
            cand.append(r)

        # ---- case selection (dedup by player) ----
        sel, seen = [], set()

        def take(r, tipo):
            if r["pid"] in seen:
                return False
            sel.append({**r, "tipo": tipo}); seen.add(r["pid"]); return True

        by_key = {(r["gd"], r["pid"]): r for r in cand}
        for pid, gd in FORCED:                                   # analysed cases
            r = by_key.get((gd, pid))
            if r:
                take(r, "OUTLIER")
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
                             "sofa": r["sofa"], "our": r["our"]})
        casedata.sort(key=lambda c: (OUT_ROLES.index(c["role"]), c["tipo"], c["name"]))

        self._build_xlsx(out, FEATS, nF, is_p90, w_of, STATS, casedata)
        self.stdout.write(self.style.SUCCESS(
            f"scritto {out} | casi: {len(casedata)} "
            f"(gol: {sum(1 for c in casedata if c['goals'])}, "
            f"KO netto: {sum(1 for c in casedata if c['tipo']=='KO netto')})"))

    # ------------------------------------------------------------------
    def _build_xlsx(self, out, FEATS, nF, is_p90, w_of, STATS, casedata):
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
        tun["A2"] = ("Edita i PESI (col C, celle gialle). Interruttore RAW/SQRT in B4. "
                     "Il VOTO (riga 20) si colora: verde=accordo, giallo=borderline, rosso=outlier.")
        tun["A3"] = ("Norm.90': le PER-90 sono gia' ×90/max(min,55). SQRT applica la √ SOLO "
                     "alle PER90 (alta varianza); TOTAL/tiri/exposure LINEARI. "
                     "Voto = 6 + 0.8·(min/(min+25))·(indice−media)/sigma, in [3,10].")
        tun["A4"] = "compressione:"; tun["B4"] = "SQRT"; tun["B4"].font = Font(bold=True); tun["B4"].fill = yel
        dv = DataValidation(type="list", formula1='"RAW,SQRT"'); tun.add_data_validation(dv); dv.add(tun["B4"])
        tun["A6"] = "feature"; tun["B6"] = "tipo"; tun["C6"] = "PESO"
        for cc in ("A6", "B6", "C6"):
            tun[cc].font = Font(bold=True, color="FFFFFF"); tun[cc].fill = fillh
        for i, f in enumerate(FEATS):
            tun.cell(7 + i, 1, f)
            tun.cell(7 + i, 2, "PER90" if is_p90[f] else ("EXPOS" if f == "_exposure" else "TOT"))
            wc = tun.cell(7 + i, 3, round(w_of(f), 3)); wc.fill = yel; wc.number_format = "0.000"
        TOG = "Tuner!$B$4"; c0 = 5
        rowlab = [(7, "giocatore"), (8, "TIPO"), (9, "ruolo"), (10, "partita (gd, risultato, gol)"),
                  (11, "minuti"), (12, "fanta"), (13, "statistico"), (14, "sofascore"),
                  (15, "nostro(attuale)"), (16, "indice"), (17, "media INDICE ruolo"),
                  (18, "sigma INDICE ruolo"), (20, "VOTO PURO (live)")]
        for rr2, lab in rowlab:
            tun.cell(rr2, c0, lab).font = Font(bold=True, size=9)
        for ci, c in enumerate(casedata):
            cc = c0 + 1 + ci; L = col(cc); mr = murow[c["role"]]
            tun.cell(7, cc, c["name"]).font = Font(bold=True)
            tun.cell(8, cc, c["tipo"]).fill = PatternFill(
                "solid", fgColor="C9E7DF" if c["tipo"] == "buono" else "F7ECDD")
            tun.cell(9, cc, c["role"]); tun.cell(10, cc, c["match"]); tun.cell(11, cc, c["min"])
            tun.cell(12, cc, c["fanta"]); tun.cell(13, cc, c["stat"] if c["stat"] is not None else "-")
            tun.cell(14, cc, c["sofa"] if c["sofa"] is not None else "-"); tun.cell(15, cc, c["our"])
            tun.cell(16, cc, f'=IF({TOG}="SQRT",SUMPRODUCT({wvec},{csq(ci)}),SUMPRODUCT({wvec},{craw(ci)}))')
            tun.cell(17, cc, f'=IF({TOG}="SQRT",calc!$C${mr},calc!$B${mr})')
            tun.cell(18, cc, f'=IF({TOG}="SQRT",calc!$E${mr},calc!$D${mr})')
            tun.cell(20, cc, f'=MAX(3,MIN(10,6+0.8*({L}11/({L}11+25))*(({L}16-{L}17)/{L}18)))')
            tun.cell(20, cc).font = Font(bold=True, size=12)
            for rr in (16, 17, 18):
                tun.cell(rr, cc).number_format = "0.000"
            tun.cell(20, cc).number_format = "0.00"
            for rr in (12, 13, 14, 15):
                if isinstance(tun.cell(rr, cc).value, (int, float)):
                    tun.cell(rr, cc).number_format = "0.0"
            tun.column_dimensions[col(cc)].width = 13
        # conditional colour on the voto row vs fanta/statistico
        first = col(c0 + 1); last = col(c0 + len(casedata)); rng = f"{first}20:{last}20"
        D = f"MIN(ABS({first}20-{first}12),IF(ISNUMBER({first}13),ABS({first}20-{first}13),99))"
        for cond, (bg, fg) in ((f"{D}<=0.75", CF_GREEN), (f"AND({D}>0.75,{D}<=1.5)", CF_YEL), (f"{D}>1.5", CF_RED)):
            tun.conditional_formatting.add(rng, FormulaRule(
                formula=[cond], fill=PatternFill("solid", fgColor=bg),
                font=Font(bold=True, size=12, color=fg)))
        tun["E22"] = ("NOTE: 'media/sigma INDICE ruolo' sono media e dev.std dell'INDICE (somma pesata) "
                      "tra i giocatori del ruolo → cambiano coi pesi. Le medie per-feature (fisse) "
                      "sono nel foglio 'cases' (colonne a destra) e 'medie'.")
        tun["E23"] = ("TIPO: OUTLIER=forte discrepanza, GOL=marcatore, 'KO netto'=sconfitta ≥3 gol "
                      "(fanta lega il voto al risultato, noi no), buono=accordo.")
        tun["E24"] = ("SGA_Pali: w(xg_on_target)=+a, w(xg_shots)=−a (differenza xgOT−xg), "
                      "w(shots_post)=+a·c (palo, c~0.2); azzera shots/shots_on_target/big_chance_missed, "
                      "creazione sulla sola expected_assists.")
        for a in ("E22", "E23", "E24"):
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

        if "Sheet" in wb.sheetnames:
            wb.remove(wb["Sheet"])
        wb.save(out)
