from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password


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


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email")


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True, min_length=8)

    def validate_username(self, value: str) -> str:
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username already exists.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        validate_password(attrs["password"])
        return attrs


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True)
