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


class CompetitionStageBuildSerializer(serializers.Serializer):
    allow_repechage = serializers.BooleanField(required=False, default=False)
    random_seed = serializers.IntegerField(required=False, default=42)
    double_round = serializers.BooleanField(required=False, default=False)


class CompetitionStageCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    stage_type = serializers.ChoiceField(choices=["round_robin", "knockout"])
    order_index = serializers.IntegerField(required=False, default=1)
    double_round = serializers.BooleanField(required=False, default=False)
    team_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=True)


class CompetitionStageUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    stage_type = serializers.ChoiceField(choices=["round_robin", "knockout"], required=False)
    order_index = serializers.IntegerField(required=False)
    double_round = serializers.BooleanField(required=False)
    team_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=True)
    random_seed = serializers.IntegerField(required=False, default=42)


class CompetitionStageRuleCreateSerializer(serializers.Serializer):
    source_stage_id = serializers.IntegerField()
    mode = serializers.ChoiceField(choices=["table_range", "winners", "losers"])
    rank_from = serializers.IntegerField(required=False, allow_null=True)
    rank_to = serializers.IntegerField(required=False, allow_null=True)
    random_seed = serializers.IntegerField(required=False, default=42)


class CompetitionPrizeCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    condition_type = serializers.ChoiceField(
        choices=["final_table_range", "stage_table_range", "stage_winner", "stage_loser"]
    )
    source_stage_id = serializers.IntegerField(required=False, allow_null=True)
    rank_from = serializers.IntegerField(required=False, allow_null=True)
    rank_to = serializers.IntegerField(required=False, allow_null=True)


class MatchdayConcludeSerializer(serializers.Serializer):
    force = serializers.BooleanField(required=False, default=False)


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
