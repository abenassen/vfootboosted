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
    # Opaque avatar descriptor, stored on the related UserProfile. Read straight
    # off the profile if present, otherwise an empty string (never null, so the
    # frontend can treat it as a plain string).
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "username", "email", "avatar")

    def get_avatar(self, user) -> str:
        profile = getattr(user, "profile", None)
        return profile.avatar if profile else ""


class ProfileUpdateSerializer(serializers.Serializer):
    """Edits the caller's own account: display username and/or avatar. Email is
    intentionally NOT here — changing it re-opens email verification, handled
    separately when that flow exists."""

    username = serializers.CharField(max_length=150, required=False)
    # Opaque client-owned string; capped only to stop unbounded payloads.
    avatar = serializers.CharField(max_length=4000, required=False, allow_blank=True,
                                   trim_whitespace=False)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user

    def validate_username(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Username cannot be empty.")
        qs = User.objects.filter(username__iexact=value)
        if self._user is not None:
            qs = qs.exclude(pk=self._user.pk)
        if qs.exists():
            raise serializers.ValidationError("Username already exists.")
        return value


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user

    def validate_current_password(self, value: str) -> str:
        if self._user is None or not self._user.check_password(value):
            raise serializers.ValidationError("Current password is not correct.")
        return value

    def validate_new_password(self, value: str) -> str:
        validate_password(value, self._user)
        return value


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    # Mandatory and unique since accounts are confirmed by email: without a
    # deliverable, unshared address there is no way to prove ownership or to
    # recover a password.
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True, min_length=8)

    def validate_username(self, value: str) -> str:
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Username already exists.")
        return value

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Email already registered.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        validate_password(attrs["password"])
        return attrs


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True)


class VerifyEmailSerializer(serializers.Serializer):
    uid = serializers.CharField(max_length=64)
    token = serializers.CharField(max_length=128)


class ResendVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()


class GoogleAuthSerializer(serializers.Serializer):
    credential = serializers.CharField(write_only=True)
