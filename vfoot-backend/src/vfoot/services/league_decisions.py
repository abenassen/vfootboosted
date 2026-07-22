"""Opening, consulting on, and settling a league's pending decisions.

The listone flow this serves: a league freezes its roles from the season-wide
inference, and every player the inference could not measure AND whose provider
position is genuinely ambiguous becomes a decision the admin has to sign off
before the market opens. Players with an unambiguous position raise no question,
and measured players already have an answer we stand behind — so the queue stays
in the tens, not the hundreds (49 on the real 2026/27 listone, against 248
players with no data at all).

Each decision carries the system's proposal, so signing off is a confirmation and
not data entry: the admin can accept the lot and only open up the handful worth
arguing about. Nothing is applied silently, because a role settled after the
bidding would change what people paid for.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from realdata.models import Player
from vfoot.models import (
    LeagueDecision, LeagueDecisionVote, LeagueMembership, LeaguePlayerRole,
    SeasonPlayerRole,
)
from vfoot.services.role_inference import TM_AMBIGUOUS, TM_DEFAULT

ROLE_LABELS = {Player.ROLE_GK: "Portiere", Player.ROLE_DEF: "Difensore",
               Player.ROLE_MID: "Centrocampista", Player.ROLE_FWD: "Attaccante"}
ROLE_OPTIONS = [{"value": r, "label": l} for r, l in ROLE_LABELS.items()
                if r != Player.ROLE_GK]

METHOD_REASON = {
    SeasonPlayerRole.METHOD_DEFAULT:
        "Nessun dato sufficiente sulla stagione precedente: il ruolo e' un default "
        "posizionale, non una misura.",
    SeasonPlayerRole.METHOD_UNKNOWN:
        "Non abbiamo ne' dati di gioco ne' una posizione affidabile.",
    SeasonPlayerRole.METHOD_TM:
        "Posizione del provider ambigua e nessun dato di gioco per scioglierla.",
}


def position_outcomes(competition_season_id: int) -> dict:
    """{tm_position: {role: share}} among the players we COULD measure.

    An ambiguous position is ambiguous by a measurable amount: of the left
    wingers we managed to classify, close to half came out attackers and half
    midfielders. Offering the admin a bare "proposta: Centrocampista" presents
    that coin flip as a judgement. Showing the split says how much of a guess the
    proposal really is, using the only evidence we have — the players in the same
    position whose football we could actually see.
    """
    counts: dict[str, dict[str, int]] = {}
    for position, role in (SeasonPlayerRole.objects
                           .filter(competition_season_id=competition_season_id,
                                   method=SeasonPlayerRole.METHOD_CATEGORY,
                                   tm_position__in=TM_AMBIGUOUS)
                           .exclude(role_data="")
                           .values_list("tm_position", "role_data")):
        counts.setdefault(position, {})
        counts[position][role] = counts[position].get(role, 0) + 1
    return {position: {"total": sum(by_role.values()), "roles": dict(by_role)}
            for position, by_role in counts.items() if sum(by_role.values())}


def _options_for(position: str, outcomes: dict) -> list:
    """The admissible roles, each carrying how often players in this position
    turned out to be that, when we could tell — and on how many cases.

    The count is not decoration: "75%" out of four players and out of forty are
    different statements, and only one of them is worth acting on.
    """
    stats = outcomes.get(position)
    if not stats:
        return [dict(option) for option in ROLE_OPTIONS]
    total = stats["total"]
    return [{**option, "share": round(stats["roles"].get(option["value"], 0) / total, 3),
             "sample": total}
            for option in ROLE_OPTIONS]


def _roster_player_ids(league) -> set[int]:
    """Players a league can actually field, i.e. its reference season's squads."""
    from realdata.models import PlayerTeamStint
    return set(PlayerTeamStint.objects
               .filter(team_season__competition_season_id=league.reference_season_id,
                       end_date__isnull=True)
               .values_list("player_id", flat=True))


def players_needing_decision(league) -> set[int]:
    """Roster players our criterion cannot settle: the provider position is
    genuinely ambiguous AND there is no play data to resolve it.

    Excludes anyone already SETTLED in this league — an open or answered
    decision, or a frozen role. A role, once settled, does not become an open
    question again: a squad must never find itself holding a player who had a
    perfectly good role when he was paid for.
    """
    if league.reference_season_id is None:
        return set()
    settled = set(LeagueDecision.objects
                  .filter(league=league, kind=LeagueDecision.KIND_PLAYER_ROLE)
                  .exclude(status=LeagueDecision.STATUS_CANCELLED)
                  .values_list("player_id", flat=True))
    settled |= set(LeaguePlayerRole.objects.filter(league=league)
                   .values_list("player_id", flat=True))
    candidates = _roster_player_ids(league) - settled
    unresolved = set(SeasonPlayerRole.objects
                     .filter(competition_season_id=league.reference_season_id,
                             player_id__in=candidates,
                             tm_position__in=TM_AMBIGUOUS)
                     .exclude(method=SeasonPlayerRole.METHOD_CATEGORY)
                     .values_list("player_id", flat=True))
    # A player who arrived since the last inference run has NO SeasonPlayerRole at
    # all. Without this he would be seeded straight from Player.classic_role —
    # the raw provider map, under which every winger is a midfielder — silently
    # bypassing the criterion and the limbo alike. Ambiguous position and nothing
    # to resolve it with is exactly the case a human has to answer, whether the
    # inference has run since he signed or not.
    from realdata.models import PlayerTeamStint
    known = set(SeasonPlayerRole.objects
                .filter(competition_season_id=league.reference_season_id,
                        player_id__in=candidates)
                .values_list("player_id", flat=True))
    unseen = set(PlayerTeamStint.objects
                 .filter(team_season__competition_season_id=league.reference_season_id,
                         end_date__isnull=True,
                         player_id__in=candidates - known,
                         tm_position__in=TM_AMBIGUOUS)
                 .values_list("player_id", flat=True))
    return unresolved | unseen


@transaction.atomic
def open_role_decisions(league, *, opened_by=None) -> int:
    """Create the blocking decisions for this league's unresolvable players.

    Idempotent: a decision already open (or already resolved) for a player is left
    alone, so re-seeding a listone never duplicates the queue or re-opens a
    question the admin has already answered.

    And a player who ALREADY HAS A FROZEN ROLE is never asked about again, whatever
    a later recomputation of the season roles may say. That is what freezing
    means. Without this a recompute could drag a player who had been seeded
    automatically — and possibly bought since — back into limbo, leaving a squad
    holding someone who had a perfectly good role when he was paid for. A role,
    once settled in a league, does not become an open question again.
    """
    needing = players_needing_decision(league)
    if not needing:
        return 0
    inferred = {r.player_id: r for r in SeasonPlayerRole.objects
                .filter(competition_season_id=league.reference_season_id,
                        player_id__in=needing)}
    # Players who signed since the last inference run have no row yet: their
    # position comes from the roster stint and their proposal from the positional
    # default. Leaving them out would be worse than seeding them wrongly — they
    # would have no role AND no question, which is to say they would be invisible.
    from realdata.models import PlayerTeamStint
    stint_pos = dict(PlayerTeamStint.objects
                     .filter(team_season__competition_season_id=league.reference_season_id,
                             end_date__isnull=True,
                             player_id__in=needing - set(inferred))
                     .values_list("player_id", "tm_position"))
    outcomes = position_outcomes(league.reference_season_id)
    names = dict(Player.objects.filter(id__in=needing)
                 .values_list("id", "short_name"))
    fulls = dict(Player.objects.filter(id__in=needing)
                 .values_list("id", "full_name"))
    made = []
    for pid in sorted(needing):
        row = inferred.get(pid)
        position = row.tm_position if row else stint_pos.get(pid, "")
        proposed = (row.role_for(league.role_mode) if row
                    else TM_DEFAULT.get(position, ""))
        rationale = (METHOD_REASON.get(row.method, "") if row else
                     "Arrivato dopo l'ultimo calcolo dei ruoli: nessuno storico "
                     "su cui sciogliere una posizione ambigua.")
        name = names.get(pid) or fulls.get(pid) or str(pid)
        made.append(LeagueDecision(
            league=league, kind=LeagueDecision.KIND_PLAYER_ROLE, player_id=pid,
            title=f"Ruolo di {name}",
            question=f"Che ruolo assegnare a {name} ({position}) nel listone?",
            options=_options_for(position, outcomes), proposed=proposed,
            rationale=rationale,
            blocks_market=True, opened_by=opened_by))
    LeagueDecision.objects.bulk_create(made, ignore_conflicts=True)
    return len(made)


def blocking_decisions(league):
    return LeagueDecision.objects.filter(league=league, blocks_market=True,
                                         status=LeagueDecision.STATUS_OPEN)


def undecided_player_ids(league) -> set[int]:
    """Players in limbo: their role is still an open question, so they cannot be
    auctioned or put on a roster.

    The gate is per PLAYER, not per league. Freezing the whole market was
    tolerable for the opening listone and wrong for the rest of the season: a
    single January signing would otherwise stop everyone from trading. Scoped
    this way the same mechanism serves all year — a newcomer is simply
    unavailable until someone says what he is.
    """
    return set(blocking_decisions(league)
               .exclude(player__isnull=True)
               .values_list("player_id", flat=True))


def undecided_notice(league) -> str | None:
    """What the league should be told, or None when nothing is pending. Not a
    block: the market stays open, these players do not."""
    n = blocking_decisions(league).count()
    if not n:
        return None
    return (f"{n} giocatori attendono una decisione sul ruolo e non sono "
            "disponibili in asta o a roster finche' non e' presa.")


def unavailable_players(league, player_ids) -> list:
    """The subset of ``player_ids`` currently in limbo, with their names, so the
    caller can say WHICH ones rather than only that something is wrong."""
    blocked = undecided_player_ids(league) & set(player_ids)
    if not blocked:
        return []
    return [{"player_id": d.player_id,
             "name": (d.player.short_name or d.player.full_name),
             "decision_id": d.id}
            for d in blocking_decisions(league)
            .filter(player_id__in=blocked).select_related("player")]


# Kept as an alias while the notice is still surfaced as a banner.
def market_blocked_reason(league) -> str | None:
    return undecided_notice(league)


@transaction.atomic
def resolve(decision, option: str, *, user=None) -> LeagueDecision:
    """Settle a decision and apply it. Raises ValueError on an option we never
    offered — an outcome outside the stated choices would be unreviewable."""
    if decision.status != LeagueDecision.STATUS_OPEN:
        raise ValueError("Questa decisione e' gia' stata chiusa.")
    if option not in {o.get("value") for o in decision.options}:
        raise ValueError(f"Opzione non ammessa: {option}")
    if decision.kind == LeagueDecision.KIND_PLAYER_ROLE:
        LeaguePlayerRole.objects.update_or_create(
            league=decision.league, player_id=decision.player_id,
            defaults={"role": option, "source": LeaguePlayerRole.SOURCE_ADMIN})
    decision.outcome = option
    decision.status = LeagueDecision.STATUS_RESOLVED
    decision.resolved_by = user
    decision.resolved_at = timezone.now()
    decision.save(update_fields=["outcome", "status", "resolved_by", "resolved_at"])
    return decision


@transaction.atomic
def accept_all_proposals(league, *, user=None, only_unconsulted: bool = True) -> int:
    """Accept the proposal on every open blocking decision at once.

    ``only_unconsulted`` protects the point of asking: a decision the admin put to
    the members is skipped, so a bulk accept cannot quietly overrule a
    consultation that is still collecting opinions.
    """
    qs = blocking_decisions(league)
    if only_unconsulted:
        qs = qs.filter(consultation_open=False)
    n = 0
    for d in qs.select_related("player"):
        if d.proposed:
            resolve(d, d.proposed, user=user)
            n += 1
    return n


def cast_vote(decision, user, option: str) -> LeagueDecisionVote:
    if decision.status != LeagueDecision.STATUS_OPEN:
        raise ValueError("La decisione e' chiusa: non si puo' piu' votare.")
    if not decision.consultation_open:
        raise ValueError("Su questa decisione non e' stata aperta una consultazione.")
    if option not in {o.get("value") for o in decision.options}:
        raise ValueError(f"Opzione non ammessa: {option}")
    if not LeagueMembership.objects.filter(league=decision.league, user=user).exists():
        raise ValueError("Solo i partecipanti della lega possono votare.")
    vote, _ = LeagueDecisionVote.objects.update_or_create(
        decision=decision, user=user, defaults={"option": option})
    return vote


def attention_count(league, user) -> int:
    """Open consultations this user has not answered yet — the notification badge.

    Only consultations: the admin's own sign-off queue is his job, not a nag for
    everyone else."""
    voted = set(LeagueDecisionVote.objects.filter(decision__league=league, user=user)
                .values_list("decision_id", flat=True))
    return (LeagueDecision.objects
            .filter(league=league, status=LeagueDecision.STATUS_OPEN,
                    consultation_open=True)
            .exclude(id__in=voted).count())
