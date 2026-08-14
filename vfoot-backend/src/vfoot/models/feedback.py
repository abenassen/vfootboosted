"""Quello che gli utenti ci dicono del sito mentre lo provano.

Non è la segnalazione di un voto sbagliato — quella nasce da una pagella e ha già
il suo posto — è il canale generale: un pulsante non risponde, una schermata non
si capisce, «qui ci vorrebbe». In fase di prova è la cosa più preziosa che
abbiamo, e finora l'unico modo di darcela era scrivere a mano a qualcuno.

Tre scelte che valgono la pena di essere dette.

**Il contesto lo raccoglie il client, non l'utente.** Chiedere «in che pagina
eri, che telefono hai» significa chiedere di compilare un modulo, e un modulo non
si compila mentre si sta facendo altro. La pagina, il browser e la misura dello
schermo arrivano da soli: sono esattamente i tre dati che servono per riprodurre
un problema, e sono i tre che nessuno ricorda di scrivere.

**L'autore può sparire, la segnalazione no.** ``user`` è SET_NULL: se l'account
viene cancellato resta il testo, che è la parte che serve a noi. Chi ha scritto
è comodo per rispondere, non è il contenuto.

**Lo stato è per chi legge, non per chi scrive.** Nessuno vede il proprio
``status``: serve a non rileggere venti volte le stesse dieci righe quando
arrivano in blocco dopo un deploy.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class Feedback(models.Model):
    KIND_BUG = "bug"
    KIND_IDEA = "idea"
    KIND_OTHER = "altro"
    KIND_CHOICES = [
        (KIND_BUG, "Non funziona"),
        (KIND_IDEA, "Proposta"),
        (KIND_OTHER, "Altro"),
    ]

    STATUS_NEW = "new"
    STATUS_SEEN = "seen"
    STATUS_DONE = "done"
    STATUS_CHOICES = [
        (STATUS_NEW, "Da leggere"),
        (STATUS_SEEN, "Letta"),
        (STATUS_DONE, "Chiusa"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="feedback")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_OTHER)
    message = models.TextField()

    # Il contesto, raccolto dal client. Tutto facoltativo: una segnalazione senza
    # contorno vale comunque più di una segnalazione non scritta.
    page = models.CharField(max_length=200, blank=True, default="")
    user_agent = models.CharField(max_length=300, blank=True, default="")
    viewport = models.CharField(max_length=20, blank=True, default="")

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_NEW)
    # Le note di chi smista, non dell'utente: perché è stata chiusa, dove è finita.
    note = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - comodità in admin
        who = self.user.username if self.user else "anonimo"
        return f"[{self.get_kind_display()}] {who}: {self.message[:50]}"
