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
from django.db.models import Q
from django.utils import timezone

from realdata.models import Player
from vfoot.models import (
    LeagueDecision, LeagueDecisionVote, LeagueMembership, LeaguePlayerRole,
    CurrentPlayerRole,
)
from vfoot.services.role_inference import (
    BOUNDARY_REVIEW, ROLE_MARGIN_REVIEW, TM_AMBIGUOUS, TM_DEFAULT,
)

ROLE_LABELS = {Player.ROLE_GK: "Portiere", Player.ROLE_DEF: "Difensore",
               Player.ROLE_MID: "Centrocampista", Player.ROLE_FWD: "Attaccante"}
ROLE_OPTIONS = [{"value": r, "label": l} for r, l in ROLE_LABELS.items()
                if r != Player.ROLE_GK]

METHOD_REASON = {
    CurrentPlayerRole.METHOD_DEFAULT:
        "Nessun dato sufficiente sulla stagione precedente: il ruolo è un default "
        "posizionale, non una misura.",
    CurrentPlayerRole.METHOD_UNKNOWN:
        "Non abbiamo né dati di gioco né una posizione affidabile.",
    CurrentPlayerRole.METHOD_TM:
        "Posizione del provider ambigua e nessun dato di gioco per scioglierla.",
    CurrentPlayerRole.METHOD_SOFA:
        "Posizione del provider ambigua e minutaggio troppo scarso per misurare come "
        "gioca: il ruolo viene dalla sola casella in distinta, che su ali e trequartisti "
        "indovina poco più di una volta su due.",
}


def decision_rationale(row) -> str:
    """Why this player is being asked about, in the admin's terms.

    Every case in the queue gets one. A question that says "decidi" without
    saying what is missing reads as an obstacle rather than as a question — and
    the two hardest cases (the coin-flip clustering and the lineup-only role) are
    precisely the ones a bare title tells nothing about.
    """
    if row is None:
        return ("Arrivato dopo l'ultimo calcolo dei ruoli: nessuno storico su cui "
                "sciogliere una posizione ambigua.")
    if row.method == CurrentPlayerRole.METHOD_CATEGORY:
        style = f" (stile di gioco: {row.category})" if row.category else ""
        # The measurement ran, and it can be open in two different ways. Telling
        # them apart is not pedantry: "i giri non si sono accordati" and "i giri si
        # sono accordati su un giocatore che sta sul confine" are different
        # questions, and an admin who reads the wrong one is being told a number
        # that contradicts the threshold it is quoted against.
        if row.role_margin < 0:
            # Un margine negativo non e' un margine stretto: i giri mettono il
            # giocatore in un ruolo DIVERSO da quello che gli assegniamo. Dirlo
            # "stacca il secondo di appena -46%" sarebbe una frase senza senso, e
            # soprattutto nasconderebbe l'unica informazione che conta qui.
            gap = f"{-row.role_margin * 100:.0f}%"
            return (f"Posizione del provider ambigua e misura in contrasto con il ruolo "
                    f"proposto{style}: i raggruppamenti lo mettono con un altro ruolo, "
                    f"e lo fanno con {gap} di scarto.")
        if row.role_margin < ROLE_MARGIN_REVIEW:
            # Saying by how much is the whole point: 34% contro 30% is a different
            # question from 60% contro 15%.
            gap = f"{row.role_margin * 100:.0f}%"
            return (f"Posizione del provider ambigua e misura in bilico{style}: il ruolo "
                    f"vincente stacca il secondo di appena {gap}, sotto la soglia oltre "
                    f"la quale ci fidiamo del dato.")
        near = f"{row.role_boundary * 100:.0f}%"
        return (f"Posizione del provider ambigua e profilo sul confine{style}: dal "
                f"gruppo di un altro ruolo dista quasi quanto dal proprio ({near}), "
                f"quindi la misura c'è ma da sola non lo colloca.")
    return METHOD_REASON.get(row.method, "")


# Below this Transfermarkt market value an ambiguous player is NOT worth an admin
# decision: he barely features (young prospects, transient squad filler), so he
# silently takes the system proposal (the SofaScore-derived role when he ever
# lined up, the raw TM default otherwise). Only relevant players reach the queue.
RELEVANCE_MIN_VALUE_EUR = 5_000_000


def _roster_player_ids(league) -> set[int]:
    """Players a league can actually field, i.e. its reference season's squads."""
    from realdata.models import PlayerTeamStint
    return set(PlayerTeamStint.objects
               .filter(team_season__competition_season_id=league.reference_season_id,
                       end_date__isnull=True)
               .values_list("player_id", flat=True))


def latest_market_values(player_ids) -> dict[int, int]:
    """player_id -> most recent Transfermarkt value_eur (0 when we have none)."""
    from realdata.models import PlayerMarketValue
    out: dict[int, int] = {}
    for pid, val in (PlayerMarketValue.objects
                     .filter(player_id__in=player_ids)
                     .order_by("player_id", "-as_of")
                     .values_list("player_id", "value_eur")):
        if pid not in out and val is not None:  # first row per player = latest as_of
            out[pid] = val
    return out


def players_needing_decision(league, *,
                             min_market_value: int = RELEVANCE_MIN_VALUE_EUR) -> set[int]:
    """Roster players our criterion cannot settle AND who are worth arbitrating:
    the provider position is genuinely ambiguous, there is no play data to resolve
    it, and the player carries enough market value to matter. Everyone below the
    value floor takes the system proposal automatically (see ``snapshot_league_
    listone``), so the admin is not asked to rule on players who never play.

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
    unresolved = set(CurrentPlayerRole.objects
                     .filter(player_id__in=candidates,
                             tm_position__in=TM_AMBIGUOUS)
                     .exclude(method=CurrentPlayerRole.METHOD_CATEGORY)
                     .values_list("player_id", flat=True))
    # Measured, but the measurement itself sits on the CEN/ATT line. Only where the
    # TM position is AMBIGUOUS: there nobody overrules the clustering, so a role
    # decided by 56% against 35% is genuinely open. Under a certain TM position
    # the same tight margin means nothing — TM matched the listone 351 times out
    # of 352, in every margin band, so those cases (Nico Paz, McTominay) belong to
    # TM and asking about them is work with nothing to correct.
    #
    # Two readings in OR, because they see different players: the margin catches
    # the runs disagreeing with each other, the boundary catches a border the runs
    # agreed on and the co-association average then erased (Esposito: margin 0.44,
    # boundary 0.82). Same criterion as ``role_inference.needs_decision``, which
    # carries the measurements; the two must not drift apart, since one reports
    # what the other enforces.
    torn = set(CurrentPlayerRole.objects
               .filter(player_id__in=candidates,
                       tm_position__in=TM_AMBIGUOUS,
                       method=CurrentPlayerRole.METHOD_CATEGORY)
               .filter(Q(role_margin__lt=ROLE_MARGIN_REVIEW)
                       | Q(role_boundary__gt=BOUNDARY_REVIEW))
               .values_list("player_id", flat=True))
    # A player who arrived since the last inference run has NO CurrentPlayerRole at
    # all. Without this he would be seeded straight from Player.classic_role_seed —
    # the raw provider map, under which every winger is a midfielder — silently
    # bypassing the criterion and the limbo alike. Ambiguous position and nothing
    # to resolve it with is exactly the case a human has to answer, whether the
    # inference has run since he signed or not.
    from realdata.models import PlayerTeamStint
    known = set(CurrentPlayerRole.objects
                .filter(player_id__in=candidates)
                .values_list("player_id", flat=True))
    unseen = set(PlayerTeamStint.objects
                 .filter(team_season__competition_season_id=league.reference_season_id,
                         end_date__isnull=True,
                         player_id__in=candidates - known,
                         tm_position__in=TM_AMBIGUOUS)
                 .values_list("player_id", flat=True))
    flagged = unresolved | unseen | torn
    # Relevance gate: only players worth an admin's time reach the queue. The rest
    # (barely-featuring youngsters and squad filler) auto-take the system proposal.
    if min_market_value:
        values = latest_market_values(flagged)
        flagged = {pid for pid in flagged
                   if values.get(pid, 0) >= min_market_value}
    return flagged


@transaction.atomic
def open_role_decisions(league, *, opened_by=None, notify: bool = False,
                        min_market_value: int = RELEVANCE_MIN_VALUE_EUR) -> int:
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
    needing = players_needing_decision(league, min_market_value=min_market_value)
    if not needing:
        return 0
    inferred = {r.player_id: r for r in CurrentPlayerRole.objects
                .filter(player_id__in=needing)}
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
        rationale = decision_rationale(row)
        name = names.get(pid) or fulls.get(pid) or str(pid)
        made.append(LeagueDecision(
            league=league, kind=LeagueDecision.KIND_PLAYER_ROLE, player_id=pid,
            title=f"Ruolo di {name}",
            question=f"Che ruolo assegnare a {name} ({position}) nel listone?",
            options=ROLE_OPTIONS, proposed=proposed, rationale=rationale,
            blocks_market=True, opened_by=opened_by))
    LeagueDecision.objects.bulk_create(made, ignore_conflicts=True)
    if made and notify:
        _push_new_decisions(league, len(made))
    return len(made)


def manual_rationale(row, frozen_role: str) -> str:
    """What we think of a player the admin is putting back on the table.

    The point of showing it is that the consultation starts from the facts rather
    than from an impression: the admin is overruling a judgement, and the league
    should be able to see what the judgement was.
    """
    head = "Rimesso in discussione dall'amministratore. "
    if row is None:
        return head + ("Non abbiamo una misura su questo giocatore: il ruolo nel "
                       "listone viene dalla posizione del provider.")
    if row.method == CurrentPlayerRole.METHOD_CATEGORY:
        style = f" ({row.category})" if row.category else ""
        return head + (
            f"La nostra misura lo dava per definito{style}: dai raggruppamenti esce "
            f"{ROLE_LABELS.get(row.role_for('data'), row.role_for('data')).lower()} "
            f"con {row.role_margin * 100:.0f}% di distacco sul secondo ruolo, e dal "
            f"gruppo di un altro ruolo dista il {row.role_boundary * 100:.0f}% di "
            f"quanto dista dal proprio. Nel listone è "
            f"{ROLE_LABELS.get(frozen_role, frozen_role).lower()}.")
    return head + METHOD_REASON.get(row.method, "")


@transaction.atomic
def open_manual_decision(league, player, *, opened_by=None) -> tuple:
    """Put a settled role back on the table because the admin says so.
    Returns ``(decision, created)``.

    The automatic queue asks only where OUR criterion is in doubt, and that is
    deliberately narrow — the winger convention alone would put fifty names in
    front of the admin every August, and none of them would be a doubt of ours.
    Narrow is not the same as right for every league, though: a league may well
    want to argue about a player we measure as a textbook wide attacker and the
    official listone calls a midfielder. So the admin can raise anyone in the
    listone, through the same machinery — proposal, consultation, and a market
    that stops for that player until it is settled.

    Refused wherever the answer could move ground somebody is already standing on.
    Three of those, and the first is the whole design speaking:

    * **he is on a roster.** A squad must never find itself holding someone whose
      role turned back into a question after it was paid for. Moving a rostered
      player's role is a rectification, not a question, and it is not this door.
    * **an auction is running.** There the roles are load-bearing for everyone at
      once — the slot counts per role are what every bid is arithmetic against —
      and pulling a player out of the pool mid-room changes the plan of people who
      cannot see why. It costs nothing to ask before the auction opens or after it
      closes.
    * **an offer is live on him.** The offer market is per-player by design, so a
      session being open is no obstacle; a bid already placed on THIS player is,
      because limbo would void it under the bidder.
    """
    from vfoot.models import (
        AuctionSession, FantasyRosterSlot, MarketOffer,
    )
    from vfoot.services.listone import eligible_player_ids

    name = player.short_name or player.full_name or str(player.id)
    if league.reference_season_id is None:
        raise ValueError("Questa lega non ha un listone su cui aprire una domanda.")
    if player.id not in eligible_player_ids(league.reference_season_id):
        raise ValueError(f"{name} non è nel listone di questa lega.")
    owner = (FantasyRosterSlot.objects
             .filter(team__league=league, player=player, released_at__isnull=True)
             .select_related("team").first())
    if owner is not None:
        raise ValueError(
            f"{name} è in rosa a {owner.team.name}: un ruolo già pagato non torna "
            "una domanda aperta. Serve una rettifica, non una consultazione.")
    if AuctionSession.objects.filter(
            league=league, status=AuctionSession.STATUS_ACTIVE).exists():
        raise ValueError(
            "C'è un'asta in corso: i ruoli tengono in piedi i conti degli slot di "
            "tutti, e non si spostano mentre si sta battendo. Riprova a asta chiusa.")
    if (MarketOffer.objects
            .filter(session__league=league, status__in=MarketOffer.LIVE_STATUSES)
            .filter(Q(target_player=player) | Q(release_player=player)).exists()):
        raise ValueError(
            f"C'è un'offerta in corso su {name}: mettere il ruolo in discussione la "
            "annullerebbe sotto chi l'ha fatta. Prima si chiude l'offerta.")
    existing = (LeagueDecision.objects
                .filter(league=league, kind=LeagueDecision.KIND_PLAYER_ROLE,
                        player=player, status=LeagueDecision.STATUS_OPEN).first())
    if existing is not None:
        return existing, False

    row = CurrentPlayerRole.objects.filter(player=player).first()
    frozen = (LeaguePlayerRole.objects.filter(league=league, player=player)
              .values_list("role", flat=True).first())
    proposed = frozen or (row.role_for(league.role_mode) if row else "") \
        or player.classic_role_seed
    position = row.tm_position if row else ""
    decision = LeagueDecision.objects.create(
        league=league, kind=LeagueDecision.KIND_PLAYER_ROLE, player=player,
        title=f"Ruolo di {name}",
        question=(f"Che ruolo assegnare a {name}"
                  f"{f' ({position})' if position else ''} nel listone?"),
        options=ROLE_OPTIONS, proposed=proposed,
        rationale=manual_rationale(row, frozen or proposed),
        blocks_market=True, opened_by=opened_by)
    return decision, True


def _push_new_decisions(league, n: int) -> int:
    """Tell the admin the queue has grown, because nothing else will.

    Only from the unattended path. A snapshot run while the admin is looking at
    the screen — creating the league, opening the market — already puts the
    questions in front of him; a notification about what he is already reading is
    noise. The one that matters is the Transfermarkt import at six in the morning,
    which is precisely when nobody is watching and the market stays blocked for
    those players until someone answers.
    """
    from vfoot.services import push_channel

    admins = [m.user for m in LeagueMembership.objects
              .filter(league=league, role=LeagueMembership.ROLE_ADMIN)
              .select_related("user")]
    if league.owner and league.owner not in admins:
        admins.append(league.owner)
    sent = 0
    for user in admins:
        sent += push_channel.send_to_user(
            user,
            title=f"🗳️ {n} {'nuovo ruolo' if n == 1 else 'nuovi ruoli'} da decidere",
            body=(f"{league.name}: il mercato reale ha portato giocatori che il "
                  f"listone non sa classificare. Restano non acquistabili finché "
                  f"non decidi."),
            url="/decisioni",
            # One tag per league: a second import before the admin has answered
            # replaces the notification instead of stacking another copy.
            tag=f"decisions-{league.id}")
    return sent


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
    # L'ultimo rimasto e' il caso piu' comune di tutti — si svuota la coda e ne
    # resta uno in consultazione — ed e' proprio li' che si leggeva "1 giocatori
    # attendono".
    if n == 1:
        return ("Un giocatore attende una decisione sul ruolo e non è "
                "disponibile in asta o a roster finché non è presa.")
    return (f"{n} giocatori attendono una decisione sul ruolo e non sono "
            "disponibili in asta o a roster finché non è presa.")


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
    # A role decision needs a subject to apply the answer to. The model permits a
    # null player (other kinds are not about one), so guard rather than trust:
    # without this an inconsistent row dies on an IntegrityError deep in the ORM
    # instead of saying what is wrong.
    if decision.kind == LeagueDecision.KIND_PLAYER_ROLE and decision.player_id:
        LeaguePlayerRole.objects.update_or_create(
            league=decision.league, player_id=decision.player_id,
            defaults={"role": option, "source": LeaguePlayerRole.SOURCE_ADMIN})
    decision.outcome = option
    decision.status = LeagueDecision.STATUS_RESOLVED
    decision.resolved_by = user
    decision.resolved_at = timezone.now()
    decision.save(update_fields=["outcome", "status", "resolved_by", "resolved_at"])
    # Whoever was asked is owed the answer — but not one email per player. The row
    # is now in the outcome queue; `decision_digest` decides when the league hears
    # about it, and sends one message for everything settled in the same sitting.
    return decision


@transaction.atomic
def set_consultation(decision, is_open: bool, *, user=None) -> LeagueDecision:
    """Ask the league, or stop asking. Queues a question on the way IN only:
    opening is a question addressed to them, closing is housekeeping.

    Nothing is sent from here. The click leaves a mark and `decision_digest`
    carries it out later, with everything else the admin asked in the same
    sitting — one message for a queue of forty players instead of forty. Which
    also means an admin who opens a consultation and thinks better of it within
    the window has bothered nobody.
    """
    if decision.status != LeagueDecision.STATUS_OPEN:
        raise ValueError("La decisione e' chiusa: non si puo' piu' consultare.")
    was_open = decision.consultation_open
    decision.consultation_open = bool(is_open)
    fields = ["consultation_open"]
    if decision.consultation_open and not was_open:
        decision.consult_opened_at = timezone.now()
        decision.consult_opened_by = user
        # The mark is what the digest reads; it is cleared of any previous send so
        # that a question asked again is asked again.
        decision.consult_notified_at = None
        fields += ["consult_opened_at", "consult_opened_by", "consult_notified_at"]
    decision.save(update_fields=fields)
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
