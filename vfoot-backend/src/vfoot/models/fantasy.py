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
    # Which role policy this league's listone was frozen under. "mitigated" lets an
    # unambiguous Transfermarkt position win; "data" lets the measured playing
    # style decide for everyone (a full-back who plays as a winger becomes an
    # attacker). Chosen when the listone opens and then fixed, like the reference
    # season: changing it mid-season would re-shuffle roles under the managers.
    ROLE_MODE_MITIGATED = "mitigated"
    ROLE_MODE_DATA = "data"
    ROLE_MODE_CHOICES = [(ROLE_MODE_MITIGATED, "Mitigata (priorita' Transfermarkt)"),
                         (ROLE_MODE_DATA, "Pura dai dati")]
    role_mode = models.CharField(max_length=10, choices=ROLE_MODE_CHOICES,
                                 default=ROLE_MODE_MITIGATED)

    # --- Auction / roster economy (classic) ------------------------------
    # Budget every manager starts the initial auction with. Serie A fantacalcio
    # convention is 1000 credits. Chosen at creation, editable ONLY until the
    # auction starts (afterwards it would rewrite what everyone paid against).
    initial_budget = models.PositiveIntegerField(default=1000)
    # Roster shape: how many players of each classic role a full squad holds.
    # Default is the standard 3-8-8-6 = 25. Total is not stored; it is the sum,
    # and the auction engine enforces "at least 1 credit reservable per unfilled
    # slot" against it.
    slots_gk = models.PositiveSmallIntegerField(default=3)
    slots_def = models.PositiveSmallIntegerField(default=8)
    slots_mid = models.PositiveSmallIntegerField(default=8)
    slots_fwd = models.PositiveSmallIntegerField(default=6)

    created_at = models.DateTimeField(default=timezone.now)

    # Classic role code (POR/DIF/CEN/ATT) -> the league quota for that role.
    def roster_quota(self) -> dict[str, int]:
        return {"POR": self.slots_gk, "DIF": self.slots_def,
                "CEN": self.slots_mid, "ATT": self.slots_fwd}

    def roster_size(self) -> int:
        return self.slots_gk + self.slots_def + self.slots_mid + self.slots_fwd

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


class SeasonPlayerRole(models.Model):
    """Roles computed for a SEASON's squads, before any league freezes them.

    Sits between the raw providers and ``LeaguePlayerRole``: the inference is
    expensive and season-wide (it clusters every player at once), while a league's
    listone is a cheap snapshot of one of the two variants. Recomputing per league
    would be wasteful and, worse, could hand two leagues different roles from the
    same evidence.

    Both variants are stored, not just the chosen one, so a league can be created
    under either policy without re-running anything — and so the two can be
    compared and audited after the fact.
    """

    METHOD_CATEGORY = "category"   # measured: we know how he played
    METHOD_TM = "tm"               # provider position, unambiguous
    METHOD_DEFAULT = "default"     # no data: positional fallback
    METHOD_UNKNOWN = "unknown"
    METHOD_CHOICES = [(METHOD_CATEGORY, "Categoria misurata"), (METHOD_TM, "Posizione TM"),
                      (METHOD_DEFAULT, "Default posizionale"), (METHOD_UNKNOWN, "Ignoto")]

    competition_season = models.ForeignKey(CompetitionSeason, on_delete=models.CASCADE,
                                           related_name="player_roles")
    player = models.ForeignKey(Player, on_delete=models.CASCADE,
                               related_name="season_roles")
    # Human-readable playing style ("ala offensiva"), empty when unmeasured.
    category = models.CharField(max_length=40, blank=True, default="")
    # How firmly he belongs to that category (co-association with its core).
    # Low values are what the admin is asked to review, not silently accepted.
    confidence = models.FloatField(default=0.0)
    role_data = models.CharField(max_length=3, blank=True, default="")
    role_mitigated = models.CharField(max_length=3, blank=True, default="")
    method = models.CharField(max_length=10, choices=METHOD_CHOICES,
                              default=METHOD_UNKNOWN)
    tm_position = models.CharField(max_length=40, blank=True, default="")
    computed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("competition_season", "player")]
        indexes = [models.Index(fields=["competition_season", "method"])]

    def role_for(self, mode: str) -> str:
        return self.role_data if mode == "data" else self.role_mitigated

    def __str__(self) -> str:
        return f"{self.player_id}@{self.competition_season_id}: {self.role_mitigated}"


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
    STATUS_CLOSED = "closed"       # assigned to a winner (or admin direct-assign)
    STATUS_CANCELLED = "cancelled"  # withdrawn without assignment (undo) -> back in pool

    # How the player was put up for auction, kept for the activity feed.
    CALL_MANUAL = "manual"          # admin picked this exact player
    CALL_RANDOM = "random"          # random over the whole remaining pool
    CALL_RANDOM_ROLE = "random_role"  # random within one role
    CALL_ASSIGN = "assign"          # admin direct-assign shortcut (verbal auction)
    CALL_CHOICES = [
        (CALL_MANUAL, "Manuale"), (CALL_RANDOM, "Casuale"),
        (CALL_RANDOM_ROLE, "Casuale per ruolo"), (CALL_ASSIGN, "Assegnazione diretta"),
    ]

    session = models.ForeignKey(AuctionSession, on_delete=models.CASCADE, related_name="nominations")
    player = models.ForeignKey(Player, on_delete=models.PROTECT, related_name="auction_nominations")
    nominator = models.ForeignKey(LeagueMembership, on_delete=models.PROTECT, related_name="nominations")
    call_mode = models.CharField(max_length=16, choices=CALL_CHOICES, default=CALL_MANUAL)
    status = models.CharField(
        max_length=16,
        choices=[(STATUS_OPEN, "Open"), (STATUS_CLOSED, "Closed"), (STATUS_CANCELLED, "Cancelled")],
        default=STATUS_OPEN,
    )
    closed_winner_team = models.ForeignKey(
        FantasyTeam, on_delete=models.SET_NULL, null=True, blank=True, related_name="won_nominations"
    )
    # Final price paid, recorded at close for the feed (also lives on the roster slot).
    winning_amount = models.IntegerField(null=True, blank=True)
    # The roster slot minted at close, so undo can revert exactly this acquisition.
    roster_slot = models.ForeignKey(
        "FantasyRosterSlot", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="from_nomination",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["session", "status"])]


class AuctionBid(models.Model):
    nomination = models.ForeignKey(AuctionNomination, on_delete=models.CASCADE, related_name="bids")
    bidder = models.ForeignKey(LeagueMembership, on_delete=models.PROTECT, related_name="auction_bids")
    amount = models.IntegerField()
    # A bid retracted by an undo is kept (not deleted) so the history stays honest;
    # only active bids count towards the current top bid.
    is_void = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["nomination", "amount"])]


class AuctionEvent(models.Model):
    """Append-only audit trail of everything that happens in an auction room.

    Doubles as the live activity feed (pushed over the WebSocket) and as the
    backbone of 'undo last action': each state-changing endpoint records one event,
    and undo endpoints record their own compensating event rather than erasing
    history. Never edited after creation."""

    TYPE_SESSION_CREATED = "session_created"
    TYPE_NOMINATED = "nominated"
    TYPE_BID = "bid"
    TYPE_BID_VOIDED = "bid_voided"
    TYPE_ASSIGNED = "assigned"          # nomination closed with a winner (or direct-assign)
    TYPE_NOMINATION_CANCELLED = "nomination_cancelled"
    TYPE_ASSIGNMENT_REVERTED = "assignment_reverted"
    TYPE_SESSION_CLOSED = "session_closed"

    session = models.ForeignKey(AuctionSession, on_delete=models.CASCADE, related_name="events")
    nomination = models.ForeignKey(
        AuctionNomination, on_delete=models.SET_NULL, null=True, blank=True, related_name="events"
    )
    event_type = models.CharField(max_length=32)
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="auction_events"
    )
    # Denormalised, human-readable snapshot (player name, team, amount, ...) so the
    # feed renders without extra joins and survives later row deletions.
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["session", "created_at"])]
        ordering = ["-created_at", "-id"]
