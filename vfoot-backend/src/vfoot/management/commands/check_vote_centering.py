"""Guard the ONE property the voto puro promises: every role averages 6.

That is a deliberate design choice, not an observation — the vote is
``6 + K·w·z`` with z measured INSIDE the role, so a role whose mean drifts away
from 6 means the index being scored is no longer the index the reference was
calibrated on. It is worth a standing check because that failure is silent: the
listone spent an entire retuning cycle showing defenders at 6.159 (it was
building the index without the defensive exposure while the reference had been
calibrated with it) and nothing anywhere protested. The numbers stayed
plausible, ordered and wrong.

Deliberately NOT a unit test: the property only exists against a real season, and
a test that skips itself on an empty test database protects nothing. Run it after
any change to the weights, the calibration, the s.v. gates or the shrinkage.

    manage.py check_vote_centering
    manage.py check_vote_centering --tolerance 0.03

Exit code 1 if any role drifts further than the tolerance.

Reading the breakdown, when it does drift — mean − 6 = K·(E[w]·E[z] + Cov(w,z)):
  * ``K E[w]E[z]``  the index sits off the reference centre. This is the term that
    moves when the scored index stops matching the calibrated one, and it is the
    one that caught the exposure bug.
  * ``K Cov(w,z)``  longer appearances earn a higher z AND carry a higher weight,
    so the two correlate and push the mean up. Structural, not a defect.
Today those two very nearly cancel, which is WHY the roles land on 6.00 — an
accident of the current constants, not a designed balance. If one of them moves,
expect the other to stop hiding it.

For POR the two terms do NOT add up to the drift, and that is expected: the keeper
channel also damps the deviation by the evidence of the match (GK_EVIDENCE_FULL),
which shrinks votes toward 6 asymmetrically and so lifts the mean a little on its
own. That is the +0.04 you see there.
"""

from __future__ import annotations

import statistics

from django.core.management.base import BaseCommand, CommandError

from realdata.models import CompetitionSeason, Match, PlayerZoneFeature
from vfoot.services import classic_rating as cr
from vfoot.services.classic_pagella import get_reference

VOTE_CENTER = 6.0


def _cov(xs, ys):
    mx, my = statistics.mean(xs), statistics.mean(ys)
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / len(xs)


def centering_report(samples: dict, k: float) -> dict:
    """{role: [(z, w, vote), ...]} -> {role: {...}} with the mean and its two parts.

    Pure arithmetic, kept out of the command body so it can be tested without a
    season behind it. ``k`` is VOTE_SPREAD_K — ma il portiere ha la sua scala
    (GK_SPREAD_K), e decomporre il suo scarto con quella di movimento sballava le
    due colonne del 9%: la media e lo scarto vengono dai voti veri e sono giusti,
    i due addendi che dovrebbero spiegarli no.
    """
    out = {}
    for role, rows in samples.items():
        if not rows:
            continue
        k_role = cr.spread_k_for(role, k)
        z = [r[0] for r in rows]
        w = [r[1] for r in rows]
        v = [r[2] for r in rows]
        ez, ew, c = statistics.mean(z), statistics.mean(w), _cov(w, z)
        out[role] = {
            "n": len(rows),
            "mean": statistics.mean(v),
            "drift": statistics.mean(v) - VOTE_CENTER,
            "centre_term": k_role * ew * ez,
            "cov_term": k_role * c,
        }
    return out


class Command(BaseCommand):
    help = "Check that every role's voto puro still averages 6 on a real season."

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, default=None,
                            help="CompetitionSeason id (default: the one with the "
                                 "most SCOREABLE matches, i.e. carrying zone features).")
        parser.add_argument("--tolerance", type=float, default=0.05,
                            help="Maximum |mean - 6| tolerated per role (default 0.05).")

    def handle(self, *args, **opts):
        cs_id = opts["season"]
        if cs_id is None:
            # By SCOREABLE matches, not by finished ones: the 2015/16 season has
            # just as many played matches and not a single sofascore zone row, so
            # counting fixtures would pick the one season this check cannot run on.
            best = None
            for cs in CompetitionSeason.objects.all():
                n = (PlayerZoneFeature.objects
                     .filter(match__competition_season=cs,
                             match__status=Match.STATUS_FINISHED,
                             provider=cr.PROVIDER_SOFASCORE)
                     .values("match_id").distinct().count())
                if n and (best is None or n > best[1]):
                    best = (cs.id, n)
            if best is None:
                raise CommandError(
                    "no season with zone features in this database — this check "
                    "needs a full copy (see export_dev_db)")
            cs_id = best[0]
        cs = CompetitionSeason.objects.get(id=cs_id)

        match_ids = list(Match.objects.filter(competition_season_id=cs_id,
                                              status=Match.STATUS_FINISHED)
                         .values_list("id", flat=True))
        totals = cr._per_match_player_totals(match_ids)
        if not totals:
            raise CommandError(
                f"{cs}: no zone features, so nothing can be scored — this check "
                "needs a full database (see export_dev_db)")
        minutes = cr._minutes_map(match_ids)
        exposure = cr.defensive_exposure(match_ids, minutes)
        goals_against = cr.on_pitch_goals_against(match_ids, minutes)
        roles = cr.current_role_map(only_declared=True)
        ref = get_reference(cs_id)

        samples: dict[str, list] = {}
        for (mid, pid), feats in totals.items():
            role = roles.get(pid)
            if not role:
                continue
            mins = minutes.get((mid, pid), 0)
            if mins <= 0 or not cr.is_rated(mins, feats):
                continue
            idx = cr.index_for_role(role, feats, mins, exposure.get((mid, pid), 0.0))
            r = ref.get(role)
            if not r:
                continue
            # The keeper channel damps the deviation by how much the match actually
            # told us about him, so the check has to apply it too or it would be
            # measuring a vote nobody is shown.
            ev = (cr.gk_evidence_weight(
                      cr.gk_evidence(feats, goals_against.get((mid, pid), 0)))
                  if role == "POR" else 1.0)
            z = (idx - r["mean"]) / r["std"]
            w = mins / (mins + cr.SHRINKAGE_MINUTES)
            vote = cr._round_half(cr._raw_vote_from_index(
                idx, role, mins, ref, evidence_weight=ev))
            samples.setdefault(role, []).append((z, w, vote))

        report = centering_report(samples, cr.VOTE_SPREAD_K)
        self.stdout.write(f"stagione: {cs}   tolleranza: +/-{opts['tolerance']}")
        self.stdout.write(f"{'ruolo':6s} {'n':>6s} {'media':>8s} {'scarto':>9s} "
                          f"{'K E[w]E[z]':>11s} {'K Cov(w,z)':>11s}")
        failed = []
        for role in sorted(report):
            d = report[role]
            bad = abs(d["drift"]) > opts["tolerance"]
            if bad:
                failed.append(role)
            line = (f"{role:6s} {d['n']:6d} {d['mean']:8.3f} {d['drift']:+9.3f} "
                    f"{d['centre_term']:+11.4f} {d['cov_term']:+11.4f}"
                    + ("   FUORI TOLLERANZA" if bad else ""))
            self.stdout.write(self.style.ERROR(line) if bad else line)

        if failed:
            self.stderr.write(self.style.ERROR(
                f"\nruoli fuori tolleranza: {', '.join(failed)}.\n"
                "Se lo scarto sta in K E[w]E[z], l'indice che stiamo votando non e'\n"
                "piu' quello su cui la reference e' stata calibrata: cerca un\n"
                "argomento non passato o una feature che non arriva, non un peso storto."))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("\nogni ruolo e' centrato sul 6"))
