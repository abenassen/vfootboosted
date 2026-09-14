"""A chi si dice che qualcosa e' rotto, e con quali cautele.

Una riga sola di risposta, perche' la domanda e' una sola. Prima stava dentro
``health_report``, che e' il rapporto quotidiano; poi ha dovuto poterla fare anche
il tick, che se ne accorge novanta volte prima. Duplicarla avrebbe voluto dire due
elenchi di destinatari che prima o poi divergono, e un guasto raccontato a meta'
delle persone.

LE DUE CAUTELE, e sono entrambe cicatrici:

* **l'invio non puo' rompere chi lo chiama.** Il tick e' la cosa che tiene vive le
  partite in corso: un server di posta con una brutta giornata non deve poter
  diventare il guasto della serata. Ogni eccezione qui dentro viene riportata e
  ingoiata, e il valore di ritorno dice se e' partita davvero.
* **il silenzio e' la buona notizia.** Nessun "va tutto bene" periodico: una mail
  che arriva tutti i giorni si impara a cancellare senza leggerla, che e'
  esattamente lo stato da cui si sta cercando di uscire.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

log = logging.getLogger(__name__)


def recipients() -> list[str]:
    """Chi riceve gli allarmi. Vuoto = nessuno configurato (non e' un errore: uno
    sviluppo senza .env non deve provare a spedire niente)."""
    raw = getattr(settings, "VFOOT_HEALTH_EMAIL", "") or ""
    return [a.strip() for a in raw.split(",") if a.strip()]


def mail(subject: str, body: str) -> bool:
    """Spedisci, e di' se e' partita. Non solleva mai."""
    to = recipients()
    if not to:
        log.warning("allarme non spedito (VFOOT_HEALTH_EMAIL non impostata): %s",
                    subject)
        return False
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, to,
                  fail_silently=False)
    except Exception as exc:  # noqa: BLE001 — v. docstring del modulo
        log.error("invio dell'allarme fallito (%s: %s); resta nel journal: %s",
                  type(exc).__name__, exc, subject)
        return False
    return True
