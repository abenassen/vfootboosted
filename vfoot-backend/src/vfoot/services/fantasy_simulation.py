from __future__ import annotations

from random import Random

from django.db import transaction
from django.utils import timezone

from realdata.models import Match, Player
from vfoot.models import (
    CompetitionTeam,
    FantasyCompetition,
    FantasyFixture,
    FantasyLineupSubmission,
    FantasyRosterSlot,
    FantasyTeam,
    LeagueMembership,
)


def _round_robin_rounds(team_ids: list[int], seed: int = 42) -> list[list[tuple[int, int]]]:
    """
    Circle-method schedule:
    - even teams: n-1 rounds
    - odd teams: adds a BYE pivot and still returns fair rounds
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
            # Alternate home/away for basic balance.
            if r % 2 == 0:
                pairs.append((a, b))
            else:
                pairs.append((b, a))
        rounds.append(pairs)
        # rotate all except first pivot
        work = [work[0], work[-1], *work[1:-1]]
    return rounds


@transaction.atomic
def generate_round_robin_fixtures(competition: FantasyCompetition, seed: int = 42) -> int:
    if competition.competition_type != FantasyCompetition.TYPE_ROUND_ROBIN:
        raise ValueError("Competition is not round-robin.")

    entries = list(CompetitionTeam.objects.filter(competition=competition).select_related("team"))
    team_ids = [e.team_id for e in entries]
    if len(team_ids) < 2:
        raise ValueError("At least 2 teams are required.")

    rounds = _round_robin_rounds(team_ids, seed=seed)

    FantasyFixture.objects.filter(competition=competition).delete()

    fixtures: list[FantasyFixture] = []
    for round_no, pairs in enumerate(rounds, start=1):
        for home_id, away_id in pairs:
            fixtures.append(
                FantasyFixture(
                    competition=competition,
                    round_no=round_no,
                    leg_no=1,
                    home_team_id=home_id,
                    away_team_id=away_id,
                )
            )

    FantasyFixture.objects.bulk_create(fixtures, batch_size=500)
    return len(fixtures)


@transaction.atomic
def generate_knockout_fixtures(competition: FantasyCompetition, seed: int = 42) -> int:
    if competition.competition_type != FantasyCompetition.TYPE_KNOCKOUT:
        raise ValueError("Competition is not knockout.")

    entries = list(CompetitionTeam.objects.filter(competition=competition).select_related("team"))
    team_ids = [e.team_id for e in entries]
    if len(team_ids) < 2:
        raise ValueError("At least 2 teams are required.")
    if len(team_ids) % 2 != 0:
        raise ValueError("Knockout competition requires an even number of teams.")

    rng = Random(seed)
    rng.shuffle(team_ids)

    FantasyFixture.objects.filter(competition=competition).delete()

    fixtures: list[FantasyFixture] = []
    for i in range(0, len(team_ids), 2):
        fixtures.append(
            FantasyFixture(
                competition=competition,
                round_no=1,
                leg_no=1,
                home_team_id=team_ids[i],
                away_team_id=team_ids[i + 1],
            )
        )

    FantasyFixture.objects.bulk_create(fixtures, batch_size=500)
    return len(fixtures)


@transaction.atomic
def map_real_matches_to_fixtures(competition: FantasyCompetition) -> int:
    """
    Beta mapping helper for simulation: assigns available real matches in order.
    Later this should be constrained by matchday windows and team/time coherence.
    """
    fixtures = list(FantasyFixture.objects.filter(competition=competition).order_by("round_no", "id"))
    real_matches = list(Match.objects.order_by("kickoff", "id")[: len(fixtures)])

    for i, fx in enumerate(fixtures):
        fx.source_real_match = real_matches[i] if i < len(real_matches) else None
    FantasyFixture.objects.bulk_update(fixtures, ["source_real_match"], batch_size=500)
    return len([f for f in fixtures if f.source_real_match_id is not None])


@transaction.atomic
def auto_submit_lineups_for_fixture(fixture: FantasyFixture) -> int:
    """
    Simulation helper: creates lineup submissions from active roster slots.
    """
    created = 0
    teams = [fixture.home_team, fixture.away_team]

    for team in teams:
        if FantasyLineupSubmission.objects.filter(fixture=fixture, team=team).exists():
            continue

        slots = list(
            FantasyRosterSlot.objects.filter(team=team, released_at__isnull=True)
            .select_related("player")
            .order_by("acquired_at", "id")
        )
        if len(slots) < 11:
            continue

        starters = slots[:11]
        bench = slots[11:16]

        FantasyLineupSubmission.objects.create(
            fixture=fixture,
            team=team,
            gk_player=starters[0].player,
            starter_player_ids=[f"P{s.player_id}" for s in starters],
            bench_player_ids=[f"P{s.player_id}" for s in bench],
            starter_backups=[],
            submitted_by=team.manager.user,
        )
        created += 1

    return created


@transaction.atomic
def bulk_assign_players_to_teams(
    league_id: int,
    player_ids: list[int],
    purchase_price: int = 1,
    random_seed: int = 42,
) -> int:
    teams = list(FantasyTeam.objects.filter(league_id=league_id).order_by("id"))
    if not teams:
        raise ValueError("League has no teams.")

    players = list(Player.objects.filter(id__in=player_ids).order_by("id"))
    if not players:
        raise ValueError("No valid players found.")

    rng = Random(random_seed)
    rng.shuffle(players)

    # clear only active slots for fresh assignment
    FantasyRosterSlot.objects.filter(team__league_id=league_id, released_at__isnull=True).update(released_at=timezone.now())

    created = 0
    for idx, p in enumerate(players):
        t = teams[idx % len(teams)]
        FantasyRosterSlot.objects.create(team=t, player=p, purchase_price=purchase_price)
        created += 1
    return created
