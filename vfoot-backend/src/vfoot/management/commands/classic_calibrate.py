"""Calibrate the classic voto-puro heuristic against SofaScore's own rating.

The rating is an independent professional 0-10 grade (in our cache, not the DB). We
use it two ways: (1) overall agreement (correlation + per-band means), and (2) OUTLIER
hunting — the performances we grade most differently than SofaScore, which surface
either bugs (like the duels_won double-count) or genuine model gaps. A dedicated
spotlight on short appearances checks that the per-90 shrinkage stops cameos inflating.

    python manage.py classic_calibrate --competition-season 2
    python manage.py classic_calibrate --competition-season 2 --spread-k 1.0 --pooled-std
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from realdata.models import CompetitionSeason, Match, Player
from vfoot.services.classic_rating import build_reference, voto_puro_for_match

DEFAULT_CACHE = str(Path(settings.VFOOT_DATA_DIR) / "historical-data" / "serie-a" / "sofascore" / "cache")


def _ratings_for_event(cache_dir, ext_id):
    """{sofascore_player_id(str): rating} from a cached lineups file, or {}."""
    try:
        d = json.load(open(f"{cache_dir}/api_v1_event_{ext_id}_lineups.json"))
    except (FileNotFoundError, ValueError):
        return {}
    out = {}
    for side in ("home", "away"):
        for pl in d.get(side, {}).get("players", []):
            pid = (pl.get("player") or {}).get("id")
            st = pl.get("statistics") or {}
            if pid is not None and st.get("rating"):
                out[str(pid)] = st["rating"]
    return out


class Command(BaseCommand):
    help = "Calibrate classic voto puro vs SofaScore rating; surface outliers."

    def add_arguments(self, parser):
        parser.add_argument("--competition-season", type=int, default=2)
        parser.add_argument("--spread-k", type=float, default=None,
                            help="Override VOTE_SPREAD_K (vote points per 1 std).")
        parser.add_argument("--pooled-std", action="store_true",
                            help="Share one spread across roles (attenuates the "
                                 "defender-dominance from tight per-role std).")
        parser.add_argument("--short-max-min", type=int, default=30)
        parser.add_argument("--examples", type=int, default=12)
        parser.add_argument("--cache-dir", default=DEFAULT_CACHE)
        parser.add_argument("--role", default=None,
                            help="Restrict to one classic role (POR/DIF/CEN/ATT).")

    def handle(self, *args, **opts):
        from vfoot.services import classic_rating as cr
        cs_id = opts["competition_season"]
        if not CompetitionSeason.objects.filter(id=cs_id).exists():
            raise CommandError(f"No CompetitionSeason id={cs_id}")
        spread_k = opts["spread_k"] if opts["spread_k"] is not None else cr.VOTE_SPREAD_K

        ref = build_reference(cs_id, pooled_std=opts["pooled_std"])
        self.stdout.write(f"spread_k={spread_k}  pooled_std={opts['pooled_std']}  "
                          f"shrinkage_min={cr.SHRINKAGE_MINUTES}  "
                          f"s.v. gate: min>={cr.MIN_MINUTES_RATED} & "
                          f"touches>={cr.MIN_TOUCHES_RATED}")
        for role in ("DIF", "CEN", "ATT"):
            r = ref.get(role)
            if r:
                self.stdout.write(f"  {role}: mean={r['mean']:+.2f} std={r['std']:.2f} n={r['n']}")

        ext = dict(Player.objects.filter(external_source="sofascore")
                   .values_list("id", "external_id"))
        rated, sv = [], 0
        pairs = []  # (voto, rating, row)
        for m in Match.objects.filter(competition_season_id=cs_id):
            ratings = _ratings_for_event(opts["cache_dir"], m.external_id) if m.external_id else {}
            for row in voto_puro_for_match(m, ref, spread_k):
                if opts["role"] and row["role"] != opts["role"]:
                    continue
                if not row["rated"]:
                    sv += 1
                    continue
                rated.append(row)
                sr = ratings.get(ext.get(row["player_id"]))
                if sr:
                    pairs.append((row["voto_puro"], sr, row))

        votes = sorted(r["voto_puro"] for r in rated)
        n = len(votes)
        self.stdout.write(f"\n=== {n} a voto, {sv} senza voto "
                          f"({100*sv/(n+sv):.1f}% s.v.) ===")
        self.stdout.write(f"  mean={sum(votes)/n:.2f} median={votes[n//2]:.1f} "
                          f"min={votes[0]:.1f} max={votes[-1]:.1f}")
        hist = Counter(votes)
        peak = max(hist.values())
        for h in [x / 2 for x in range(int(votes[0]*2), int(votes[-1]*2)+1)]:
            c = hist.get(h, 0)
            self.stdout.write(f"  {h:4.1f} | {'█'*round(40*c/peak) if c else ''} {c}")

        # agreement with SofaScore rating
        if pairs:
            import math
            vs = [a for a, _, _ in pairs]
            rs = [b for _, b, _ in pairs]
            mv, mr = sum(vs)/len(vs), sum(rs)/len(rs)
            cov = sum((a-mv)*(b-mr) for a, b, _ in pairs)/len(pairs)
            sv_ = math.sqrt(sum((a-mv)**2 for a in vs)/len(vs))
            sr_ = math.sqrt(sum((b-mr)**2 for b in rs)/len(rs))
            self.stdout.write(f"\nvs SofaScore rating (n={len(pairs)}): "
                              f"corr={cov/(sv_*sr_):.3f}")
            k = opts["examples"]
            # divergence in each one's own distribution (centred), for outlier hunt
            for a, b, row in pairs:
                row["_div"] = (a - mv) - (b - mr)
            ranked = sorted(pairs, key=lambda t: t[2]["_div"])
            self.stdout.write(f"\nWe rate FAR BELOW SofaScore (possible misses), top {k}:")
            for a, b, row in ranked[:k]:
                self.stdout.write(f"  voto={a:4.1f} rating={b:4.1f}  {row['name']:<22} "
                                  f"{row['role']} {row['minutes']}' tch={row['touches']}")
            self.stdout.write(f"We rate FAR ABOVE SofaScore (possible over-credit), top {k}:")
            for a, b, row in reversed(ranked[-k:]):
                self.stdout.write(f"  voto={a:4.1f} rating={b:4.1f}  {row['name']:<22} "
                                  f"{row['role']} {row['minutes']}' tch={row['touches']}")

        # short-appearance spotlight: are brief cameos over-rated?
        short = sorted([r for r in rated if r["minutes"] <= opts["short_max_min"]],
                       key=lambda r: r["voto_puro"], reverse=True)
        self.stdout.write(f"\nShort apps (<= {opts['short_max_min']}'), highest votes "
                          f"(shrinkage should keep these near 6):")
        for r in short[:opts["examples"]]:
            self.stdout.write(f"  voto={r['voto_puro']:4.1f}  {r['name']:<22} {r['role']} "
                              f"{r['minutes']}' tch={r['touches']} idx={r['index']}")
