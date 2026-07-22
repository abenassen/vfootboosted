"""Reconcile Transfermarkt rosters against SofaScore Player identities.

A feasibility experiment for cross-provider identity matching: how reliably can a
Transfermarkt squad entry be matched to the SofaScore ``Player`` we already have,
using only (name, date-of-birth)? Runs OFFLINE — reads the Transfermarkt cache
written by ``scrape_transfermarkt_squads.py`` and the sofascore Player rows in the
DB; touches no network.

The headline questions it answers:
  * Of TM players who actually appeared in a match (so they SHOULD be in our DB),
    how many match cleanly on DOB? How many need fuzzy name help (transliteration /
    nickname)? How many DOB collisions force name disambiguation?
  * TM players with NO DOB match = squad members who never played yet (the exact
    gap rosters-from-matches can't fill) OR a DOB discrepancy.
  * SofaScore players who played but are in NO current TM squad = transfer-out
    signals / TM gaps — the consistency invariant between appearance and roster.

    python manage.py match_transfermarkt \
        --cache-dir /…/historical-data/serie-a/transfermarkt/IT1/2025
"""

from __future__ import annotations

import glob
import json
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from django.core.management.base import BaseCommand

from realdata.models import MatchAppearance, Player, PROVIDER_SOFASCORE


def _norm(name: str) -> str:
    """Lowercase, strip accents/punctuation, collapse spaces."""
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    no_marks = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = "".join(c if c.isalnum() else " " for c in no_marks.lower())
    return " ".join(cleaned.split())


def _sim(a: str, b: str) -> float:
    """Name similarity in [0,1], robust to token reordering (surname-first)."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    direct = SequenceMatcher(None, na, nb).ratio()
    sa, sb = set(na.split()), set(nb.split())
    token = len(sa & sb) / len(sa | sb) if (sa | sb) else 0.0
    return max(direct, token)


class Command(BaseCommand):
    help = "Reconcile Transfermarkt rosters vs SofaScore Players by name + DOB."

    def add_arguments(self, parser):
        parser.add_argument("--cache-dir", required=True,
                            help="Dir with club_*.json from the TM scraper.")
        parser.add_argument("--fuzzy", type=float, default=0.6,
                            help="Min name similarity to accept a DOB-less or "
                                 "ambiguous match (default 0.6).")
        parser.add_argument("--list-aliases", action="store_true",
                            help="Print every DOB-matched pair whose names differ.")

    def handle(self, *args, **opts):
        cache = Path(opts["cache_dir"])
        files = sorted(glob.glob(str(cache / "club_*.json")))
        if not files:
            self.stderr.write(f"No club_*.json in {cache}")
            return

        tm_players = []
        for f in files:
            data = json.loads(Path(f).read_text())
            club = data["club"]["name"]
            for p in data["players"]:
                tm_players.append({**p, "club": club})
        tm_with_dob = [p for p in tm_players if p["dob"]]
        self.stdout.write(
            f"Transfermarkt: {len(tm_players)} squad players "
            f"({len(tm_with_dob)} with DOB) across {len(files)} clubs.")

        # SofaScore side: every Player we imported (i.e. who appeared in a match).
        ss = list(Player.objects.filter(external_source=PROVIDER_SOFASCORE))
        by_dob: dict[str, list] = {}
        for p in ss:
            if p.date_of_birth:
                by_dob.setdefault(p.date_of_birth.isoformat(), []).append(p)
        self.stdout.write(
            f"SofaScore: {len(ss)} players "
            f"({sum(1 for p in ss if p.date_of_birth)} with DOB).\n")

        matched_ss_ids: set = set()
        exact, fuzzy, ambiguous, dob_only_one = [], [], [], 0
        no_dob_match, dob_no_name = [], []

        for tp in tm_with_dob:
            cands = by_dob.get(tp["dob"], [])
            if not cands:
                no_dob_match.append(tp)
                continue
            best = max(cands, key=lambda c: max(
                _sim(tp["name"], c.full_name), _sim(tp["name"], c.short_name)))
            score = max(_sim(tp["name"], best.full_name),
                        _sim(tp["name"], best.short_name))
            matched_ss_ids.add(best.id)
            pair = {"tm": tp, "ss": best, "score": score,
                    "n_cands": len(cands)}
            if len(cands) == 1:
                dob_only_one += 1
            if score >= 0.95:
                exact.append(pair)
            elif score >= opts["fuzzy"]:
                fuzzy.append(pair)
            elif len(cands) > 1:
                ambiguous.append(pair)
            else:
                # single DOB candidate but the name is wildly different —
                # suspicious (possible DOB data error or wrong person)
                dob_no_name.append(pair)

        # Reverse: SofaScore players who PLAYED but aren't in any current TM squad.
        played_ids = set(MatchAppearance.objects
                         .values_list("player_id", flat=True).distinct())
        ss_by_id = {p.id: p for p in ss}
        orphan_ss = [ss_by_id[i] for i in played_ids
                     if i in ss_by_id and i not in matched_ss_ids]

        total_dob = len(tm_with_dob)
        clean = len(exact) + len(fuzzy)
        self.stdout.write(self.style.SUCCESS("=== MATCH REPORT ==="))
        self.stdout.write(
            f"TM players w/ DOB matched to a SofaScore identity: "
            f"{clean}/{total_dob} ({100 * clean / total_dob:.1f}%)")
        self.stdout.write(f"  exact name+DOB        : {len(exact)}")
        self.stdout.write(f"  DOB + fuzzy name      : {len(fuzzy)}  "
                          f"(transliteration/nickname — the interesting cases)")
        self.stdout.write(f"  DOB collision (>1 cand): {len(ambiguous)}  "
                          f"(needed name to disambiguate; below fuzzy threshold)")
        self.stdout.write(f"  single DOB, name way off: {len(dob_no_name)}  "
                          f"(suspicious — review)")
        self.stdout.write(
            f"TM players w/ DOB and NO SofaScore match: {len(no_dob_match)}  "
            f"(squad members who never played yet, or DOB mismatch)")
        self.stdout.write(
            f"SofaScore players who PLAYED but not in any TM squad: "
            f"{len(orphan_ss)}  (transfer-out signal / TM gap)\n")

        def _show(title, rows, fmt, n=15):
            if not rows:
                return
            self.stdout.write(self.style.WARNING(f"-- {title} (showing {min(n, len(rows))}/{len(rows)}):"))
            for r in rows[:n]:
                self.stdout.write("   " + fmt(r))

        if opts["list_aliases"]:
            _show("DOB+fuzzy name pairs", sorted(fuzzy, key=lambda r: r["score"]),
                  lambda r: f"[{r['score']:.2f}] TM '{r['tm']['name']}' "
                            f"== SS '{r['ss'].full_name}' / '{r['ss'].short_name}'",
                  n=len(fuzzy))
        else:
            _show("sample DOB+fuzzy name pairs", sorted(fuzzy, key=lambda r: r["score"]),
                  lambda r: f"[{r['score']:.2f}] TM '{r['tm']['name']}' "
                            f"== SS '{r['ss'].full_name}' / '{r['ss'].short_name}'")
        _show("DOB collisions (disambiguated by name)", ambiguous,
              lambda r: f"[{r['score']:.2f}, {r['n_cands']} same-DOB] "
                        f"TM '{r['tm']['name']}' -> SS '{r['ss'].full_name}'")
        _show("single-DOB but name way off (review)", dob_no_name,
              lambda r: f"[{r['score']:.2f}] TM '{r['tm']['name']}' ({r['tm']['dob']}) "
                        f"?= SS '{r['ss'].full_name}'")
        _show("TM squad players with no DOB match", no_dob_match,
              lambda r: f"{r['name']} ({r['dob']}, {r['club']}, {r.get('position')})")
        _show("SofaScore played-but-not-in-TM-squad", orphan_ss,
              lambda p: f"{p.full_name} ({p.date_of_birth}) [ss_id={p.external_id}]")
