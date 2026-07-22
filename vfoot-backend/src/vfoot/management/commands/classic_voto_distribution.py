"""Inspect the classic-mode 'voto puro' heuristic on real data, to calibrate it.

Builds the per-role reference distribution for a season, then prints the resulting
voto-puro histogram (should look pagella-like: median ~6, most in 5.5-7, rare tails)
plus per-role medians and a few sanity examples (best/worst games).

    python manage.py classic_voto_distribution --competition-season 2
    python manage.py classic_voto_distribution --competition-season 2 --matchday 1
"""

from __future__ import annotations

from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError

from realdata.models import CompetitionSeason, Match
from vfoot.services.classic_rating import build_reference, voto_puro_for_match


class Command(BaseCommand):
    help = "Show the classic voto-puro distribution on real matches (calibration)."

    def add_arguments(self, parser):
        parser.add_argument("--competition-season", type=int, default=2)
        parser.add_argument("--matchday", type=int, default=None,
                            help="Limit the histogram to one matchday (reference is "
                                 "still built over the whole season).")
        parser.add_argument("--examples", type=int, default=8)

    def handle(self, *args, **opts):
        cs_id = opts["competition_season"]
        if not CompetitionSeason.objects.filter(id=cs_id).exists():
            raise CommandError(f"No CompetitionSeason id={cs_id}")

        self.stdout.write("Building per-role reference distribution…")
        ref = build_reference(cs_id)
        self.stdout.write("Reference (per-90 index by role):")
        for role in ("DIF", "CEN", "ATT"):
            r = ref.get(role)
            if r:
                self.stdout.write(f"  {role}: mean={r['mean']:+.2f} std={r['std']:.2f} "
                                  f"n={r['n']}")

        matches = Match.objects.filter(competition_season_id=cs_id)
        if opts["matchday"] is not None:
            matches = matches.filter(matchday=opts["matchday"])
        matches = list(matches)
        self.stdout.write(f"\nScoring {len(matches)} matches…")

        all_rows = []
        for m in matches:
            all_rows.extend(voto_puro_for_match(m, ref))

        votes = [r["voto_puro"] for r in all_rows]
        if not votes:
            self.stdout.write("No outfield performances found.")
            return
        votes.sort()
        n = len(votes)
        median = votes[n // 2]
        mean = sum(votes) / n
        self.stdout.write(f"\n=== voto puro distribution (n={n}) ===")
        self.stdout.write(f"  mean={mean:.2f}  median={median:.1f}  "
                          f"min={votes[0]:.1f}  max={votes[-1]:.1f}")

        hist = Counter(votes)
        peak = max(hist.values())
        for half in [x / 2 for x in range(int(min(votes) * 2), int(max(votes) * 2) + 1)]:
            c = hist.get(half, 0)
            bar = "█" * round(40 * c / peak) if c else ""
            self.stdout.write(f"  {half:4.1f} | {bar} {c}")

        # per-role medians (should each sit near 6 by construction)
        by_role = defaultdict(list)
        for r in all_rows:
            by_role[r["role"]].append(r["voto_puro"])
        self.stdout.write("\nPer-role median voto puro:")
        for role in ("DIF", "CEN", "ATT"):
            vs = sorted(by_role.get(role, []))
            if vs:
                self.stdout.write(f"  {role}: median={vs[len(vs)//2]:.1f} (n={len(vs)})")

        k = opts["examples"]
        all_rows.sort(key=lambda d: d["voto_puro"], reverse=True)
        self.stdout.write(f"\nTop {k} games:")
        for r in all_rows[:k]:
            self.stdout.write(f"  {r['voto_puro']:4.1f}  {r['name']:<24} {r['role']} "
                              f"{r['minutes']}'  idx={r['index']}")
        self.stdout.write(f"Bottom {k} games (>=20'):")
        for r in [x for x in all_rows if x["minutes"] >= 20][-k:]:
            self.stdout.write(f"  {r['voto_puro']:4.1f}  {r['name']:<24} {r['role']} "
                              f"{r['minutes']}'  idx={r['index']}")
