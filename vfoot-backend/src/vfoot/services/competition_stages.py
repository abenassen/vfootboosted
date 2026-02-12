from __future__ import annotations

from random import Random

from django.db import transaction

from vfoot.models import (
    CompetitionStage,
    CompetitionStageParticipant,
    CompetitionStageRule,
    CompetitionTeam,
    FantasyCompetition,
    FantasyFixture,
)


def _is_power_of_two(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def _floor_power_of_two(n: int) -> int:
    p = 1
    while p * 2 <= n:
        p *= 2
    return p


def _clear_stage_graph(competition: FantasyCompetition) -> None:
    stage_ids = list(CompetitionStage.objects.filter(competition=competition).values_list("id", flat=True))
    # Stage-based orchestration supersedes flat competition fixtures:
    # clear all fixtures for this competition before rebuilding the graph.
    FantasyFixture.objects.filter(competition=competition).delete()
    if stage_ids:
        CompetitionStage.objects.filter(id__in=stage_ids).delete()


def _round_robin_rounds(team_ids: list[int], seed: int = 42) -> list[list[tuple[int, int]]]:
    """
    Circle-method schedule:
    - even teams: n-1 rounds
    - odd teams: a BYE slot is inserted
    """
    rng = Random(seed)
    work = list(team_ids)
    rng.shuffle(work)

    if len(work) % 2 == 1:
        work.append(-1)  # BYE

    n = len(work)
    rounds: list[list[tuple[int, int]]] = []
    for r in range(n - 1):
        pairs: list[tuple[int, int]] = []
        for i in range(n // 2):
            a = work[i]
            b = work[n - 1 - i]
            if a == -1 or b == -1:
                continue
            if r % 2 == 0:
                pairs.append((a, b))
            else:
                pairs.append((b, a))
        rounds.append(pairs)
        work = [work[0], work[-1], *work[1:-1]]
    return rounds


@transaction.atomic
def _generate_round_robin_stage_fixtures(stage: CompetitionStage, seed: int = 42) -> int:
    entries = list(CompetitionStageParticipant.objects.filter(stage=stage).select_related("team"))
    team_ids = [e.team_id for e in entries]
    if len(team_ids) < 2:
        return 0

    rounds = _round_robin_rounds(team_ids, seed=seed)

    FantasyFixture.objects.filter(stage=stage).delete()
    fixtures: list[FantasyFixture] = []
    for round_no, pairs in enumerate(rounds, start=1):
        for home_id, away_id in pairs:
            fixtures.append(
                FantasyFixture(
                    competition=stage.competition,
                    stage=stage,
                    round_no=round_no,
                    leg_no=1,
                    home_team_id=home_id,
                    away_team_id=away_id,
                )
            )

    FantasyFixture.objects.bulk_create(fixtures, batch_size=500, ignore_conflicts=True)
    return FantasyFixture.objects.filter(stage=stage).count()


@transaction.atomic
def _generate_knockout_stage_fixtures(stage: CompetitionStage, seed: int = 42) -> int:
    entries = list(CompetitionStageParticipant.objects.filter(stage=stage).select_related("team"))
    team_ids = [e.team_id for e in entries]
    if len(team_ids) < 2 or len(team_ids) % 2 != 0:
        return 0

    rng = Random(seed)
    rng.shuffle(team_ids)

    FantasyFixture.objects.filter(stage=stage).delete()
    fixtures: list[FantasyFixture] = []
    pair_idx = 0
    for i in range(0, len(team_ids), 2):
        pair_idx += 1
        fixtures.append(
            FantasyFixture(
                competition=stage.competition,
                stage=stage,
                round_no=max(1, stage.order_index),
                leg_no=1,
                home_team_id=team_ids[i],
                away_team_id=team_ids[i + 1],
            )
        )

    FantasyFixture.objects.bulk_create(fixtures, batch_size=500, ignore_conflicts=True)
    return FantasyFixture.objects.filter(stage=stage).count()


def _stage_table_ranking(source_stage: CompetitionStage) -> list[int]:
    rows: dict[int, dict] = {}
    fixtures = FantasyFixture.objects.filter(stage=source_stage, status=FantasyFixture.STATUS_FINISHED)
    for fx in fixtures:
        for tid in [fx.home_team_id, fx.away_team_id]:
            rows.setdefault(tid, {"pts": 0, "gf": 0.0, "ga": 0.0})
        ht, at = fx.home_team_id, fx.away_team_id
        hs, as_ = fx.home_total, fx.away_total
        rows[ht]["gf"] += hs
        rows[ht]["ga"] += as_
        rows[at]["gf"] += as_
        rows[at]["ga"] += hs
        if hs > as_:
            rows[ht]["pts"] += source_stage.competition.points_win
            rows[at]["pts"] += source_stage.competition.points_loss
        elif hs < as_:
            rows[at]["pts"] += source_stage.competition.points_win
            rows[ht]["pts"] += source_stage.competition.points_loss
        else:
            rows[ht]["pts"] += source_stage.competition.points_draw
            rows[at]["pts"] += source_stage.competition.points_draw
    ranking = sorted(rows.items(), key=lambda kv: (kv[1]["pts"], kv[1]["gf"] - kv[1]["ga"], kv[1]["gf"]), reverse=True)
    return [tid for tid, _ in ranking]


def _stage_winners_or_losers(source_stage: CompetitionStage, mode: str) -> list[int]:
    winners: list[int] = []
    losers: list[int] = []
    fixtures = FantasyFixture.objects.filter(stage=source_stage, status=FantasyFixture.STATUS_FINISHED).order_by("id")
    for fx in fixtures:
        if fx.home_total == fx.away_total:
            continue
        if fx.home_total > fx.away_total:
            winners.append(fx.home_team_id)
            losers.append(fx.away_team_id)
        else:
            winners.append(fx.away_team_id)
            losers.append(fx.home_team_id)
    return winners if mode == CompetitionStageRule.MODE_WINNERS else losers


@transaction.atomic
def resolve_stage(stage: CompetitionStage, seed: int = 42) -> dict:
    CompetitionStageParticipant.objects.filter(stage=stage, source=CompetitionStageParticipant.SOURCE_RULE).delete()

    resolved = 0
    unresolved = 0
    for rule in CompetitionStageRule.objects.filter(target_stage=stage).select_related("source_stage"):
        source = rule.source_stage
        ids: list[int]
        if rule.mode == CompetitionStageRule.MODE_TABLE_RANGE:
            ranking = _stage_table_ranking(source)
            if not ranking:
                unresolved += 1
                continue
            rf = max(1, rule.rank_from or 1)
            rt = max(rf, rule.rank_to or rf)
            ids = ranking[rf - 1 : rt]
        else:
            ids = _stage_winners_or_losers(source, rule.mode)
            if not ids:
                unresolved += 1
                continue

        for tid in ids:
            _, created = CompetitionStageParticipant.objects.get_or_create(
                stage=stage,
                team_id=tid,
                defaults={"source": CompetitionStageParticipant.SOURCE_RULE},
            )
            if created:
                resolved += 1

    fixtures_created = 0
    if stage.stage_type == CompetitionStage.TYPE_ROUND_ROBIN:
        fixtures_created = _generate_round_robin_stage_fixtures(stage, seed=seed)
    elif stage.stage_type == CompetitionStage.TYPE_KNOCKOUT:
        fixtures_created = _generate_knockout_stage_fixtures(stage, seed=seed)

    return {
        "stage_id": stage.id,
        "resolved_rule_participants": resolved,
        "unresolved_rules": unresolved,
        "fixtures_created": fixtures_created,
    }


@transaction.atomic
def build_default_stage_graph(competition: FantasyCompetition, allow_repechage: bool = False, seed: int = 42) -> dict:
    base_entries = list(
        CompetitionTeam.objects.filter(competition=competition)
        .select_related("team")
        .order_by("seed", "id")
    )
    team_ids = [e.team_id for e in base_entries]
    if len(team_ids) < 2:
        raise ValueError("At least 2 teams are required.")

    _clear_stage_graph(competition)

    if competition.competition_type == FantasyCompetition.TYPE_ROUND_ROBIN:
        stage = CompetitionStage.objects.create(
            competition=competition,
            name="Regular season",
            stage_type=CompetitionStage.TYPE_ROUND_ROBIN,
            order_index=1,
        )
        CompetitionStageParticipant.objects.bulk_create(
            [
                CompetitionStageParticipant(stage=stage, team_id=tid, source=CompetitionStageParticipant.SOURCE_MANUAL)
                for tid in team_ids
            ]
        )
        fixtures = _generate_round_robin_stage_fixtures(stage, seed=seed)
        return {"competition_id": competition.id, "stages_created": 1, "fixtures_created": fixtures}

    rng = Random(seed)
    shuffled = list(team_ids)
    rng.shuffle(shuffled)
    n = len(shuffled)
    base = _floor_power_of_two(n)

    stages_created = 0
    fixtures_created = 0
    prev_stage = None
    working_round_teams: list[int] = shuffled
    stage_order = 1

    if n != base:
        # Play-in: reduce from n to nearest lower power-of-two.
        eliminate = n - base
        play_in_team_count = eliminate * 2
        if play_in_team_count > n:
            play_in_team_count = n - (n % 2)
        play_in_teams = shuffled[:play_in_team_count]
        bye_teams = shuffled[play_in_team_count:]

        play_in = CompetitionStage.objects.create(
            competition=competition,
            name="Play-in",
            stage_type=CompetitionStage.TYPE_KNOCKOUT,
            order_index=stage_order,
        )
        stages_created += 1
        stage_order += 1
        CompetitionStageParticipant.objects.bulk_create(
            [
                CompetitionStageParticipant(stage=play_in, team_id=tid, source=CompetitionStageParticipant.SOURCE_MANUAL)
                for tid in play_in_teams
            ]
        )
        fixtures_created += _generate_knockout_stage_fixtures(play_in, seed=seed)
        prev_stage = play_in
        working_round_teams = bye_teams

    round_size = base
    current_seed = seed + 17
    while round_size >= 2:
        if round_size == 2:
            name = "Final"
        elif round_size == 4:
            name = "Semifinal"
        elif round_size == 8:
            name = "Quarterfinal"
        else:
            name = f"Round of {round_size}"

        stage = CompetitionStage.objects.create(
            competition=competition,
            name=name,
            stage_type=CompetitionStage.TYPE_KNOCKOUT,
            order_index=stage_order,
        )
        stage_order += 1
        stages_created += 1

        if prev_stage is None:
            CompetitionStageParticipant.objects.bulk_create(
                [
                    CompetitionStageParticipant(stage=stage, team_id=tid, source=CompetitionStageParticipant.SOURCE_MANUAL)
                    for tid in working_round_teams
                ]
            )
            fixtures_created += _generate_knockout_stage_fixtures(stage, seed=current_seed)
        else:
            if working_round_teams:
                CompetitionStageParticipant.objects.bulk_create(
                    [
                        CompetitionStageParticipant(stage=stage, team_id=tid, source=CompetitionStageParticipant.SOURCE_MANUAL)
                        for tid in working_round_teams
                    ]
                )
            CompetitionStageRule.objects.create(
                target_stage=stage,
                source_stage=prev_stage,
                mode=CompetitionStageRule.MODE_WINNERS,
            )
            if not allow_repechage:
                resolve_stage(stage, seed=current_seed)

        prev_stage = stage
        working_round_teams = []
        round_size //= 2
        current_seed += 13

    return {
        "competition_id": competition.id,
        "stages_created": stages_created,
        "fixtures_created": fixtures_created,
        "allow_repechage": allow_repechage,
    }
