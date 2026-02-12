from django.db import models
from django.utils import timezone


class ZoneSet(models.Model):
    """Pitch partition definition used by the Vfoot engine."""

    KIND_GRID = "grid"
    KIND_POLYGONS = "polygons"

    kind = models.CharField(
        max_length=20,
        choices=[(KIND_GRID, "Grid"), (KIND_POLYGONS, "Polygons")],
        default=KIND_GRID,
    )
    name = models.CharField(max_length=80, default="Default grid")
    params = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"{self.name} ({self.kind})"


class Zone(models.Model):
    zone_set = models.ForeignKey(ZoneSet, on_delete=models.CASCADE, related_name="zones")
    code = models.CharField(max_length=32)

    # normalized bbox [0,1]
    x0 = models.FloatField()
    y0 = models.FloatField()
    x1 = models.FloatField()
    y1 = models.FloatField()

    polygon = models.JSONField(null=True, blank=True)

    row = models.IntegerField(null=True, blank=True)
    col = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = [("zone_set", "code")]
        indexes = [models.Index(fields=["zone_set", "code"])]

    def __str__(self) -> str:
        return f"{self.zone_set_id}:{self.code}"
