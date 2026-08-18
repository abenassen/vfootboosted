"""Le immagini caricate come stemma, e le segnalazioni su di esse.

Lo stemma di una squadra resta quello che è sempre stato: un descrittore opaco in
``FantasyTeam.crest``, che il server immagazzina senza guardarci dentro (v. il
commento sul campo, e ``tests_team_identity.test_crest_is_opaque_to_the_server``).
Chi carica un'immagine non cambia quel meccanismo: aggiunge al descrittore una
chiave ``img`` con l'impronta dell'immagine, e i pixel finiscono qui.

**Indirizzate dal contenuto.** La chiave primaria è lo sha256 dei byte *dopo* la
nostra ricodifica, non un id progressivo. Tre conseguenze, tutte volute:

  * due squadre che caricano la stessa immagine condividono una riga sola;
  * l'URL è immutabile per costruzione, quindi si può servire con una cache
    eterna: quel contenuto a quell'indirizzo non cambierà mai;
  * un'impronta nel descrittore non punta mai alla cosa sbagliata. Al massimo
    non punta a niente — e il render, quando l'immagine non risponde, ricade
    sui livelli composti che nel descrittore sono rimasti.

Quest'ultimo punto è ciò che permette al server di restare opaco: l'impronta nel
descrittore è una *pretesa*, questa tabella è l'*autorità*. Non serve validare in
scrittura ciò che si può semplicemente non servire in lettura.

**Revocare, non cancellare.** Un'immagine tolta lascia la riga con ``revoked_at``
e i byte azzerati. Cancellarla e basta libererebbe l'indirizzo: siccome l'impronta
è il contenuto, chi la ricarica la rimetterebbe online identica. La lapide invece
vieta quel contenuto, non quel file.

**I byte stanno nel database.** Non un ``ImageField``: file su disco vorrebbero
dire due archivi da tenere allineati (il backup notturno fa già due artefatti
separati, e si ripristinano separatamente), una scrittura fuori dalla transazione,
e una ``location /media/`` in nginx che oggi non esiste. Su PostgreSQL una bytea
oltre i 2 KB va comunque fuori riga in TOAST — con la differenza che ci va dentro
la stessa transazione e lo stesso ``pg_dump``. A quattro cifre di stemmi la
domanda cambia, e la risposta sarà un object storage: siccome l'URL è costruito
sull'impronta, cambierebbe solo chi risponde a quell'indirizzo.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class CrestImage(models.Model):
    # Lo sha256 esadecimale dei byte ricodificati. Chiave primaria: l'identità
    # dell'immagine È il suo contenuto.
    hash = models.CharField(max_length=64, primary_key=True)

    # I byte che serviamo, prodotti dal NOSTRO encoder: dell'originale caricato
    # non sopravvive niente (v. services/crest_images.py). Vuoti = revocata.
    data = models.BinaryField(blank=True, default=b"")
    # Quasi sempre image/webp. Sta qui perché non ogni build di Pillow ha il
    # WebP, e in quel caso ricadiamo su PNG: il tipo lo deve dire la riga, non
    # l'estensione nell'URL.
    content_type = models.CharField(max_length=32, default="image/webp")
    bytes = models.PositiveIntegerField(default=0)

    # Chi l'ha caricata. SET_NULL come per le segnalazioni: se l'account sparisce
    # l'immagine resta servibile, altrimenti gli stemmi di mezza lega si
    # spegnerebbero per la cancellazione di un altro.
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="crest_images")
    created_at = models.DateTimeField(default=timezone.now)

    # --- moderazione ---------------------------------------------------------
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="crest_revocations")
    revoked_reason = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["-created_at"])]

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def revoke(self, by=None, reason: str = "") -> None:
        """Toglie l'immagine dalla circolazione e ne libera i byte.

        Le segnalazioni che la riguardavano si chiudono da sole: sono state
        accolte, e lasciarle aperte vorrebbe dire riesaminare una cosa già fatta.
        """
        self.revoked_at = timezone.now()
        self.revoked_by = by
        self.revoked_reason = (reason or "")[:200]
        self.data = b""
        self.bytes = 0
        self.save(update_fields=["revoked_at", "revoked_by", "revoked_reason",
                                 "data", "bytes"])
        self.reports.filter(resolved_at__isnull=True).update(resolved_at=self.revoked_at)

    def __str__(self) -> str:  # pragma: no cover - comodità in admin
        stato = "revocata" if self.is_revoked else f"{self.bytes} byte"
        return f"{self.hash[:12]}… ({stato})"


class CrestReport(models.Model):
    """«Questo stemma non va bene»: un membro della lega lo dice, l'admin decide.

    La responsabilità sta dove sta il danno. Uno stemma lo vedono i dieci di una
    lega, che si conoscono: sono loro ad accorgersene per primi, ed è l'admin di
    quella lega ad avere sia il contesto sia l'interesse a intervenire. Qui resta
    la traccia, che serve a noi per due cose diverse — accorgersi di chi carica
    ripetutamente roba da togliere, e accorgersi di chi segnala per dispetto.

    ``league`` non è un dettaglio burocratico: dice DOVE l'immagine è stata vista,
    ed è ciò che autorizza l'admin di quella lega a toglierla. Un admin non può
    revocare un'immagine che nella sua lega non compare.
    """

    image = models.ForeignKey(CrestImage, on_delete=models.CASCADE,
                              related_name="reports")
    league = models.ForeignKey("vfoot.FantasyLeague", on_delete=models.CASCADE,
                               related_name="crest_reports")
    # La squadra che la esponeva quando è stata segnalata. SET_NULL: la
    # segnalazione riguarda l'immagine, e sopravvive a chi l'aveva addosso.
    team = models.ForeignKey("vfoot.FantasyTeam", on_delete=models.SET_NULL,
                             null=True, blank=True, related_name="crest_reports")
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="crest_reports")
    reason = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    # Null = da guardare. Si valorizza quando l'immagine viene revocata, o quando
    # l'admin decide che va bene così.
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Una segnalazione a testa per immagine e per lega: senza, il
            # pulsante premuto dieci volte per rabbia diventa dieci righe, e
            # l'admin legge dieci volte la stessa cosa.
            models.UniqueConstraint(fields=["image", "league", "reporter"],
                                    name="uniq_crest_report_per_reporter"),
        ]

    def __str__(self) -> str:  # pragma: no cover - comodità in admin
        chi = self.reporter.username if self.reporter else "anonimo"
        return f"{self.image_id[:12]}… segnalata da {chi}"
