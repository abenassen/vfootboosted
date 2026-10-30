"""A provider correction that arrives after a league has closed the round.

The +8h confirmation (``realdata.services.match_scheduler``) waits for SofaScore's
one routine revision of a match, so a round a league concludes is, in the normal
case, built on final numbers. What can still come later is the exception the
+24h look exists for: a FACT corrected — a goal given to somebody else, an own goal,
an assist, the score (Sassuolo-Lazio, 27/10/2026: Thorstvedt's goal became Sutalo's
own goal).

The policy, decided 30/10/2026:

* a corrected FACT on a round a league has already CONCLUDED flags that round
  (``FantasyMatchday.correction_pending_at``) and tells the league's admins what
  moved and which of its fixtures would change. It does NOT re-score by itself: a
  re-score can turn a result, the table and a cup round drawn from it since, and
  that is the admin's call — the button is the existing recompute ("regole
  congelate"), which clears the flag;
* a late re-estimate of xG/xGOT alone is only logged (``live_ingest.fact_changes``
  filters it out before it gets here): decimals that the half-point rounding nearly
  always swallows are not worth reopening a closed round for;
* a round not yet concluded needs nothing: it is computed live, so it already
  reads the corrected data.

Classic only, like the recompute: an aura round copies the real scoreline.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from vfoot.models import FantasyLeague, FantasyMatchday, LeagueMembership

log = logging.getLogger(__name__)


def _match_label(match) -> str:
    return f"{match.home_team.team.name}-{match.away_team.team.name}"


def fixtures_that_would_move(league, md) -> list[dict]:
    """The fixtures whose frozen score differs from a re-score on today's data.

    A PREVIEW: the same live scorer the calendar uses, under the round's frozen
    rules, compared with what the conclusion stored. A team that did not field is
    read as "previous lineup" here while the admin may have chosen forfait at the
    conclusion, so a fixture of that kind can show up as moving when it would not;
    the recompute itself asks again.
    """
    from vfoot.models import FantasyFixture
    from vfoot.services.classic_matchday_scoring import live_scorer, ruleset_for_round

    score = live_scorer(league, md, ruleset_for_round(league, md))
    out = []
    for fx in (FantasyFixture.objects.filter(fantasy_matchday=md)
               .select_related("home_team", "away_team", "competition", "stage", "detail")):
        detail = getattr(fx, "detail", None)
        if detail is None:
            continue
        now = score(fx)
        before = (detail.vfoot_home, detail.vfoot_away)
        after = (now["home_total"], now["away_total"])
        if any(abs((a or 0) - (b or 0)) > 1e-6 for a, b in zip(after, before)):
            out.append({
                "fixture_id": fx.id,
                "home": fx.home_team.name, "away": fx.away_team.name,
                "before": {"totals": before, "goals": (fx.home_total, fx.away_total)},
                "after": {"totals": after,
                          "goals": (now["home_goals"], now["away_goals"])},
            })
    return out


def _describe_fixture(f: dict) -> str:
    bh, ba = f["before"]["totals"]
    ah, aa = f["after"]["totals"]
    gb = "-".join(str(int(g or 0)) for g in f["before"]["goals"])
    ga = "-".join(str(int(g or 0)) for g in f["after"]["goals"])
    tail = f" (risultato {gb} -> {ga})" if gb != ga else ""
    return f"{f['home']}-{f['away']}: {bh:g}-{ba:g} -> {ah:g}-{aa:g}{tail}"


def flag_concluded_rounds(match, facts: list[str], now=None) -> list[dict]:
    """Flag every concluded classic round this match belongs to, and tell its admins.

    ``facts`` are the corrected facts, already in words (``live_ingest.fact_changes``).
    Returns one entry per league flagged, for the caller's log. Never raises: the
    caller is the tick, which keeps the live matches alive, and a failure to flag is
    logged rather than allowed to stop it.
    """
    if not facts or match.matchday is None:
        return []
    from vfoot.services import league_notifications

    now = now or timezone.now()
    label = _match_label(match)
    flagged = []
    rounds = (FantasyMatchday.objects
              .filter(league__reference_season_id=match.competition_season_id,
                      league__mode=FantasyLeague.MODE_CLASSIC,
                      real_competition_season_id=match.competition_season_id,
                      real_matchday=match.matchday,
                      status=FantasyMatchday.STATUS_CONCLUDED)
              .select_related("league"))
    for md in rounds:
        league = md.league
        try:
            moving = fixtures_that_would_move(league, md)
        except Exception:                                 # noqa: BLE001
            log.exception("Anteprima del ricalcolo fallita: lega %s, giornata %s",
                          league.id, md.real_matchday)
            moving = None
        note = (f"{label}: " + "; ".join(facts)
                + ("" if moving is None else
                   " — nessuna sfida cambierebbe" if not moving else
                   " — cambierebbero: " + "; ".join(_describe_fixture(f) for f in moving)))
        # A second correction on the same round before the admin acted on the first
        # adds to the note rather than replacing it: both are still to be applied.
        md.correction_note = (md.correction_note + "\n" + note
                              if md.correction_pending_at else note)
        md.correction_pending_at = now
        md.save(update_fields=["correction_pending_at", "correction_note"])
        admins = [m.user for m in LeagueMembership.objects
                  .filter(league=league, role=LeagueMembership.ROLE_ADMIN)
                  .select_related("user")]
        league_notifications.on_commit(
            league_notifications.notify_provider_correction,
            league, md, label, facts, moving, admins)
        flagged.append({"league_id": league.id, "league": league.name,
                        "matchday": md.real_matchday,
                        "fixtures_moving": None if moving is None else len(moving)})
    return flagged


def clear(md) -> None:
    """The admin has re-scored the round: the correction is applied."""
    if md.correction_pending_at is None and not md.correction_note:
        return
    md.correction_pending_at = None
    md.correction_note = ""
    md.save(update_fields=["correction_pending_at", "correction_note"])
