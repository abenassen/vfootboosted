from django.db import models
from django.utils import timezone

from realdata.models import MatchAppearance


class HeatmapGrid(models.Model):
    """Normalized heatmap for one appearance, reusable across ZoneSets."""

    appearance = models.OneToOneField(MatchAppearance, on_delete=models.CASCADE, related_name="heatmap")
    grid_w = models.IntegerField(default=30)
    grid_h = models.IntegerField(default=20)
    values = models.JSONField(default=list)
    created_at = models.DateTimeField(default=timezone.now)
