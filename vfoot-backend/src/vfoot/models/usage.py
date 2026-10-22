"""Quali pagine si usano, e per quanto: la misura su cui leggere l'esperienza utente.

Una riga è un TRATTO in primo piano su una pagina: comincia quando la pagina si
apre o torna visibile, finisce quando si cambia pagina o la scheda va in secondo
piano. Non una «visita» nel senso dei siti: chi passa all'app di messaggi e torna
produce due righe, ed è giusto così — il tempo che ci interessa è quello in cui la
pagina era davvero davanti a qualcuno.

Cosa NON c'è, apposta: nessun utente, nessun IP, nessun orario preciso. La riga
porta il giorno e una sessione casuale per scheda, che serve a ricostruire un
percorso (Pagella → Formazione) e a nient'altro. Con una quindicina di iscritti
anche questo è più vicino a una persona di quanto sembri, ed è il motivo per cui
il registro parte SPENTO (``VFOOT_USAGE_LOG``) e le righe scadono da sole
(``RETENTION``).

Gli account staff non vengono registrati: chi sviluppa il sito lo usa in un modo
che nessun utente usa, e su questi numeri basterebbe da solo a disegnare le
statistiche.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import models
from django.utils import timezone

# Abbastanza da confrontare una stagione con la successiva a pari giornata no, ma
# da vedere un girone intero sì: per la domanda «come si usa l'app» basta, e un
# registro che non scade è un registro che nessuno ricorda più di avere.
RETENTION = timedelta(days=180)


class PageVisit(models.Model):
    DEVICE_MOBILE = "mobile"
    DEVICE_DESKTOP = "desktop"
    DEVICE_CHOICES = [(DEVICE_MOBILE, "Telefono"), (DEVICE_DESKTOP, "Computer")]

    day = models.DateField(default=timezone.localdate)
    # La rotta con gli identificativi tolti (``/matches/:id``): ci interessa la
    # PAGINA, non quale partita — e un codice d'invito nell'indirizzo è un segreto.
    route = models.CharField(max_length=120)
    visible_ms = models.PositiveIntegerField()
    device = models.CharField(max_length=8, choices=DEVICE_CHOICES)
    # Aperta dall'app installata o dal browser: due modi di usarla diversi, e la
    # PWA è la cosa su cui abbiamo investito.
    standalone = models.BooleanField(default=False)
    signed_in = models.BooleanField(default=False)
    # C'era una partita di Serie A in corso quando la riga è arrivata. La stessa
    # pagina si usa in due modi opposti a seconda che la giornata sia in campo.
    live = models.BooleanField(default=False)
    session = models.CharField(max_length=16)

    class Meta:
        indexes = [models.Index(fields=["day"]), models.Index(fields=["route", "day"])]

    def __str__(self) -> str:  # pragma: no cover - comodità per l'admin
        return f"{self.day} {self.route} {self.visible_ms / 1000:.0f}s ({self.device})"

    @classmethod
    def prune(cls, *, today=None) -> int:
        today = today or timezone.localdate()
        return cls.objects.filter(day__lt=today - RETENTION).delete()[0]
