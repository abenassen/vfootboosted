"""The calendar of a competition BEFORE its teams are known.

A competition's rounds exist as a plan long before there is a fixture to hang on
them: ``round_calendar`` reserves a real matchday for every round the stage graph
foresees, and a stage fed by a rule ("the winners of the semifinals", "the top 4
of the championship after round 7") stays empty until the source has been played.
Read only through the fixtures — which is what the calendar page did — those
rounds simply do not exist, so a cup whose semifinals are being played shows
nothing at all for the final and looks finished.

What this module produces is the OTHER half of the calendar: the rounds that are
planned and undrawn, each with the rule that will fill it, said in a sentence a
manager can act on ("Le vincenti di «Semifinali»"). Two levels, because the
undetermined part can be either:

* ONE tie — the final, whose two teams are a semifinal away. Naming it is enough.
* A WHOLE PHASE — a group stage entered by the top four of a championship. Listing
  its six matches would be six copies of "da definire"; the honest thing is to
  drop the fixture list and present the rule in its place, with the span of
  matchdays it will occupy.

Both come out of the same per-stage record, so the UI decides which to draw from
``planned_rounds`` and does not need a second concept.

It also answers the question that only shows up when something goes wrong: WHY a
stage has not filled yet. "Waiting for round 7" is the normal case and needs no
alarm; "waiting for a matchday the admin never closed" and "waiting for a matchday
parked for a postponement" are the two that quietly stop a competition, and they
are told apart here — see ``blocker``.
"""
from __future__ import annotations

from vfoot.models import (
    CompetitionStage,
    CompetitionStageRule,
    FantasyCompetition,
    FantasyFixture,
    FantasyMatchday,
)
from vfoot.services.competition_stages import (
    competition_round_rows,
    rule_is_ready,
    stage_team_count,
)

# ---------------------------------------------------------------------------
# Saying the rule out loud
# ---------------------------------------------------------------------------

def _table_range_phrase(rank_from: int, rank_to: int) -> str:
    if rank_from == rank_to:
        return f"La {rank_from}ª classificata"
    if rank_from == 1:
        return f"Le prime {rank_to}"
    return f"Dalla {rank_from}ª alla {rank_to}ª classificata"


def _source_label(rule: CompetitionStageRule, competition: FantasyCompetition) -> str:
    """«Semifinali» inside the competition, «Girone A» di Champions from outside.

    A competition made of ONE stage simply IS that stage, and naming both —
    «Campionato» di Campionato Lega — is a database detail leaking into a sentence
    a manager reads. There the competition's name is the whole answer.
    """
    source = rule.source_stage
    if source.competition_id == competition.id:
        return f"«{source.name}»"
    if CompetitionStage.objects.filter(competition_id=source.competition_id).count() == 1:
        return f"«{source.competition.name}»"
    return f"«{source.name}» di {source.competition.name}"


def rule_sentence(rule: CompetitionStageRule, competition: FantasyCompetition) -> str:
    """The rule as a manager reads it, not as the database stores it."""
    where = _source_label(rule, competition)
    if rule.mode == CompetitionStageRule.MODE_WINNERS:
        return f"Le vincenti di {where}"
    if rule.mode == CompetitionStageRule.MODE_LOSERS:
        return f"Le perdenti di {where}"
    rank_from = max(1, rule.rank_from or 1)
    rank_to = max(rank_from, rule.rank_to or rank_from)
    # Only a CUT needs saying. With no round the rule reads the final table, which
    # is what "la classifica di «Girone unico»" already means — spelling it out
    # ("a fine competizione") says the same thing twice and, when the source is a
    # stage rather than a whole competition, says it wrongly.
    cut = f" dopo il turno {rule.source_round}" if rule.source_round else ""
    return f"{_table_range_phrase(rank_from, rank_to)} di {where}{cut}"


# ---------------------------------------------------------------------------
# Why it has not happened yet
# ---------------------------------------------------------------------------

def _unfinished_source_rounds(rule: CompetitionStageRule) -> list[FantasyFixture]:
    fixtures = FantasyFixture.objects.filter(stage=rule.source_stage)
    if rule.mode == CompetitionStageRule.MODE_TABLE_RANGE and rule.source_round:
        fixtures = fixtures.filter(round_no__lte=rule.source_round)
    return list(
        fixtures.exclude(status=FantasyFixture.STATUS_FINISHED)
        .select_related("fantasy_matchday")
        .order_by("round_no", "id")
    )


def blocker(rule: CompetitionStageRule, league) -> dict | None:
    """Why this rule cannot be applied yet — or None when it can.

    Three answers, and the difference between them is the whole reason this exists.
    Only the first is normal:

    * ``da_giocare``     — the round it reads has not been played. Nothing is wrong;
                           it will happen by itself on the matchday named.
    * ``da_conteggiare`` — every real match of that matchday is in the books and the
                           admin has not concluded it. The LEAGUE is what is late,
                           not football, and nothing downstream can move until he
                           clicks. A forgotten conclusion does not stop the league
                           (deliberately, see matchday_state) but it does stop every
                           competition that reads it, silently, which is why it is
                           named here rather than left to be inferred.
    * ``recupero``       — that matchday is parked waiting for a postponed match.
                           This is the one that can deadlock: the league has moved
                           on, the round that decides the field will not close until
                           the recovery is played, and the phase it feeds may be due
                           before that happens.
    """
    if rule_is_ready(rule):
        return None

    pending = _unfinished_source_rounds(rule)
    source_comp = rule.source_stage.competition
    if not pending:
        # No fixtures at all in the source: it is itself waiting to be drawn.
        return {
            "kind": "sorgente_da_definire",
            "detail": f"«{rule.source_stage.name}» non ha ancora le sue squadre",
            "real_matchday": None,
            "source_competition_id": source_comp.id,
        }

    first = pending[0]
    real_md = (first.fantasy_matchday.real_matchday
               if first.fantasy_matchday_id else None)
    base = {"real_matchday": real_md, "source_competition_id": source_comp.id,
            "source_round": first.round_no}
    if real_md is None:
        return {**base, "kind": "da_giocare",
                "detail": f"il turno {first.round_no} di {source_comp.name} non ha ancora una data"}

    md = FantasyMatchday.objects.filter(
        league=league, real_matchday=real_md).order_by("id").first()
    if md is not None and md.status == FantasyMatchday.STATUS_AWAITING:
        reason = f" ({md.awaiting_reason})" if md.awaiting_reason else ""
        return {**base, "kind": "recupero",
                "detail": f"la giornata {real_md} è in attesa di recupero{reason}"}

    if md is not None and md.status != FantasyMatchday.STATUS_CONCLUDED:
        from vfoot.api.league_views import _real_matchday_stats  # local: avoids a cycle

        stats = _real_matchday_stats(md.real_competition_season_id, real_md, league)
        if stats["is_completed"]:
            return {**base, "kind": "da_conteggiare",
                    "detail": f"la giornata {real_md} è finita ma non è ancora stata conclusa"}

    return {**base, "kind": "da_giocare",
            "detail": f"si gioca sulla giornata {real_md}"}


# ---------------------------------------------------------------------------
# The plan, stage by stage
# ---------------------------------------------------------------------------

def _expected_fixtures_per_round(stage: CompetitionStage) -> int:
    """How many matches one round of this stage will hold once it is drawn."""
    n = stage_team_count(stage)
    return max(0, n // 2)


def stage_plan(competition: FantasyCompetition, league=None) -> list[dict]:
    """One record per stage: where it sits, whether it is drawn, and if not, why.

    ``league`` is only needed to explain a blockage in the league's own terms
    (parked matchday / unconcluded matchday); without it the rule is still named,
    which is what the calendar mostly wants.
    """
    league = league or competition.league
    calendar = {int(k): int(v) for k, v in (competition.round_calendar or {}).items()
                if str(k).isdigit()}
    stages = list(
        CompetitionStage.objects.filter(competition=competition)
        .order_by("order_index", "id")
    )
    fixture_rounds: dict[int, int] = {}
    for sid, rno in FantasyFixture.objects.filter(competition=competition).values_list(
            "stage_id", "round_no"):
        fixture_rounds[sid] = fixture_rounds.get(sid, 0) + 1

    rules_by_target: dict[int, list[CompetitionStageRule]] = {}
    for rule in (CompetitionStageRule.objects
                 .filter(target_stage__competition=competition)
                 .select_related("source_stage", "source_stage__competition")):
        rules_by_target.setdefault(rule.target_stage_id, []).append(rule)

    # Computed at most once, and only if some stage actually needs it: this
    # serializer runs for every competition of the league on every page.
    cache: dict[str, set[int]] = {}

    def unplaceable() -> set[int]:
        """Rounds that can no longer be played — the same two tests the draw makes,
        so the calendar cannot promise a sorteggio that `resolve_stage` will refuse."""
        if "v" not in cache:
            from vfoot.services.competition_calendar import (
                plan_rounds, rounds_already_counted,
            )
            all_rounds = [r["round_no"] for r in competition_round_rows(competition)]
            cache["v"] = (set(plan_rounds(competition)["unplaceable"])
                          | set(rounds_already_counted(competition, all_rounds)))
        return cache["v"]

    out = []
    for stage in stages:
        first_round = (stage.round_offset or 0) + 1
        last_round = (stage.round_offset or 0) + (stage.planned_rounds or 1)
        mds = [calendar[r] for r in range(first_round, last_round + 1) if r in calendar]
        rules = rules_by_target.get(stage.id, [])
        fixtures = fixture_rounds.get(stage.id, 0)
        described = []
        blockers = []
        # Is there anywhere left in the season to play it? Asked only for a stage
        # that is still waiting — for everyone else the answer is "it is already
        # scheduled" and the query would be pure cost. See plan_rounds: the same
        # arithmetic the reflow uses, so the calendar cannot promise a slot the
        # draw will then refuse.
        if rules and not fixtures and set(range(first_round, last_round + 1)) & unplaceable():
            blockers.append({
                "kind": "senza_giornate",
                "detail": "le giornate su cui doveva giocarsi sono passate o già conteggiate",
                "real_matchday": None,
                "source_competition_id": competition.id,
            })
        for rule in rules:
            why = blocker(rule, league) if not fixtures else None
            described.append({
                "mode": rule.mode,
                "text": rule_sentence(rule, competition),
                "source_stage_id": rule.source_stage_id,
                "source_stage_name": rule.source_stage.name,
                "source_competition_id": rule.source_stage.competition_id,
                "source_competition_name": rule.source_stage.competition.name,
                "source_round": rule.source_round,
                "ready": why is None,
                "blocker": why,
            })
            if why is not None:
                blockers.append(why)
        # The one worth showing: "it can no longer be played" beats a deadlock, a
        # deadlock beats a wait, and a wait beats nothing. Naming the wait on a
        # phase that has run out of season would be answering the wrong question.
        rank = {"senza_giornate": -1, "recupero": 0, "da_conteggiare": 1,
                "sorgente_da_definire": 2, "da_giocare": 3}
        worst = min(blockers, key=lambda b: rank.get(b["kind"], 9), default=None)
        out.append({
            "stage_id": stage.id,
            "name": stage.name,
            "stage_type": stage.stage_type,
            "order_index": stage.order_index,
            "first_round": first_round,
            "last_round": last_round,
            "planned_rounds": stage.planned_rounds or 1,
            "first_matchday": min(mds) if mds else None,
            "last_matchday": max(mds) if mds else None,
            "fixtures": fixtures,
            "expected_participants": stage.expected_participants or 0,
            "expected_fixtures_per_round": _expected_fixtures_per_round(stage),
            # Planned, undrawn, and fed by a rule: the state this module is about.
            # A stage with no rule and no fixtures is not "pending", it is unbuilt —
            # the admin has to draw it himself, and pretending a rule will is worse
            # than saying nothing.
            "pending": bool(rules) and fixtures == 0,
            "rules": described,
            "rule_text": " + ".join(r["text"] for r in described),
            "blocker": worst,
        })
    return out


def pending_rounds(competition: FantasyCompetition, league=None,
                   plans: list[dict] | None = None) -> dict[int, dict]:
    """{round_no: the stage plan it belongs to} for every planned, undrawn round.

    The lookup the calendar needs: given a round with no fixtures, what should be
    shown in their place. ``plans`` lets a caller that already has the stage plan
    reuse it — computing it explains a blockage, which costs queries.
    """
    plans = [p for p in (plans if plans is not None else stage_plan(competition, league))
             if p["pending"]]
    out: dict[int, dict] = {}
    for plan in plans:
        for rno in range(plan["first_round"], plan["last_round"] + 1):
            out[rno] = plan
    return out


def matchday_impacts(league) -> dict[int, list[dict]]:
    """{real matchday: the phases whose field it decides}.

    The answer the admin needs at exactly two moments, and at both of them the
    screen used to say nothing:

    * he is about to PARK a matchday for a postponement. The league carries on —
      deliberately, see ``matchday_state`` — but a cup that reads the table of that
      round does not, and it will sit undrawn until the recovery is played. If its
      own matchdays go by in the meantime it has missed its slot;
    * he is LATE closing one. Same consequence, no postponement to blame: the
      competition is waiting on a click.

    ``at_risk`` is the one that turns a note into a warning: the phase's own first
    matchday has ALREADY locked, so it cannot be played where it was planned and
    will have to be moved (which ``competition_calendar.reflow_pending_rounds``
    does, at the moment it is finally drawn).
    """
    from vfoot.services import matchday_state

    csid = league.reference_season_id
    locked = matchday_state.locked_matchdays(csid) if csid else set()

    out: dict[int, list[dict]] = {}
    for competition in FantasyCompetition.objects.filter(league=league):
        for plan in stage_plan(competition, league):
            if not plan["pending"]:
                continue
            for rule_row in plan["rules"]:
                why = rule_row["blocker"]
                if why is None or why.get("real_matchday") is None:
                    continue
                target = plan["first_matchday"]
                out.setdefault(int(why["real_matchday"]), []).append({
                    "competition_id": competition.id,
                    "competition_name": competition.name,
                    "stage_id": plan["stage_id"],
                    "stage_name": plan["name"],
                    "rule_text": rule_row["text"],
                    "blocker_kind": why["kind"],
                    "target_matchday": target,
                    "at_risk": target is not None and target in locked,
                })
    return out


def round_plan_rows(competition: FantasyCompetition, league=None,
                    plans: list[dict] | None = None) -> list[dict]:
    """Every round of the competition — drawn or not — with what fills it.

    ``competition_round_rows`` already knows the layout; this adds the two things a
    calendar cannot work without: how many fixtures the round actually has, and,
    when it has none, the rule that will give it some.
    """
    counts: dict[int, int] = {}
    for rno in FantasyFixture.objects.filter(competition=competition).values_list(
            "round_no", flat=True):
        counts[rno] = counts.get(rno, 0) + 1
    pending = pending_rounds(competition, league, plans)
    calendar = {str(k): int(v) for k, v in (competition.round_calendar or {}).items()
                if str(k).isdigit()}
    rows = []
    for row in competition_round_rows(competition):
        rno = row["round_no"]
        plan = pending.get(rno)
        rows.append({
            **row,
            "real_matchday": calendar.get(str(rno)),
            "fixtures": counts.get(rno, 0),
            "pending": plan is not None,
            "rule_text": plan["rule_text"] if plan else None,
            "blocker": plan["blocker"] if plan else None,
            "expected_fixtures": (plan["expected_fixtures_per_round"] if plan else 0),
        })
    return rows
