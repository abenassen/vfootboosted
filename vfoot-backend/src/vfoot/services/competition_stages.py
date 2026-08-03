"""Stage graph: how a competition is shaped, numbered and filled.

Three separable jobs live here.

1. LAYOUT — a competition is a container of stages, and its rounds are numbered
   competition-wide (the calendar, the "table after round N" qualification rules
   and the fixture uniqueness constraint all key on the round number). Stages that
   share an ``order_index`` run in PARALLEL (two groups played side by side) and
   share their rounds; a later ``order_index`` is numbered after the earlier ones.
   ``recompute_round_layout`` owns ``round_offset`` and keeps existing fixtures in
   step by SHIFTING them, never by regenerating — results already played must
   survive a stage being added next to them.

2. GENERATION — pairings for a stage whose participants are known.

3. RESOLUTION — filling a stage whose participants are a rule ("the top 4 of the
   group", "the winners of the semifinals") once the source has been played.
"""

from __future__ import annotations

from random import Random

from django.db import transaction

from realdata.models import Match
from vfoot.models import (
    CompetitionStage,
    CompetitionStageParticipant,
    CompetitionStageRule,
    CompetitionTeam,
    FantasyCompetition,
    FantasyFixture,
    FantasyMatchday,
)

# A round-robin of this many teams over this many legs is already a full season;
# past it the calendar has nowhere left to go. 5 legs of 8 teams = 35 rounds.
MAX_LEGS = 5


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


# Stage names are shown to the user as they are — the wizard speaks Italian
# ("Campionato", "Coppa", "Turno preliminare"), so what it generates must too.
# Keyed by the number of TEAMS still in the round; the API labels rounds by the
# number of FIXTURES instead (_KO_ROUND_LABELS in league_views), which is why the
# two tables look similar but are not the same mapping.
_KO_STAGE_NAMES = {
    2: "Finale",
    4: "Semifinali",
    8: "Quarti di finale",
    16: "Ottavi di finale",
    32: "Sedicesimi di finale",
}


def knockout_stage_name(round_size: int) -> str:
    return _KO_STAGE_NAMES.get(round_size, f"Turno da {round_size}")


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def rounds_per_leg(team_count: int) -> int:
    """Rounds one full pass of a round-robin takes. Odd fields need a bye round."""
    if team_count < 2:
        return 0
    return team_count - 1 if team_count % 2 == 0 else team_count


def stage_team_count(stage: CompetitionStage) -> int:
    """Teams this stage will field: the ones it has, or the ones it is promised."""
    actual = CompetitionStageParticipant.objects.filter(stage=stage).count()
    return actual or max(0, stage.expected_participants or 0)


def stage_legs(stage: CompetitionStage) -> int:
    """Quante volte si gioca ogni accoppiamento di questa fase.

    Per un turno a eliminazione sono 1 (gara secca) o 2 (andata e ritorno): un
    terzo incontro fra le stesse due squadre non e' un turno, e' un'altra cosa.
    """
    legs = max(1, min(MAX_LEGS, stage.legs or 1))
    if stage.stage_type == CompetitionStage.TYPE_KNOCKOUT:
        return min(2, legs)
    return legs


def home_advantage_for_leg(leg: int, legs: int) -> bool:
    """La tornata ``leg`` di ``legs`` si gioca su un campo, o in campo neutro?

    Le tornate si compensano a coppie: nella prima ospito io, nella seconda tu.
    Se sono in numero DISPARI l'ultima non ha una gemella — qualcuno giocherebbe
    in casa una volta in piu' degli altri — e allora si gioca in campo neutro.
    Il caso piu' comune e' anche il piu' facile da dimenticare: la sola andata
    (``legs`` = 1) e' tutta campo neutro, perche' chi ospita l'ha deciso il
    sorteggio del calendario e non il merito.
    """
    return leg <= legs - (legs % 2)


def planned_rounds_for(stage: CompetitionStage) -> int:
    if stage.stage_type == CompetitionStage.TYPE_KNOCKOUT:
        # Andata e ritorno occupano DUE turni della competizione, quindi due
        # giornate: il calendario le distribuisce come qualunque altra coppia di
        # turni, e le due gare del confronto restano una sfida sola (v. knockout).
        return stage_legs(stage)
    n = stage_team_count(stage)
    return max(1, rounds_per_leg(n) * stage_legs(stage))


@transaction.atomic
def recompute_round_layout(competition: FantasyCompetition) -> dict:
    """Re-derive every stage's round span and offset, shifting fixtures to match.

    Called after ANY change to the stage graph. Fixtures are moved, not rebuilt:
    a stage inserted before another must not wipe results the other already has.
    """
    stages = list(CompetitionStage.objects.filter(competition=competition).order_by("order_index", "id"))
    offset = 0
    group_span = 0
    current_order: int | None = None
    shifted = 0

    for stage in stages:
        if stage.order_index != current_order:
            offset += group_span
            group_span = 0
            current_order = stage.order_index

        planned = planned_rounds_for(stage)
        old_offset = stage.round_offset or 0
        if old_offset != offset or stage.planned_rounds != planned:
            delta = offset - old_offset
            stage.round_offset = offset
            stage.planned_rounds = planned
            stage.save(update_fields=["round_offset", "planned_rounds"])
            if delta:
                # Move whole rounds at a time, and in the order that cannot collide
                # with the rounds not moved yet: unique_together includes round_no.
                rounds = sorted(
                    set(FantasyFixture.objects.filter(stage=stage).values_list("round_no", flat=True)),
                    reverse=delta > 0,
                )
                for rno in rounds:
                    shifted += FantasyFixture.objects.filter(stage=stage, round_no=rno).update(
                        round_no=rno + delta
                    )

        group_span = max(group_span, planned)

    return {"competition_id": competition.id, "stages": len(stages), "fixtures_shifted": shifted}


def competition_round_rows(competition: FantasyCompetition) -> list[dict]:
    """Every round of the competition, in order, said in the user's terms.

    "Round 9" means nothing on its own once a competition has more than one stage;
    "Semifinali · gara 1" does. This is the list the calendar UI and the
    qualification-rule picker both read.
    """
    stages = list(CompetitionStage.objects.filter(competition=competition).order_by("order_index", "id"))
    rows: dict[int, dict] = {}
    for stage in stages:
        span = stage.planned_rounds or planned_rounds_for(stage)
        for local in range(1, span + 1):
            rno = (stage.round_offset or 0) + local
            if rno in rows:
                # Parallel groups share rounds: name the round once, for the group.
                rows[rno]["stage_names"].append(stage.name)
                continue
            rows[rno] = {
                "round_no": rno,
                "stage_id": stage.id,
                "stage_names": [stage.name],
                "stage_type": stage.stage_type,
                "local_round": local,
                "local_rounds": span,
            }

    if not rows:
        # A flat competition (no stages) still has whatever rounds its fixtures show.
        for rno in sorted(set(FantasyFixture.objects.filter(competition=competition).values_list("round_no", flat=True))):
            rows[rno] = {
                "round_no": rno,
                "stage_id": None,
                "stage_names": [competition.name],
                "stage_type": competition.competition_type,
                "local_round": rno,
                "local_rounds": 0,
            }

    out = []
    for rno in sorted(rows):
        row = rows[rno]
        stage_label = " / ".join(row.pop("stage_names"))
        if row["stage_type"] == CompetitionStage.TYPE_KNOCKOUT and row["local_rounds"] == 2:
            # Due turni di una fase a eliminazione sono una sfida sola giocata due
            # volte: "Semifinali · giornata 2" suonerebbe come un secondo turno.
            row["label"] = f"{stage_label} · {'andata' if row['local_round'] == 1 else 'ritorno'}"
        elif row["local_rounds"] > 1:
            row["label"] = f"{stage_label} · giornata {row['local_round']}"
        else:
            row["label"] = stage_label
        row["stage_name"] = stage_label
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


def _kickoff_for(real_competition_season_id: int, real_matchday: int):
    return (
        Match.objects.filter(
            competition_season_id=real_competition_season_id,
            matchday=real_matchday,
            kickoff__isnull=False,
        )
        .order_by("kickoff")
        .values_list("kickoff", flat=True)
        .first()
    )


@transaction.atomic
def apply_round_calendar(competition: FantasyCompetition, real_competition_season_id: int | None = None) -> int:
    """Hang the fixtures on the real matchdays the PLAN assigns to their rounds.

    Idempotent, and safe to call whenever fixtures appear — which is the point: a
    rule-fed cup gets its calendar the day it is created and its fixtures weeks
    later, when the group it waits on finishes.
    """
    calendar = competition.round_calendar or {}
    if not calendar:
        return 0
    csid = real_competition_season_id
    if csid is None:
        season = competition.league.reference_season
        csid = season.id if season else None
    if not csid:
        return 0

    scheduled = 0
    md_cache: dict[int, FantasyMatchday] = {}
    for raw_round, raw_md in calendar.items():
        try:
            rno = int(raw_round)
            real_md = int(raw_md)
        except (TypeError, ValueError):
            continue
        fmd = md_cache.get(real_md)
        if fmd is None:
            fmd, _ = FantasyMatchday.objects.get_or_create(
                league=competition.league,
                real_competition_season_id=csid,
                real_matchday=real_md,
            )
            md_cache[real_md] = fmd
        # A played game keeps the matchday it was played on: rescheduling is about
        # what is still to come, and moving a finished fixture would detach its
        # result from the real performances that produced it.
        updated = (
            FantasyFixture.objects.filter(competition=competition, round_no=rno)
            .exclude(status=FantasyFixture.STATUS_FINISHED)
            .update(fantasy_matchday=fmd, kickoff=_kickoff_for(csid, real_md))
        )
        scheduled += int(updated or 0)
    return scheduled


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


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
    legs = stage_legs(stage)
    base = stage.round_offset or 0

    FantasyFixture.objects.filter(stage=stage).delete()
    fixtures: list[FantasyFixture] = []
    for leg in range(1, legs + 1):
        # Even legs are the return legs: same pairings, ground swapped. With an odd
        # number of legs somebody would end up one home game ahead — so that last
        # tornata is played on neutral ground and the home bonus does not apply.
        swap = leg % 2 == 0
        at_home = home_advantage_for_leg(leg, legs)
        for local_round, pairs in enumerate(rounds, start=1):
            round_no = base + (leg - 1) * len(rounds) + local_round
            for home_id, away_id in pairs:
                h, a = (away_id, home_id) if swap else (home_id, away_id)
                fixtures.append(
                    FantasyFixture(
                        competition=stage.competition,
                        stage=stage,
                        round_no=round_no,
                        leg_no=leg,
                        home_team_id=h,
                        away_team_id=a,
                        home_advantage=at_home,
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
    base = (stage.round_offset or 0) + 1
    legs = stage_legs(stage)
    fixtures: list[FantasyFixture] = []
    for i in range(0, len(team_ids), 2):
        a, b = team_ids[i], team_ids[i + 1]
        for leg in range(1, legs + 1):
            # Andata e ritorno: stessa sfida, campi invertiti, e il turno successivo
            # della competizione — cioe' un'altra giornata, che e' il punto. Con la
            # gara secca (legs = 1) non cambia nulla rispetto a prima.
            home, away = (b, a) if leg == 2 else (a, b)
            fixtures.append(
                FantasyFixture(
                    competition=stage.competition,
                    stage=stage,
                    round_no=base + leg - 1,
                    leg_no=leg,
                    home_team_id=home,
                    away_team_id=away,
                    # Una sfida a due gare ha un campo per ciascuno; una gara secca
                    # e' campo neutro, chi "ospita" l'ha deciso il sorteggio.
                    home_advantage=legs == 2,
                )
            )

    FantasyFixture.objects.bulk_create(fixtures, batch_size=500, ignore_conflicts=True)
    return FantasyFixture.objects.filter(stage=stage).count()


def stage_has_results(stage: CompetitionStage) -> bool:
    return FantasyFixture.objects.filter(stage=stage, status=FantasyFixture.STATUS_FINISHED).exists()


def generate_stage_fixtures(stage: CompetitionStage, seed: int = 42) -> int:
    # Generation is destructive by design (a new draw replaces the old one). Once a
    # single fixture of the stage has been played that is no longer acceptable:
    # freeze it and let the caller say so, rather than quietly erasing results.
    if stage_has_results(stage):
        return 0
    if stage.stage_type == CompetitionStage.TYPE_ROUND_ROBIN:
        return _generate_round_robin_stage_fixtures(stage, seed=seed)
    if stage.stage_type == CompetitionStage.TYPE_KNOCKOUT:
        return _generate_knockout_stage_fixtures(stage, seed=seed)
    return 0


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _stage_table_ranking(source_stage: CompetitionStage, cut_round: int | None = None) -> list[int]:
    rows: dict[int, dict] = {}
    fixtures = FantasyFixture.objects.filter(stage=source_stage, status=FantasyFixture.STATUS_FINISHED)
    if cut_round is not None:
        fixtures = fixtures.filter(round_no__lte=cut_round)
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
    """Chi passa e chi esce da una fase a eliminazione.

    Una sfida in parità NON è più un turno senza vincitore: la si decide col
    punteggio (vedi ``knockout``, che è la stessa regola letta dai premi). Prima
    veniva semplicemente saltata, e siccome il turno successivo si sorteggia solo
    quando la sua regola produce un campo, un pareggio in semifinale lasciava la
    finale non sorteggiata e la competizione senza fine.
    """
    from vfoot.services.knockout import tie_outcomes

    fixtures = list(
        FantasyFixture.objects.filter(stage=source_stage, status=FantasyFixture.STATUS_FINISHED)
        .select_related("detail")
        .order_by("id")
    )
    outcomes = tie_outcomes(fixtures)
    if mode == CompetitionStageRule.MODE_WINNERS:
        return [t.winner_id for t in outcomes]
    return [t.loser_id for t in outcomes]


def rule_is_ready(rule: CompetitionStageRule) -> bool:
    """Is the source played far enough for this rule to mean anything?

    A table read while its rounds are still being played is not the table the rule
    names, so a half-finished source is treated as no source at all rather than
    silently qualifying whoever happens to lead.
    """
    fixtures = FantasyFixture.objects.filter(stage=rule.source_stage)
    if rule.mode == CompetitionStageRule.MODE_TABLE_RANGE and rule.source_round:
        fixtures = fixtures.filter(round_no__lte=rule.source_round)
    if not fixtures.exists():
        return False
    return not fixtures.exclude(status=FantasyFixture.STATUS_FINISHED).exists()


@transaction.atomic
def resolve_stage(stage: CompetitionStage, seed: int = 42) -> dict:
    CompetitionStageParticipant.objects.filter(stage=stage, source=CompetitionStageParticipant.SOURCE_RULE).delete()

    resolved = 0
    unresolved = 0
    for rule in CompetitionStageRule.objects.filter(target_stage=stage).select_related("source_stage"):
        source = rule.source_stage
        if not rule_is_ready(rule):
            unresolved += 1
            continue
        ids: list[int]
        if rule.mode == CompetitionStageRule.MODE_TABLE_RANGE:
            ranking = _stage_table_ranking(source, cut_round=rule.source_round)
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

    # A stage still waiting on a source is NOT drawn, even if some of its field is
    # already known: a play-in bracket whose byes are in place would otherwise be
    # drawn between the byes alone, and the winners coming up would have nowhere
    # to go. Half a field is not a field.
    fixtures_created = 0
    calendar = {"moved": {}, "unplaceable": [], "warnings": []}
    no_matchdays_left = False
    if not unresolved:
        # BEFORE drawing, not after: the dates the plan reserved for this stage may
        # have gone by while it waited for its source (a postponement, or an admin
        # who closed the deciding round late). Fixtures created onto a matchday that
        # has already kicked off are a tie nobody could ever field. Local import —
        # competition_calendar reads this module.
        from vfoot.services.competition_calendar import (
            reflow_pending_rounds, rounds_already_counted,
        )

        calendar = reflow_pending_rounds(stage.competition)
        # ...and if the delay has outrun the season, DO NOT DRAW. Two ways it has,
        # and they are independent because each is invisible to the other's test:
        #
        # * no matchday is still FIELDABLE for these rounds — the tie would be one
        #   nobody could choose a lineup for, decided by whatever fallback the
        #   conclusion applies, and it would hand out a trophy for a competition
        #   that was never played;
        # * the matchday has already been COUNTED. The fieldability check is
        #   deliberately inert on a league with no lineup deadline and on a season
        #   with nothing left to field (see plan_rounds), which is precisely where
        #   this one bites: the fixture would hang off a concluded round and no
        #   code path would ever score it. A permanent 0-0.
        #
        # The stage stays empty and says why. Whether to call the competition off is
        # the admin's decision, not something to do to him by side effect.
        mine = list(range(
            (stage.round_offset or 0) + 1,
            (stage.round_offset or 0) + (stage.planned_rounds or 1) + 1))
        no_matchdays_left = bool(
            set(mine) & set(calendar["unplaceable"])
            or rounds_already_counted(stage.competition, mine)
        )
        if not no_matchdays_left:
            fixtures_created = generate_stage_fixtures(stage, seed=seed)
    if fixtures_created:
        # New fixtures inherit the calendar their rounds were already planned for.
        apply_round_calendar(stage.competition)

    return {
        "stage_id": stage.id,
        "resolved_rule_participants": resolved,
        "unresolved_rules": unresolved,
        "fixtures_created": fixtures_created,
        # WHERE it ended up, when that is not where the plan said. The degenerate
        # case — a phase whose source arrives so late that the season has no
        # fieldable matchday left — cannot be fixed here (there is nowhere to put
        # it), so it is REFUSED and reported instead of being drawn onto a past
        # round in silence.
        "calendar_moved": calendar["moved"],
        "calendar_warnings": calendar["warnings"],
        "no_matchdays_left": no_matchdays_left,
    }


def resolve_pending_stages(competition: FantasyCompetition, seed: int = 42) -> dict:
    """Try to fill every stage that is still waiting on a rule, earliest first."""
    filled = 0
    still_waiting = 0
    moved: dict[int, int] = {}
    warnings: list[str] = []
    unplayable: list[int] = []
    for stage in CompetitionStage.objects.filter(competition=competition).order_by("order_index", "id"):
        if not CompetitionStageRule.objects.filter(target_stage=stage).exists():
            continue
        if FantasyFixture.objects.filter(stage=stage).exists():
            continue
        result = resolve_stage(stage, seed=seed)
        moved.update(result["calendar_moved"])
        warnings.extend(result["calendar_warnings"])
        if result["no_matchdays_left"]:
            unplayable.append(stage.id)
        if result["fixtures_created"]:
            filled += 1
        else:
            still_waiting += 1
    return {"stages_filled": filled, "stages_waiting": still_waiting,
            "calendar_moved": moved, "calendar_warnings": warnings,
            # Stages that will never be drawn now: the season ran out. The caller
            # surfaces this — it is the one outcome the admin has to act on.
            "stages_without_matchdays": unplayable}


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def _knockout_chain(
    competition: FantasyCompetition,
    *,
    entry_team_count: int,
    start_order: int,
    seed: int,
    legs: int = 1,
    final_legs: int | None = None,
) -> list[CompetitionStage]:
    """Bracket stages for ``entry_team_count`` teams, each fed by the previous one.

    Participants are NOT assigned here — the caller either seeds the first stage
    with real teams or points a rule at it.

    ``legs`` = 2 makes every round a two-legged tie. ``final_legs`` overrides it
    for the last round alone, because that is how cups are actually played:
    andata e ritorno fino alla semifinale, finale in gara secca.
    """
    legs = 2 if legs == 2 else 1
    final_legs = legs if final_legs is None else (2 if final_legs == 2 else 1)
    stages: list[CompetitionStage] = []
    order = start_order
    base = _floor_power_of_two(entry_team_count)

    if entry_team_count != base:
        play_in = CompetitionStage.objects.create(
            competition=competition,
            name="Turno preliminare",
            stage_type=CompetitionStage.TYPE_KNOCKOUT,
            order_index=order,
            legs=legs,
            expected_participants=(entry_team_count - base) * 2,
        )
        stages.append(play_in)
        order += 1

    size = base
    while size >= 2:
        stage = CompetitionStage.objects.create(
            competition=competition,
            name=knockout_stage_name(size),
            stage_type=CompetitionStage.TYPE_KNOCKOUT,
            order_index=order,
            legs=final_legs if size == 2 else legs,
            expected_participants=size,
        )
        stages.append(stage)
        order += 1
        size //= 2

    for prev, nxt in zip(stages, stages[1:]):
        CompetitionStageRule.objects.create(
            target_stage=nxt,
            source_stage=prev,
            mode=CompetitionStageRule.MODE_WINNERS,
        )
    return stages


@transaction.atomic
def build_league_graph(competition: FantasyCompetition, team_ids: list[int], legs: int = 1, seed: int = 42) -> dict:
    """One stage, everybody against everybody, ``legs`` times over."""
    _clear_stage_graph(competition)
    stage = CompetitionStage.objects.create(
        competition=competition,
        name="Campionato",
        stage_type=CompetitionStage.TYPE_ROUND_ROBIN,
        order_index=1,
        legs=max(1, min(MAX_LEGS, legs)),
        expected_participants=len(team_ids),
    )
    CompetitionStageParticipant.objects.bulk_create(
        [
            CompetitionStageParticipant(stage=stage, team_id=tid, source=CompetitionStageParticipant.SOURCE_MANUAL)
            for tid in team_ids
        ]
    )
    recompute_round_layout(competition)
    stage.refresh_from_db()
    fixtures = _generate_round_robin_stage_fixtures(stage, seed=seed)
    return {"competition_id": competition.id, "stages_created": 1, "fixtures_created": fixtures}


@transaction.atomic
def build_cup_graph(
    competition: FantasyCompetition,
    team_ids: list[int] | None = None,
    expected_teams: int | None = None,
    seed: int = 42,
    knockout_legs: int = 1,
    final_legs: int | None = None,
) -> dict:
    """A straight bracket. ``team_ids`` when the field is known, ``expected_teams``
    when it is still a promise (a cup fed by a table that has not been played).

    ``knockout_legs`` = 2 plays every round over andata e ritorno; ``final_legs``
    lets the final be a single match anyway, which is how most cups are run."""
    _clear_stage_graph(competition)
    n = len(team_ids) if team_ids else int(expected_teams or 0)
    if n < 2:
        raise ValueError("At least 2 teams are required.")

    stages = _knockout_chain(competition, entry_team_count=n, start_order=1, seed=seed,
                             legs=knockout_legs, final_legs=final_legs)
    recompute_round_layout(competition)

    fixtures_created = 0
    if team_ids:
        first = stages[0]
        first.refresh_from_db()
        rng = Random(seed)
        shuffled = list(team_ids)
        rng.shuffle(shuffled)
        base = _floor_power_of_two(n)
        if n != base:
            play_in_count = (n - base) * 2
            play_in_teams = shuffled[:play_in_count]
            bye_teams = shuffled[play_in_count:]
            CompetitionStageParticipant.objects.bulk_create(
                [
                    CompetitionStageParticipant(stage=first, team_id=tid, source=CompetitionStageParticipant.SOURCE_MANUAL)
                    for tid in play_in_teams
                ]
            )
            fixtures_created += _generate_knockout_stage_fixtures(first, seed=seed)
            # The teams that skip the play-in wait in the next stage; the winners of
            # the play-in join them there through the rule already in place.
            second = stages[1]
            second.refresh_from_db()
            CompetitionStageParticipant.objects.bulk_create(
                [
                    CompetitionStageParticipant(stage=second, team_id=tid, source=CompetitionStageParticipant.SOURCE_MANUAL)
                    for tid in bye_teams
                ]
            )
        else:
            CompetitionStageParticipant.objects.bulk_create(
                [
                    CompetitionStageParticipant(stage=first, team_id=tid, source=CompetitionStageParticipant.SOURCE_MANUAL)
                    for tid in shuffled
                ]
            )
            fixtures_created += _generate_knockout_stage_fixtures(first, seed=seed)

    return {
        "competition_id": competition.id,
        "stages_created": len(stages),
        "fixtures_created": fixtures_created,
        "first_stage_id": stages[0].id if stages else None,
    }


@transaction.atomic
def build_groups_knockout_graph(
    competition: FantasyCompetition,
    team_ids: list[int] | None = None,
    expected_teams: int | None = None,
    groups: int = 1,
    advance_per_group: int = 2,
    legs: int = 1,
    seed: int = 42,
    knockout_legs: int = 1,
    final_legs: int | None = None,
) -> dict:
    """Group stage(s), then a bracket for whoever finishes high enough.

    The World Cup shape, and the one the wizard was missing: the groups are
    ordinary round-robin stages sharing ``order_index`` 1 (they run side by side,
    on the same rounds), and the bracket is fed by table-range rules — so it fills
    itself the moment the groups are done.
    """
    _clear_stage_graph(competition)
    n = len(team_ids) if team_ids else int(expected_teams or 0)
    groups = max(1, int(groups))
    advance_per_group = max(1, int(advance_per_group))
    if n < 2:
        raise ValueError("At least 2 teams are required.")
    if groups > n // 2:
        raise ValueError("Troppi gironi per il numero di squadre.")
    qualified = groups * advance_per_group
    if qualified < 2:
        raise ValueError("Devono qualificarsi almeno 2 squadre.")
    if qualified > n:
        raise ValueError("Non possono qualificarsi più squadre di quante partecipano.")

    rng = Random(seed)
    shuffled = list(team_ids or [])
    rng.shuffle(shuffled)

    group_stages: list[CompetitionStage] = []
    fixtures_created = 0
    for gi in range(groups):
        size = n // groups + (1 if gi < n % groups else 0)
        if advance_per_group > size:
            raise ValueError("Da ogni girone non possono passare più squadre di quante lo compongono.")
        stage = CompetitionStage.objects.create(
            competition=competition,
            name="Girone unico" if groups == 1 else f"Girone {chr(ord('A') + gi)}",
            stage_type=CompetitionStage.TYPE_ROUND_ROBIN,
            order_index=1,
            legs=max(1, min(MAX_LEGS, legs)),
            expected_participants=size,
        )
        group_stages.append(stage)

    ko_stages = _knockout_chain(competition, entry_team_count=qualified, start_order=2, seed=seed,
                                legs=knockout_legs, final_legs=final_legs)
    first_ko = ko_stages[0]
    for stage in group_stages:
        CompetitionStageRule.objects.create(
            target_stage=first_ko,
            source_stage=stage,
            mode=CompetitionStageRule.MODE_TABLE_RANGE,
            rank_from=1,
            rank_to=advance_per_group,
        )

    recompute_round_layout(competition)

    if shuffled:
        cursor = 0
        for gi, stage in enumerate(group_stages):
            size = n // groups + (1 if gi < n % groups else 0)
            slice_ids = shuffled[cursor : cursor + size]
            cursor += size
            CompetitionStageParticipant.objects.bulk_create(
                [
                    CompetitionStageParticipant(stage=stage, team_id=tid, source=CompetitionStageParticipant.SOURCE_MANUAL)
                    for tid in slice_ids
                ]
            )
            stage.refresh_from_db()
            fixtures_created += _generate_round_robin_stage_fixtures(stage, seed=seed + gi)

    return {
        "competition_id": competition.id,
        "stages_created": len(group_stages) + len(ko_stages),
        "fixtures_created": fixtures_created,
        "group_stage_ids": [s.id for s in group_stages],
        "knockout_stage_ids": [s.id for s in ko_stages],
    }


@transaction.atomic
def build_default_stage_graph(
    competition: FantasyCompetition,
    allow_repechage: bool = False,
    seed: int = 42,
    legs: int = 1,
) -> dict:
    """Legacy entry point: shape a competition from its own participants + type."""
    base_entries = list(
        CompetitionTeam.objects.filter(competition=competition)
        .select_related("team")
        .order_by("seed", "id")
    )
    team_ids = [e.team_id for e in base_entries]
    if len(team_ids) < 2:
        raise ValueError("At least 2 teams are required.")

    if competition.competition_type == FantasyCompetition.TYPE_ROUND_ROBIN:
        return build_league_graph(competition, team_ids, legs=legs, seed=seed)
    result = build_cup_graph(competition, team_ids=team_ids, seed=seed)
    if not allow_repechage:
        resolve_pending_stages(competition, seed=seed)
    return result
