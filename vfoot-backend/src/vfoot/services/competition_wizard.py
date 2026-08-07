"""One transaction, one competition.

Creating a competition used to be four or five separate calls from the browser —
container, stages, qualification rule, calendar, prizes — each able to fail on its
own and leave a half-built thing behind that the UI then had to explain. It is one
call now: the whole shape is described up front, validated, and either built or
not built at all.
"""

from __future__ import annotations

from django.db import transaction

from vfoot.models import (
    CompetitionStage,
    CompetitionStageRule,
    CompetitionTeam,
    FantasyCompetition,
    FantasyTeam,
)
from vfoot.services import competition_calendar as calendar
from vfoot.services.competition_prizes import materialise_prize
from vfoot.services.competition_stages import (
    MAX_LEGS,
    build_cup_graph,
    build_groups_knockout_graph,
    build_league_graph,
    competition_round_rows,
    recompute_round_layout,
    resolve_pending_stages,
)

FORMATS = (
    FantasyCompetition.FORMAT_LEAGUE,
    FantasyCompetition.FORMAT_CUP,
    FantasyCompetition.FORMAT_GROUPS_KNOCKOUT,
)


class WizardError(ValueError):
    pass


def qualified_team_count(source_stage: CompetitionStage, mode: str, rank_from, rank_to) -> int:
    """How many teams a qualification rule will produce, before it produces them."""
    if mode == CompetitionStageRule.MODE_TABLE_RANGE:
        rf = max(1, int(rank_from or 1))
        rt = max(rf, int(rank_to or rf))
        return rt - rf + 1
    # winners/losers of a knockout stage: one per tie.
    played = source_stage.fixtures.count()
    if played:
        return played
    expected = source_stage.expected_participants or 0
    return max(1, expected // 2)


def _entry_stages(competition: FantasyCompetition) -> list[CompetitionStage]:
    """The stages a competition's field walks in through: the earliest ones."""
    stages = list(CompetitionStage.objects.filter(competition=competition).order_by("order_index", "id"))
    if not stages:
        return []
    first_order = stages[0].order_index
    return [s for s in stages if s.order_index == first_order]


@transaction.atomic
def create_competition(
    league,
    *,
    name: str,
    fmt: str,
    team_ids: list[int] | None = None,
    qualification: dict | None = None,
    legs: int = 1,
    knockout_legs: int = 1,
    final_legs: int | None = None,
    groups: int = 1,
    advance_per_group: int = 2,
    points: dict | None = None,
    start_matchday: int | None = None,
    end_matchday: int | None = None,
    prizes: list[dict] | None = None,
    seed: int = 42,
) -> dict:
    name = (name or "").strip()
    if not name:
        raise WizardError("Serve un nome per la competizione.")
    if fmt not in FORMATS:
        raise WizardError("Formato non riconosciuto.")
    if FantasyCompetition.objects.filter(league=league, name=name).exists():
        raise WizardError("Esiste già una competizione con questo nome in questa lega.")

    legs = max(1, min(MAX_LEGS, int(legs or 1)))
    # Un turno a eliminazione si gioca una volta o due: "tre volte" non è un turno.
    knockout_legs = 2 if int(knockout_legs or 1) == 2 else 1
    final_legs = knockout_legs if final_legs is None else (2 if int(final_legs) == 2 else 1)
    groups = max(1, int(groups or 1))
    advance_per_group = max(1, int(advance_per_group or 1))

    # --- who plays -------------------------------------------------------
    source_stage = None
    expected_teams = 0
    resolved_team_ids: list[int] = []

    if qualification:
        source_stage = (
            CompetitionStage.objects.filter(id=qualification.get("source_stage_id"))
            .select_related("competition")
            .first()
        )
        if source_stage is None or source_stage.competition.league_id != league.id:
            raise WizardError("Lo stage di qualificazione non appartiene a questa lega.")
        mode = qualification.get("mode") or CompetitionStageRule.MODE_TABLE_RANGE
        expected_teams = qualified_team_count(
            source_stage, mode, qualification.get("rank_from"), qualification.get("rank_to")
        )
        if expected_teams < 2:
            raise WizardError("Devono qualificarsi almeno 2 squadre.")
        source_round = qualification.get("source_round")
        if source_round is not None:
            rows = competition_round_rows(source_stage.competition)
            valid = {r["round_no"] for r in rows}
            if int(source_round) not in valid:
                last = max(valid) if valid else 0
                raise WizardError(
                    f"«{source_stage.competition.name}» arriva al turno {last}: "
                    f"il {source_round}º non esiste."
                )
        if fmt == FantasyCompetition.FORMAT_GROUPS_KNOCKOUT and groups > 1:
            raise WizardError(
                "Con i partecipanti qualificati da un'altra competizione è previsto un girone unico."
            )
    else:
        valid_ids = list(
            FantasyTeam.objects.filter(league=league, id__in=list(team_ids or [])).values_list("id", flat=True)
        )
        resolved_team_ids = [tid for tid in (team_ids or []) if tid in set(valid_ids)]
        if len(resolved_team_ids) < 2:
            raise WizardError("Servono almeno 2 squadre.")
        expected_teams = len(resolved_team_ids)

    competition_type = (
        FantasyCompetition.TYPE_ROUND_ROBIN
        if fmt == FantasyCompetition.FORMAT_LEAGUE
        else FantasyCompetition.TYPE_KNOCKOUT
    )
    pts = points or {}
    comp = FantasyCompetition.objects.create(
        league=league,
        name=name,
        format=fmt,
        competition_type=competition_type,
        status=FantasyCompetition.STATUS_ACTIVE,
        points_win=int(pts.get("win", 3)),
        points_draw=int(pts.get("draw", 1)),
        points_loss=int(pts.get("loss", 0)),
        start_matchday=start_matchday,
        end_matchday=end_matchday,
    )
    if resolved_team_ids:
        CompetitionTeam.objects.bulk_create(
            [CompetitionTeam(competition=comp, team_id=tid) for tid in resolved_team_ids]
        )

    # --- the shape -------------------------------------------------------
    try:
        if fmt == FantasyCompetition.FORMAT_LEAGUE:
            if resolved_team_ids:
                build_league_graph(comp, resolved_team_ids, legs=legs, seed=seed)
            else:
                # Rule-fed league: the stage exists with its rounds planned from the
                # promised head-count, so the calendar can be laid out today even
                # though the field is decided months from now.
                CompetitionStage.objects.create(
                    competition=comp,
                    name="Campionato",
                    stage_type=CompetitionStage.TYPE_ROUND_ROBIN,
                    order_index=1,
                    legs=legs,
                    expected_participants=expected_teams,
                )
                recompute_round_layout(comp)
        elif fmt == FantasyCompetition.FORMAT_CUP:
            build_cup_graph(
                comp,
                team_ids=resolved_team_ids or None,
                expected_teams=expected_teams,
                seed=seed,
                knockout_legs=knockout_legs,
                final_legs=final_legs,
            )
        else:
            build_groups_knockout_graph(
                comp,
                team_ids=resolved_team_ids or None,
                expected_teams=expected_teams,
                groups=groups,
                advance_per_group=advance_per_group,
                legs=legs,
                seed=seed,
                knockout_legs=knockout_legs,
                final_legs=final_legs,
            )
    except ValueError as exc:
        raise WizardError(str(exc)) from exc

    # --- how the field is decided ---------------------------------------
    if qualification and source_stage is not None:
        mode = qualification.get("mode") or CompetitionStageRule.MODE_TABLE_RANGE
        for entry in _entry_stages(comp):
            CompetitionStageRule.objects.create(
                target_stage=entry,
                source_stage=source_stage,
                mode=mode,
                source_round=qualification.get("source_round"),
                rank_from=qualification.get("rank_from"),
                rank_to=qualification.get("rank_to"),
            )

    # --- when it is played ----------------------------------------------
    schedule_result = calendar.schedule(comp, start_md=start_matchday, end_md=end_matchday)

    # A league created on an already-concluded season can resolve at once; one on a
    # season still to be played simply waits, and the calendar is already there for
    # when it does.
    resolution = resolve_pending_stages(comp, seed=seed)
    if resolution["stages_filled"]:
        recompute_round_layout(comp)
        schedule_result = calendar.schedule(comp)

    # --- what is at stake ------------------------------------------------
    created_prizes = []
    for spec in prizes or []:
        if not (spec.get("name") or "").strip():
            continue
        created_prizes.append(materialise_prize(comp, spec))

    comp.refresh_from_db()
    return {
        "competition": comp,
        "schedule": schedule_result,
        "resolution": resolution,
        "prizes": created_prizes,
    }
