from rest_framework import serializers


class CreateLeagueSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    team_name = serializers.CharField(max_length=120)


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


class CompetitionScheduleSerializer(serializers.Serializer):
    starts_at = serializers.DateField(required=False, allow_null=True)
    ends_at = serializers.DateField(required=False, allow_null=True)
    round_mapping = serializers.DictField(required=False)


class CompetitionSchedulePreviewSerializer(serializers.Serializer):
    starts_at = serializers.DateField(required=False, allow_null=True)
    ends_at = serializers.DateField(required=False, allow_null=True)


class QualificationRuleCreateSerializer(serializers.Serializer):
    source_competition_id = serializers.IntegerField()
    source_stage = serializers.ChoiceField(choices=["halfway", "final"], default="final")
    mode = serializers.ChoiceField(choices=["table_range", "winner", "loser"])
    rank_from = serializers.IntegerField(required=False, allow_null=True)
    rank_to = serializers.IntegerField(required=False, allow_null=True)


class CompetitionStageBuildSerializer(serializers.Serializer):
    allow_repechage = serializers.BooleanField(required=False, default=False)
    random_seed = serializers.IntegerField(required=False, default=42)


class CompetitionStageCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    stage_type = serializers.ChoiceField(choices=["round_robin", "knockout"])
    order_index = serializers.IntegerField(required=False, default=1)
    team_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=True)


class CompetitionStageUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    stage_type = serializers.ChoiceField(choices=["round_robin", "knockout"], required=False)
    order_index = serializers.IntegerField(required=False)
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
    name = serializers.CharField(max_length=120, required=False, default="Main Auction")
    player_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    random_seed = serializers.IntegerField(required=False, default=42)


class PlaceBidSerializer(serializers.Serializer):
    amount = serializers.IntegerField(min_value=1)
