"""What a prize is worth: the condition that assigns it, and who has met it.

A prize is declared when the competition is created ("Scudetto: chi arriva primo",
"Coppa: chi vince la finale") and stays undecided until the rounds it depends on
have actually been played. Nothing here writes: the winner is DERIVED, so a
rectified result changes the honours board with it.
"""

from __future__ import annotations

from vfoot.models import CompetitionPrize, CompetitionStage, FantasyCompetition, FantasyFixture


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


def _all_played(qs) -> bool:
    return qs.exists() and not qs.exclude(status=FantasyFixture.STATUS_FINISHED).exists()


def prize_winner_team_ids(prize: CompetitionPrize) -> list[int]:
    """Teams that have won this prize, or [] while it is still undecided."""
    comp = prize.competition
    cond = prize.condition_type

    if cond == CompetitionPrize.CONDITION_FINAL_TABLE_RANGE:
        qs = FantasyFixture.objects.filter(competition=comp)
        if not _all_played(qs):
            return []
        ranking = _table(qs, comp)
    elif prize.source_stage_id:
        stage_qs = FantasyFixture.objects.filter(stage_id=prize.source_stage_id)
        if not _all_played(stage_qs):
            return []
        if cond == CompetitionPrize.CONDITION_STAGE_TABLE_RANGE:
            ranking = _table(stage_qs, comp)
        else:
            want_winner = cond == CompetitionPrize.CONDITION_STAGE_WINNER
            out: list[int] = []
            for fx in stage_qs.order_by("id"):
                if fx.home_total == fx.away_total:
                    continue
                home_won = fx.home_total > fx.away_total
                out.append(fx.home_team_id if home_won == want_winner else fx.away_team_id)
            return out
    else:
        return []

    rf = max(1, prize.rank_from or 1)
    rt = max(rf, prize.rank_to or rf)
    return ranking[rf - 1 : rt]


def describe_condition(prize: CompetitionPrize) -> str:
    cond = prize.condition_type
    rf = prize.rank_from
    rt = prize.rank_to or rf
    stage = prize.source_stage.name if prize.source_stage_id else "?"
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
    """Turn the wizard's vocabulary ("winner", "runner_up", "rank") into a condition.

    The wizard cannot name a stage that does not exist yet, and "chi vince" means a
    table position in a league and a final in a cup. Both translations happen here,
    once, instead of in every caller.
    """
    name = (spec.get("name") or "").strip()
    icon = (spec.get("icon") or "🏆")[:8]
    condition = spec.get("condition") or "winner"
    rank_from = spec.get("rank_from")
    rank_to = spec.get("rank_to")

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
