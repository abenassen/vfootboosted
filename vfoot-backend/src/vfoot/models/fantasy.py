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
    # Max bench substitutions applied when scoring a matchday (classic: an s.v.
    # starter is replaced by the first eligible bench player in priority order, up
    # to this many times). League-configurable by the admin; fantacalcio default 5.
    max_substitutions = models.PositiveSmallIntegerField(default=5)
    # Defence modifier (classic): a reward for fielding a strong, deep defence.
    # Awarded only to a defence at least four strong — WHICH four is the gate below.
    DEF_BONUS_ADD_OWN = "add_own"
    DEF_BONUS_SUB_OPP = "subtract_opponent"
    DEF_BONUS_MODE_CHOICES = [
        (DEF_BONUS_ADD_OWN, "Aggiunto alla propria squadra"),
        (DEF_BONUS_SUB_OPP, "Sottratto alla squadra avversaria"),
    ]
    # WHICH lineup has to hold four defenders. The two readings are both defensible
    # and neither is a variant of the other, so the league says which one it plays:
    #
    # * "starters" — the lineup AS SENT. Four defenders from the first minute or no
    #   modifier: what is rewarded is having committed to a back four, and a back
    #   four arrived at because a midfielder was s.v. was never a commitment.
    # * "effective" — the lineup AS IT ENDED, substitutions included, counting the
    #   defenders who actually took a vote. What is rewarded is the defence that
    #   played, however it was arrived at — and, by the same token, a back four that
    #   lost a man to an s.v. nobody could cover does not collect it.
    DEF_GATE_STARTERS = "starters"
    DEF_GATE_EFFECTIVE = "effective"
    DEF_BONUS_GATE_CHOICES = [
        (DEF_GATE_STARTERS, "Formazione schierata (4 difensori dal 1')"),
        (DEF_GATE_EFFECTIVE, "Formazione acquisita (4 difensori con voto)"),
    ]
    defense_bonus_enabled = models.BooleanField(default=True)
    defense_bonus_mode = models.CharField(
        max_length=20, choices=DEF_BONUS_MODE_CHOICES, default=DEF_BONUS_ADD_OWN)
    defense_bonus_gate = models.CharField(
        max_length=10, choices=DEF_BONUS_GATE_CHOICES, default=DEF_GATE_STARTERS)
    # Voto d'ufficio sui BUCHI: un titolare senza voto che la panchina non e'
    # riuscita a coprire vale questo, invece di non valere niente. 0 = spento (il
    # default, cioe' la regola classica: chi gioca in dieci somma dieci voti).
    #
    # E' un voto d'ufficio come quelli dell'OfficeOverride, e si comporta come
    # loro: entra nel totale E nell'aritmetica del modificatore difesa — che per un
    # portiere mancante e' l'unico modo di avere un numero da mettere nella media —
    # ma non regala mai il clean sheet, perche' nessuno ha giocato quella partita.
    #
    # Serve soprattutto ai portieri: senza un secondo portiere schierabile il buco
    # costa il voto pieno E il modificatore, e a meta' stagione capita per motivi
    # che non dipendono da come si e' schierato.
    sv_office_vote = models.FloatField(default=0.0)
    # Optional "clean sheet" modifier (classic): +1 to the team total when the
    # effective goalkeeper played (has a vote) and conceded no goals. Off by default;
    # the defence modifier is the only one enabled out of the box.
    keeper_clean_sheet_enabled = models.BooleanField(default=False)
    # When True (the real-league default), a lineup locks. Turn OFF for test leagues
    # played on an ALREADY FINISHED season, where every kickoff is in the past and
    # would block editing.
    enforce_lineup_deadline = models.BooleanField(default=True)
    # WHAT locks, once the deadline is enforced. Two leagues can play the same
    # calendar under two different deadlines and neither is a variant of the other:
    #
    # * "matchday" — the whole lineup freezes at the round's FIRST confirmed
    #   kickoff. One deadline for everybody, the fantacalcio tradition: you commit
    #   to eleven names before a single ball is kicked.
    # * "own" — the whole lineup freezes at the first kickoff of a match involving
    #   one of the manager's OWN players, all twenty-five of them and not only the
    #   eleven. The tradition without its one arbitrary edge: a Friday match in
    #   which you have nobody is not your business. When you save, none of your
    #   players has a vote yet — a benched player who had already played would have
    #   his vote on the board while you could still field, and that vote would
    #   become a choice, which is why the count is over the roster and not the XI.
    #   The default.
    # * "player" — each player freezes when HIS OWN club kicks off, and the rest of
    #   the lineup stays editable until the round's LAST kickoff. A manager whose
    #   striker plays on Monday can still decide about him on Sunday night. What it
    #   must never allow is un-deciding someone whose match is under way, which is
    #   why the check is "did this player's placement change", not "is the round
    #   open". It is the only mode in which a manager can choose KNOWING part of
    #   the votes, and the only one that needs the extra rules (no overtaking a
    #   frozen player, defenders first on the bench).
    LOCK_MATCHDAY = "matchday"
    LOCK_OWN = "own"
    LOCK_PLAYER = "player"
    LOCK_MODE_CHOICES = [
        (LOCK_MATCHDAY, "Al primo calcio d'inizio della giornata"),
        (LOCK_OWN, "Alla prima partita di un tuo giocatore"),
        (LOCK_PLAYER, "Ogni giocatore all'inizio della sua partita"),
    ]
    lineup_lock_mode = models.CharField(
        max_length=10, choices=LOCK_MODE_CHOICES, default=LOCK_OWN)
    # Fattore campo: quanto vale giocare in casa, in punti di fantavoto aggiunti
    # alla squadra di casa. 0 = spento (il default: e' un modificatore in piu', non
    # una regola del fantacalcio).
    #
    # Si applica SOLO dove giocare in casa vuol dire qualcosa, e chi lo decide non
    # e' questa impostazione ma la singola partita (``FantasyFixture.home_advantage``):
    # un girone di sola andata, o la tornata dispari di un campionato, non hanno un
    # campo — assegnare li' un bonus regalerebbe punti a chi capita sorteggiato in
    # casa. La lega dice QUANTO vale; il calendario dice DOVE vale.
    home_advantage_bonus = models.FloatField(default=0.0)
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
    # Opaque, client-composed crest descriptor — same deal as UserProfile.avatar:
    # the SPA owns the schema and draws the SVG, the server only stores and echoes
    # it. Deliberately NOT an ImageField: uploads would mean files to serve, back
    # up and deploy, and the dev-db release (a bare SQLite dump) would hand out
    # rows pointing at images nobody has. Empty => the UI falls back to a crest
    # seeded from the team name.
    crest = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("league", "name")]

    def __str__(self) -> str:
        return self.name


class FantasyRosterSlot(models.Model):
    """Un contratto: chi, per quale squadra, da quando, a quanto — e, se e' finito,
    fino a quando e con quanto incassato.

    Le quattro date/cifre bastano a ricostruire rosa E budget di un allenatore a
    una data qualunque della stagione, senza nessun saldo accumulato altrove: la
    rosa a T sono i contratti aperti a T, il budget e' quello iniziale meno quel
    che pesa ancora piu' quel che si e' bruciato per strada.
    """

    team = models.ForeignKey(FantasyTeam, on_delete=models.CASCADE, related_name="roster_slots")
    player = models.ForeignKey(Player, on_delete=models.PROTECT, related_name="fantasy_rosters")
    acquired_at = models.DateTimeField(default=timezone.now)
    released_at = models.DateTimeField(null=True, blank=True)
    purchase_price = models.IntegerField(default=1)
    # Lo scambio da cui questo contratto nasce (o in cui e' finito), se ce n'e'
    # uno. Serve alla bacheca: uno scambio si racconta come uno scambio, e senza
    # questo i due contratti nuovi comparivano anche come acquisti — cioe' come
    # crediti spesi, che in uno scambio non e' quello che e' successo.
    from_trade = models.ForeignKey(
        "vfoot.PlayerTrade", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="slots")
    # Quanto e' rientrato in cassa chiudendo il contratto. Null finche' e' aperto.
    #
    # Senza questo campo il recupero non esisteva: il budget si ricalcola dai soli
    # contratti aperti, quindi chiudendone uno tornavano indietro TUTTI i crediti
    # pagati, qualunque cifra fosse stata pattuita. Il mercato a offerte applicava
    # il tetto giusto al momento dell'offerta e poi, alla validazione, restituiva
    # la differenza dal nulla (comprato a 100, recupero pattuito 1: la squadra ci
    # guadagnava 99). Non e' vincolato a essere <= purchase_price: rivendere in
    # guadagno e' normale, e qui l'admin trascrive un accordo presso fuori.
    sale_price = models.IntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["team", "released_at"])]


class FantasyCompetition(models.Model):
    TYPE_ROUND_ROBIN = "round_robin"
    TYPE_KNOCKOUT = "knockout"

    # How the competition was SHAPED, which ``competition_type`` cannot express:
    # a group stage followed by a bracket is round-robin AND knockout at once, and
    # a hand-built graph is neither. Purely descriptive — the generators read the
    # stages, never this — but it is what lets the UI say "campionato" vs "coppa"
    # and decide which edits still make sense after creation.
    FORMAT_LEAGUE = "league"
    FORMAT_CUP = "cup"
    FORMAT_GROUPS_KNOCKOUT = "groups_knockout"
    FORMAT_CUSTOM = "custom"

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
    format = models.CharField(
        max_length=24,
        choices=[
            (FORMAT_LEAGUE, "Campionato"),
            (FORMAT_CUP, "Coppa a eliminazione"),
            (FORMAT_GROUPS_KNOCKOUT, "Gironi + eliminazione"),
            (FORMAT_CUSTOM, "Personalizzata"),
        ],
        default=FORMAT_CUSTOM,
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
    # The PLAN: {"<competition round>": <real matchday>}. Written when the calendar
    # is computed (uniform spread, then admin fine-tuning) and read back whenever
    # fixtures appear. Keeping it here rather than only on the fixtures is what lets
    # a competition whose participants are still unknown — a cup fed by the table
    # after round 7 — already have a calendar: the rounds exist as a plan long
    # before there is a single fixture to hang a matchday on.
    round_calendar = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    # Quando la competizione e' finita davvero: la data della giornata che l'ha
    # chiusa, non l'istante in cui il codice se n'e' accorto. Scritta una volta,
    # dalla conclusione, insieme ai premi. E' anche la bandiera che evita di
    # richiedersi "sara' finita?" a ogni apertura di pagina: `status` dice se,
    # questa dice quando.
    completed_at = models.DateTimeField(null=True, blank=True)

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
    # Stages with the SAME order_index are played in PARALLEL (two groups running
    # side by side) and therefore share round numbers; a higher order_index means
    # "after", and its rounds are numbered after the previous ones.
    order_index = models.IntegerField(default=1)
    # Round-robin only: how many times the full set of pairings is played
    # ("tornate"). 1 = sola andata, 2 = andata e ritorno, 3+ = a Serie-A-length
    # season out of few teams. Home and away swap on every even leg. Ignored for
    # knockout.
    legs = models.IntegerField(default=1)
    # Round numbering is COMPETITION-wide (the calendar, the "table after round N"
    # rules and the fixture uniqueness all key on it), so each stage starts after
    # the ones before it. Derived — recompute_round_layout() owns this field.
    round_offset = models.IntegerField(default=0)
    # How many competition rounds this stage occupies, and with how many teams —
    # known from the plan even before a rule-fed stage has resolved a single
    # participant, which is what lets its calendar be laid out in advance.
    planned_rounds = models.IntegerField(default=1)
    expected_participants = models.IntegerField(default=0)
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
    # The source may live in ANOTHER competition of the same league: this single
    # relation is how "the top 4 of the championship after round 7 enter the cup"
    # and "the winners of the semifinals play the final" are both expressed.
    source_stage = models.ForeignKey(CompetitionStage, on_delete=models.CASCADE, related_name="rules_out")
    mode = models.CharField(
        max_length=16,
        choices=[(MODE_TABLE_RANGE, "Table Range"), (MODE_WINNERS, "Winners"), (MODE_LOSERS, "Losers")],
        default=MODE_WINNERS,
    )
    # Table cut-off, as a round number of the SOURCE stage's competition. Null =
    # the stage's final table. This is what makes "primi 4 alla giornata 7" a
    # different thing from "primi 4 a fine campionato".
    source_round = models.IntegerField(null=True, blank=True)
    rank_from = models.IntegerField(null=True, blank=True)
    rank_to = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)


class FantasyMatchday(models.Model):
    """One real matchday as the LEAGUE's ledger sees it.

    Three states, and the middle one is the whole point. ``planned`` is waiting its
    turn; ``concluded`` has been scored and counts. ``awaiting`` is the admin saying
    "a real match of this round has not been played yet (a postponement) — the league
    moves on, this one stays open and will be scored when the recovery is played".
    Without it the ledger pointer is a single file: one incomplete round and every
    round behind it is stuck, which in Serie A 2025-26 would have frozen a league for
    four weeks (matchday 16, four matches recovered on 14-15 January).

    Note this is the LEDGER only. What is being played, what can still be fielded and
    when the market is frozen are read from the real calendar (see
    ``services/matchday_state.py``) and never wait for an admin to click anything.
    """

    STATUS_PLANNED = "planned"
    STATUS_AWAITING = "awaiting"
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
        choices=[(STATUS_PLANNED, "Planned"), (STATUS_AWAITING, "Awaiting"),
                 (STATUS_CONCLUDED, "Concluded")],
        default=STATUS_PLANNED,
    )
    # Set when the admin parks the matchday to let the league advance past it.
    awaiting_since = models.DateTimeField(null=True, blank=True)
    awaiting_reason = models.CharField(max_length=200, blank=True, default="")
    # Last time we nudged the admin about this matchday waiting to be concluded.
    # A stamp, not a counter: it exists so the reminder repeats at a decent interval
    # instead of once per tick.
    nudged_at = models.DateTimeField(null=True, blank=True)
    concluded_at = models.DateTimeField(null=True, blank=True)
    concluded_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="concluded_fantasy_matchdays",
    )
    # The classic ruleset frozen at conclusion (Ruleset.to_snapshot): max_substitutions,
    # defence on/mode, keeper clean sheet, rules_version. Read back by the manual
    # recompute so a concluded matchday stays interpretable even if the league's live
    # settings change afterwards. Empty until the matchday is scored by the classic engine.
    ruleset_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("league", "real_competition_season", "real_matchday")]
        indexes = [models.Index(fields=["league", "status"]), models.Index(fields=["real_competition_season", "real_matchday"])]
        ordering = ["real_matchday", "id"]


class OfficeOverride(models.Model):
    """League-scoped 'voto d'ufficio': an IMPOSED VOTE for a real match the league
    has decided not to wait for (typically a postponement).

    Each league decides independently: one may impose the 6 on Como-Milan of 21
    December while another waits for the 15 January recovery, and neither sees the
    other's choice — which is why this is keyed on (league, match) and touches no
    real-data table.

    Deliberately a SCALAR, not fabricated data. An earlier design gave outfield
    players a global-mean zone vector and goalkeepers a neutral goals-prevented
    figure; that would have injected into the database something shaped exactly like
    a measurement and, from there, into every average, exposure and model that reads
    zones. An office vote is not a datum, it is a ruling: it enters the scoring at
    the level of the vote, gets no bonus/malus (no events happened), and applies to
    goalkeepers through the same door as everyone else — their goals-prevented
    channel is simply not consulted.
    """

    league = models.ForeignKey(FantasyLeague, on_delete=models.CASCADE, related_name="office_overrides")
    # Context: which fantasy matchday this override belongs to (for listing/UI).
    fantasy_matchday = models.ForeignKey(
        FantasyMatchday, on_delete=models.CASCADE, related_name="office_overrides"
    )
    # The real match whose data is replaced. Players appearing in this match (per
    # roster / lineup) get the office substitute instead of their real performance.
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="office_overrides")

    # The imposed vote. It is both the voto puro and the fantavoto of every player of
    # this match: with no game played there is no goal, no assist and no card to add.
    # 6.0 is the conventional "d'ufficio", but a league is free to rule otherwise.
    voto = models.FloatField(default=6.0)

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
    roles. The global ``Player.classic_role_seed`` (live from TM) only SEEDS this snapshot;
    admin overrides live here, scoped to the league.
    """

    SOURCE_SEED = "seed"      # snapshotted from Player.classic_role_seed (TM-derived)
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


class CurrentPlayerRole(models.Model):
    """The CURRENT resolved classic role of each player — ONE row per player.

    Sits between the raw provider seed (``Player.classic_role_seed``) and a
    league's frozen ``LeaguePlayerRole``: the k-means inference is expensive, so
    it is computed once (``manage.py compute_classic_roles``) and cached here, and
    every league created at that moment snapshots from the same evidence. There is
    deliberately NO season dimension — a role is the current best estimate, not a
    per-season record; recomputing (on a fresh scrape) overwrites it in place, and
    leagues that need permanence freeze their own copy.

    Both variants are stored, not just the chosen one, so a league can be created
    under either policy without re-running anything — and so the two can be
    compared and audited after the fact.
    """

    METHOD_CATEGORY = "category"   # measured: we know how he played
    METHOD_TM = "tm"               # provider position, unambiguous
    METHOD_SOFA = "sofa"           # too few minutes to cluster, but SofaScore's
                                   # coarse lineup position (F/M/D) disambiguates
    METHOD_DEFAULT = "default"     # no data at all: positional fallback
    METHOD_UNKNOWN = "unknown"
    METHOD_CHOICES = [(METHOD_CATEGORY, "Categoria misurata"), (METHOD_TM, "Posizione TM"),
                      (METHOD_SOFA, "Posizione SofaScore"),
                      (METHOD_DEFAULT, "Default posizionale"), (METHOD_UNKNOWN, "Ignoto")]

    player = models.OneToOneField(Player, on_delete=models.CASCADE,
                                  related_name="current_role")
    # Human-readable playing style ("ala offensiva"), empty when unmeasured.
    category = models.CharField(max_length=40, blank=True, default="")
    # How firmly he belongs to that category (co-association with its core).
    confidence = models.FloatField(default=0.0)
    # How far the FANTASY ROLE we assign him leads the best rival (-1..1). This, not
    # ``confidence``, is what the admin is asked to review: bouncing between two
    # styles that condense to the same role is harmless, being split across the
    # CEN/ATT line is not. Negative where the runs contradict the role we assign,
    # which is a doubt like any other and reads as one. 1.0 when the role did not
    # come from the clustering.
    role_margin = models.FloatField(default=1.0)
    # The same question asked in the feature space: how close he sits to a
    # category of ANOTHER role, as a ratio of the distance to his own. Above
    # BOUNDARY_REVIEW he is on the CEN/ATT line even when the runs agreed — the
    # co-association matrix the margin is read from averages that border away.
    # 0.0 when the role did not come from the clustering.
    role_boundary = models.FloatField(default=0.0)
    role_data = models.CharField(max_length=3, blank=True, default="")
    role_mitigated = models.CharField(max_length=3, blank=True, default="")
    method = models.CharField(max_length=10, choices=METHOD_CHOICES,
                              default=METHOD_UNKNOWN)
    tm_position = models.CharField(max_length=40, blank=True, default="")
    computed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["method"])]

    def role_for(self, mode: str) -> str:
        return self.role_data if mode == "data" else self.role_mitigated

    def __str__(self) -> str:
        return f"player {self.player_id}: {self.role_mitigated}"


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
    # Not a position but a record: the highest (or lowest) value of one measure
    # over the whole competition. "Media punteggio piu' alta", "miglior attacco",
    # "peggior difesa" — the honours a league invents for itself, which a table
    # position cannot express and which are the ones people actually argue about.
    CONDITION_STAT_TOP = "stat_top"
    CONDITION_STAT_BOTTOM = "stat_bottom"

    STAT_AVG_SCORE = "avg_score"
    STAT_GOALS_FOR = "goals_for"
    STAT_GOALS_AGAINST = "goals_against"
    STAT_BEST_ROUND = "best_round"
    STAT_WINS = "wins"
    STATS = [
        (STAT_AVG_SCORE, "Media punteggio"),
        (STAT_GOALS_FOR, "Gol fatti"),
        (STAT_GOALS_AGAINST, "Gol subiti"),
        (STAT_BEST_ROUND, "Miglior punteggio in una giornata"),
        (STAT_WINS, "Vittorie"),
    ]

    competition = models.ForeignKey(FantasyCompetition, on_delete=models.CASCADE, related_name="prizes")
    name = models.CharField(max_length=120)
    # A single emoji standing in for the trophy. Cheap identity now; a drawn crest
    # (like the team ones) can replace it later without touching the condition.
    icon = models.CharField(max_length=8, blank=True, default="🏆")
    condition_type = models.CharField(
        max_length=24,
        choices=[
            (CONDITION_FINAL_TABLE_RANGE, "Final table range"),
            (CONDITION_STAGE_TABLE_RANGE, "Stage table range"),
            (CONDITION_STAGE_WINNER, "Stage winner"),
            (CONDITION_STAGE_LOSER, "Stage loser"),
            (CONDITION_STAT_TOP, "Highest of a measure"),
            (CONDITION_STAT_BOTTOM, "Lowest of a measure"),
        ],
        default=CONDITION_FINAL_TABLE_RANGE,
    )
    # Which measure, for the two conditions above. The DIRECTION is the condition
    # and not part of the name on purpose: "miglior difesa" and "peggior difesa"
    # read the same number from opposite ends, and a league that wants the joke
    # prize should not need a second measure to get it.
    stat = models.CharField(max_length=24, blank=True, default="", choices=STATS)
    # CASCADE, not PROTECT: a prize and the stage that decides it are cascaded
    # together when their competition goes, and PROTECT made that deletion
    # impossible at the database level — a cup with a "chi vince la finale" prize
    # could not be deleted at all. Stages referenced by prizes in OTHER
    # competitions are still guarded, in the delete views, where the check can say
    # which prize is in the way instead of raising an integrity error.
    source_stage = models.ForeignKey(
        CompetitionStage,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="awarded_prizes",
    )
    rank_from = models.IntegerField(null=True, blank=True)
    rank_to = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["id"]


class AwardedPrize(models.Model):
    """Un premio VINTO: il momento in cui una regola e' diventata un fatto.

    ``CompetitionPrize`` e' la regola ("chi arriva primo"); questa riga e' la
    conseguenza ("l'ha vinto la Juve, il 23 maggio"). Sono due cose diverse e
    prima erano una sola: il vincitore veniva ricalcolato dai risultati a OGNI
    lettura — 287 ms per l'apertura della home, 403 per un albo d'oro, e in
    crescita con la carriera del fantallenatore, perche' rileggeva i tabellini di
    ogni competizione di ogni lega in cui avesse mai giocato.

    QUANDO SI SCRIVE. Alla conclusione della competizione, tutti insieme: un
    premio appartiene alla competizione, quindi e' la sua fine ad assegnarlo,
    anche quando il vincitore era matematicamente gia' deciso (il primo di un
    girone). Una regola sola, un momento solo, facile da raccontare.

    QUANDO SI RISCRIVE. Se una rettifica cambia i risultati a competizione
    chiusa, i premi si ricontrollano e il cambiamento si DICE. Il rischio di un
    dato salvato non e' che esista: e' che nessuno lo aggiorni.
    """

    prize = models.ForeignKey(CompetitionPrize, on_delete=models.CASCADE, related_name="awarded")
    team = models.ForeignKey(FantasyTeam, on_delete=models.CASCADE, related_name="honours")
    # La data del REGISTRO — la conclusione della giornata che ha deciso il premio
    # — non l'istante in cui questa riga e' stata scritta. Cosi' un riempimento
    # fatto oggi su una stagione dell'anno scorso non data i trofei a oggi.
    awarded_at = models.DateTimeField(null=True, blank=True)
    # CHI era, quel giorno. Nome e stemma copiati al momento dell'assegnazione,
    # non letti dalla squadra quando qualcuno apre l'albo d'oro.
    #
    # Nome e stemma di una FantasyTeam si cambiano quando si vuole, dalla pagina
    # rose; leggerli al volo vuol dire che ribattezzarsi riscrive il passato, e
    # che la coppa vinta a maggio compare oggi con lo stemma di adesso. Un albo
    # d'oro e' un registro storico: il resto della riga (la data, il premio) e'
    # gia' congelato, e non c'era ragione perche' la squadra non lo fosse.
    #
    # Vuoti sulle righe scritte prima che questi campi esistessero; li' si
    # ricade sulla squadra viva, che e' esattamente la risposta di prima.
    team_name = models.CharField(max_length=120, blank=True, default="")
    team_crest = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        # Un premio puo' avere piu' vincitori (una fascia di posizioni, un primato
        # a pari merito): la coppia e' unica, non il premio.
        unique_together = [("prize", "team")]
        indexes = [models.Index(fields=["team"])]


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
    # Giocare in casa, qui, conta? Deciso quando la partita viene generata e non
    # ricavabile dopo: dipende da come e' fatto il turno, non da chi ci gioca.
    #
    # * andata e ritorno (turno a eliminazione a due gare, tornata pari di un
    #   girone): si', ognuno ospita una volta e il campo e' un vantaggio simmetrico;
    # * gara secca, o la tornata dispari in piu' di un campionato: NO, campo
    #   neutro. Chi ospita e' stato deciso dal sorteggio, e un bonus li' sarebbe
    #   un regalo a sorte.
    #
    # Il valore del bonus e' della lega (``FantasyLeague.home_advantage_bonus``);
    # questo campo dice soltanto se c'e' un campo di cui tener conto.
    home_advantage = models.BooleanField(default=False)

    # Real match source used to score this fantasy fixture in simulation
    source_real_match = models.ForeignKey(Match, on_delete=models.SET_NULL, null=True, blank=True, related_name="mapped_fantasy_fixtures")

    # La serie di rigori che ha deciso questa sfida, tiro per tiro. Sta sulla
    # gara che l'ha chiusa (il ritorno, o la gara secca) ed e' scritta UNA volta,
    # quando la sfida viene risolta. Non si ricalcola leggendo il tabellone: e'
    # deterministica, quindi ricalcolarla darebbe sempre lo stesso risultato, e
    # allora tanto vale non rifarla. Null = non ci sono stati rigori.
    shootout = models.JSONField(null=True, blank=True)

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
    # NESSUNO L'HA VOLUTO. Fuori dal giro, ma non venduto: il caso normale di
    # un'asta, non un errore. Si distingue da "cancelled" per una ragione sola e
    # concreta: un annullamento rimette il giocatore nel sacchetto e il sorteggio
    # può ripescarlo (era la correzione di una chiamata sbagliata, e deve poter
    # tornare), mentre uno che nessuno vuole ripescato non lo deve essere — o si
    # ripropone all'infinito lo stesso giocatore che la stanza ha già scartato.
    # Resta chiamabile a mano, che è come si recupera se qualcuno ci ripensa.
    STATUS_UNSOLD = "unsold"

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
        choices=[(STATUS_OPEN, "Open"), (STATUS_CLOSED, "Closed"),
                 (STATUS_CANCELLED, "Cancelled"), (STATUS_UNSOLD, "Invenduto")],
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
        constraints = [
            # UNA SOLA CHIAMATA APERTA PER ASTA, garantita dal database.
            #
            # La vista che chiama un giocatore il controllo lo faceva gia', ma
            # leggendo e poi scrivendo dentro la transazione: con UN banditore e'
            # irraggiungibile, con DUE amministratori che premono «Chiama» nello
            # stesso istante no. Su Postgres in READ COMMITTED tutte e due le
            # transazioni leggono «nessuna chiamata aperta» — nessuna delle due
            # vede l'inserimento dell'altra prima della commit — e inseriscono.
            #
            # Il danno non sarebbe stato un errore ma un silenzio: lo stato mostra
            # `_open_nomination()`, cioe' la PRIMA, e la seconda resterebbe aperta
            # per sempre, tenendo fuori dal sorteggio un giocatore che nessuno sta
            # piu' chiamando. Piu' amministratori per lega sono previsti apposta
            # (MemberRoleUpdateView), quindi non e' un caso di scuola.
            #
            # Chiuso, chiamata annullata e invenduto restano liberi di essere
            # quanti sono: la condizione tiene dentro solo `open`.
            models.UniqueConstraint(
                fields=["session"],
                condition=models.Q(status="open"),
                name="uniq_open_nomination_per_session",
            )
        ]
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
    TYPE_NOMINATION_UNSOLD = "nomination_unsold"  # chiamato, nessuna offerta, si va avanti
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


# --- Repair market: offer-based sessions on free agents (classic) ------------
# The post-auction transfer window. The admin opens a session; managers place
# credit offers on free agents (players in the listone not on any active roster),
# each pledging to release one of their own players of the SAME classic role. An
# offer that leads its target for 24h without a higher rebid is promoted to
# "accepted" and queued; the admin then applies the roster swap. See
# docs/offer_market_plan.md.

class MarketSession(models.Model):
    STATUS_OPEN = "open"          # accepting offers, timers running
    STATUS_SUSPENDED = "suspended"  # frozen: no new offers, no promotions
    STATUS_CLOSED = "closed"      # finished; history stays visible
    STATUS_CHOICES = [
        (STATUS_OPEN, "Aperta"), (STATUS_SUSPENDED, "Sospesa"), (STATUS_CLOSED, "Chiusa"),
    ]

    # How credits are recovered when a manager releases a player as part of an
    # offer. Fixed amount, or a fraction of the price he originally paid for the
    # released player (rounded UP), frozen for the whole session.
    RECOVERY_FIXED = "fixed"
    RECOVERY_FRAC30 = "frac30"
    RECOVERY_FRAC50 = "frac50"
    RECOVERY_FRAC75 = "frac75"
    RECOVERY_CHOICES = [
        (RECOVERY_FIXED, "Credito fisso"),
        (RECOVERY_FRAC30, "30% del prezzo d'acquisto"),
        (RECOVERY_FRAC50, "50% del prezzo d'acquisto"),
        (RECOVERY_FRAC75, "75% del prezzo d'acquisto"),
    ]

    league = models.ForeignKey(
        FantasyLeague, on_delete=models.CASCADE, related_name="market_sessions")
    name = models.CharField(max_length=120, default="Mercato di riparazione")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_OPEN)
    # Apertura PROGRAMMATA. Nel futuro = sessione annunciata ma non ancora
    # cominciata: si vede, si guarda chi e' libero, non si offre. L'admin la
    # fissa per poterla annunciare alla lega prima che cominci.
    opens_at = models.DateTimeField(default=timezone.now)
    # Scheduled end. Null = indefinite: the admin opens and closes it by hand.
    closes_at = models.DateTimeField(null=True, blank=True)
    credit_recovery_mode = models.CharField(
        max_length=10, choices=RECOVERY_CHOICES, default=RECOVERY_FIXED)
    # Only meaningful when credit_recovery_mode == fixed.
    fixed_recovery_amount = models.PositiveSmallIntegerField(default=1)
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="created_market_sessions")
    created_at = models.DateTimeField(default=timezone.now)
    # I FATTI accanto ai piani: `opens_at`/`closes_at` sono quel che l'admin ha
    # annunciato, `opened_at`/`closed_at` quel che e' davvero successo. Serve
    # anche all'apertura stessa, che porta con se' un aggiornamento del listone:
    # senza un segno che sia gia' avvenuta si rifarebbe a ogni richiesta.
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # At most one live (open or suspended) session per league.
            models.UniqueConstraint(
                fields=["league"],
                condition=models.Q(status__in=["open", "suspended"]),
                name="uniq_live_market_session_per_league",
            )
        ]
        indexes = [models.Index(fields=["league", "status"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.league_id}/{self.status})"

    def is_pending(self, now=None) -> bool:
        """Programmata: l'ora di apertura non e' ancora arrivata."""
        return (self.status == self.STATUS_OPEN
                and self.opens_at is not None
                and self.opens_at > (now or timezone.now()))


class MarketOffer(models.Model):
    STATUS_LEADING = "leading"    # current top offer for its target; timer runs
    STATUS_OUTBID = "outbid"      # superseded by a higher offer on the same target
    STATUS_ACCEPTED = "accepted"  # reached deadline (or admin picked it); awaits roster apply
    STATUS_SETTLED = "settled"    # admin applied the roster swap
    STATUS_REJECTED = "rejected"  # admin rejected it
    STATUS_CANCELLED = "cancelled"  # session closed before resolution / admin cancelled
    STATUS_CHOICES = [
        (STATUS_LEADING, "In testa"), (STATUS_OUTBID, "Superata"),
        (STATUS_ACCEPTED, "Accettata"), (STATUS_SETTLED, "Conclusa"),
        (STATUS_REJECTED, "Rifiutata"), (STATUS_CANCELLED, "Annullata"),
    ]
    # Statuses that still commit ("reserve") credits and hold a roster pledge.
    LIVE_STATUSES = (STATUS_LEADING, STATUS_ACCEPTED)

    session = models.ForeignKey(
        MarketSession, on_delete=models.CASCADE, related_name="offers")
    team = models.ForeignKey(
        FantasyTeam, on_delete=models.CASCADE, related_name="market_offers")
    target_player = models.ForeignKey(
        Player, on_delete=models.PROTECT, related_name="market_offers_in")
    release_player = models.ForeignKey(
        Player, on_delete=models.PROTECT, related_name="market_offers_out")
    amount = models.IntegerField()
    # Credits recovered from releasing release_player, snapshot at offer time
    # under the session's recovery mode (recovery depends on the price paid, which
    # is stable, but we store it so history renders without recomputation).
    recovery_amount = models.IntegerField(default=0)
    role = models.CharField(max_length=8)  # shared classic role of target & release
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_LEADING)
    # now + 24h when this offer becomes leading; a higher rebid mints a new leading
    # offer with a fresh deadline, so the countdown is effectively per-target.
    deadline_at = models.DateTimeField()
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="resolved_market_offers")
    # Roster slots touched when the swap is applied, for audit/undo.
    acquire_slot = models.ForeignKey(
        FantasyRosterSlot, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="from_market_offer")

    class Meta:
        indexes = [
            models.Index(fields=["session", "status"]),
            models.Index(fields=["session", "target_player", "status"]),
            models.Index(fields=["team", "status"]),
        ]

    def __str__(self) -> str:
        return f"offer#{self.id} {self.amount} for {self.target_player_id} ({self.status})"


class MarketEvent(models.Model):
    """Append-only feed/audit of a market session (mirrors AuctionEvent)."""

    TYPE_SESSION_CREATED = "session_created"
    TYPE_SESSION_OPENED = "session_opened"      # apertura programmata scattata
    TYPE_SESSION_SUSPENDED = "session_suspended"
    TYPE_SESSION_RESUMED = "session_resumed"
    TYPE_SESSION_CLOSED = "session_closed"
    TYPE_OFFER_PLACED = "offer_placed"
    TYPE_OFFER_OUTBID = "offer_outbid"
    TYPE_OFFER_ACCEPTED = "offer_accepted"      # promoted at deadline
    TYPE_OFFER_SETTLED = "offer_settled"        # roster swap applied
    TYPE_OFFER_REJECTED = "offer_rejected"
    TYPE_OFFER_CANCELLED = "offer_cancelled"
    # L'offerta di sotto rimessa in testa dopo che l'admin ha tolto il rilancio
    # che l'aveva superata (v. market_engine.restore_previous_offer).
    TYPE_OFFER_RESTORED = "offer_restored"

    session = models.ForeignKey(
        MarketSession, on_delete=models.CASCADE, related_name="events")
    offer = models.ForeignKey(
        MarketOffer, on_delete=models.SET_NULL, null=True, blank=True, related_name="events")
    event_type = models.CharField(max_length=32)
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="market_events")
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["session", "created_at"])]
        ordering = ["-created_at", "-id"]


class PlayerTrade(models.Model):
    """Uno scambio fra due allenatori, scritto come UN gesto solo.

    Nasce ribaltando una decisione presa quando il mercato a offerte fu costruito
    (v. il commento sopra le operazioni di rosa in ``api/league_views.py``): «uno
    scambio si scrive come una vendita di qua e un acquisto di la'». Si puo' fare,
    ma a mano si perdono tre cose che qui contano — il PREZZO che viaggia col
    giocatore, la contropartita in crediti, e le formazioni aperte da riparare
    dalle due parti nello stesso istante.

    Il prezzo che viaggia e' il punto. Il contratto si chiude a incasso pieno di
    qua e se ne apre uno identico di la': Yildiz comprato a 50 arriva alla nuova
    squadra *a 50*, quindi se un domani lo svincola in una sessione col recupero
    al 50% ne riprende 25 — la plusvalenza resta di chi l'ha fatta. Rivenderlo
    all'altro come un acquisto qualunque avrebbe riscritto quel prezzo.

    Il ``payload`` e' una fotografia denormalizzata (nomi, prezzi, ruoli) come
    quella di ``MarketEvent``: la bacheca racconta lo scambio da qui invece di
    rimettere insieme quattro contratti e indovinare che erano lo stesso gesto.
    """

    league = models.ForeignKey(
        FantasyLeague, on_delete=models.CASCADE, related_name="player_trades")
    team_a = models.ForeignKey(
        FantasyTeam, on_delete=models.CASCADE, related_name="trades_as_a")
    team_b = models.ForeignKey(
        FantasyTeam, on_delete=models.CASCADE, related_name="trades_as_b")
    payload = models.JSONField(default=dict)
    note = models.CharField(max_length=200, blank=True, default="")
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="created_trades")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["league", "created_at"])]
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"trade#{self.id} {self.team_a_id}<->{self.team_b_id}"


class BudgetGrant(models.Model):
    """Crediti che l'admin concede (o toglie) fuori dall'asta e dal mercato.

    E' l'unica cosa che il budget NON puo' leggere dai contratti: la dote che si
    da' alla lega prima di una sessione di mercato non e' un acquisto ne' una
    cessione, non lascia traccia in nessuna rosa, e senza una riga sua dovrebbe
    stare in un saldo accumulato — cioe' proprio il numero che ``team_budgets``
    evita di tenere (v. il suo modulo). Qui il saldo resta una somma di fatti:

        remaining = initial_budget + concessioni - contratti aperti - buchi chiusi

    ``amount`` puo' essere negativo: una concessione sbagliata si corregge, e
    togliere crediti e' una cosa che un admin fa per davvero.

    ``batch`` tiene insieme le righe nate dallo stesso gesto — «50 a tutti» sono
    dieci righe e una notizia sola. ``trade`` marca invece la contropartita in
    crediti di uno scambio, che in bacheca si racconta dentro lo scambio e non
    come un regalo a se' stante.
    """

    team = models.ForeignKey(
        FantasyTeam, on_delete=models.CASCADE, related_name="budget_grants")
    amount = models.IntegerField()
    reason = models.CharField(max_length=200, blank=True, default="")
    batch = models.CharField(max_length=32, db_index=True)
    trade = models.ForeignKey(
        PlayerTrade, on_delete=models.CASCADE, null=True, blank=True,
        related_name="cash_legs")
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="granted_budgets")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["team", "created_at"])]
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"grant {self.amount:+d} -> {self.team_id}"
