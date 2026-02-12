from django.db import models
from django.utils import timezone


class Competition(models.Model):
    name = models.CharField(max_length=80)          # "Serie A"
    country = models.CharField(max_length=40, blank=True, default="")

    external_source = models.CharField(max_length=50, blank=True, default="")
    external_id = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["external_source", "external_id"])]

    def __str__(self):
        return self.name


class Season(models.Model):
    """
    Generic season label, e.g. 2025-2026.
    """
    code = models.CharField(max_length=20, unique=True)  # "2025-2026"
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.code


class CompetitionSeason(models.Model):
    """
    Specific edition of a competition, e.g. Serie A 2025-2026.
    """
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="editions")
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="competitions")

    name = models.CharField(max_length=120, blank=True, default="")  # optional "Serie A 2025/26"
    # rounds could be useful later (matchday indexing)
    num_rounds = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = [("competition", "season")]

    def __str__(self):
        return self.name or f"{self.competition} {self.season}"


class Team(models.Model):
    name = models.CharField(max_length=100)  # "Juventus"
    short_name = models.CharField(max_length=40, blank=True, default="")
    city = models.CharField(max_length=80, blank=True, default="")

    external_source = models.CharField(max_length=50, blank=True, default="")
    external_id = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["external_source", "external_id"]),
                   models.Index(fields=["name"])]

    def __str__(self):
        return self.short_name or self.name


class TeamSeason(models.Model):
    """
    A team registered to a competition edition.
    """
    competition_season = models.ForeignKey(CompetitionSeason, on_delete=models.CASCADE, related_name="teams")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="seasons")

    class Meta:
        unique_together = [("competition_season", "team")]

    def __str__(self):
        return f"{self.team} ({self.competition_season})"


class Player(models.Model):
    """
    Canonical player identity across seasons.
    """
    full_name = models.CharField(max_length=120)
    short_name = models.CharField(max_length=120, blank=True, default="")
    date_of_birth = models.DateField(null=True, blank=True)

    # provider identifiers for robust matching across sources
    external_source = models.CharField(max_length=50, blank=True, default="")
    external_id = models.CharField(max_length=100, blank=True, default="")

    avatar = models.ImageField(upload_to="player_avatars/", null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["external_source", "external_id"]),
                   models.Index(fields=["full_name"])]

    def __str__(self):
        return self.short_name or self.full_name


class PlayerAlias(models.Model):
    """
    Optional: helps if names differ across sources/years.
    """
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="aliases")
    source = models.CharField(max_length=50, blank=True, default="")
    alias = models.CharField(max_length=120)

    class Meta:
        unique_together = [("player", "source", "alias")]
        indexes = [models.Index(fields=["source", "alias"])]

    def __str__(self):
        return f"{self.alias} -> {self.player_id}"


class Match(models.Model):
    competition_season = models.ForeignKey(CompetitionSeason, on_delete=models.CASCADE, related_name="matches")

    matchday = models.IntegerField(null=True, blank=True)  # giornata
    kickoff = models.DateTimeField(null=True, blank=True)

    home_team = models.ForeignKey(TeamSeason, on_delete=models.PROTECT, related_name="home_matches")
    away_team = models.ForeignKey(TeamSeason, on_delete=models.PROTECT, related_name="away_matches")

    home_goals = models.IntegerField(null=True, blank=True)
    away_goals = models.IntegerField(null=True, blank=True)

    external_source = models.CharField(max_length=50, blank=True, default="")
    external_id = models.CharField(max_length=100, blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["competition_season", "matchday"]),
                   models.Index(fields=["external_source", "external_id"])]

    def __str__(self):
        return f"{self.home_team} vs {self.away_team} ({self.competition_season})"


class MatchAppearance(models.Model):
    """
    Player participation in a match.
    IMPORTANT: team_season is the effective team for that match (transfer-safe).
    """
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="appearances")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="appearances")

    team_season = models.ForeignKey(TeamSeason, on_delete=models.PROTECT, related_name="appearances")
    side = models.CharField(max_length=10, choices=[("home", "Home"), ("away", "Away")])

    minutes_played = models.IntegerField(default=0)
    is_starter = models.BooleanField(default=False)

    class Meta:
        unique_together = [("match", "player")]
        indexes = [models.Index(fields=["match", "side"]),
                   models.Index(fields=["match", "team_season"])]

    def __str__(self):
        return f"{self.match_id} - {self.player_id} ({self.side})"


class PlayerTeamStint(models.Model):
    """
    Optional market history: player was registered to team during a date interval.
    Not strictly required for vfoot computations (MatchAppearance already carries team).
    """
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="team_stints")
    team_season = models.ForeignKey(TeamSeason, on_delete=models.CASCADE, related_name="player_stints")

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    transfer_kind = models.CharField(max_length=20, blank=True, default="")  # "loan", "permanent", ...

    class Meta:
        indexes = [models.Index(fields=["player", "team_season"]),
                   models.Index(fields=["team_season", "start_date"])]

