"""WHEN the league gets told, so that forty questions are one message and not forty.

A decision about a role is a decision about one player, and there is no honest way
to make it anything else: the admin answers them one at a time because they are
one at a time. What was wrong was the notification following that shape. A
Transfermarkt import lands a queue, the admin walks down it clicking «Chiedi alla
lega», and every click used to leave the building as its own email to every
member. Nobody reads the fortieth. Worse, nobody reads the next one either.

So the click no longer sends anything. It leaves a mark on the decision
(``consult_opened_at``), and this module — run from ``send_decision_digests`` on a
timer — collects the marks, decides whether the burst is over, and hands
``league_notifications`` a LIST.

**The window.** A batch goes out when it has been QUIET for
``VFOOT_DIGEST_QUIET_MINUTES``: the last question was asked ten minutes ago, so
the admin has probably put the queue down. Silence is the signal, not a fixed
clock, because the thing being waited for is a human finishing a session of
clicking. The one failure mode of waiting for silence is never getting any — an
admin who opens one question every eight minutes all afternoon would hold the
first one hostage — so ``VFOOT_DIGEST_MAX_WAIT_MINUTES`` sends anyway once the
OLDEST item has waited long enough. Quiet decides normally; the cap decides in the
pathological case.

**Stamped once, sent once.** The stamp goes on whether or not the relay took the
message. That is deliberate and it is a trade: a digest lost to a dead SMTP server
is lost, where retrying it next run would recover it. But retrying means
re-sending a batch we may have half-delivered, and duplicated mail is the exact
complaint this module exists to answer. A lost notification is what the immediate
sends already risked; a duplicated flood is what they already caused.

**Two things the window gets right for free:**

* a consultation opened and withdrawn before the digest leaves is never mentioned
  to anyone — the query only ever looks at consultations that are still open;
* a consultation opened and settled inside the same window says nothing either:
  the outcome digest requires the question to have actually been asked
  (``consult_notified_at`` set), so nobody is told the answer to something they
  were never asked.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from vfoot.models import LeagueDecision
from vfoot.services import league_notifications as notify

CONSULTATION = "consultation"
OUTCOME = "outcome"


def _window(name: str, default: int) -> timedelta:
    return timedelta(minutes=int(getattr(settings, name, default)))


def quiet_window() -> timedelta:
    return _window("VFOOT_DIGEST_QUIET_MINUTES", 10)


def max_wait() -> timedelta:
    """Never shorter than the quiet window: a cap that fires first would make the
    quiet rule unreachable and turn every digest back into one message per click."""
    return max(_window("VFOOT_DIGEST_MAX_WAIT_MINUTES", 60), quiet_window())


def pending_consultations():
    """Questions asked of the league and not yet carried out of the building."""
    return (LeagueDecision.objects
            .filter(status=LeagueDecision.STATUS_OPEN, consultation_open=True,
                    consult_notified_at__isnull=True)
            .select_related("league")
            .order_by("consult_opened_at", "id"))


def pending_outcomes():
    """Answers owed to whoever was asked — and only to them, hence the requirement
    that the question itself went out."""
    return (LeagueDecision.objects
            .filter(status=LeagueDecision.STATUS_RESOLVED, consultation_open=True,
                    consult_notified_at__isnull=False,
                    outcome_notified_at__isnull=True)
            .select_related("league")
            .order_by("resolved_at", "id"))


def _queued_at(decision, kind: str):
    """When this item joined the queue. ``created_at`` is the fallback for rows
    that predate the stamps rather than a meaningful answer."""
    if kind == CONSULTATION:
        return decision.consult_opened_at or decision.created_at
    return decision.resolved_at or decision.created_at


def ripe(batch: list, kind: str, now) -> bool:
    """Is this league's batch finished settling? See the module header."""
    stamps = [_queued_at(d, kind) for d in batch]
    return (now - max(stamps) >= quiet_window()
            or now - min(stamps) >= max_wait())


def _by_league(decisions) -> dict:
    out: dict = {}
    for d in decisions:
        out.setdefault(d.league_id, (d.league, []))[1].append(d)
    return out


def _deliver(kind: str, league, batch: list, now) -> None:
    """Stamp, then send after the commit — a message about something the database
    does not record is a message about nothing."""
    field = ("consult_notified_at" if kind == CONSULTATION
             else "outcome_notified_at")
    send = (notify.notify_consultations_opened if kind == CONSULTATION
            else notify.notify_decisions_resolved)
    with transaction.atomic():
        (LeagueDecision.objects.filter(id__in=[d.id for d in batch])
         .update(**{field: now}))
        transaction.on_commit(lambda: send(league, batch))


def flush(*, now=None, force: bool = False, dry_run: bool = False) -> dict:
    """Send every batch whose window has closed. Returns what it did, per kind.

    ``force`` ignores the window (the manual «send it now» of a support session);
    ``dry_run`` decides exactly the same things and sends nothing.
    """
    now = now or timezone.now()
    stats = {"leagues": 0, "consultations": 0, "outcomes": 0, "waiting": 0,
             "batches": []}
    for kind, pending in ((CONSULTATION, pending_consultations()),
                          (OUTCOME, pending_outcomes())):
        for league, batch in _by_league(pending).values():
            if not (force or ripe(batch, kind, now)):
                stats["waiting"] += len(batch)
                continue
            stats["batches"].append((league, kind, len(batch)))
            stats["consultations" if kind == CONSULTATION else "outcomes"] += len(batch)
            if not dry_run:
                _deliver(kind, league, batch, now)
    stats["leagues"] = len({league.id for league, _, _ in stats["batches"]})
    return stats


def oldest_pending(now=None):
    """How long the most patient unsent item has been waiting, or None when the
    queue is empty. Read by ``health_report``: a queue that keeps growing is how a
    digest timer nobody enabled announces itself."""
    now = now or timezone.now()
    stamps = [_queued_at(d, CONSULTATION) for d in pending_consultations()]
    stamps += [_queued_at(d, OUTCOME) for d in pending_outcomes()]
    return (now - min(stamps)) if stamps else None
