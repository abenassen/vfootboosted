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

    class Meta:
        unique_together = [("league_id", "matchday_id")]
        indexes = [models.Index(fields=["league_id", "matchday_id"])]
