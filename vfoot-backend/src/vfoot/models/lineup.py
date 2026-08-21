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
