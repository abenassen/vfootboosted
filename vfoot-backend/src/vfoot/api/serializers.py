from rest_framework import serializers


class StarterBackupSerializer(serializers.Serializer):
    starter_player_id = serializers.CharField(max_length=64)
    backup_player_ids = serializers.ListField(child=serializers.CharField(max_length=64), allow_empty=True)


class SaveLineupRequestSerializer(serializers.Serializer):
    league_id = serializers.CharField(max_length=64)
    matchday_id = serializers.CharField(max_length=64)
    gk_player_id = serializers.CharField(max_length=64, allow_null=True, required=False)
    starter_player_ids = serializers.ListField(child=serializers.CharField(max_length=64), allow_empty=False)
    bench_player_ids = serializers.ListField(child=serializers.CharField(max_length=64), allow_empty=True)
    starter_backups = StarterBackupSerializer(many=True, required=False)


class LineupContextQuerySerializer(serializers.Serializer):
    league_id = serializers.CharField(max_length=64, required=False, default="L1")
    matchday_id = serializers.CharField(max_length=64, required=False, default="MD24")


class MatchesQuerySerializer(serializers.Serializer):
    league_id = serializers.CharField(max_length=64, required=False, default="L1")
    matchday_id = serializers.CharField(max_length=64, required=False, default="MD24")
