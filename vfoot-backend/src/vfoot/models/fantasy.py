from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
import secrets

from realdata.models import CompetitionSeason, Match, Player


class FantasyLeague(models.Model):
    # Game mode, chosen at creation; drives formation rules, scoring engine and
    # page rendering. "aura" = the innovative zone-occupation/duel mode (default,
    # the existing behaviour); "classic" = traditional fantacalcio (role-based
    # formations, score = sum of fantavoti = voto puro + bonus/malus).
    MODE_AURA = "aura"
    MODE_CLASSIC = "classic"
    MODE_CHOICES = [(MODE_AURA, "Aura"), (MODE_CLASSIC, "Classic")]

    name = models.CharField(max_length=120)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name="owned_fantasy_leagues")
    mode = models.CharField(max_length=16, choices=MODE_CHOICES, default=MODE_AURA)
    invite_code = models.CharField(max_length=12, unique=True, db_index=True, null=True, blank=True)
    market_open = models.BooleanField(default=True)
    # Max bench substitutions applied when scoring a matchday (classic: an s.v.
    # starter is replaced by the first eligible bench player in priority order, up
    # to this many times). League-configurable by the admin; fantacalcio default 5.
    max_substitutions = models.PositiveSmallIntegerField(default=5)
    # Defence modifier (classic): a reward for fielding a strong, deep defence.
    # Awarded only if AT LEAST 4 defenders START (not if 4 is reached via subs).
    DEF_BONUS_ADD_OWN = "add_own"
    DEF_BONUS_SUB_OPP = "subtract_opponent"
    DEF_BONUS_MODE_CHOICES = [
        (DEF_BONUS_ADD_OWN, "Aggiunto alla propria squadra"),
        (DEF_BONUS_SUB_OPP, "Sottratto alla squadra avversaria"),
    ]
    defense_bonus_enabled = models.BooleanField(default=True)
    defense_bonus_mode = models.CharField(
        max_length=20, choices=DEF_BONUS_MODE_CHOICES, default=DEF_BONUS_ADD_OWN)
    # Real-world season this fantasy league is played on top of (e.g. Serie A
    # 2025-26). Competition rounds map to this season's real matchdays.
    reference_season = models.ForeignKey(
        CompetitionSeason,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fantasy_leagues",
    )
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.invite_code:
            self.invite_code = secrets.token_urlsafe(6)[:10]
        return super().save(*args, **kwargs)


class LeagueMembership(models.Model):
    ROLE_ADMIN = "admin"
    ROLE_MANAGER = "manager"

    league = models.ForeignKey(FantasyLeague, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="fantasy_memberships")
    role = models.CharField(max_length=16, choices=[(ROLE_ADMIN, "Admin"), (ROLE_MANAGER, "Manager")], default=ROLE_MANAGER)
    joined_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("league", "user")]


class FantasyTeam(models.Model):
    league = models.ForeignKey(FantasyLeague, on_delete=models.CASCADE, related_name="teams")
    manager = models.OneToOneField(LeagueMembership, on_delete=models.PROTECT, related_name="team")
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("league", "name")]

    def __str__(self) -> str:
        return self.name


class FantasyRosterSlot(models.Model):
    team = models.ForeignKey(FantasyTeam, on_delete=models.CASCADE, related_name="roster_slots")
    player = models.ForeignKey(Player, on_delete=models.PROTECT, related_name="fantasy_rosters")
    acquired_at = models.DateTimeField(default=timezone.now)
    released_at = models.DateTimeField(null=True, blank=True)
    purchase_price = models.IntegerField(default=1)

    class Meta:
        indexes = [models.Index(fields=["team", "released_at"])]


class FantasyCompetition(models.Model):
    TYPE_ROUND_ROBIN = "round_robin"
    TYPE_KNOCKOUT = "knockout"

    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_DONE = "done"

    league = models.ForeignKey(FantasyLeague, on_delete=models.CASCADE, related_name="competitions")
    name = models.CharField(max_length=120)
    competition_type = models.CharField(
        max_length=24,
        choices=[(TYPE_ROUND_ROBIN, "Round Robin"), (TYPE_KNOCKOUT, "Knockout")],
        default=TYPE_ROUND_ROBIN,
    )
    status = models.CharField(
        max_length=16,
        choices=[(STATUS_DRAFT, "Draft"), (STATUS_ACTIVE, "Active"), (STATUS_DONE, "Done")],
        default=STATUS_DRAFT,
    )

    # Customizable scoring (can be tuned later)
    points_win = models.IntegerField(default=3)
    points_draw = models.IntegerField(default=1)
    points_loss = models.IntegerField(default=0)

    starts_at = models.DateField(null=True, blank=True)
    ends_at = models.DateField(null=True, blank=True)
    # Span over the league's reference-season real matchdays: the competition's
    # rounds are spread uniformly across [start_matchday, end_matchday].
    start_matchday = models.IntegerField(null=True, blank=True)
    end_matchday = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("league", "name")]


class CompetitionStage(models.Model):
    TYPE_ROUND_ROBIN = "round_robin"
    TYPE_KNOCKOUT = "knockout"

    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_DONE = "done"

    competition = models.ForeignKey(FantasyCompetition, on_delete=models.CASCADE, related_name="stages")
    name = models.CharField(max_length=120)
    stage_type = models.CharField(
        max_length=24,
        choices=[(TYPE_ROUND_ROBIN, "Round Robin"), (TYPE_KNOCKOUT, "Knockout")],
        default=TYPE_ROUND_ROBIN,
    )
    order_index = models.IntegerField(default=1)
    # Round-robin only: when true, every pairing is played twice (home/away
    # swapped), doubling the rounds (andata/ritorno). Ignored for knockout.
    double_round = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16,
        choices=[(STATUS_DRAFT, "Draft"), (STATUS_ACTIVE, "Active"), (STATUS_DONE, "Done")],
        default=STATUS_DRAFT,
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("competition", "name")]
        ordering = ["order_index", "id"]


class CompetitionStageParticipant(models.Model):
    SOURCE_MANUAL = "manual"
    SOURCE_RULE = "rule"

    stage = models.ForeignKey(CompetitionStage, on_delete=models.CASCADE, related_name="participants")
    team = models.ForeignKey(FantasyTeam, on_delete=models.CASCADE, related_name="stage_entries")
    source = models.CharField(max_length=12, choices=[(SOURCE_MANUAL, "Manual"), (SOURCE_RULE, "Rule")], default=SOURCE_MANUAL)
    seed = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = [("stage", "team")]


class CompetitionStageRule(models.Model):
    MODE_TABLE_RANGE = "table_range"
    MODE_WINNERS = "winners"
    MODE_LOSERS = "losers"

    target_stage = models.ForeignKey(CompetitionStage, on_delete=models.CASCADE, related_name="rules_in")
    source_stage = models.ForeignKey(CompetitionStage, on_delete=models.CASCADE, related_name="rules_out")
    mode = models.CharField(
        max_length=16,
        choices=[(MODE_TABLE_RANGE, "Table Range"), (MODE_WINNERS, "Winners"), (MODE_LOSERS, "Losers")],
        default=MODE_WINNERS,
    )
    rank_from = models.IntegerField(null=True, blank=True)
    rank_to = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)


class FantasyMatchday(models.Model):
    STATUS_PLANNED = "planned"
    STATUS_CONCLUDED = "concluded"

    league = models.ForeignKey(FantasyLeague, on_delete=models.CASCADE, related_name="fantasy_matchdays")
    real_competition_season = models.ForeignKey(
        CompetitionSeason,
        on_delete=models.PROTECT,
        related_name="fantasy_matchdays",
    )
    real_matchday = models.IntegerField()
    status = models.CharField(
        max_length=16,
        choices=[(STATUS_PLANNED, "Planned"), (STATUS_CONCLUDED, "Concluded")],
        default=STATUS_PLANNED,
    )
    concluded_at = models.DateTimeField(null=True, blank=True)
    concluded_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="concluded_fantasy_matchdays",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("league", "real_competition_season", "real_matchday")]
        indexes = [models.Index(fields=["league", "status"]), models.Index(fields=["real_competition_season", "real_matchday"])]
        ordering = ["real_matchday", "id"]


class OfficeOverride(models.Model):
    """League-scoped 'voto d'ufficio': substitute a real match's data with an
    office result when that data is missing/late (typically a postponement).

    Takes PRIORITY over real SofaScore data when the league computes its fantasy
    scores. Each league decides INDEPENDENTLY — and occasionally — whether to wait
    for the real data or impose an office result for a given real match; one league
    overriding a match does not affect another.

    The substitute follows the "abolish roles" design: outfield players receive a
    global-mean, 90'-normalised zone vector (an average contributor — the spatial
    equivalent of a flat "6"); goalkeepers, scored on their separate goals-prevented
    channel, receive a neutral goals-prevented scalar instead. Both are tunable
    around the mean. The mean is computed at scoring time, so this row only stores
    the decision + tuning, never frozen numbers.
    """

    TEMPLATE_NEUTRAL_MEAN = "neutral_mean"
    TEMPLATE_CHOICES = [(TEMPLATE_NEUTRAL_MEAN, "Neutral mean (6 d'ufficio)")]

    league = models.ForeignKey(FantasyLeague, on_delete=models.CASCADE, related_name="office_overrides")
    # Context: which fantasy matchday this override belongs to (for listing/UI).
    fantasy_matchday = models.ForeignKey(
        FantasyMatchday, on_delete=models.CASCADE, related_name="office_overrides"
    )
    # The real match whose data is replaced. Players appearing in this match (per
    # roster / lineup) get the office substitute instead of their real performance.
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="office_overrides")

    template = models.CharField(max_length=24, choices=TEMPLATE_CHOICES, default=TEMPLATE_NEUTRAL_MEAN)
    # Outfield tuning: multiplier on the global-mean zone vector (1.0 = exactly
    # average). >1 rewards, <1 penalises, uniformly across zones.
    outfield_scale = models.FloatField(default=1.0)
    # Goalkeeper office value: an explicit goals-prevented scalar. Null => use the
    # neutral/global-mean goals-prevented at scoring time.
    gk_goals_prevented = models.FloatField(null=True, blank=True)

    reason = models.CharField(max_length=200, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_office_overrides")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("league", "match")]
        indexes = [
            models.Index(fields=["league", "fantasy_matchday"]),
            models.Index(fields=["match", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"OfficeOverride(league={self.league_id}, match={self.match_id})"


class LeaguePlayerRole(models.Model):
    """Frozen per-league 'listone' for classic mode: the role each player holds in
    THIS league.

    Classic fantacalcio fixes roles at season start and never changes them, even if
    a player later plays elsewhere on the pitch. So roles are SNAPSHOTTED per league
    when its listone opens and are immune to later Transfermarkt role changes — a
    weekly TM re-import refreshes rosters/DOBs but must NOT mutate a started league's
    roles. The global ``Player.classic_role`` (live from TM) only SEEDS this snapshot;
    admin overrides live here, scoped to the league.
    """

    SOURCE_SEED = "seed"      # snapshotted from Player.classic_role (TM-derived)
    SOURCE_ADMIN = "admin"    # admin override within this league
    SOURCE_CHOICES = [(SOURCE_SEED, "Seed (TM)"), (SOURCE_ADMIN, "Admin override")]

    league = models.ForeignKey(FantasyLeague, on_delete=models.CASCADE, related_name="player_roles")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="league_roles")
    role = models.CharField(max_length=3, choices=Player.CLASSIC_ROLE_CHOICES)
    source = models.CharField(max_length=8, choices=SOURCE_CHOICES, default=SOURCE_SEED)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("league", "player")]
        indexes = [models.Index(fields=["league", "role"])]

    def __str__(self) -> str:
        return f"{self.player_id}={self.role} @league {self.league_id}"


class CompetitionTeam(models.Model):
    """Direct participants of a competition (manual or from qualification rules)."""

    SOURCE_MANUAL = "manual"
    SOURCE_RULE = "rule"

    competition = models.ForeignKey(FantasyCompetition, on_delete=models.CASCADE, related_name="participants")
    team = models.ForeignKey(FantasyTeam, on_delete=models.CASCADE, related_name="competition_entries")
    source = models.CharField(max_length=12, choices=[(SOURCE_MANUAL, "Manual"), (SOURCE_RULE, "Rule")], default=SOURCE_MANUAL)
    seed = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = [("competition", "team")]


class CompetitionQualificationRule(models.Model):
    """
    Defines participants of a competition from results of another competition.
    Example: top 4 of championship at halfway stage enter Champions league.
    """

    STAGE_HALF = "halfway"
    STAGE_FINAL = "final"

    MODE_TABLE_RANGE = "table_range"
    MODE_WINNER = "winner"
    MODE_LOSER = "loser"

    competition = models.ForeignKey(FantasyCompetition, on_delete=models.CASCADE, related_name="qualification_rules")
    source_competition = models.ForeignKey(FantasyCompetition, on_delete=models.CASCADE, related_name="targeted_by_rules")
    source_stage = models.CharField(max_length=12, choices=[(STAGE_HALF, "Halfway"), (STAGE_FINAL, "Final")], default=STAGE_FINAL)
    # When set, the source table is snapshotted after this round of the source
    # competition (e.g. "top 5 after round 19"). Takes precedence over
    # source_stage; source_stage stays as the coarse fallback (halfway/final).
    source_round = models.IntegerField(null=True, blank=True)
    mode = models.CharField(
        max_length=16,
        choices=[(MODE_TABLE_RANGE, "Table Range"), (MODE_WINNER, "Winner"), (MODE_LOSER, "Loser")],
        default=MODE_TABLE_RANGE,
    )

    rank_from = models.IntegerField(null=True, blank=True)
    rank_to = models.IntegerField(null=True, blank=True)


class CompetitionPrize(models.Model):
    CONDITION_FINAL_TABLE_RANGE = "final_table_range"
    CONDITION_STAGE_TABLE_RANGE = "stage_table_range"
    CONDITION_STAGE_WINNER = "stage_winner"
    CONDITION_STAGE_LOSER = "stage_loser"

    competition = models.ForeignKey(FantasyCompetition, on_delete=models.CASCADE, related_name="prizes")
    name = models.CharField(max_length=120)
    condition_type = models.CharField(
        max_length=24,
        choices=[
            (CONDITION_FINAL_TABLE_RANGE, "Final table range"),
            (CONDITION_STAGE_TABLE_RANGE, "Stage table range"),
            (CONDITION_STAGE_WINNER, "Stage winner"),
            (CONDITION_STAGE_LOSER, "Stage loser"),
        ],
        default=CONDITION_FINAL_TABLE_RANGE,
    )
    source_stage = models.ForeignKey(
        CompetitionStage,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="awarded_prizes",
    )
    rank_from = models.IntegerField(null=True, blank=True)
    rank_to = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["id"]


class FantasyFixture(models.Model):
    STATUS_SCHEDULED = "scheduled"
    STATUS_LIVE = "live"
    STATUS_FINISHED = "finished"

    competition = models.ForeignKey(FantasyCompetition, on_delete=models.CASCADE, related_name="fixtures")
    stage = models.ForeignKey(CompetitionStage, on_delete=models.CASCADE, related_name="fixtures", null=True, blank=True)
    fantasy_matchday = models.ForeignKey(FantasyMatchday, on_delete=models.SET_NULL, related_name="fixtures", null=True, blank=True)
    round_no = models.IntegerField(default=1)
    leg_no = models.IntegerField(default=1)

    home_team = models.ForeignKey(FantasyTeam, on_delete=models.PROTECT, related_name="home_fixtures")
    away_team = models.ForeignKey(FantasyTeam, on_delete=models.PROTECT, related_name="away_fixtures")

    kickoff = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=[(STATUS_SCHEDULED, "Scheduled"), (STATUS_LIVE, "Live"), (STATUS_FINISHED, "Finished")],
        default=STATUS_SCHEDULED,
    )

    # Real match source used to score this fantasy fixture in simulation
    source_real_match = models.ForeignKey(Match, on_delete=models.SET_NULL, null=True, blank=True, related_name="mapped_fantasy_fixtures")

    # Final fantasy score produced by zone duel engine
    home_total = models.FloatField(default=0.0)
    away_total = models.FloatField(default=0.0)

    class Meta:
        unique_together = [("competition", "round_no", "leg_no", "home_team", "away_team")]
        indexes = [models.Index(fields=["competition", "round_no"]), models.Index(fields=["status"])]


class FantasyLineupSubmission(models.Model):
    fixture = models.ForeignKey(FantasyFixture, on_delete=models.CASCADE, related_name="lineup_submissions")
    team = models.ForeignKey(FantasyTeam, on_delete=models.CASCADE, related_name="lineup_submissions")

    gk_player = models.ForeignKey(Player, on_delete=models.SET_NULL, null=True, blank=True, related_name="as_gk_submissions")
    starter_player_ids = models.JSONField(default=list)
    bench_player_ids = models.JSONField(default=list)
    starter_backups = models.JSONField(default=list)

    submitted_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="submitted_lineups")
    submitted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("fixture", "team")]
        indexes = [models.Index(fields=["fixture", "team"])]


class FantasyFixtureDetail(models.Model):
    """Rich, self-contained per-fixture breakdown for the match-detail UI
    (Vfoot scores, zone-vector duel, per-zone macros/players, lineups).

    Stored as a JSON payload with the same shape the simulation produces, so the
    real match-detail page reuses the exact same components."""

    fixture = models.OneToOneField(FantasyFixture, on_delete=models.CASCADE, related_name="detail")
    vfoot_home = models.FloatField(default=0.0)
    vfoot_away = models.FloatField(default=0.0)
    payload = models.JSONField(default=dict)


class AuctionSession(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_CLOSED = "closed"

    league = models.ForeignKey(FantasyLeague, on_delete=models.CASCADE, related_name="auction_sessions")
    name = models.CharField(max_length=120, default="Main Auction")
    status = models.CharField(
        max_length=16,
        choices=[(STATUS_DRAFT, "Draft"), (STATUS_ACTIVE, "Active"), (STATUS_CLOSED, "Closed")],
        default=STATUS_DRAFT,
    )
    nomination_order = models.JSONField(default=list)
    nomination_index = models.IntegerField(default=0)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_auctions")
    created_at = models.DateTimeField(default=timezone.now)


class AuctionNomination(models.Model):
    STATUS_OPEN = "open"
    STATUS_CLOSED = "closed"

    session = models.ForeignKey(AuctionSession, on_delete=models.CASCADE, related_name="nominations")
    player = models.ForeignKey(Player, on_delete=models.PROTECT, related_name="auction_nominations")
    nominator = models.ForeignKey(LeagueMembership, on_delete=models.PROTECT, related_name="nominations")
    status = models.CharField(
        max_length=16,
        choices=[(STATUS_OPEN, "Open"), (STATUS_CLOSED, "Closed")],
        default=STATUS_OPEN,
    )
    closed_winner_team = models.ForeignKey(
        FantasyTeam, on_delete=models.SET_NULL, null=True, blank=True, related_name="won_nominations"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["session", "status"])]


class AuctionBid(models.Model):
    nomination = models.ForeignKey(AuctionNomination, on_delete=models.CASCADE, related_name="bids")
    bidder = models.ForeignKey(LeagueMembership, on_delete=models.PROTECT, related_name="auction_bids")
    amount = models.IntegerField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["nomination", "amount"])]
