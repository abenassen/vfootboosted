"""Le novità del prodotto: due righe, a tutti, una volta sola.

Non è la bacheca. La bacheca racconta cosa è successo in UNA lega — un acquisto,
uno scambio, un premio — e la scrive il gioco. Questa dice cosa è cambiato
nell'APPLICAZIONE, la scriviamo noi, e vale per chiunque: «le probabili
formazioni ora ci sono». Due canali diversi perché rispondono a due domande
diverse, e mescolarli vorrebbe dire che una notizia di prodotto compare dentro il
racconto di una lega, dove nessuno la cerca.

E non è nemmeno ``UpdateBanner``, che dice che c'è una versione nuova da
caricare: quello è un fatto tecnico e si risolve premendo un bottone. Qui si dice
cosa quella versione ha portato, che è l'unica parte che interessa a chi gioca.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone


class ProductNews(models.Model):
    """Un annuncio, breve. Chi lo scrive lo scrive dall'admin di Django."""

    # Il titolo È il messaggio: deve reggere da solo, perché su un telefono è
    # spesso l'unica riga che si legge davvero. «Probabili formazioni», non
    # «Aggiornamento del 28 agosto».
    title = models.CharField(max_length=80)
    # Una o due frasi. Se ne servono di più, la novità è troppo grande per una
    # striscia e vuole una pagina.
    body = models.CharField(max_length=280, blank=True, default="")

    published_at = models.DateTimeField(default=timezone.now)
    # Scritta ma non ancora annunciata: si prepara il testo con calma e lo si
    # accende quando il deploy è andato, invece di scriverlo di fretta dopo.
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-published_at", "-id"]
        indexes = [models.Index(fields=["active", "published_at"])]
        verbose_name_plural = "product news"

    def __str__(self) -> str:  # pragma: no cover - comodità per l'admin
        return f"{self.published_at:%d/%m/%Y} — {self.title}"
