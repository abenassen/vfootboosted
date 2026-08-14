"""Le segnalazioni degli utenti, da leggere e smistare.

L'admin di Django è quasi vuoto di proposito — tutto il resto del sito si governa
dalle sue pagine, non da qui — ma per le segnalazioni è il posto giusto: sono
righe di testo che si leggono in ordine di arrivo, si marcano e si dimenticano.
Costruire una schermata dedicata per fare esattamente questo sarebbe stato
lavoro speso per riottenere ciò che c'è già.
"""
from django.contrib import admin

from vfoot.models import Feedback


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
