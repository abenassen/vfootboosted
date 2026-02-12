from django.db import models
from django.utils import timezone
from realdata.models import Match, MatchAppearance, Player


class ZoneSet(models.Model):
    """
    A partition of the pitch.
    Default is a grid (4x3), but you can introduce polygons later without changing consumers.
    """
    KIND_GRID = "grid"
    KIND_POLYGONS = "polygons"

    kind = models.CharField(
        max_length=20,
        choices=[(KIND_GRID, "Grid"), (KIND_POLYGONS, "Polygons")],
        default=KIND_GRID,
    )
    name = models.CharField(max_length=80, default="Default grid")
    params = models.JSONField(default=dict, blank=True)  # e.g. {"nx": 4, "ny": 3}
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.name} ({self.kind})"


class Zone(models.Model):
    zone_set = models.ForeignKey(ZoneSet, on_delete=models.CASCADE, related_name="zones")
    code = models.CharField(max_length=32)  # stable, e.g. "Z_2_1"

    # normalized bbox [0,1]
    x0 = models.FloatField()
    y0 = models.FloatField()
    x1 = models.FloatField()
    y1 = models.FloatField()

    # future: polygons (normalized)
    polygon = models.JSONField(null=True, blank=True)

    row = models.IntegerField(null=True, blank=True)
    col = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = [("zone_set", "code")]
        indexes = [models.Index(fields=["zone_set", "code"])]

    def __str__(self):
        return f"{self.zone_set_id}:{self.code}"


class HeatmapGrid(models.Model):
    """
    Normalized heatmap for one appearance.
    Store a fixed-resolution grid so that you can recompute presences for any ZoneSet later.
    """
    appearance = models.OneToOneField(MatchAppearance, on_delete=models.CASCADE, related_name="heatmap")

    grid_w = models.IntegerField(default=30)
    grid_h = models.IntegerField(default=20)
    values = models.JSONField(default=list)  # row-major length = grid_w*grid_h

    created_at = models.DateTimeField(default=timezone.now)


class PlayerZonePresence(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="zone_presences")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="zone_presences")
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name="player_presences")

    presence = models.FloatField()        # 0..1
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

