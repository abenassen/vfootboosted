"""What a prize is worth: the condition that assigns it, and who has met it.

A prize is declared when the competition is created ("Scudetto: chi arriva primo",
"Coppa: chi vince la finale") and stays undecided until the rounds it depends on
have actually been played. Nothing here writes: the winner is DERIVED, so a
rectified result changes the honours board with it.

Two families of condition, and they answer different questions:

* a POSITION — the table, the final. Decided by where you finished;
* a RECORD — the highest average score, the best attack, the worst defence. Not a
  position at all: it is read off the whole competition at the end, and it is what
  a league invents when it wants to award something the table cannot say.

A record can be TIED, and when it is, everyone who tied has won it. That is why
this module returns a list of winners everywhere and never a single team.
"""

from __future__ import annotations

from vfoot.models import (
    CompetitionPrize,
    CompetitionStage,
    FantasyCompetition,
    FantasyFixture,
    FantasyFixtureDetail,
)
from vfoot.services.knockout import deciding_ties


def _table(fixtures, comp: FantasyCompetition) -> list[int]:
    rows: dict[int, dict] = {}
    for fx in fixtures:
        for tid in (fx.home_team_id, fx.away_team_id):
            rows.setdefault(tid, {"pts": 0, "gf": 0.0, "ga": 0.0})
        hs, as_ = fx.home_total, fx.away_total
        rows[fx.home_team_id]["gf"] += hs
        rows[fx.home_team_id]["ga"] += as_
        rows[fx.away_team_id]["gf"] += as_
        rows[fx.away_team_id]["ga"] += hs
        if hs > as_:
            rows[fx.home_team_id]["pts"] += comp.points_win
            rows[fx.away_team_id]["pts"] += comp.points_loss
        elif hs < as_:
            rows[fx.away_team_id]["pts"] += comp.points_win
            rows[fx.home_team_id]["pts"] += comp.points_loss
        else:
            rows[fx.home_team_id]["pts"] += comp.points_draw
            rows[fx.away_team_id]["pts"] += comp.points_draw
    ranked = sorted(rows.items(), key=lambda kv: (kv[1]["pts"], kv[1]["gf"] - kv[1]["ga"], kv[1]["gf"]), reverse=True)
    return [tid for tid, _ in ranked]


def _all_played(fixtures) -> bool:
    return bool(fixtures) and all(fx.status == FantasyFixture.STATUS_FINISHED for fx in fixtures)


def competition_fixtures(competition: FantasyCompetition) -> list[FantasyFixture]:
    """Every fixture of a competition, in one read, with its tabellino attached.

    A competition's prizes all ask about the same fixtures — six honours on a
    38-round championship re-read the same six hundred rows six times, which is
    most of the cost of drawing the home page. Callers that settle a whole
    competition (see ``honours``) read them once and hand the list down.
    """
    return list(
        FantasyFixture.objects.filter(competition=competition)
        .select_related("fantasy_matchday", "detail")
        # Dei tabellini servono i punteggi di squadra, non i referti: `payload` e'
        # l'intera pagella di venticinque giocatori e deserializzarla costa piu'
        # di tutto il resto messo insieme.
        .defer("detail__payload")
        .order_by("id")
    )


def _records(fixtures, details=None) -> dict[int, dict]:
    """Per-team totals for the measures a record prize can be awarded on.

    The team's score in a fixture is the fantasy total when the tabellino has one
    (``FantasyFixtureDetail.vfoot_*``, the sum of the eleven fantavoti) and the
    goals otherwise. In a classic league every concluded fixture has a detail and
    in aura none has, so the two never mix inside one competition — and if a
    half-converted league ever managed it, the average would still be an average
    of that team's own scores.
    """
    rows: dict[int, dict] = {}
    if details is None:
        details = {
            d.fixture_id: d for d in
            FantasyFixtureDetail.objects.filter(fixture_id__in=[fx.id for fx in fixtures])
        }

    def row(tid: int) -> dict:
        return rows.setdefault(tid, {"played": 0, "wins": 0, "goals_for": 0.0,
                                     "goals_against": 0.0, "score_sum": 0.0,
                                     "best_round": None})

    for fx in fixtures:
        detail = details.get(fx.id)
        h, a = row(fx.home_team_id), row(fx.away_team_id)
        hs, as_ = fx.home_total, fx.away_total
        h_score = detail.vfoot_home if detail else hs
        a_score = detail.vfoot_away if detail else as_
        for side, gf, ga, score in ((h, hs, as_, h_score), (a, as_, hs, a_score)):
            side["played"] += 1
            side["goals_for"] += gf
            side["goals_against"] += ga
            side["score_sum"] += score
            side["best_round"] = score if side["best_round"] is None else max(side["best_round"], score)
        if hs > as_:
            h["wins"] += 1
        elif as_ > hs:
            a["wins"] += 1
    return rows


def _measure(row: dict, stat: str) -> float:
    if stat == CompetitionPrize.STAT_AVG_SCORE:
        return row["score_sum"] / row["played"] if row["played"] else 0.0
    if stat == CompetitionPrize.STAT_BEST_ROUND:
        return row["best_round"] or 0.0
    if stat == CompetitionPrize.STAT_WINS:
        return float(row["wins"])
    return float(row.get(stat, 0.0))


def _record_holders(fixtures, stat: str, *, highest: bool, details=None) -> list[int]:
    """Who holds the record, everyone who ties for it included.

    Rounded to the third decimal before comparing: two teams whose averages differ
    at the twelfth are tied in every way anyone can see, and letting float noise
    pick a winner would make the honours board depend on the order of the sum.
    """
    rows = _records(fixtures, details)
    if not rows:
        return []
    values = {tid: round(_measure(row, stat), 3) for tid, row in rows.items()}
    want = max(values.values()) if highest else min(values.values())
    return sorted(tid for tid, v in values.items() if v == want)


def prize_scope(prize: CompetitionPrize, fixtures) -> list[FantasyFixture]:
    """The fixtures this prize is decided by: its phase's, or the competition's."""
    if prize.source_stage_id:
        return [fx for fx in fixtures if fx.stage_id == prize.source_stage_id]
    return list(fixtures)


def prize_winner_team_ids(prize: CompetitionPrize, fixtures=None) -> list[int]:
    """Teams that have won this prize, or [] while it is still undecided.

    ``fixtures`` is the competition's fixtures when the caller already holds them
    (``competition_fixtures``); left out, they are read here.
    """
    comp = prize.competition
    cond = prize.condition_type
    if fixtures is None:
        fixtures = competition_fixtures(comp)
    scope = prize_scope(prize, fixtures)

    if cond in (CompetitionPrize.CONDITION_STAT_TOP, CompetitionPrize.CONDITION_STAT_BOTTOM):
        # A record is read off the FULL run — a leader at round 12 has won nothing —
        # so the gate is the same "everything played" as the final table, over the
        # source stage when one is named and over the whole competition otherwise.
        if not _all_played(scope):
            return []
        details = {fx.id: getattr(fx, "detail", None) for fx in scope}
        return _record_holders(scope, prize.stat or CompetitionPrize.STAT_AVG_SCORE,
                               highest=cond == CompetitionPrize.CONDITION_STAT_TOP,
                               details={k: v for k, v in details.items() if v is not None})

    if cond == CompetitionPrize.CONDITION_FINAL_TABLE_RANGE:
        if not _all_played(fixtures):
            return []
        ranking = _table(fixtures, comp)
    elif prize.source_stage_id:
        if not _all_played(scope):
            return []
        if cond == CompetitionPrize.CONDITION_STAGE_TABLE_RANGE:
            ranking = _table(scope, comp)
        else:
            # The LAST round of the phase, not all of it. A phase is usually one
            # round — the wizard builds a cup as Quarti / Semifinali / Finale, three
            # stages — but nothing says it must be, and a hand-built "Fase finale"
            # holding semi-finals AND final would otherwise award the cup to both
            # semi-final winners and to nobody who actually lifted it.
            want_winner = cond == CompetitionPrize.CONDITION_STAGE_WINNER
            # La stessa regola con cui il tabellone manda avanti qualcuno: gol,
            # poi somma dei punteggi, poi fattore campo — e andata e ritorno
            # contano come una sfida sola. Se qui si decidesse diversamente, la
            # coppa la alzerebbe una squadra e in finale ne sarebbe passata
            # un'altra.
            outcomes = deciding_ties(scope)
            return [t.winner_id if want_winner else t.loser_id for t in outcomes]
    else:
        return []

    rf = max(1, prize.rank_from or 1)
    rt = max(rf, prize.rank_to or rf)
    return ranking[rf - 1 : rt]


# How each measure reads in a sentence, from both ends. Held here rather than
# assembled from "piu' alta / piu' bassa" because Italian does not work that way:
# the opposite of "miglior attacco" is "peggior attacco", not "attacco piu' basso".
_STAT_PHRASES = {
    CompetitionPrize.STAT_AVG_SCORE: ("media punteggio più alta", "media punteggio più bassa"),
    CompetitionPrize.STAT_GOALS_FOR: ("miglior attacco", "peggior attacco"),
    CompetitionPrize.STAT_GOALS_AGAINST: ("peggior difesa", "miglior difesa"),
    CompetitionPrize.STAT_BEST_ROUND: ("miglior punteggio in una giornata",
                                       "peggior punteggio migliore di giornata"),
    CompetitionPrize.STAT_WINS: ("più vittorie", "meno vittorie"),
}


def describe_condition(prize: CompetitionPrize) -> str:
    cond = prize.condition_type
    rf = prize.rank_from
    rt = prize.rank_to or rf
    stage = prize.source_stage.name if prize.source_stage_id else "?"
    if cond in (CompetitionPrize.CONDITION_STAT_TOP, CompetitionPrize.CONDITION_STAT_BOTTOM):
        top, bottom = _STAT_PHRASES.get(prize.stat, (prize.stat, prize.stat))
        phrase = top if cond == CompetitionPrize.CONDITION_STAT_TOP else bottom
        if prize.source_stage_id:
            return f"{phrase} in «{stage}»"
        return phrase
    if cond == CompetitionPrize.CONDITION_FINAL_TABLE_RANGE:
        if rf and rt and rf == rt:
            return f"{rf}° in classifica finale"
        return f"posizioni {rf}–{rt} della classifica finale"
    if cond == CompetitionPrize.CONDITION_STAGE_TABLE_RANGE:
        if rf and rt and rf == rt:
            return f"{rf}° nella classifica di «{stage}»"
        return f"posizioni {rf}–{rt} di «{stage}»"
    if cond == CompetitionPrize.CONDITION_STAGE_WINNER:
        return f"vince «{stage}»"
    if cond == CompetitionPrize.CONDITION_STAGE_LOSER:
        return f"perde «{stage}»"
    return cond


def default_prizes_for(competition: FantasyCompetition) -> list[dict]:
    """The honours a template implies, offered pre-filled by the wizard."""
    last_stage = CompetitionStage.objects.filter(competition=competition).order_by("-order_index", "-id").first()
    if competition.format == FantasyCompetition.FORMAT_LEAGUE:
        return [
            {"name": "Scudetto", "icon": "🏆", "condition": "winner"},
            {"name": "Secondo classificato", "icon": "🥈", "condition": "runner_up"},
        ]
    name = "Coppa"
    return [
        {"name": name, "icon": "🏆", "condition": "winner", "stage_id": last_stage.id if last_stage else None},
        {"name": "Finalista", "icon": "🥈", "condition": "runner_up", "stage_id": last_stage.id if last_stage else None},
    ]


def materialise_prize(competition: FantasyCompetition, spec: dict) -> CompetitionPrize:
    """Turn the wizard's vocabulary ("winner", "runner_up", "rank", "stat") into a
    condition.

    The wizard cannot name a stage that does not exist yet, and "chi vince" means a
    table position in a league and a final in a cup. Both translations happen here,
    once, instead of in every caller.
    """
    name = (spec.get("name") or "").strip()
    icon = (spec.get("icon") or "🏆")[:8]
    condition = spec.get("condition") or "winner"
    rank_from = spec.get("rank_from")
    rank_to = spec.get("rank_to")

    if condition == "stat":
        # A record does not care what shape the competition has: it is read off
        # every fixture of it, so there is no stage to translate and nothing that
        # differs between a championship and a cup.
        return CompetitionPrize.objects.create(
            competition=competition,
            name=name,
            icon=icon,
            condition_type=(CompetitionPrize.CONDITION_STAT_BOTTOM
                            if spec.get("direction") == "bottom"
                            else CompetitionPrize.CONDITION_STAT_TOP),
            stat=spec.get("stat") or CompetitionPrize.STAT_AVG_SCORE,
        )

    knockout_ending = competition.format in (
        FantasyCompetition.FORMAT_CUP,
        FantasyCompetition.FORMAT_GROUPS_KNOCKOUT,
    )
    last_stage = CompetitionStage.objects.filter(competition=competition).order_by("-order_index", "-id").first()

    if condition == "rank":
        rf = max(1, int(rank_from or 1))
        rt = max(rf, int(rank_to or rf))
        return CompetitionPrize.objects.create(
            competition=competition,
            name=name,
            icon=icon,
            condition_type=CompetitionPrize.CONDITION_FINAL_TABLE_RANGE,
            rank_from=rf,
            rank_to=rt,
        )

    if condition == "runner_up":
        if knockout_ending and last_stage:
            return CompetitionPrize.objects.create(
                competition=competition,
                name=name,
                icon=icon,
                condition_type=CompetitionPrize.CONDITION_STAGE_LOSER,
                source_stage=last_stage,
            )
        return CompetitionPrize.objects.create(
            competition=competition,
            name=name,
            icon=icon,
            condition_type=CompetitionPrize.CONDITION_FINAL_TABLE_RANGE,
            rank_from=2,
            rank_to=2,
        )

    # "winner"
    if knockout_ending and last_stage:
        return CompetitionPrize.objects.create(
            competition=competition,
            name=name,
            icon=icon,
            condition_type=CompetitionPrize.CONDITION_STAGE_WINNER,
            source_stage=last_stage,
        )
    return CompetitionPrize.objects.create(
        competition=competition,
        name=name,
        icon=icon,
        condition_type=CompetitionPrize.CONDITION_FINAL_TABLE_RANGE,
        rank_from=1,
        rank_to=1,
    )
