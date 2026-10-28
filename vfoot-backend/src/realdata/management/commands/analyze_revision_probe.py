"""Read the revision probe's file and say when SofaScore stops revising a match.

    python manage.py analyze_revision_probe
    python manage.py analyze_revision_probe --eps 0.02 --share 0.10 --partial

For each match the LAST reading is the reference (the +48h one: only complete
matches count unless ``--partial``). A reading's DISTANCE is the sum, over the shots
present in both, of |dxG| + |dxGOT|: how much of the final numbers it still lacked.
``--eps`` is the distance below which a reading counts as already final (0.02 is a
fifth of one half-point of xGOT on a single shot, i.e. nothing a vote can show);
the answer is the earliest offset where at most ``--share`` of the matches are
still further than that from their reference.

The keeper's own numbers ride along (largest |dgoalsPrevented| on the squad sheet)
because they are what a keeper's vote reads and they are not derived from the shots.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from realdata.services.revision_probe import PROBE_OFFSETS, readings_file


def distance(ref: dict, r: dict) -> tuple[float, int, float]:
    """(sum |dxG|+|dxGOT|, shots changed, max |d goalsPrevented|) of ``r`` vs ``ref``."""
    total, changed = 0.0, 0
    for sid, (rx, rg) in ref["shots"].items():
        if sid not in r["shots"]:
            continue
        x, g = r["shots"][sid]
        d = abs((x or 0) - (rx or 0)) + abs((g or 0) - (rg or 0))
        total += d
        if d > 1e-4:
            changed += 1
    gp = 0.0
    for pid, rs in ref["players"].items():
        a, b = rs.get("goalsPrevented"), (r["players"].get(pid) or {}).get("goalsPrevented")
        if a is not None and b is not None:
            gp = max(gp, abs(a - b))
    return total, changed, gp


class Command(BaseCommand):
    help = "When does SofaScore stop revising a finished match? (reads the probe file)"

    def add_arguments(self, parser):
        parser.add_argument("--file", default=None)
        parser.add_argument("--eps", type=float, default=0.02)
        parser.add_argument("--share", type=float, default=0.10)
        parser.add_argument("--partial", action="store_true",
                            help="also matches that have no +48h reading yet")

    def handle(self, *args, **o):
        from pathlib import Path
        path = Path(o["file"]) if o["file"] else readings_file()
        try:
            rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        except OSError as exc:
            raise CommandError(f"no readings at {path}: {exc}") from exc

        by_match = defaultdict(dict)
        for r in rows:
            by_match[r["match"]][r["offset"]] = r
        last = PROBE_OFFSETS[-1][0]
        matches = {m: rs for m, rs in by_match.items() if o["partial"] or last in rs}
        self.stdout.write(f"{len(by_match)} matches read, {len(matches)} used "
                          f"({'partial allowed' if o['partial'] else f'complete up to +{last}'})")
        if not matches:
            return

        order = [lab for lab, _ in PROBE_OFFSETS]
        per_offset = defaultdict(list)  # label -> [(D, changed, gp)]
        for m, rs in matches.items():
            ref_label = max(rs, key=lambda k: order.index(k))
            ref = rs[ref_label]
            for lab, r in rs.items():
                if lab != ref_label:
                    per_offset[lab].append(distance(ref, r))

        self.stdout.write(f"\n{'offset':>6} {'n':>3} {'median D':>9} {'max D':>7} "
                          f"{'shots chg (med)':>16} {'max dGP':>8} {'> eps':>7}")
        answer = None
        for lab in order:
            v = per_offset.get(lab)
            if not v:
                continue
            ds = [d for d, _c, _g in v]
            over = sum(1 for d in ds if d > o["eps"]) / len(ds)
            self.stdout.write(
                f"{'+' + lab:>6} {len(v):>3} {statistics.median(ds):>9.3f} {max(ds):>7.3f} "
                f"{statistics.median(c for _d, c, _g in v):>16.0f} "
                f"{max(g for _d, _c, g in v):>8.4f} {over:>6.0%}")
            if answer is None and over <= o["share"]:
                answer = lab
        self.stdout.write("")
        if answer:
            self.stdout.write(self.style.SUCCESS(
                f"earliest offset with at most {o['share']:.0%} of matches still more than "
                f"{o['eps']} from their reference: +{answer}"))
        else:
            self.stdout.write(self.style.WARNING(
                "no probed offset before the reference gets there: the revision is "
                "later than the readings (or the sample is too small)"))
