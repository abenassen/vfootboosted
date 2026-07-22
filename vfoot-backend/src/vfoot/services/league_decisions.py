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
from vfoot.services.role_inference import TM_AMBIGUOUS

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


def _roster_player_ids(league) -> set[int]:
    """Players a league can actually field, i.e. its reference season's squads."""
    from realdata.models import PlayerTeamStint
    return set(PlayerTeamStint.objects
               .filter(team_season__competition_season_id=league.reference_season_id,
                       end_date__isnull=True)
               .values_list("player_id", flat=True))


@transaction.atomic
def open_role_decisions(league, *, opened_by=None) -> int:
    """Create the blocking decisions for this league's unresolvable players.

    Idempotent: a decision already open (or already resolved) for a player is left
    alone, so re-seeding a listone never duplicates the queue or re-opens a
    question the admin has already answered.
    """
    if league.reference_season_id is None:
        return 0
    roster = _roster_player_ids(league)
    settled = set(LeagueDecision.objects
                  .filter(league=league, kind=LeagueDecision.KIND_PLAYER_ROLE)
                  .exclude(status=LeagueDecision.STATUS_CANCELLED)
                  .values_list("player_id", flat=True))
    rows = (SeasonPlayerRole.objects
            .filter(competition_season_id=league.reference_season_id,
                    player_id__in=roster - settled,
                    tm_position__in=TM_AMBIGUOUS)
            .exclude(method=SeasonPlayerRole.METHOD_CATEGORY)
            .select_related("player"))
    made = []
    for r in rows:
        name = r.player.short_name or r.player.full_name
        made.append(LeagueDecision(
            league=league, kind=LeagueDecision.KIND_PLAYER_ROLE, player_id=r.player_id,
            title=f"Ruolo di {name}",
            question=f"Che ruolo assegnare a {name} ({r.tm_position}) nel listone?",
            options=ROLE_OPTIONS, proposed=r.role_for(league.role_mode),
            rationale=METHOD_REASON.get(r.method, ""),
            blocks_market=True, opened_by=opened_by))
    LeagueDecision.objects.bulk_create(made, ignore_conflicts=True)
    return len(made)


def blocking_decisions(league):
    return LeagueDecision.objects.filter(league=league, blocks_market=True,
                                         status=LeagueDecision.STATUS_OPEN)


def market_blocked_reason(league) -> str | None:
    """Why the market/roster is closed, or None when it may open. Returned to the
    client verbatim: 'non puoi' without 'perche'' is the worst kind of gate."""
    n = blocking_decisions(league).count()
    if not n:
        return None
    return (f"{n} giocatori del listone attendono una decisione sul ruolo. "
            "Completa le disambiguazioni per aprire il mercato.")


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
