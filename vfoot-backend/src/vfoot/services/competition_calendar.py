"""Where a competition's rounds land on the real championship calendar.

A fantasy round is played "on" a real matchday: that is what decides which real
performances score it. Mapping the two is mostly arithmetic — spread N rounds over
the available matchdays — but two constraints make it more than that, and both were
missing:

* A competition whose field is decided by another one cannot START before the
  moment that decides it. "The top 4 after round 7 enter the cup" and "the cup
  begins on matchday 3" cannot both be true.
* Two rounds of the same competition cannot share a real matchday: a team would
  play twice, and its lineup for that matchday is a single object.

Both are enforced here, in one place, for the preview and for the write — so what
the admin is shown is exactly what will be saved.
"""

from __future__ import annotations

from django.db import transaction

from realdata.models import Match
from vfoot.models import (
    CompetitionQualificationRule,
    CompetitionStage,
    CompetitionStageRule,
    FantasyCompetition,
    FantasyFixture,
)
from vfoot.services.competition_stages import (
    apply_round_calendar,
    competition_round_rows,
    recompute_round_layout,
)


# ---------------------------------------------------------------------------
# Available real matchdays
# ---------------------------------------------------------------------------


def _pick_real_competition_and_matchdays(starts_at, ends_at):
    """Legacy fallback: infer the real season from the competition's date window."""
    from django.db.models import Count

    if not starts_at or not ends_at:
        return None, []

    base = Match.objects.filter(
        kickoff__date__gte=starts_at,
        kickoff__date__lte=ends_at,
        matchday__isnull=False,
    )
    if not base.exists():
        return None, []

    top = (
        base.values("competition_season_id")
        .annotate(c=Count("id"))
        .order_by("-c", "competition_season_id")
        .first()
    )
    if not top:
        return None, []
    csid = int(top["competition_season_id"])
    matchdays = list(
        base.filter(competition_season_id=csid)
        .order_by("matchday")
        .values_list("matchday", flat=True)
        .distinct()
    )
    return csid, [int(x) for x in matchdays if x is not None]


def season_matchdays(competition: FantasyCompetition) -> tuple[int | None, list[int]]:
    """Every real matchday of the league's reference season, span ignored."""
    season = competition.league.reference_season
    if season is None:
        return _pick_real_competition_and_matchdays(competition.starts_at, competition.ends_at)
    matchdays = list(
        Match.objects.filter(competition_season_id=season.id, matchday__isnull=False)
        .order_by("matchday")
        .values_list("matchday", flat=True)
        .distinct()
    )
    return season.id, [int(x) for x in matchdays if x is not None]


def reference_matchdays(competition: FantasyCompetition, start_md=None, end_md=None):
    """Real matchdays usable by this competition, inside the [start, end] span."""
    csid, matchdays = season_matchdays(competition)
    if csid is None:
        return None, []
    lo = start_md if start_md is not None else competition.start_matchday
    hi = end_md if end_md is not None else competition.end_matchday
    out = [md for md in matchdays if (lo is None or md >= lo) and (hi is None or md <= hi)]
    return csid, out


# ---------------------------------------------------------------------------
# Dependencies: what has to happen before this competition can start
# ---------------------------------------------------------------------------


def _round_matchday(competition: FantasyCompetition, round_no: int | None) -> int | None:
    """Real matchday a given round of ``competition`` is played on."""
    if round_no is None:
        return None
    planned = (competition.round_calendar or {}).get(str(round_no))
    if planned:
        return int(planned)
    row = (
        FantasyFixture.objects.filter(competition=competition, round_no=round_no, fantasy_matchday__isnull=False)
        .select_related("fantasy_matchday")
        .values_list("fantasy_matchday__real_matchday", flat=True)
        .first()
    )
    return int(row) if row is not None else None


def _last_round(competition: FantasyCompetition) -> int | None:
    rows = competition_round_rows(competition)
    return rows[-1]["round_no"] if rows else None


def dependencies(competition: FantasyCompetition) -> list[dict]:
    """Every "this competition waits on that one" link, with the matchday it lands on.

    Both mechanisms are read: the stage rules (what the wizard writes now) and the
    older competition-level qualification rules, so a league built before the
    rewrite is constrained just the same.
    """
    out: list[dict] = []

    rules = (
        CompetitionStageRule.objects.filter(target_stage__competition=competition)
        .exclude(source_stage__competition=competition)
        .select_related("source_stage", "source_stage__competition", "target_stage")
    )
    for rule in rules:
        source_comp = rule.source_stage.competition
        cut = rule.source_round or _last_round(source_comp)
        out.append(
            {
                "kind": "stage_rule",
                "source_competition_id": source_comp.id,
                "source_competition_name": source_comp.name,
                "source_stage_name": rule.source_stage.name,
                "source_round": cut,
                "real_matchday": _round_matchday(source_comp, cut),
                "target_stage_id": rule.target_stage_id,
            }
        )

    for rule in (
        CompetitionQualificationRule.objects.filter(competition=competition)
        .exclude(source_competition=competition)
        .select_related("source_competition")
    ):
        source_comp = rule.source_competition
        cut = rule.source_round or _last_round(source_comp)
        out.append(
            {
                "kind": "qualification_rule",
                "source_competition_id": source_comp.id,
                "source_competition_name": source_comp.name,
                "source_stage_name": None,
                "source_round": cut,
                "real_matchday": _round_matchday(source_comp, cut),
                "target_stage_id": None,
            }
        )
    return out


def earliest_start_matchday(competition: FantasyCompetition) -> tuple[int | None, list[str]]:
    """First real matchday this competition may be played on, and why."""
    floor: int | None = None
    reasons: list[str] = []
    for dep in dependencies(competition):
        md = dep["real_matchday"]
        if md is None:
            continue
        candidate = int(md) + 1
        who = dep["source_competition_name"]
        # TURNO, perché è il conto interno dell'altra competizione — e questa
        # frase dice "giornata reale" due parole dopo, per un numero diverso.
        where = f"turno {dep['source_round']}" if dep["source_round"] else "fine"
        reasons.append(
            f"i partecipanti si decidono a {where} di «{who}» (giornata reale {md}): "
            f"non può iniziare prima della {candidate}ª"
        )
        floor = candidate if floor is None else max(floor, candidate)
    return floor, reasons


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def uniform_mapping(round_nos: list[int], real_matchdays: list[int], spread: bool = True) -> dict[int, int]:
    """Place each round on a real matchday, one round per matchday.

    ``spread`` decides between the two things "automatic" can mean, and the
    difference is not cosmetic: two cup rounds over the 26 matchdays left in a
    season come out as matchday 13 and matchday 38 when spread, which is nobody's
    idea of a cup. So spreading happens only when the admin has SAID where the
    competition ends; with an open end, rounds run back to back from the start.
    """
    mapping: dict[int, int] = {}
    if not round_nos or not real_matchdays:
        return mapping
    if not spread or len(round_nos) >= len(real_matchdays):
        for rno, md in zip(round_nos, real_matchdays):
            mapping[rno] = md
        return mapping
    span = len(real_matchdays) - 1
    steps = len(round_nos) - 1
    used: set[int] = set()
    for idx, rno in enumerate(round_nos):
        pos = 0 if steps == 0 else int(round(idx * span / steps))
        while pos < len(real_matchdays) and real_matchdays[pos] in used:
            pos += 1
        pos = min(pos, len(real_matchdays) - 1)
        mapping[rno] = real_matchdays[pos]
        used.add(real_matchdays[pos])
    return mapping


def normalise_mapping(
    round_nos: list[int],
    proposed: dict[int, int],
    available: list[int],
) -> tuple[dict[int, int], list[str]]:
    """Force a mapping to be legal: inside the span, and strictly increasing."""
    warnings: list[str] = []
    allowed = [md for md in available]
    out: dict[int, int] = {}
    last: int | None = None
    for rno in round_nos:
        want = proposed.get(rno)
        candidates = [md for md in allowed if last is None or md > last]
        if not candidates:
            warnings.append(f"turno {rno}: non restano giornate reali disponibili")
            continue
        if want is None or want not in allowed:
            chosen = candidates[0]
        elif last is not None and want <= last:
            chosen = candidates[0]
            warnings.append(
                f"turno {rno}: spostato alla {chosen}ª — non può essere giocato prima del precedente"
            )
        else:
            chosen = want
        out[rno] = chosen
        last = chosen
    return out, warnings


def _mapping_from_fixtures(competition: FantasyCompetition) -> dict[int, int]:
    """Where the rounds actually are, for a competition built before the plan existed."""
    mapping: dict[int, int] = {}
    for rno, real_md in (
        FantasyFixture.objects.filter(competition=competition, fantasy_matchday__isnull=False)
        .values_list("round_no", "fantasy_matchday__real_matchday")
        .distinct()
    ):
        if rno is None or real_md is None:
            continue
        mapping[int(rno)] = int(real_md)
    return mapping


def preview(competition: FantasyCompetition, start_md=None, end_md=None) -> dict:
    # Read-only on purpose: recomputing the layout here would renumber the rounds
    # of a competition somebody merely opened to look at.
    rows = competition_round_rows(competition)
    round_nos = [r["round_no"] for r in rows]
    csid, all_matchdays = season_matchdays(competition)
    floor, floor_reasons = earliest_start_matchday(competition)

    effective_start = start_md if start_md is not None else competition.start_matchday
    if floor is not None:
        effective_start = floor if effective_start is None else max(int(effective_start), floor)
    effective_end = end_md if end_md is not None else competition.end_matchday

    available = [
        md
        for md in all_matchdays
        if (effective_start is None or md >= effective_start) and (effective_end is None or md <= effective_end)
    ]

    stored = {int(k): int(v) for k, v in (competition.round_calendar or {}).items() if str(k).isdigit()}
    if not stored:
        stored = _mapping_from_fixtures(competition)
    base = uniform_mapping(round_nos, available, spread=effective_end is not None)
    proposed, _ = normalise_mapping(round_nos, base, available)
    current, current_warnings = normalise_mapping(round_nos, stored, available) if stored else ({}, [])

    warnings = list(current_warnings)
    if round_nos and len(available) < len(round_nos):
        warnings.append(
            f"servono {len(round_nos)} giornate reali, nell'intervallo scelto ce ne sono {len(available)}"
        )

    return {
        "competition_id": competition.id,
        "competition_name": competition.name,
        "starts_at": competition.starts_at.isoformat() if competition.starts_at else None,
        "ends_at": competition.ends_at.isoformat() if competition.ends_at else None,
        "start_matchday": effective_start,
        "end_matchday": effective_end,
        "min_start_matchday": floor,
        "constraints": floor_reasons,
        "dependencies": dependencies(competition),
        "rounds": round_nos,
        "round_rows": rows,
        "available_real_matchdays": available,
        "season_real_matchdays": all_matchdays,
        "real_competition_season_id": csid,
        "proposed_mapping": proposed,
        "current_mapping": current or stored,
        "warnings": warnings,
    }


@transaction.atomic
def schedule(
    competition: FantasyCompetition,
    round_mapping: dict[int, int] | None = None,
    start_md=None,
    end_md=None,
) -> dict:
    """Write the calendar: store the plan, then hang the fixtures on it."""
    recompute_round_layout(competition)
    rows = competition_round_rows(competition)
    round_nos = [r["round_no"] for r in rows]
    if not round_nos:
        return {"competition_id": competition.id, "scheduled_fixtures": 0, "rounds": 0, "real_matchdays": []}

    floor, floor_reasons = earliest_start_matchday(competition)
    effective_start = start_md if start_md is not None else competition.start_matchday
    if floor is not None:
        effective_start = floor if effective_start is None else max(int(effective_start), floor)
    effective_end = end_md if end_md is not None else competition.end_matchday

    span_fields = []
    if effective_start != competition.start_matchday:
        competition.start_matchday = effective_start
        span_fields.append("start_matchday")
    if effective_end != competition.end_matchday:
        competition.end_matchday = effective_end
        span_fields.append("end_matchday")

    csid, all_matchdays = season_matchdays(competition)
    available = [
        md
        for md in all_matchdays
        if (effective_start is None or md >= effective_start) and (effective_end is None or md <= effective_end)
    ]
    if not csid or not available:
        if span_fields:
            competition.save(update_fields=span_fields)
        return {
            "competition_id": competition.id,
            "scheduled_fixtures": 0,
            "rounds": len(round_nos),
            "real_matchdays": [],
            "warnings": ["nessuna giornata reale disponibile nell'intervallo scelto"] + floor_reasons,
        }

    wanted = dict(uniform_mapping(round_nos, available, spread=effective_end is not None))
    stored = {int(k): int(v) for k, v in (competition.round_calendar or {}).items() if str(k).isdigit()}
    if not stored:
        # First write for a competition built before the plan existed: adopt the
        # calendar it is already being played on rather than inventing a new one.
        stored = _mapping_from_fixtures(competition)
    wanted.update({k: v for k, v in stored.items() if k in round_nos})
    if round_mapping:
        wanted.update({int(k): int(v) for k, v in round_mapping.items() if int(k) in round_nos})

    mapping, warnings = normalise_mapping(round_nos, wanted, available)

    competition.round_calendar = {str(k): int(v) for k, v in mapping.items()}
    competition.save(update_fields=[*span_fields, "round_calendar"])

    scheduled = apply_round_calendar(competition, csid)

    return {
        "competition_id": competition.id,
        "scheduled_fixtures": scheduled,
        "rounds": len(round_nos),
        "real_matchdays": available,
        "mapped_rounds": mapping,
        "min_start_matchday": floor,
        "warnings": warnings + ([] if len(available) >= len(round_nos) else [
            f"servono {len(round_nos)} giornate reali, ce ne sono {len(available)}"
        ]),
    }


def _first_free_matchday(matchdays, locked, floor, end) -> int | None:
    """The earliest matchday still fieldable, after ``floor``, preferring the span."""
    def usable(md):
        return md not in locked and (floor is None or md > floor)

    inside = [md for md in matchdays if usable(md) and (end is None or md <= end)]
    if inside:
        return inside[0]
    # Out of the declared span is better than in the past: a competition that has
    # overrun its window is a scheduling problem the admin can see and fix, a
    # competition placed on a matchday that has already kicked off is a tie nobody
    # can field.
    outside = [md for md in matchdays if usable(md)]
    return outside[0] if outside else None


def rounds_already_counted(competition: FantasyCompetition, round_nos) -> list[int]:
    """Of these rounds, the ones planned on a matchday the league has ALREADY SCORED.

    The second, independent reason a stage must not be drawn — and the one the
    fieldability check cannot see, because it is switched off exactly where this
    bites. A fixture hung on a concluded matchday is never scored by anything: the
    conclusion has happened, and nothing goes back over it. It would sit in the
    calendar at 0-0 for ever, in a competition that can no longer finish.

    This is a statement about the LEDGER, not about kickoff times, which is what
    makes it right for the two leagues the deadline check has to ignore: a league
    replaying a season from ten years ago has every kickoff in the past and a ledger
    that is only at matchday 12, so its cup at matchday 15 is perfectly drawable.
    """
    from vfoot.models import FantasyMatchday

    calendar = {int(k): int(v) for k, v in (competition.round_calendar or {}).items()
                if str(k).isdigit()}
    wanted = {calendar[r] for r in round_nos if r in calendar}
    if not wanted:
        return []
    counted = set(
        FantasyMatchday.objects.filter(
            league_id=competition.league_id, real_matchday__in=wanted,
            status=FantasyMatchday.STATUS_CONCLUDED,
        ).values_list("real_matchday", flat=True)
    )
    return [r for r in round_nos if calendar.get(r) in counted]


def plan_rounds(competition: FantasyCompetition, now=None) -> dict:
    """Where each round WOULD go if the calendar were re-laid out right now.

    Pure — it writes nothing — so the same arithmetic answers both "move it" and
    "can it still be played at all". Returns ``mapping`` (round -> real matchday),
    ``unplaceable`` (rounds with nowhere left to go, which keep their old date) and
    ``warnings``.

    The rules, in order of who wins:

    * a round that ALREADY HAS FIXTURES never moves. It may have lineups against it,
      and a played round must keep the matchday its performances came from;
    * an undrawn round whose matchday is still open keeps it too — the plan is not
      rewritten for the fun of it;
    * anything else takes the EARLIEST matchday still open after the previous round.
      Which means this is not a rigid shift: a competition booked on 8-9-11 whose
      dates have gone by comes out compacted onto three consecutive rounds, because
      each one asks for the first free slot rather than for "its own date plus N".
      The gaps of the original plan survive only where they are still usable.
    """
    stored = {int(k): int(v) for k, v in (competition.round_calendar or {}).items() if str(k).isdigit()}
    rows = competition_round_rows(competition)
    round_nos = [r["round_no"] for r in rows]
    empty = {"mapping": {}, "unplaceable": [], "warnings": []}
    if not stored or not round_nos:
        return empty

    csid, all_matchdays = season_matchdays(competition)
    if not csid or not all_matchdays:
        return empty

    from vfoot.services import matchday_state  # local: matchday_state imports models only

    # A matchday is "gone" only for a league that HAS a deadline. Without one —
    # ``enforce_lineup_deadline`` off, which is the flag that exists for a league
    # played over an ALREADY FINISHED season, i.e. for testing — every kickoff is in
    # the past by construction, including the matchdays the league has not reached
    # yet, so "this one has already started" says nothing about anything. There the
    # whole mechanism must be inert; the guard that still applies is the LEDGER one
    # (``rounds_already_counted``), which asks a question that is true either way.
    #
    # Deliberately NOT extended to "the real season has run out of fieldable
    # matchdays". That is a genuine end-of-season state in a real league, and there
    # refusing to draw is the right answer — not a special case to be waved through.
    locked = (matchday_state.locked_matchdays(csid, now)
              if competition.league.enforce_lineup_deadline else set())
    drawn = set(
        FantasyFixture.objects.filter(competition=competition).values_list("round_no", flat=True)
    )

    out: dict[int, int] = {}
    unplaceable: list[int] = []
    warnings: list[str] = []
    floor: int | None = None
    for rno in round_nos:
        want = stored.get(rno)
        if rno in drawn:
            if want is not None:
                out[rno] = want
                floor = want if floor is None else max(floor, want)
            continue
        if want is not None and want not in locked and (floor is None or want > floor):
            out[rno] = want
            floor = want
            continue
        chosen = _first_free_matchday(all_matchdays, locked, floor, competition.end_matchday)
        if chosen is None:
            unplaceable.append(rno)
            if want is not None:
                out[rno] = want
                warnings.append(
                    f"turno {rno}: non restano giornate su cui giocarlo in questa stagione"
                )
            continue
        out[rno] = chosen
        floor = chosen

    return {"mapping": out, "unplaceable": unplaceable, "warnings": warnings}


@transaction.atomic
def reflow_pending_rounds(competition: FantasyCompetition, now=None) -> dict:
    """Move the rounds that are not drawn yet off matchdays that can no longer be played.

    A stage fed by a rule comes into being LATE by construction — it exists the day
    the competition is created and gets its fixtures weeks later, when the round it
    reads has been played and counted. Usually that is well before the dates the plan
    reserved for it. But it is exactly what a postponement and a forgotten conclusion
    both delay, and when the delay outruns the plan the fixtures are created on
    matchdays whose lineups locked days ago: a semifinal nobody was ever able to
    field, scored on the performances of a round played before it was drawn.

    Where each round goes is ``plan_rounds``. This writes the answer down.

    When there is nowhere left to go (the season is over) the plan is left exactly as
    it is and the round comes back in ``unplaceable``: inventing a date outside the
    season would be worse than an honest "this cannot be played any more", and the
    caller must NOT draw a stage whose rounds are in there.
    """
    plan = plan_rounds(competition, now)
    out, warnings = plan["mapping"], list(plan["warnings"])
    stored = {int(k): int(v) for k, v in (competition.round_calendar or {}).items() if str(k).isdigit()}
    csid, _ = season_matchdays(competition)

    moved = {rno: md for rno, md in out.items() if stored.get(rno) != md}
    if moved:
        fields = ["round_calendar"]
        competition.round_calendar = {str(k): int(v) for k, v in out.items()}
        # If the delay pushed the competition past the window it declared, the
        # window has to follow. Leaving it behind is not a cosmetic mismatch: the
        # admin's own calendar page runs `schedule`, which only keeps a round whose
        # matchday is INSIDE the span — so a cup moved to matchday 13 with an end
        # still at 9 would be silently dragged back into a round already played the
        # next time anyone opened that page and saved.
        last = max(out.values(), default=None)
        if last is not None and competition.end_matchday is not None and last > competition.end_matchday:
            competition.end_matchday = last
            fields.append("end_matchday")
            warnings.append(
                f"la competizione sfora la finestra dichiarata: fine spostata alla {last}ª giornata"
            )
        competition.save(update_fields=fields)
        apply_round_calendar(competition, csid)
    return {"moved": moved, "unplaceable": plan["unplaceable"], "warnings": warnings}


def stage_round_bounds(competition: FantasyCompetition) -> dict[int, dict]:
    """First/last real matchday of each stage, for "when does this stage play?"."""
    calendar = {int(k): int(v) for k, v in (competition.round_calendar or {}).items() if str(k).isdigit()}
    out: dict[int, dict] = {}
    for stage in CompetitionStage.objects.filter(competition=competition).order_by("order_index", "id"):
        first_round = (stage.round_offset or 0) + 1
        last_round = (stage.round_offset or 0) + (stage.planned_rounds or 1)
        mds = [calendar[r] for r in range(first_round, last_round + 1) if r in calendar]
        out[stage.id] = {
            "first_round": first_round,
            "last_round": last_round,
            "first_matchday": min(mds) if mds else None,
            "last_matchday": max(mds) if mds else None,
        }
    return out
