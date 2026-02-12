from django.db import models

from realdata.models import Match, Player
from vfoot.models.zones import Zone


class PlayerZonePresence(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="zone_presences")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="zone_presences")
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name="player_presences")

    presence = models.FloatField()
    activity_score = models.FloatField(default=0.0)

    class Meta:
        unique_together = [("match", "player", "zone")]
        indexes = [models.Index(fields=["match", "zone"])]


class ZoneDuel(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="zone_duels")
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name="duels")

    home_score = models.FloatField(default=0.0)
    away_score = models.FloatField(default=0.0)
    winner = models.CharField(
        max_length=10,
        choices=[("home", "Home"), ("away", "Away"), ("draw", "Draw")],
        default="draw",
    )
    intensity = models.FloatField(default=0.0)

    class Meta:
        unique_together = [("match", "zone")]
        indexes = [models.Index(fields=["match"])]
