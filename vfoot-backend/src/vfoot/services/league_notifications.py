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

And even those two are not sent one per event. A decision about a role is a
decision about ONE PLAYER, so a league that reopens forty roles asked its members
forty times — which is how a courtesy becomes the reason somebody stops reading
us. The two consultation messages are therefore PLURAL: they take a list, and
what ends up in that list is ``decision_digest``'s job, not theirs. The
notifications that are naturally one-of-a-kind (a matchday to close, a lineup
repaired under its owner) stay immediate.

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


def _recipients(league) -> list:
    """Members who can actually be reached: an address, and an active account.

    Everyone, actor included — with a digest the actor cannot be dropped here any
    more, because one message can carry both what he did and what somebody else
    did. Who gets left out of WHICH lines is decided per recipient, at the point
    the message is built.
    """
    return [m.user for m in (LeagueMembership.objects.filter(league=league)
                             .select_related("user")
                             .exclude(user__email="")
                             .filter(user__is_active=True))]


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


def _numbered(items: list) -> str:
    """One block per decision, numbered only when there is more than one — a list
    of one that says "1." reads like a fragment of something longer. Blank line
    between them: forty three-line blocks with no air is a wall, not a list."""
    if len(items) == 1:
        return items[0]
    return "\n\n".join(f"{i}. {block}" for i, block in enumerate(items, start=1))


def _options(decision) -> str:
    return ", ".join(_label(decision, o.get("value")) for o in decision.options)


def _common_options(decisions: list) -> str:
    """The options, when every question in the digest offers the same ones — which
    for a queue of roles is always. Repeating the same four words under forty
    entries is how a list becomes unreadable; said once, at the bottom, it is
    still said."""
    offered = {_options(d) for d in decisions}
    return offered.pop() if len(offered) == 1 else ""


def _consultation_block(decision, *, with_options: bool = True) -> str:
    lines = [decision.question or decision.title]
    if decision.proposed:
        lines.append(f"   Proposta del sistema: {_label(decision, decision.proposed)}.")
    if decision.rationale:
        lines.append(f"   Perche' lo chiediamo: {decision.rationale}")
    if with_options:
        lines.append(f"   Opzioni: {_options(decision)}.")
    return "\n".join(lines)


def _outcome_block(decision) -> str:
    tally = decision.tally()
    votes = ", ".join(f"{_label(decision, v)}: {n}" for v, n in tally.items() if n)
    line = f"{decision.title}: {_label(decision, decision.outcome)}."
    return line + (f"\n   Pareri raccolti: {votes}." if votes else "")


def notify_consultations_opened(league, decisions: list) -> None:
    """The admin has asked the league. Everyone else gets the questions — ALL of
    them, in one message.

    Plural on purpose. The singular version of this function sent one email per
    decision, which is correct for a league that is asked something once a month
    and indefensible for a role queue, where one Transfermarkt import asks forty
    questions in the same second. What arrives now is one message per digest run;
    what is IN it is decided by ``decision_digest``.

    Each recipient is filtered separately: whoever opened a question is not asked
    his own, and only drops out of the mail entirely when he opened all of them.
    """
    if not _enabled() or not decisions:
        return
    for user in _recipients(league):
        mine = [d for d in decisions if d.consult_opened_by_id != user.id]
        if not mine:
            continue
        n = len(mine)
        # Con una sola domanda le opzioni stanno bene dove sono, sotto di lei.
        shared = _common_options(mine) if n > 1 else ""
        subject = (f"Ti hanno chiesto un parere · {league.name}" if n == 1
                   else f"Ti hanno chiesto {n} pareri · {league.name}")
        # Tag per LEGA, non per decisione. Prima ogni domanda aveva il suo e
        # quaranta domande erano quaranta notifiche impilate nella tendina; con
        # uno solo, il digest successivo prende il posto del precedente — e non
        # si perde niente, perche' entrambi puntano alla pagina che le elenca
        # tutte.
        _push([user], title=subject, body=_summary(mine),
              tag=f"consultations-{league.id}")
        body = (
            "{greeting}\n\n"
            f"Nella lega \"{league.name}\" l'amministratore "
            + ("ha aperto una consultazione:" if n == 1
               else f"ha aperto {n} consultazioni:")
            + "\n\n"
            + _numbered([_consultation_block(d, with_options=not shared)
                         for d in mine])
            + (f"\n\nLe opzioni sono le stesse per tutte: {shared}." if shared else "")
            + f"\n\nPuoi dire la tua qui: {_decisions_link()}\n\n"
            "Il parere e' consultativo: decide comunque l'amministratore, ma sapere "
            "cosa ne pensa la lega e' esattamente il motivo per cui te lo chiede.\n"
        )
        _send([_message(user, subject, body)])


def notify_decisions_resolved(league, decisions: list) -> None:
    """How they ended. Only for decisions the league was actually asked about:
    whoever was asked is owed the answer, and nobody needs the admin's routine
    sign-offs."""
    if not _enabled() or not decisions:
        return
    for user in _recipients(league):
        mine = [d for d in decisions if d.resolved_by_id != user.id]
        if not mine:
            continue
        n = len(mine)
        subject = (f"Decisione presa · {league.name}" if n == 1
                   else f"{n} decisioni prese · {league.name}")
        _push([user], title=subject, body=_summary(mine),
              tag=f"outcomes-{league.id}")
        body = (
            "{greeting}\n\n"
            f"Nella lega \"{league.name}\" "
            + ("e' stata presa la decisione su cui ti era stato chiesto un parere:"
               if n == 1 else
               f"sono state prese {n} decisioni su cui ti era stato chiesto un parere:")
            + "\n\n"
            + _numbered([_outcome_block(d) for d in mine])
            + f"\n\nLo storico e' in fondo alla pagina: {_decisions_link()}\n"
        )
        _send([_message(user, subject, body)])


def _summary(decisions: list, limit: int = 3) -> str:
    """What fits in a push: the question when there is one, otherwise the subjects.

    A notification is a pointer, never the content — see push_channel — so a long
    queue is named by its first few and counted, not spelled out.
    """
    if len(decisions) == 1:
        return decisions[0].question or decisions[0].title
    heads = ", ".join(d.title for d in decisions[:limit])
    rest = len(decisions) - limit
    return heads + (f" e altre {rest}" if rest > 0 else "")


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
    """The same text, greeted by name — one message per recipient (see the header).

    ``replace`` and not ``format``: a digest carries text we did not write (a
    question, a player's name, an admin's rationale), and a stray brace in any of
    it would make ``format`` raise on the way out of the building. The template's
    only placeholder is the greeting, so the crude substitution is also the exact
    one.
    """
    body = body_template.replace("{greeting}", f"Ciao {user.username},")
    return EmailMessage(subject=subject, body=body, to=[user.email])


def on_commit(fn, *args, **kwargs) -> None:
    """Queue a notification for after the surrounding transaction commits."""
    transaction.on_commit(lambda: fn(*args, **kwargs))
