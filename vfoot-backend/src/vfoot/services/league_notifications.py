"""Telling a league's members what has been asked of them, and how it ended.

Written for the role consultations, but deliberately not about roles: a decision
carries its own question, options and outcome, so the same two messages serve
whatever a league is asked next.

Three rules the code enforces rather than trusts:

* **after the commit, never inside it.** A mail sent from inside the transaction
  that then rolls back is a message about something that did not happen. Every
  send goes through ``transaction.on_commit``.
* **a failed send is not a failed action.** The admin opened a consultation; if
  the relay is down that is our problem, not a 500 on his screen. Failures are
  logged and swallowed.
* **one recipient per message.** Nobody's address ends up in anyone else's
  headers.

Only the answer is worth an email, not every keystroke: opening a consultation
(a question addressed to you) and settling it (the answer to it). Everything
else belongs to the league feed, when there is one.

Two channels, one decision about WHAT to say. Email reaches anyone with an
address; a push reaches only who installed the app (on iOS, only from the Home
Screen) — so push is an addition, never a replacement, and the two are sent
together rather than one instead of the other. A user with both simply learns
faster.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import get_connection, EmailMessage
from django.db import transaction

from vfoot.models import LeagueMembership

log = logging.getLogger(__name__)


def _enabled() -> bool:
    return bool(getattr(settings, "VFOOT_NOTIFY_EMAILS", True))


def _decisions_link() -> str:
    base = str(getattr(settings, "VFOOT_FRONTEND_BASE_URL", "")).rstrip("/")
    return f"{base}/decisioni"


def _recipients(league, *, exclude_user=None) -> list:
    """Members who can actually be reached: an address, and an active account.

    The actor is excluded — he has just done the thing the mail is about.
    """
    qs = (LeagueMembership.objects.filter(league=league)
          .select_related("user")
          .exclude(user__email="")
          .filter(user__is_active=True))
    if exclude_user is not None and getattr(exclude_user, "id", None):
        qs = qs.exclude(user_id=exclude_user.id)
    return [m.user for m in qs]


def _send(messages: list) -> None:
    """Deliver, or say in the log why we could not. Never raises."""
    if not messages:
        return
    try:
        connection = get_connection(fail_silently=False)
        connection.send_messages(messages)
    except Exception:                                     # noqa: BLE001
        log.exception("Invio notifiche di lega fallito (%d messaggi)", len(messages))


def _label(decision, value: str) -> str:
    for o in decision.options:
        if o.get("value") == value:
            return str(o.get("label") or value)
    return value or "—"


def notify_consultation_opened(decision, actor=None) -> None:
    """The admin has asked the league. Everyone else gets the question."""
    if not _enabled():
        return
    users = _recipients(decision.league, exclude_user=actor)
    if not users:
        return
    _push(users, title=f"Ti hanno chiesto un parere · {decision.league.name}",
          body=decision.question or decision.title, tag=f"decision-{decision.id}")
    proposal = (f"\nLa proposta del sistema e': {_label(decision, decision.proposed)}.\n"
                if decision.proposed else "")
    reason = f"\nPerche' lo chiediamo: {decision.rationale}\n" if decision.rationale else ""
    options = ", ".join(_label(decision, o.get("value")) for o in decision.options)
    body = (
        "{greeting}\n\n"
        f"Nella lega \"{decision.league.name}\" l'amministratore ha aperto una "
        f"consultazione:\n\n{decision.question or decision.title}\n"
        f"{reason}{proposal}\n"
        f"Opzioni: {options}.\n\n"
        f"Puoi dire la tua qui: {_decisions_link()}\n\n"
        "Il parere e' consultativo: decide comunque l'amministratore, ma sapere "
        "cosa ne pensa la lega e' esattamente il motivo per cui te lo chiede.\n"
    )
    _send([_message(u, f"Ti hanno chiesto un parere · {decision.league.name}", body)
           for u in users])


def notify_decision_resolved(decision, actor=None) -> None:
    """How it ended. Sent only where a consultation was open: whoever was asked
    is owed the answer, and nobody else needs the admin's routine sign-offs."""
    if not _enabled() or not decision.consultation_open:
        return
    users = _recipients(decision.league, exclude_user=actor)
    if not users:
        return
    tally = decision.tally()
    votes = ", ".join(f"{_label(decision, v)}: {n}" for v, n in tally.items() if n)
    _push(users, title=f"Decisione presa · {decision.league.name}",
          body=f"{decision.title}: {_label(decision, decision.outcome)}",
          tag=f"decision-{decision.id}")
    body = (
        "{greeting}\n\n"
        f"Nella lega \"{decision.league.name}\" e' stata presa la decisione su cui "
        f"ti era stato chiesto un parere:\n\n{decision.title}\n\n"
        f"Esito: {_label(decision, decision.outcome)}.\n"
        + (f"Pareri raccolti: {votes}.\n" if votes else "")
        + f"\nLo storico e' in fondo alla pagina: {_decisions_link()}\n"
    )
    _send([_message(u, f"Decisione presa · {decision.league.name}", body)
           for u in users])


def notify_conclusions_pending(league, matchdays, admins) -> None:
    """The league is waiting on the admin: these matchdays are complete and unscored.

    Sent to the admins only — the rest of the league sees the same thing as a banner
    on the home, which is the part that actually works: in a league of friends the
    other participants are a better reminder than any scheduler.
    """
    if not _enabled() or not matchdays or not admins:
        return
    users = [a for a in admins if a.email and a.is_active]
    if not users:
        return
    rounds = ", ".join(str(m.real_matchday) for m in matchdays)
    n = len(matchdays)
    subject = (f"Giornata da chiudere · {league.name}" if n == 1
               else f"{n} giornate da chiudere · {league.name}")
    _push(users, title=subject,
          body=f"Giornat{'a' if n == 1 else 'e'} {rounds}: i risultati aspettano te.",
          tag=f"conclusions-{league.id}", url="/league-admin?tab=matchdays")
    base = str(getattr(settings, "VFOOT_FRONTEND_BASE_URL", "")).rstrip("/")
    body = (
        "{greeting}\n\n"
        f"Nella lega \"{league.name}\" "
        + (f"la giornata {rounds} è finita" if n == 1
           else f"le giornate {rounds} sono finite")
        + " ma non risulta"
        + ("" if n == 1 else "no")
        + " ancora conclusa"
        + ("" if n == 1 else "e")
        + ".\n\n"
        "Finché non la chiudi, punteggi e classifica restano fermi — il resto della "
        "lega intanto continua a giocare e a schierare normalmente.\n\n"
        f"Puoi chiuderla qui: {base}/league-admin?tab=matchdays\n"
    )
    _send([_message(u, subject, body) for u in users])


def notify_lineup_repaired(league, manager, out_player_id, in_player_id, matchdays) -> None:
    """His acquisition landed in a lineup he had already sent.

    Not a courtesy: the swap changed a team sheet he had decided, and finding out at
    the tabellino would be the worst possible moment. He still has time — validations
    only happen before the lock — so the message is early enough to be acted on.
    """
    if not _enabled() or manager is None:
        return
    from realdata.models import Player
    names = dict(Player.objects.filter(id__in=[out_player_id, in_player_id])
                 .values_list("id", "full_name"))
    out_name = names.get(out_player_id, str(out_player_id))
    in_name = names.get(in_player_id, str(in_player_id))
    rounds = ", ".join(str(m) for m in matchdays)
    subject = f"La tua formazione è cambiata · {league.name}"
    _push([manager], title=subject,
          body=f"{in_name} prende il posto di {out_name} (giornata {rounds}).",
          tag=f"lineup-repair-{league.id}", url="/squad/formation")
    base = str(getattr(settings, "VFOOT_FRONTEND_BASE_URL", "")).rstrip("/")
    body = (
        "{greeting}\n\n"
        f"Nella lega \"{league.name}\" la tua offerta è stata validata: {out_name} "
        f"lascia la rosa e al suo posto arriva {in_name}.\n\n"
        f"{out_name} era schierato nella formazione della giornata {rounds}, quindi "
        f"{in_name} ne ha preso esattamente il posto — stesso ruolo, stessa "
        "posizione. La formazione resta valida e completa.\n\n"
        f"Se preferisci schierarla diversamente sei ancora in tempo: {base}/squad/formation\n"
    )
    if not manager.email or not manager.is_active:
        return
    _send([_message(manager, subject, body)])


def _push(users: list, *, title: str, body: str, tag: str = "", url: str = "/decisioni") -> None:
    """The second channel. Silent when push is not configured, and never able to
    stop the email: whoever installed the app hears sooner, nobody hears less."""
    from vfoot.services import push_channel
    if not push_channel.configured():
        return
    for user in users:
        try:
            push_channel.send_to_user(user, title=title, body=body,
                                      url=url, tag=tag)
        except Exception:                                 # noqa: BLE001
            log.exception("Notifica push fallita per l'utente %s", user.id)


def _message(user, subject: str, body_template: str) -> EmailMessage:
    body = body_template.format(greeting=f"Ciao {user.username},")
    return EmailMessage(subject=subject, body=body, to=[user.email])


def on_commit(fn, *args, **kwargs) -> None:
    """Queue a notification for after the surrounding transaction commits."""
    transaction.on_commit(lambda: fn(*args, **kwargs))
