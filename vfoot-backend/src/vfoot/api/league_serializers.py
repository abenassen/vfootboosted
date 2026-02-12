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


class CompetitionUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    status = serializers.ChoiceField(choices=["draft", "active", "done"], required=False)
    points_win = serializers.IntegerField(required=False)
    points_draw = serializers.IntegerField(required=False)
    points_loss = serializers.IntegerField(required=False)


class QualificationRuleCreateSerializer(serializers.Serializer):
    source_competition_id = serializers.IntegerField()
    source_stage = serializers.ChoiceField(choices=["halfway", "final"], default="final")
    mode = serializers.ChoiceField(choices=["table_range", "winner", "loser"])
    rank_from = serializers.IntegerField(required=False, allow_null=True)
    rank_to = serializers.IntegerField(required=False, allow_null=True)


class ImportRosterCSVSerializer(serializers.Serializer):
    csv_text = serializers.CharField(required=False, allow_blank=True)


class CreateAuctionSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False, default="Main Auction")
    player_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    random_seed = serializers.IntegerField(required=False, default=42)


class PlaceBidSerializer(serializers.Serializer):
    amount = serializers.IntegerField(min_value=1)
