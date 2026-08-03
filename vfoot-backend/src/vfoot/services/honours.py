"""L'albo d'oro: what has been won, by whom, and when.

A prize is a rule until the day it becomes a fact. ``competition_prizes`` owns the
rule and says who currently meets it; this module is about the fact — the moment a
competition ran out of football, the honours that were settled with it, and the
list of them that follows a manager around.

THREE DECISIONS WORTH KNOWING
-----------------------------
**Nothing is written down.** No AwardedPrize table, no "won_at" column. Who won is
derived from the results and the date from the ledger, exactly like the winner
itself — so an admin who rectifies the last matchday changes the albo d'oro with
it, instead of leaving a trophy behind in the name of somebody who no longer won
anything. The cost is a handful of queries per league; the alternative is a second
source of truth that can disagree with the first, which for an honours board is the
worst possible failure.

**A competition is over when there is no football left in it**, not when someone
declares it over: every fixture played AND every phase drawn. The second half is
not decorative — a cup whose semi-finals have just been concluded has all of its
fixtures finished and a final that does not exist yet, and without that test it
would announce a champion at the semi-final stage, every time.

**The date is the ledger's, not the clock's.** A competition ends when the matchday
that closed it was concluded, which is the same instant the results became
official. Reading ``timezone.now()`` instead would date the whole honours board to
whenever this code happened to run, and re-date it on every rebuild.
"""
from __future__ import annotations

from vfoot.models import (
    CompetitionStage,
    FantasyCompetition,
    FantasyFixture,
    FantasyTeam,
)
from vfoot.services.competition_prizes import (
    competition_fixtures,
    describe_condition,
    prize_scope,
    prize_winner_team_ids,
)


def _concluded_at(fixtures):
    """When the last of these fixtures was counted, or None if any never was.

    None is the honest answer for a competition whose results were written by
    something other than a conclusion (a seed, a simulation): it has no date, and
    a made-up one would sort it to the top of a feed it does not belong in.
    """
    stamps = [fx.fantasy_matchday.concluded_at if fx.fantasy_matchday_id else None
              for fx in fixtures]
    return max(stamps) if stamps and all(s is not None for s in stamps) else None


def is_complete(competition: FantasyCompetition, fixtures=None) -> bool:
    """Is there any football left in this competition?

    Two tests, and the second is the one that is easy to forget: a knockout draws
    its next round only when the previous one is done, so "all the fixtures that
    exist are finished" is true at every single round of a cup.
    """
    fixtures = competition_fixtures(competition) if fixtures is None else fixtures
    if not fixtures:
        return False
    if any(fx.status != FantasyFixture.STATUS_FINISHED for fx in fixtures):
        return False
    drawn = {fx.stage_id for fx in fixtures}
    planned = set(CompetitionStage.objects.filter(competition=competition)
                  .values_list("id", flat=True))
    return not (planned - drawn)


def completed_at(competition: FantasyCompetition, fixtures=None):
    """The instant this competition became history, or None if it has not."""
    fixtures = competition_fixtures(competition) if fixtures is None else fixtures
    if not is_complete(competition, fixtures):
        return None
    return _concluded_at(fixtures)


def prize_awards(competition: FantasyCompetition, fixtures=None) -> list[dict]:
    """Every prize of this competition that has been settled, with its date.

    An undecided prize is simply absent — the honours board shows what has been
    won, and "Scudetto: nessuno, ancora" belongs on the competition's own page,
    where the rule is what is being read.
    """
    fixtures = competition_fixtures(competition) if fixtures is None else fixtures
    out = []
    for prize in competition.prizes.select_related("source_stage").all():
        winners = prize_winner_team_ids(prize, fixtures)
        if not winners:
            continue
        out.append({
            "prize": prize,
            "competition": competition,
            "team_ids": winners,
            # Dated by what decided it: the final is over before the competition is
            # (a third-place play-off may follow), and a table prize is settled by
            # the last round of the table it reads.
            "at": _concluded_at(prize_scope(prize, fixtures)),
        })
    return out


def league_honours(league) -> dict:
    """Everything a league has finished and everything it has awarded.

    One pass over the league's competitions, because both the news feed and the
    honours board want the same two lists and asking twice doubles the queries on
    a page that already has plenty.
    """
    finished, awards = [], []
    for comp in FantasyCompetition.objects.filter(league=league).prefetch_related("prizes"):
        fixtures = competition_fixtures(comp)
        if not is_complete(comp, fixtures):
            continue
        finished.append({"competition": comp, "at": _concluded_at(fixtures)})
        awards.extend(prize_awards(comp, fixtures))
    return {"finished": finished, "awards": awards}


def manager_honours(user, *, leagues=None) -> list[dict]:
    """The albo d'oro of one manager: every prize won by any team he fields.

    Across leagues on purpose. A league lasts a season, a manager does not, and a
    palmarès that reset every August would be worth nothing — the point of the
    thing is precisely that it accumulates. ``leagues`` narrows it to the ones the
    viewer is allowed to see; without it, everything the manager has won.

    Newest first, undated last: a competition whose results were seeded rather than
    concluded has no date, and it should not sort as though it happened in year
    zero.
    """
    teams = FantasyTeam.objects.filter(manager__user=user).select_related("league")
    if leagues is not None:
        teams = teams.filter(league__in=leagues)
    by_id = {t.id: t for t in teams}
    if not by_id:
        return []

    out = []
    for comp in (FantasyCompetition.objects
                 .filter(league__in={t.league_id for t in by_id.values()})
                 .select_related("league")
                 .prefetch_related("prizes")):
        for award in prize_awards(comp):
            mine = [tid for tid in award["team_ids"] if tid in by_id]
            for tid in mine:
                team = by_id[tid]
                out.append({
                    "prize": award["prize"],
                    "competition": comp,
                    "team": team,
                    "at": award["at"],
                    # Shared honours exist (two teams tie a record) and hiding it
                    # would read as an outright win.
                    "shared_with": len(award["team_ids"]) - 1,
                })
    out.sort(key=lambda a: (a["at"] is not None, a["at"] or ""), reverse=True)
    return out


def serialize_award(award: dict) -> dict:
    """One line of an honours board, as the browser wants it."""
    prize = award["prize"]
    comp = award["competition"]
    team = award.get("team")
    return {
        "prize_id": prize.id,
        "name": prize.name,
        "icon": prize.icon or "🏆",
        "condition_label": describe_condition(prize),
        "competition_id": comp.id,
        "competition_name": comp.name,
        "competition_format": comp.format,
        "league_id": comp.league_id,
        "league_name": comp.league.name,
        "team_id": team.id if team else None,
        "team_name": team.name if team else None,
        "crest": team.crest if team else "",
        "shared_with": award.get("shared_with", 0),
        "at": award["at"].isoformat() if award["at"] else None,
    }
