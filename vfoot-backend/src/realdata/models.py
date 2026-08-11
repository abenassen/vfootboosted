from datetime import timedelta

from django.db import models
from django.utils import timezone

PROVIDER_STATSBOMB = "statsbomb"
PROVIDER_WYSCOUT = "wyscout"
PROVIDER_SOFASCORE = "sofascore"
PROVIDER_CHOICES = [
    (PROVIDER_STATSBOMB, "StatsBomb"),
    (PROVIDER_WYSCOUT, "Wyscout"),
    (PROVIDER_SOFASCORE, "SofaScore"),
]

SIDE_HOME = "home"
SIDE_AWAY = "away"
SIDE_UNKNOWN = "unknown"
SIDE_CHOICES = [
    (SIDE_HOME, "Home"),
    (SIDE_AWAY, "Away"),
    (SIDE_UNKNOWN, "Unknown"),
]

CARD_YELLOW = "yellow"
CARD_SECOND_YELLOW = "second_yellow"
CARD_RED = "red"
CARD_UNKNOWN = "unknown"
CARD_CHOICES = [
    (CARD_YELLOW, "Yellow"),
    (CARD_SECOND_YELLOW, "Second Yellow"),
    (CARD_RED, "Red"),
    (CARD_UNKNOWN, "Unknown"),
]

INTERVAL_STARTING_XI = "starting_xi"
INTERVAL_SUBSTITUTION_ON = "substitution_on"
INTERVAL_TACTICAL_SHIFT = "tactical_shift"
INTERVAL_PLAYER_ON = "player_on"
INTERVAL_UNKNOWN_START = "unknown_start"
INTERVAL_START_REASON_CHOICES = [
    (INTERVAL_STARTING_XI, "Starting XI"),
    (INTERVAL_SUBSTITUTION_ON, "Substitution On"),
    (INTERVAL_TACTICAL_SHIFT, "Tactical Shift"),
    (INTERVAL_PLAYER_ON, "Player On"),
    (INTERVAL_UNKNOWN_START, "Unknown Start"),
]

INTERVAL_FINAL_WHISTLE = "final_whistle"
INTERVAL_SUBSTITUTION_OFF = "substitution_off"
INTERVAL_RED_CARD = "red_card"
INTERVAL_PLAYER_OFF = "player_off"
INTERVAL_UNKNOWN_END = "unknown_end"
INTERVAL_END_REASON_CHOICES = [
    (INTERVAL_FINAL_WHISTLE, "Final Whistle"),
    (INTERVAL_SUBSTITUTION_OFF, "Substitution Off"),
    (INTERVAL_TACTICAL_SHIFT, "Tactical Shift"),
    (INTERVAL_RED_CARD, "Red Card"),
    (INTERVAL_PLAYER_OFF, "Player Off"),
    (INTERVAL_UNKNOWN_END, "Unknown End"),
]


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

    # Provider identity of this specific edition. For SofaScore this is the
    # season id (e.g. 95836 for Serie A 2026/27) — resolved once, by name, at
    # league-creation time, and then STABLE. The calendar-sync and per-match
    # scrapers key off this instead of a hardcoded id.
    external_source = models.CharField(max_length=50, blank=True, default="")
    external_id = models.CharField(max_length=100, blank=True, default="")

    # Last time the provider's fixture list was read for this edition, and only on
    # a read that WENT THROUGH. It is what lets the sync decide "am I due?" instead
    # of running on a fixed clock — see calendar_sync.sync_is_due — and stamping it
    # only on success is what makes a blocked egress retry at the next tick rather
    # than wait out the whole interval.
    calendar_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("competition", "season")]
        indexes = [models.Index(fields=["external_source", "external_id"])]

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

    # Fixed goalkeeper tag from the authoritative roster source (Transfermarkt
    # position == "Goalkeeper"). Kept as a stored flag, NOT inferred from match
    # data: a keeper who has never played (new signing / unused sub) must still be
    # recognisable for the formation's one-GK constraint, and box-share inference
    # is fragile in rare/extreme cases. Goalkeepers are scored on a separate
    # channel (goals-prevented), never via zone vectors.
    is_goalkeeper = models.BooleanField(default=False)

    # RAW PROVIDER SEED, not a resolved role. This is the Transfermarkt position
    # mapped to POR/DIF/CEN/ATT — under which every winger is a CEN by convention
    # (Leão included) — optionally corrected by an admin (see role_source). It is a
    # SEED for the resolved roles, and must NEVER be read to SCORE the voto puro:
    #   * resolved SCORING role  -> CurrentPlayerRole via
    #     `classic_rating.current_role_map()` (TM + k-means + SofaScore fallback);
    #   * a league's FROZEN role  -> LeaguePlayerRole (authority inside a league).
    # Kept on the player (not provider-namespaced) only as the single seed those
    # layers snapshot from. POR is kept in sync with is_goalkeeper. See AGENTS.md
    # "Classic Role Resolution".
    ROLE_GK = "POR"
    ROLE_DEF = "DIF"
    ROLE_MID = "CEN"
    ROLE_FWD = "ATT"
    CLASSIC_ROLE_CHOICES = [
        (ROLE_GK, "Portiere"),
        (ROLE_DEF, "Difensore"),
        (ROLE_MID, "Centrocampista"),
        (ROLE_FWD, "Attaccante"),
    ]
    # NB: the name predates the resolution layers; it is a provider seed despite
    # reading like a settled role. help_text spells that out in the admin/API.
    classic_role_seed = models.CharField(
        max_length=3, choices=CLASSIC_ROLE_CHOICES, blank=True, default="",
        help_text="Raw Transfermarkt provider seed (winger→CEN by convention), "
                  "NOT the resolved scoring role — see CurrentPlayerRole / "
                  "current_role_map().")

    # Where classic_role_seed came from: the raw provider map, or an "admin" override
    # (preserved across TM re-imports, same non-clobber rule as date_of_birth
    # corrections). Either way it stays a SEED, never the scoring role.
    ROLE_SOURCE_TM = "transfermarkt"
    ROLE_SOURCE_ADMIN = "admin"
    role_source = models.CharField(max_length=16, blank=True, default="")

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
    # Lifecycle status, mirrored from the provider's event status. `postponed`
    # is the one that drives league behaviour: a postponed real match can leave a
    # fantasy matchday without data, so a league either waits or imposes an
    # OfficeOverride. `live` enables a provisional (non-final) estimate.
    STATUS_SCHEDULED = "scheduled"
    STATUS_LIVE = "live"
    STATUS_FINISHED = "finished"
    STATUS_POSTPONED = "postponed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_LIVE, "Live"),
        (STATUS_FINISHED, "Finished"),
        (STATUS_POSTPONED, "Postponed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    competition_season = models.ForeignKey(CompetitionSeason, on_delete=models.CASCADE, related_name="matches")

    matchday = models.IntegerField(null=True, blank=True)  # giornata
    kickoff = models.DateTimeField(null=True, blank=True)
    # True while the provider still ships a PLACEHOLDER kickoff (whole round shares
    # one identical timestamp, exact slot not yet assigned). The scheduler must NOT
    # open a live-poll window on a provisional kickoff; it waits for confirmation.
    kickoff_provisional = models.BooleanField(default=False)

    home_team = models.ForeignKey(TeamSeason, on_delete=models.PROTECT, related_name="home_matches")
    away_team = models.ForeignKey(TeamSeason, on_delete=models.PROTECT, related_name="away_matches")

    home_goals = models.IntegerField(null=True, blank=True)
    away_goals = models.IntegerField(null=True, blank=True)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_SCHEDULED)
    # True only once the COMPLETE scoring data (shotmap + per-player heatmaps +
    # statistics) is present AND has stopped changing after full-time. A finished
    # match is not necessarily scoreable-as-final until SofaScore stabilises it;
    # this flag is what lets a fantasy matchday be computed as definitive.
    data_ready = models.BooleanField(default=False)
    # Last live ROUND: status, score and the per-player totals, every couple of
    # minutes (VFOOT_LIVE_POLL_MINUTES).
    data_checked_at = models.DateTimeField(null=True, blank=True)
    # Last HEAVY round — the one that also pulled a heatmap per player, and with
    # them the positional half of the model. Every k-th round carries it
    # (VFOOT_LIVE_HEAVY_EVERY); the two stamps are not two clocks, since a heavy
    # round never happens outside a round.
    data_imported_at = models.DateTimeField(null=True, blank=True)
    # When the match was FIRST observed as finished (full time). The scheduler
    # measures the +15min / +1h finalization windows from this, so it must be the
    # real observed FT, not an estimate from kickoff + nominal duration.
    finished_at = models.DateTimeField(null=True, blank=True)

    external_source = models.CharField(max_length=50, blank=True, default="")
    external_id = models.CharField(max_length=100, blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["competition_season", "matchday"]),
                   models.Index(fields=["external_source", "external_id"]),
                   models.Index(fields=["status", "data_ready"])]

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
    # Per-player scoring events (bonus/malus inputs). Populated from the provider's
    # lineup statistics at import time; cards live in MatchDisciplinaryEvent.
    goals = models.IntegerField(default=0)
    assists = models.IntegerField(default=0)

    # The provider's COMPLETE per-match statistics for this player, as sent.
    #
    # Kept verbatim, and deliberately not curated, because the alternative has
    # already cost us three full re-imports of the season: every time a question
    # needed a column the adapter had not been told to keep — duels lost, tackles,
    # dribbles conceded — the only way to answer it was to ingest everything
    # again. Sixty-odd numbers per appearance is nothing to store and removes the
    # need to predict which of them a future question will want.
    #
    # This is a RAW mirror, not an interface: nothing should score off it directly.
    # Anything the model actually uses gets a named feature with its own semantics
    # (see DISTRIBUTED_STAT_MAP), so provider quirks stay in one place.
    raw_stats = models.JSONField(default=dict, blank=True)

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

    # Raw provider position for THIS season's squad entry ("left winger", ...).
    # Kept per stint, not on Player: a position is a fact about a season, and the
    # role inference must be able to read the season it is reasoning about without
    # reaching back into the scrape cache.
    tm_position = models.CharField(max_length=40, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["player", "team_season"]),
                   models.Index(fields=["team_season", "start_date"])]


class PlayerMarketValue(models.Model):
    """Market valuation of a player from an EXTERNAL provider (e.g. Transfermarkt).

    Modelled as provenanced external data, not a bare field on Player: a market
    value belongs to a provider and to a moment in time (it is re-quoted as the
    market moves), so this is a small time series. The latest row per
    (player, provider) is the current valuation.

    It is deliberately NOT a performance rating — it is used as a secondary signal
    for players we have no on-pitch history for (newcomers), never as a substitute
    for a voto.
    """
    player = models.ForeignKey(Player, on_delete=models.CASCADE,
                               related_name="market_values")
    provider = models.CharField(max_length=50)  # e.g. "transfermarkt"
    provider_player_id = models.CharField(max_length=100, blank=True, default="")

    value_eur = models.BigIntegerField(null=True, blank=True)  # normalized amount
    currency = models.CharField(max_length=8, default="EUR")
    raw_value = models.CharField(max_length=32, blank=True, default="")  # "€3.50m"
    as_of = models.DateField()

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("player", "provider", "as_of")]
        indexes = [models.Index(fields=["provider", "as_of"]),
                   models.Index(fields=["player", "provider"])]

    def __str__(self):
        return f"{self.player_id} {self.raw_value or self.value_eur} ({self.provider} {self.as_of})"


class DataIngestionManifest(models.Model):
    """
    Tracks external dataset versions used to generate DB features.
    """

    provider = models.CharField(max_length=24, choices=PROVIDER_CHOICES, default=PROVIDER_STATSBOMB)
    dataset_key = models.CharField(max_length=80, default="default")
    data_version = models.CharField(max_length=80, default="unknown")
    formula_version = models.CharField(max_length=80, default="features_v1")
    source_path = models.CharField(max_length=500, blank=True, default="")
    notes = models.CharField(max_length=300, blank=True, default="")
    imported_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("provider", "dataset_key", "data_version", "formula_version")]
        indexes = [
            models.Index(fields=["provider", "data_version"]),
            models.Index(fields=["imported_at"]),
        ]


class JobRun(models.Model):
    """One run of a scheduled job: what it was DUE to do, and what it DID.

    WHY THIS EXISTS, given that systemd already logs to the journal. Because the
    failure this is here to catch does not look like a failure. A scraper whose
    provider renamed a field still exits 0: the import runs, the journal says
    "applied", and what enters the database is a season of players with no stats
    and a voto puro flattened onto 6.0 for everybody. Exit codes see none of it;
    neither does a human reading the journal, because there is nothing to read.

    So the row carries NUMBERS, not an outcome — how many matches were seen, how
    many players updated, how many requests the egress made. A count that halves
    overnight is a signal; "success" is not.

    ``due`` is the half that is easy to forget and is the whole point. A tick that
    imported nothing is normal a thousand times a day and an alarm on a Sunday at
    18:00 — and the two are the same journal line. The tick already computes its
    plan before acting (``match_scheduler.plan_tick``), so it knows which of the two
    it is; this is where that knowledge is written down instead of thrown away.
    Everything ``health_report`` can say rests on the pair being recorded together.

    Append-only, one row per run, pruned by ``health_report --prune``. The tick
    alone writes ~1440 rows a day: uninteresting ones (nothing due, no error) are
    kept 14 days, the rest 90 — see ``prune``.
    """

    job = models.CharField(max_length=40, help_text="tick, sync_calendar, ...")
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    # None is not "unknown": it is a run that started and never wrote its own
    # ending — killed, OOM, the machine rebooted mid-run. Distinguishing that from
    # an orderly failure matters, so it is a third state and not a default of False.
    ok = models.BooleanField(null=True, blank=True)
    dry_run = models.BooleanField(default=False)
    due = models.JSONField(default=dict, blank=True)
    did = models.JSONField(default=dict, blank=True)
    note = models.CharField(max_length=300, blank=True, default="")
    error = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["job", "-started_at"]),
            models.Index(fields=["-started_at"]),
        ]

    def __str__(self) -> str:
        state = {True: "ok", False: "FAILED", None: "interrupted"}[self.ok]
        return f"{self.job} @ {self.started_at:%Y-%m-%d %H:%M} [{state}]"

    @property
    def seconds(self) -> float | None:
        if not self.finished_at:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    @property
    def idle(self) -> bool:
        """True when the run had nothing to do — the boring majority of ticks.

        Not the same as ``did`` being empty: a run that WAS owed something and
        produced nothing is the interesting case, and must never be pruned as if it
        were quiet."""
        return not self.due and not self.error and self.ok is True

    @classmethod
    def prune(cls, *, keep_idle_days: int = 14, keep_days: int = 90) -> int:
        """Drop old rows. Returns how many went.

        Two ages on purpose. The quiet rows are what makes the table big and they
        stop being worth anything within days: they only ever answer "was the timer
        alive on the 3rd of March". A run that failed, or that was owed work, is
        evidence — that one is kept long enough to see a pattern across a couple of
        months, which is exactly the reading a human (or the maintenance agent)
        does after the second time something goes wrong.
        """
        now = timezone.now()
        gone = cls.objects.filter(
            started_at__lt=now - timedelta(days=keep_idle_days),
            ok=True, due={}, error="").delete()[0]
        gone += cls.objects.filter(
            started_at__lt=now - timedelta(days=keep_days)).delete()[0]
        return gone


class MaintenanceRun(models.Model):
    """One pass of the maintenance agent: what woke it, and what it concluded.

    The agent is STATELESS between passes. Without a written record it would
    re-diagnose Tuesday's problem from scratch on Wednesday and quite possibly
    "fix" it a second time — so this table is not a log, it is the agent's memory,
    and the rule that reads it (never re-propose what was rejected) is what stops
    it from becoming a colleague who repeats the same idea every morning.

    ``agent_cmd`` records WHICH adapter produced the pass. Two providers behind one
    contract means a proposal's quality cannot be read without knowing who wrote it,
    and "which model was this?" is the first question asked of a bad proposal.
    """

    TRIGGER_ALARM = "alarm"
    TRIGGER_WEEKLY = "weekly"
    TRIGGER_MANUAL = "manual"
    TRIGGER_CHOICES = [
        (TRIGGER_ALARM, "Verdetto rosso"),
        (TRIGGER_WEEKLY, "Passata settimanale"),
        (TRIGGER_MANUAL, "A mano"),
    ]

    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    trigger = models.CharField(max_length=12, choices=TRIGGER_CHOICES,
                               default=TRIGGER_ALARM)
    agent_cmd = models.CharField(max_length=200, blank=True, default="")
    # The health verdict that woke it, stored verbatim: the proposal is only
    # judgeable next to the evidence the agent was actually given.
    context = models.JSONField(default=dict, blank=True)
    ok = models.BooleanField(null=True, blank=True)
    summary = models.CharField(max_length=300, blank=True, default="")
    diagnosis = models.TextField(blank=True, default="")
    error = models.TextField(blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["-started_at"])]

    def __str__(self) -> str:
        state = {True: "ok", False: "FALLITA", None: "interrotta"}[self.ok]
        return f"manutenzione {self.started_at:%d/%m %H:%M} [{state}]"


class MaintenanceProposal(models.Model):
    """One thing the agent proposes doing. The agent NEVER acts — this is the seam.

    ``kind`` comes from a closed set and ``payload`` is re-validated in Python at
    execution time (see ``services/maintenance.validate``). That double check is the
    whole security model: the agent's input contains error strings that came from
    other people's websites, so a fully hijacked model must still be unable to do
    anything but propose one of these — and a human must still click.

    The list of permitted actions therefore lives in an ``if``, not in a prompt that
    politely asks the model to behave.
    """

    KIND_RESTART_UNIT = "restart_unit"
    KIND_RERUN_COMMAND = "rerun_command"
    KIND_CLEAR_CACHE_FILE = "clear_cache_file"
    KIND_APPLY_PATCH = "apply_patch"
    KIND_NONE = "none"
    KIND_CHOICES = [
        (KIND_RESTART_UNIT, "Riavvia un'unita'"),
        (KIND_RERUN_COMMAND, "Rilancia un comando"),
        (KIND_CLEAR_CACHE_FILE, "Cancella un file di cache"),
        (KIND_APPLY_PATCH, "Applica una patch"),
        (KIND_NONE, "Nessuna azione"),
    ]

    # Kinds that may execute without a human, when the auto tier is switched on.
    # apply_patch is deliberately absent and must stay absent.
    AUTO_KINDS = (KIND_RESTART_UNIT, KIND_RERUN_COMMAND, KIND_CLEAR_CACHE_FILE)

    STATUS_PROPOSED = "proposed"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_REFUSED = "refused"
    STATUS_CHOICES = [
        (STATUS_PROPOSED, "In attesa di un sì"),
        (STATUS_APPROVED, "Approvata, da eseguire"),
        (STATUS_REJECTED, "Rifiutata"),
        (STATUS_DONE, "Eseguita"),
        (STATUS_FAILED, "Esecuzione fallita"),
        (STATUS_REFUSED, "Respinta dalla validazione"),
    ]

    run = models.ForeignKey(MaintenanceRun, on_delete=models.CASCADE,
                            related_name="proposals")
    kind = models.CharField(max_length=24, choices=KIND_CHOICES)
    payload = models.JSONField(default=dict, blank=True)
    rationale = models.TextField(blank=True, default="")
    evidence = models.JSONField(default=dict, blank=True)
    # sha256 of (kind, payload): the identity used to recognise a proposal already
    # rejected once. Without it the agent re-proposes the same rejected idea nightly.
    fingerprint = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES,
                              default=STATUS_PROPOSED)
    decided_by = models.ForeignKey("auth.User", null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name="maintenance_decisions")
    decided_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    result = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["fingerprint"]),
        ]

    def __str__(self) -> str:
        return f"{self.kind} [{self.status}]"

    @property
    def needs_human(self) -> bool:
        """True when no auto tier may ever execute this. ``apply_patch`` always does."""
        return self.kind not in self.AUTO_KINDS


class PlayerZoneFeature(models.Model):
    """
    Aggregated feature values by player and zone for one match.
    One row per feature key.
    """

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="player_zone_features")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="zone_features")
    team_side = models.CharField(max_length=12, choices=SIDE_CHOICES, default=SIDE_UNKNOWN)
    zone_key = models.CharField(max_length=24)
    feature_key = models.CharField(max_length=64)
    value = models.FloatField(default=0.0)
    provider = models.CharField(max_length=24, choices=PROVIDER_CHOICES, default=PROVIDER_STATSBOMB)
    source_method = models.CharField(max_length=40, default="event_spatial_exact")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("match", "player", "team_side", "zone_key", "feature_key", "provider")]
        indexes = [
            models.Index(fields=["match", "player"]),
            models.Index(fields=["match", "zone_key"]),
            models.Index(fields=["feature_key"]),
        ]


class MatchShot(models.Model):
    """One shot, with WHEN and WHERE it happened.

    The zone features aggregate shots and throw the minute away, which is fine for
    a season total and wrong for anything that has to respect who was on the pitch.
    It cost us a real defect: charging a defender with the danger conceded in his
    zones, scaled by minutes played, misattributed more than 20 percentage points
    of a match's danger for one defender in seven — a player penalised for a goal
    conceded after he had already been substituted.

    Kept as its own row rather than as another zone feature because a shot is an
    event, not a quantity: it has a time, an outcome and a taker. Live scoring and
    match timelines need the same thing.
    """

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="shots")
    player = models.ForeignKey(Player, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="shots")
    team_side = models.CharField(max_length=12, choices=SIDE_CHOICES, default=SIDE_UNKNOWN)
    # Match minute as the provider reports it (stoppage time folded into the
    # preceding minute, so a 90+3 shot reads 90).
    minute = models.IntegerField(null=True, blank=True)
    # Sub-minute timing from the provider (SofaScore ``timeSeconds``): seconds from
    # kick-off. Kept so an own goal can be linked to the EXACT shot it deflected — a
    # minute is too coarse, coincidental shots share it (Bonny/Edmundsson). Null for
    # rows imported before this was captured; a re-scrape backfills them.
    elapsed_seconds = models.IntegerField(null=True, blank=True)
    zone_key = models.CharField(max_length=24)
    xg = models.FloatField(default=0.0)
    xgot = models.FloatField(default=0.0)     # post-shot xG; 0 when off target
    is_goal = models.BooleanField(default=False)
    shot_type = models.CharField(max_length=24, blank=True, default="")
    # The play the shot came from (SofaScore ``situation``): regular, fast-break,
    # set-piece, corner, assisted, and — the one we act on — ``penalty``. A missed
    # penalty (situation=penalty, not is_goal) carries the -3 fantavoto malus and a
    # result-scaled voto-puro drop, neither of which shot_type (the outcome) can tell.
    situation = models.CharField(max_length=24, blank=True, default="")
    provider = models.CharField(max_length=24, choices=PROVIDER_CHOICES,
                                default=PROVIDER_SOFASCORE)
    external_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["match", "team_side"]),
                   models.Index(fields=["match", "minute"])]
        constraints = [
            # The provider's own shot id makes re-imports idempotent.
            models.UniqueConstraint(fields=["match", "provider", "external_id"],
                                    condition=~models.Q(external_id=""),
                                    name="uniq_shot_per_provider_id"),
        ]

    def __str__(self) -> str:
        return f"{self.match_id} {self.minute}' {self.team_side} xg={self.xg:.2f}"


class TeamZoneFeature(models.Model):
    """
    Aggregated feature values by team side and zone for one match.
    One row per feature key.
    """

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="team_zone_features")
    team_side = models.CharField(max_length=12, choices=SIDE_CHOICES, default=SIDE_UNKNOWN)
    zone_key = models.CharField(max_length=24)
    feature_key = models.CharField(max_length=64)
    value = models.FloatField(default=0.0)
    provider = models.CharField(max_length=24, choices=PROVIDER_CHOICES, default=PROVIDER_STATSBOMB)
    source_method = models.CharField(max_length=40, default="event_spatial_exact")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("match", "team_side", "zone_key", "feature_key", "provider")]
        indexes = [
            models.Index(fields=["match", "team_side"]),
            models.Index(fields=["match", "zone_key"]),
            models.Index(fields=["feature_key"]),
        ]


class MatchDisciplinaryEvent(models.Model):
    """
    Provider-normalized disciplinary event for one match.

    This keeps a stable internal card taxonomy while preserving source-specific
    identifiers and labels for auditing and future provider adapters.
    """

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="disciplinary_events")
    player = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disciplinary_events",
    )
    team_season = models.ForeignKey(
        TeamSeason,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disciplinary_events",
    )

    team_side = models.CharField(max_length=12, choices=SIDE_CHOICES, default=SIDE_UNKNOWN)
    period = models.IntegerField(default=1)
    minute = models.IntegerField(default=0)
    second = models.IntegerField(default=0)
    elapsed_seconds = models.IntegerField(default=0)

    card_type = models.CharField(max_length=24, choices=CARD_CHOICES, default=CARD_UNKNOWN)
    reason = models.CharField(max_length=80, blank=True, default="")

    provider = models.CharField(max_length=24, choices=PROVIDER_CHOICES, default=PROVIDER_STATSBOMB)
    provider_event_id = models.CharField(max_length=80, blank=True, default="")
    source_event_type = models.CharField(max_length=80, blank=True, default="")
    source_card_name = models.CharField(max_length=80, blank=True, default="")
    payload = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("match", "provider", "provider_event_id", "card_type")]
        indexes = [
            models.Index(fields=["match", "team_side"]),
            models.Index(fields=["match", "player"]),
            models.Index(fields=["match", "card_type"]),
            models.Index(fields=["provider", "source_event_type"]),
            models.Index(fields=["minute", "second"]),
        ]


class PlayerOnPitchInterval(models.Model):
    """
    Provider-normalized interval during which a player was on the pitch.

    This is the canonical temporal participation object for future event-window
    scoring and fantasy substitution logic.
    """

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="on_pitch_intervals")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="on_pitch_intervals")
    team_season = models.ForeignKey(TeamSeason, on_delete=models.PROTECT, related_name="on_pitch_intervals")

    team_side = models.CharField(max_length=12, choices=SIDE_CHOICES, default=SIDE_UNKNOWN)
    start_period = models.IntegerField(default=1)
    start_minute = models.IntegerField(default=0)
    start_second = models.IntegerField(default=0)
    start_elapsed_seconds = models.IntegerField(default=0)
    end_period = models.IntegerField(null=True, blank=True)
    end_minute = models.IntegerField(default=90)
    end_second = models.IntegerField(default=0)
    end_elapsed_seconds = models.IntegerField(default=90 * 60)

    start_reason = models.CharField(
        max_length=32,
        choices=INTERVAL_START_REASON_CHOICES,
        default=INTERVAL_UNKNOWN_START,
    )
    end_reason = models.CharField(
        max_length=32,
        choices=INTERVAL_END_REASON_CHOICES,
        default=INTERVAL_UNKNOWN_END,
    )
    source_start_reason = models.CharField(max_length=120, blank=True, default="")
    source_end_reason = models.CharField(max_length=120, blank=True, default="")
    source_position = models.CharField(max_length=80, blank=True, default="")

    provider = models.CharField(max_length=24, choices=PROVIDER_CHOICES, default=PROVIDER_STATSBOMB)
    provider_interval_id = models.CharField(max_length=120, blank=True, default="")
    payload = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("match", "player", "provider", "provider_interval_id")]
        indexes = [
            models.Index(fields=["match", "team_side"]),
            models.Index(fields=["match", "player"]),
            models.Index(fields=["match", "start_elapsed_seconds"]),
            models.Index(fields=["match", "end_elapsed_seconds"]),
            models.Index(fields=["start_reason", "end_reason"]),
        ]
