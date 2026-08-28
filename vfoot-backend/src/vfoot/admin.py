"""Quello che si smista a mano: le segnalazioni, e gli stemmi caricati.

L'admin di Django è quasi vuoto di proposito — tutto il resto del sito si governa
dalle sue pagine, non da qui — ma per le segnalazioni è il posto giusto: sono
righe di testo che si leggono in ordine di arrivo, si marcano e si dimenticano.
Costruire una schermata dedicata per fare esattamente questo sarebbe stato
lavoro speso per riottenere ciò che c'è già. Vale uguale per le immagini
caricate come stemma: una griglia di miniature con un pulsante «revoca» è
esattamente quello che l'admin di Django sa fare da solo.
"""
import base64

from django.contrib import admin
from django.utils.html import format_html

from vfoot.models import CrestImage, CrestReport, Feedback, ProductNews


@admin.register(ProductNews)
class ProductNewsAdmin(admin.ModelAdmin):
    """Da qui si scrivono gli annunci. Il titolo e' il messaggio: deve reggere da
    solo, perche' su un telefono e' spesso l'unica riga che si legge."""

    list_display = ("published_at", "title", "active")
    list_filter = ("active",)
    search_fields = ("title", "body")
    ordering = ("-published_at",)


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    # Il messaggio in elenco, non solo in dettaglio: arrivano a grappoli dopo un
    # deploy, e aprirle una per una per scoprire che tre dicono la stessa cosa è
    # il modo di smettere di leggerle.
    list_display = ("created_at", "kind", "user", "estratto", "page", "status")
    list_filter = ("status", "kind", "created_at")
    search_fields = ("message", "user__username", "page")
    list_editable = ("status",)
    readonly_fields = ("user", "kind", "message", "page", "user_agent", "viewport",
                       "created_at")
    date_hierarchy = "created_at"
    actions = ["segna_letta", "segna_chiusa"]

    @admin.display(description="Messaggio")
    def estratto(self, obj: Feedback) -> str:
        return obj.message[:80] + ("…" if len(obj.message) > 80 else "")

    @admin.action(description="Segna come letta")
    def segna_letta(self, request, queryset):
        queryset.update(status=Feedback.STATUS_SEEN)

    @admin.action(description="Segna come chiusa")
    def segna_chiusa(self, request, queryset):
        queryset.update(status=Feedback.STATUS_DONE)


@admin.register(CrestImage)
class CrestImageAdmin(admin.ModelAdmin):
    """Le immagini caricate come stemma. Si guardano, e se serve si tolgono.

    `data` non compare da nessuna parte: sono byte, e il modo di guardare
    un'immagine è vederla — perciò l'anteprima. Revocare da qui è l'ultima
    istanza, quella che vale su tutte le leghe; la prima è l'admin della lega,
    che se ne accorge prima di noi.
    """

    list_display = ("hash_breve", "anteprima", "uploaded_by", "created_at",
                    "bytes", "stato")
    list_filter = ("created_at", "revoked_at")
    search_fields = ("hash", "uploaded_by__username")
    readonly_fields = ("hash", "anteprima_grande", "content_type", "bytes",
                       "uploaded_by", "created_at", "revoked_at", "revoked_by")
    exclude = ("data",)
    date_hierarchy = "created_at"
    actions = ["revoca"]

    @admin.display(description="Impronta")
    def hash_breve(self, obj: CrestImage) -> str:
        return obj.hash[:12] + "…"

    @admin.display(description="Stato")
    def stato(self, obj: CrestImage) -> str:
        return "revocata" if obj.is_revoked else "attiva"

    def _img(self, obj: CrestImage, side: int) -> str:
        if obj.is_revoked or not obj.data:
            return "—"
        # L'immagine inline invece dell'URL dell'endpoint: l'admin di Django gira
        # su un'altra sessione, e un data URI si vede senza dipendere da questo.
        b64 = base64.b64encode(bytes(obj.data)).decode("ascii")
        return format_html(
            '<img src="data:{};base64,{}" width="{}" height="{}" '
            'style="border-radius:8px;object-fit:cover" />',
            obj.content_type, b64, side, side)

    @admin.display(description="Stemma")
    def anteprima(self, obj: CrestImage):
        return self._img(obj, 40)

    @admin.display(description="Stemma")
    def anteprima_grande(self, obj: CrestImage):
        return self._img(obj, 160)

    @admin.action(description="Revoca le immagini selezionate")
    def revoca(self, request, queryset):
        tolte = 0
        for image in queryset.filter(revoked_at__isnull=True):
            image.revoke(by=request.user, reason="revocata dall'admin del sito")
            tolte += 1
        self.message_user(request, f"{tolte} immagini revocate.")


@admin.register(CrestReport)
class CrestReportAdmin(admin.ModelAdmin):
    """Chi ha segnalato cosa. Serve a due cose opposte: accorgersi di chi carica
    ripetutamente roba da togliere, e accorgersi di chi segnala per dispetto."""

    list_display = ("created_at", "image", "league", "team", "reporter",
                    "reason", "resolved_at")
    list_filter = ("created_at", "resolved_at", "league")
    search_fields = ("image__hash", "reporter__username", "team__name", "reason")
    readonly_fields = ("image", "league", "team", "reporter", "reason", "created_at")
    date_hierarchy = "created_at"
