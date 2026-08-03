from rest_framework import serializers


class CreateLeagueSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    team_name = serializers.CharField(max_length=120)
    # The real championship the league is played on. Chosen ONCE at creation and
    # then immutable: rosters, listone and calendar all depend on it.
    reference_season_id = serializers.IntegerField()
    mode = serializers.ChoiceField(choices=["aura", "classic"], required=False, default="aura")
    # Auction economy (classic). Optional at creation with the standard defaults;
    # editable from settings until the auction starts.
    initial_budget = serializers.IntegerField(required=False, min_value=1, default=1000)
    slots_gk = serializers.IntegerField(required=False, min_value=0, default=3)
    slots_def = serializers.IntegerField(required=False, min_value=0, default=8)
    slots_mid = serializers.IntegerField(required=False, min_value=0, default=8)
    slots_fwd = serializers.IntegerField(required=False, min_value=0, default=6)


class JoinLeagueSerializer(serializers.Serializer):
    invite_code = serializers.CharField(max_length=12)
    team_name = serializers.CharField(max_length=120)


class UpdateMyTeamSerializer(serializers.Serializer):
    """Edits the caller's OWN team inside one league: display name and/or crest.

    Both fields are optional so the UI can save one without touching the other —
    renaming should not silently rewrite a crest the user never opened. The crest
    is an opaque descriptor (see FantasyTeam.crest); blank means "back to the
    default drawn from the team name", which is why it is allow_blank.
    """

    name = serializers.CharField(max_length=120, required=False)
    crest = serializers.CharField(max_length=4000, required=False, allow_blank=True,
                                  trim_whitespace=False)

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Il nome della squadra non può essere vuoto.")
        return name


class UpdateMemberRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["admin", "manager"])


class MarketToggleSerializer(serializers.Serializer):
    is_open = serializers.BooleanField()


class AddRosterPlayerSerializer(serializers.Serializer):
    player_id = serializers.IntegerField()
    purchase_price = serializers.IntegerField(min_value=1, default=1)


class RemoveRosterPlayerSerializer(serializers.Serializer):
    player_id = serializers.IntegerField()


class BulkAssignRosterSerializer(serializers.Serializer):
    player_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False, required=False)
    purchase_price = serializers.IntegerField(min_value=1, default=1, required=False)
    random_seed = serializers.IntegerField(required=False, default=42)
    assignments = serializers.ListField(child=serializers.DictField(), allow_empty=False, required=False)


class CompetitionTemplateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    competition_type = serializers.ChoiceField(choices=["round_robin", "knockout"])
    team_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=True)
    starts_at = serializers.DateField(required=False, allow_null=True)
    ends_at = serializers.DateField(required=False, allow_null=True)
    container_only = serializers.BooleanField(required=False, default=False)


class CompetitionUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    status = serializers.ChoiceField(choices=["draft", "active", "done"], required=False)
    points_win = serializers.IntegerField(required=False)
    points_draw = serializers.IntegerField(required=False)
    points_loss = serializers.IntegerField(required=False)
    starts_at = serializers.DateField(required=False, allow_null=True)
    ends_at = serializers.DateField(required=False, allow_null=True)
    start_matchday = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    end_matchday = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class CompetitionScheduleSerializer(serializers.Serializer):
    starts_at = serializers.DateField(required=False, allow_null=True)
    ends_at = serializers.DateField(required=False, allow_null=True)
    # Real-matchday span over the league reference season.
    start_matchday = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    end_matchday = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    round_mapping = serializers.DictField(required=False)


class CompetitionSchedulePreviewSerializer(serializers.Serializer):
    starts_at = serializers.DateField(required=False, allow_null=True)
    ends_at = serializers.DateField(required=False, allow_null=True)
    start_matchday = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    end_matchday = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class QualificationRuleCreateSerializer(serializers.Serializer):
    source_competition_id = serializers.IntegerField()
    source_stage = serializers.ChoiceField(choices=["halfway", "final"], default="final")
    # Optional explicit round cut-off; when given it overrides source_stage
    # (e.g. "table after round 19"). min 1.
    source_round = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    mode = serializers.ChoiceField(choices=["table_range", "winner", "loser"])
    rank_from = serializers.IntegerField(required=False, allow_null=True)
    rank_to = serializers.IntegerField(required=False, allow_null=True)


# Beyond this a round-robin is longer than the real championship it is played on.
MAX_LEGS = 5


class CompetitionStageBuildSerializer(serializers.Serializer):
    allow_repechage = serializers.BooleanField(required=False, default=False)
    random_seed = serializers.IntegerField(required=False, default=42)
    legs = serializers.IntegerField(required=False, default=1, min_value=1, max_value=MAX_LEGS)


class CompetitionStageCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    stage_type = serializers.ChoiceField(choices=["round_robin", "knockout"])
    order_index = serializers.IntegerField(required=False, default=1)
    legs = serializers.IntegerField(required=False, default=1, min_value=1, max_value=MAX_LEGS)
    team_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=True)
    # How many teams a still-unresolved stage will field, so its rounds (and the
    # calendar built on them) exist before its participants do.
    expected_participants = serializers.IntegerField(required=False, allow_null=True, min_value=0)


class CompetitionStageUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    stage_type = serializers.ChoiceField(choices=["round_robin", "knockout"], required=False)
    order_index = serializers.IntegerField(required=False)
    legs = serializers.IntegerField(required=False, min_value=1, max_value=MAX_LEGS)
    team_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=True)
    expected_participants = serializers.IntegerField(required=False, min_value=0)
    random_seed = serializers.IntegerField(required=False, default=42)


class CompetitionStageRuleCreateSerializer(serializers.Serializer):
    source_stage_id = serializers.IntegerField()
    mode = serializers.ChoiceField(choices=["table_range", "winners", "losers"])
    # Table cut-off inside the source stage's competition ("dopo la giornata 7").
    source_round = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    rank_from = serializers.IntegerField(required=False, allow_null=True)
    rank_to = serializers.IntegerField(required=False, allow_null=True)
    random_seed = serializers.IntegerField(required=False, default=42)


PRIZE_STATS = ["avg_score", "goals_for", "goals_against", "best_round", "wins"]


class CompetitionPrizeCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    icon = serializers.CharField(max_length=8, required=False, allow_blank=True)
    condition_type = serializers.ChoiceField(
        choices=["final_table_range", "stage_table_range", "stage_winner", "stage_loser",
                 "stat_top", "stat_bottom"]
    )
    # Only for the two stat conditions: which measure the record is on. The
    # direction (highest / lowest) is the condition itself.
    stat = serializers.ChoiceField(choices=PRIZE_STATS, required=False, allow_blank=True)
    source_stage_id = serializers.IntegerField(required=False, allow_null=True)
    rank_from = serializers.IntegerField(required=False, allow_null=True)
    rank_to = serializers.IntegerField(required=False, allow_null=True)


class WizardQualificationSerializer(serializers.Serializer):
    source_stage_id = serializers.IntegerField()
    mode = serializers.ChoiceField(choices=["table_range", "winners", "losers"], default="table_range")
    source_round = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    rank_from = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    rank_to = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class WizardPrizeSerializer(serializers.Serializer):
    """A prize said the way the wizard says it, before there are stages to point at.

    "Chi vince" is a table position in a league and a final in a cup; the backend
    translates, so the browser never has to guess a stage id it cannot know yet.
    """

    name = serializers.CharField(max_length=120)
    icon = serializers.CharField(max_length=8, required=False, allow_blank=True)
    condition = serializers.ChoiceField(choices=["winner", "runner_up", "rank", "stat"],
                                        default="winner")
    rank_from = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    rank_to = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    # "stat" only: which record, and from which end.
    stat = serializers.ChoiceField(choices=PRIZE_STATS, required=False, allow_blank=True)
    direction = serializers.ChoiceField(choices=["top", "bottom"], required=False, default="top")


class CompetitionPointsSerializer(serializers.Serializer):
    win = serializers.IntegerField(default=3)
    draw = serializers.IntegerField(default=1)
    loss = serializers.IntegerField(default=0)


class CompetitionWizardSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    format = serializers.ChoiceField(choices=["league", "cup", "groups_knockout"])
    team_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=True)
    qualification = WizardQualificationSerializer(required=False, allow_null=True)
    legs = serializers.IntegerField(required=False, default=1, min_value=1, max_value=MAX_LEGS)
    # Turni a eliminazione: 1 = gara secca, 2 = andata e ritorno (due giornate).
    # ``final_legs`` permette il caso più comune di tutti — andata e ritorno fino
    # alla semifinale, finale in gara unica.
    knockout_legs = serializers.IntegerField(required=False, default=1, min_value=1, max_value=2)
    final_legs = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=2)
    groups = serializers.IntegerField(required=False, default=1, min_value=1, max_value=8)
    advance_per_group = serializers.IntegerField(required=False, default=2, min_value=1, max_value=8)
    points = CompetitionPointsSerializer(required=False)
    start_matchday = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    end_matchday = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    prizes = WizardPrizeSerializer(many=True, required=False)
    random_seed = serializers.IntegerField(required=False, default=42)

    def validate(self, data):
        if not data.get("qualification") and len(data.get("team_ids") or []) < 2:
            raise serializers.ValidationError(
                {"team_ids": "Scegli almeno 2 squadre, oppure una regola di qualificazione."}
            )
        return data


class CompetitionWizardPreviewSerializer(serializers.Serializer):
    format = serializers.ChoiceField(choices=["league", "cup", "groups_knockout"])
    team_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=True)
    qualification = WizardQualificationSerializer(required=False, allow_null=True)
    legs = serializers.IntegerField(required=False, default=1, min_value=1, max_value=MAX_LEGS)
    knockout_legs = serializers.IntegerField(required=False, default=1, min_value=1, max_value=2)
    final_legs = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=2)
    groups = serializers.IntegerField(required=False, default=1, min_value=1, max_value=8)
    advance_per_group = serializers.IntegerField(required=False, default=2, min_value=1, max_value=8)


class MatchdayConcludeSerializer(serializers.Serializer):
    force = serializers.BooleanField(required=False, default=False)
    # {team_id: "forfait" | "previous"} — how to score a team with no lineup for this
    # matchday (classic). Keys are team ids as strings.
    lineup_resolutions = serializers.DictField(
        child=serializers.ChoiceField(choices=["forfait", "previous"]),
        required=False,
        default=dict,
    )


class ImportRosterCSVSerializer(serializers.Serializer):
    csv_text = serializers.CharField(required=False, allow_blank=True)


class CreateAuctionSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False, default="Asta iniziale")
    # The eligible pool. Optional: when omitted the whole classic listone is used.
    player_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False, required=False)


class NominateSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=["manual", "random", "random_role"], required=False, default="random")
    # Required when mode == manual.
    player_id = serializers.IntegerField(required=False)
    # Required when mode == random_role (POR/DIF/CEN/ATT).
    role = serializers.ChoiceField(
        choices=["POR", "DIF", "CEN", "ATT"], required=False)
    # Optional determinism for the random draw (tests / reproducibility).
    random_seed = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, data):
        if data.get("mode") == "manual" and not data.get("player_id"):
            raise serializers.ValidationError({"player_id": "Obbligatorio in modalita' manuale."})
        if data.get("mode") == "random_role" and not data.get("role"):
            raise serializers.ValidationError({"role": "Obbligatorio in modalita' casuale-per-ruolo."})
        return data


class PlaceBidSerializer(serializers.Serializer):
    amount = serializers.IntegerField(min_value=1)
    # Admin-only: place the bid on behalf of another team (verbal auctions).
    team_id = serializers.IntegerField(required=False)


class AuctionAssignSerializer(serializers.Serializer):
    """Admin direct-assign shortcut: give a player to a team at a set price."""
    player_id = serializers.IntegerField()
    team_id = serializers.IntegerField()
    price = serializers.IntegerField(min_value=1)


class CreateMarketSessionSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False,
                                 default="Mercato di riparazione")
    credit_recovery_mode = serializers.ChoiceField(
        choices=["fixed", "frac30", "frac50", "frac75"], default="fixed")
    fixed_recovery_amount = serializers.IntegerField(min_value=0, required=False, default=1)
    # Scheduled end. Null/omitted = indefinite (admin opens and closes by hand).
    closes_at = serializers.DateTimeField(required=False, allow_null=True)


class PlaceOfferSerializer(serializers.Serializer):
    target_player_id = serializers.IntegerField()
    release_player_id = serializers.IntegerField()
    amount = serializers.IntegerField(min_value=1)
