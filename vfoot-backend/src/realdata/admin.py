"""L'unica cosa dei dati che si corregge a mano: il nome breve di un giocatore.

Il nome breve non lo componiamo noi, arriva abbreviato da SofaScore, e in certi
casi la sua abbreviazione e' semplicemente sbagliata. Una parte la ripariamo da
soli — le particelle di cognome, "G. D. Marzi" -> "G. De Marzi" (v.
``identity.spell_out_particles``) — perche' li' la prova sta nel nome completo:
il "De" c'e' scritto.

Il resto NON e' ricavabile da nessun dato che abbiamo. "Carlos Augusto" e' un
nome doppio, non nome piu' cognome, e nella riga non c'e' niente che lo distingua
da "Carlos Augusto Silva": per saperlo bisogna conoscere il giocatore. Serve
quindi una persona, e quella persona e' chi gestisce il SITO — non l'admin di una
lega, che sui dati veri non mette mano.

Perche' qui e non in una pagina dell'app, come tutto il resto: questo e' un
elenco che si cerca per nome e una casella di testo da correggere. Una schermata
dedicata sarebbe lavoro speso per riottenere quello che l'admin di Django fa gia'
(stessa scelta, e stesse ragioni, delle segnalazioni in ``vfoot/admin.py``).

Il resto della riga e' in sola lettura di proposito. Il ruolo NON si tocca da
qui: ha tre livelli e una risoluzione tutta sua (AGENTS.md, "Classic Role
Resolution"), e una modifica fatta scavalcando quel percorso si vedrebbe in un
posto solo.
"""
from django.contrib import admin

from realdata.models import Player


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("full_name", "short_name", "short_name_source", "external_source")
    # Correggibile dall'ELENCO: i nomi da sistemare si scoprono a grappoli
    # leggendo il listone, e aprire una scheda per volta per cambiare due parole
    # e' il modo di rimandare la correzione.
    list_editable = ("short_name",)
    list_filter = ("short_name_source", "external_source", "is_goalkeeper")
    search_fields = ("full_name", "short_name")
    ordering = ("full_name",)
    fields = ("full_name", "short_name", "short_name_source", "date_of_birth",
              "external_source", "external_id", "is_goalkeeper", "classic_role_seed")
    readonly_fields = ("full_name", "short_name_source", "date_of_birth",
                       "external_source", "external_id", "is_goalkeeper",
                       "classic_role_seed")
    actions = ["riaffida_all_automatismo"]

    def has_add_permission(self, request):
        """I giocatori li creano le importazioni: uno aggiunto a mano non avrebbe
        l'identificativo del fornitore e resterebbe scollegato da ogni partita."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Cancellarne uno porterebbe via presenze, voti e contratti in cascata."""
        return False

    def save_model(self, request, obj, form, change):
        """Chi ha scritto quel nome. Solo se il nome e' CAMBIATO davvero: aprire una
        scheda e salvarla senza toccare niente non e' una decisione, e marcarla
        come tale sottrarrebbe la riga alle riparazioni automatiche per sbaglio."""
        if "short_name" in form.changed_data:
            obj.short_name_source = Player.SHORT_NAME_ADMIN
        super().save_model(request, obj, form, change)

    @admin.action(description="Riaffida il nome breve all'automatismo")
    def riaffida_all_automatismo(self, request, queryset):
        """La porta di ritorno. Senza, una correzione a mano e' definitiva: il valore
        resta quello ma nessuna riparazione futura potra' piu' toccarlo, e il
        motivo (un flag) non si vedrebbe da nessuna parte."""
        n = queryset.update(short_name_source="")
        self.message_user(request, f"{n} nomi riaffidati alle riparazioni automatiche.")
