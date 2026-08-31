"""Where a user's browser can be reached with a push notification.

One row per INSTALLATION, not per user: the same person with the app on the
phone and the site open on the laptop is two subscriptions, and both want the
notification. The endpoint is the natural key — it is the URL the browser
vendor's push service handed out, and re-subscribing on the same install returns
the same one.

Nothing secret of ours lives here. ``p256dh`` and ``auth`` are the browser's own
public key material, used to encrypt the payload so that Google or Apple carry
our messages without being able to read them; our signing key stays in settings.

A subscription dies without telling us: the user clears site data, removes the
installed app, or the push service rotates it. The only way to find out is to
send and be told 404/410, so ``last_error_at``/``failures`` exist to make that
visible rather than to accumulate silent ghosts.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class PushSubscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE,
                             related_name="push_subscriptions")
    # The vendor's push endpoint (FCM for Chrome, APNs for Safari, autopush for
    # Firefox). Long on purpose: FCM's are ~200 chars and there is no stated cap.
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    # Free-text hint for the user ("Chrome su Android"), so a subscription list
    # is something a person can recognise and revoke.
    user_agent = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    failures = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["user", "created_at"])]
        ordering = ["-created_at"]

    def as_subscription_info(self) -> dict:
        """The shape pywebpush expects, i.e. the browser's own PushSubscription."""
        return {"endpoint": self.endpoint,
                "keys": {"p256dh": self.p256dh, "auth": self.auth}}

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.endpoint[:40]}…"


class LiveEventNotice(models.Model):
    """Un evento di una partita in corso GIA' ANNUNCIATO, e a chi.

    Nasce da due difetti trovati insieme il 31/08/2026, che hanno la stessa radice:
    l'annuncio si decideva dalla differenza fra due istantanee della partita, prese
    ai due lati dell'import, e di quella differenza non restava traccia.

    * **Un gol poteva sparire per sempre.** Se l'import scriveva il gol ma
      l'annuncio non girava — tick ucciso, o import fallito a meta' — il giro dopo
      il gol era gia' nell'istantanea «prima» e non lo annunciava piu' nessuno. In
      silenzio: niente riprova, niente riga.
    * **E non si poteva rispondere a «non mi e' arrivata».** Il contatore diceva
      «due consegne», non a chi ne' quale.

    Questa riga e' l'anagrafe che mancava: una per (partita, giocatore, tipo,
    occorrenza), scritta quando si annuncia. L'annuncio smette di guardare la
    differenza e guarda LA REALTA' MENO CIO' CHE E' GIA' STATO DETTO, che e'
    idempotente per costruzione — riavvii, doppi tick e import a meta' compresi.

    ``occurrence`` e' il quale, non il quanti: il secondo gol dello stesso giocatore
    e' un evento a se', da annunciare a se'. ``recipients`` tiene il destinatario e
    l'esito per ciascuno, ed e' l'unica cosa che permette di rispondere, un mese
    dopo, a che cosa il server credeva di aver mandato.

    ``retracted_at`` serve al caso opposto e altrettanto reale: il fornitore che
    toglie un gol che aveva dato (VAR, o un errore suo). Fino al 31/08/2026 la
    discesa non produceva niente e la notifica falsa restava in tendina senza
    smentita.
    """
    KIND_GOAL = "goal"
    KIND_RED = "red"
    KIND_CHOICES = [(KIND_GOAL, "gol"), (KIND_RED, "espulsione")]

    match = models.ForeignKey("realdata.Match", on_delete=models.CASCADE,
                              related_name="live_notices")
    player = models.ForeignKey("realdata.Player", on_delete=models.CASCADE,
                               related_name="live_notices")
    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    # Il n-esimo evento di quel tipo per quel giocatore in quella partita: 1 per
    # l'espulsione (non se ne prende una seconda), 1..n per i gol.
    occurrence = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(default=timezone.now)
    retracted_at = models.DateTimeField(null=True, blank=True)
    # [{"user_id": 3, "username": "andrea", "devices": 2, "delivered": 2}, ...]
    # Vuoto e' un esito legittimo e va distinto dall'assenza della riga: significa
    # «l'evento c'e' stato, non lo aspettava nessuno», e non va rivalutato.
    recipients = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["match", "player", "kind", "occurrence"],
                name="uniq_live_notice_per_event"),
        ]
        indexes = [models.Index(fields=["match", "kind"])]
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.match_id} {self.kind}#{self.occurrence} p{self.player_id}"

    @property
    def delivered(self) -> int:
        """Quante consegne sono andate a buon fine, in tutto."""
        return sum(int(r.get("delivered") or 0) for r in (self.recipients or []))
