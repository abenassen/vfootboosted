from django.db import models
from django.utils import timezone


class SavedLineupSnapshot(models.Model):
    """Persisted lineup payload aligned with frontend SaveLineupRequest."""

    league_id = models.CharField(max_length=64)
    matchday_id = models.CharField(max_length=64)

    lineup_id = models.CharField(max_length=64)
    gk_player_id = models.CharField(max_length=64, null=True, blank=True)
    starter_player_ids = models.JSONField(default=list)
    bench_player_ids = models.JSONField(default=list)
    starter_backups = models.JSONField(default=list)

    saved_at = models.DateTimeField(default=timezone.now)
    # QUESTA FORMAZIONE E' STATA TOCCATA A GIORNATA GIA' COMINCIATA.
    #
    # Serve al vincolo sui difensori: chi modifica dopo il primo calcio d'inizio lo
    # fa sapendo dei voti, e da quel momento le sostituzioni non possono piu'
    # cambiare quanti difensori scendono in campo (v. `apply_classic_substitutions`,
    # parametro ``def_locked``). Chi non ha toccato niente non ha usato nessuna
    # informazione e non paga nulla.
    #
    # E' un campo e non un confronto fra date perche' `saved_at` non risponde: ha
    # ``default=timezone.now`` e il salvataggio non lo rimette nei ``defaults``
    # dell'``update_or_create``, quindi resta l'ora della PRIMA scrittura. E perche'
    # la domanda vera non e' «ha salvato dopo il fischio» ma «ha CAMBIATO qualcosa
    # dopo il fischio»: chi apre la pagina alle 20:30, non tocca niente e preme
    # Salva non deve perdere i cambi di ruolo per nulla.
    edited_after_kickoff = models.BooleanField(default=False)
    # CHI L'HA SCRITTA. ``manager``: l'allenatore, dalla pagina. ``baseline``: il
    # server, quando la rosa si e' completata — l'undici suggerito per la prima
    # giornata da giocare, cosi' che «non ha mandato la formazione» non esista
    # piu' come caso (v. services/lineup_baseline). E' una formazione a tutti gli
    # effetti: il punteggio la legge, le giornate successive la ereditano, il
    # mercato la ripara. Il campo serve alla pagina, per dire «proposta dal
    # suggeritore: se non la tocchi, gioca questa» invece di «salvata».
    ORIGIN_MANAGER = "manager"
    ORIGIN_BASELINE = "baseline"
    origin = models.CharField(max_length=10, default=ORIGIN_MANAGER)

    class Meta:
        # A saved lineup is identified by league + matchday + lineup_id, where
        # lineup_id encodes the team (and competition). The constraint MUST include
        # lineup_id, else only one team per league could store a lineup per matchday.
        unique_together = [("league_id", "matchday_id", "lineup_id")]
        indexes = [models.Index(fields=["league_id", "matchday_id"])]
