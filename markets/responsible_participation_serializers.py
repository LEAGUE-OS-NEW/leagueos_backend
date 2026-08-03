from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from markets.models import MarketResponsibleParticipationEvent


class LimitsSerializer(serializers.Serializer):
    max_order_notional = serializers.DecimalField(
        20, 4, allow_null=True, required=False, min_value=0
    )
    daily_buy_notional_limit = serializers.DecimalField(
        20, 4, allow_null=True, required=False, min_value=0
    )
    weekly_buy_notional_limit = serializers.DecimalField(
        20, 4, allow_null=True, required=False, min_value=0
    )
    max_open_buy_commitment = serializers.DecimalField(
        20, 4, allow_null=True, required=False, min_value=0
    )
    max_market_exposure = serializers.DecimalField(
        20, 4, allow_null=True, required=False, min_value=0
    )
    max_total_exposure = serializers.DecimalField(
        20, 4, allow_null=True, required=False, min_value=0
    )
    max_cumulative_realized_loss = serializers.DecimalField(
        20, 4, allow_null=True, required=False, min_value=0
    )


class ResponsibleStatusSerializer(serializers.Serializer):
    limits = LimitsSerializer()
    utilization = serializers.DictField()
    cooling_off_until = serializers.DateTimeField(allow_null=True)
    cooling_off_active = serializers.BooleanField()
    self_exclusion_until = serializers.DateTimeField(allow_null=True)
    self_exclusion_active = serializers.BooleanField()
    self_excluded_indefinitely = serializers.BooleanField()
    administrative_block_active = serializers.BooleanField()
    buy_allowed = serializers.BooleanField()
    sell_allowed = serializers.BooleanField()
    participation_allowed = serializers.BooleanField()
    buy_reason_codes = serializers.ListField(child=serializers.CharField())
    sell_reason_codes = serializers.ListField(child=serializers.CharField())
    next_actions = serializers.ListField(child=serializers.CharField())
    evaluated_at = serializers.DateTimeField()


class DurationSerializer(serializers.Serializer):
    duration = serializers.ChoiceField(choices=("ONE_HOUR", "ONE_DAY", "SEVEN_DAYS", "THIRTY_DAYS"))


class SelfExclusionSerializer(serializers.Serializer):
    duration = serializers.ChoiceField(
        choices=("ONE_DAY", "SEVEN_DAYS", "THIRTY_DAYS", "NINETY_DAYS", "INDEFINITE")
    )


class ResponsibleEventSerializer(serializers.ModelSerializer):
    actor = serializers.UUIDField(source="actor_id", read_only=True)

    class Meta:
        model = MarketResponsibleParticipationEvent
        fields = (
            "id",
            "participant",
            "actor",
            "event_type",
            "previous_state",
            "new_state",
            "reason",
            "created_at",
        )
        read_only_fields = fields


class ParticipantResponsibleEventSerializer(serializers.ModelSerializer):
    previous_state = serializers.SerializerMethodField()
    new_state = serializers.SerializerMethodField()

    @staticmethod
    def _public_state(value):
        return {key: item for key, item in value.items() if key != "administrative_block_reason"}

    @extend_schema_field(serializers.DictField)
    def get_previous_state(self, obj):
        return self._public_state(obj.previous_state)

    @extend_schema_field(serializers.DictField)
    def get_new_state(self, obj):
        return self._public_state(obj.new_state)

    class Meta:
        model = MarketResponsibleParticipationEvent
        fields = ("id", "event_type", "previous_state", "new_state", "created_at")
        read_only_fields = fields


class AdminResponsibleUpdateSerializer(LimitsSerializer):
    administrative_block_until = serializers.DateTimeField(allow_null=True, required=False)
    cooling_off_until = serializers.DateTimeField(allow_null=True, required=False)
    self_exclusion_until = serializers.DateTimeField(allow_null=True, required=False)
    self_excluded_indefinitely = serializers.BooleanField(required=False)
    administrative_block_reason = serializers.CharField(required=False, allow_blank=True)
    reason = serializers.CharField(write_only=True, allow_blank=False, trim_whitespace=True)


class ParticipantLimitsUpdateSerializer(LimitsSerializer):
    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({"code": "PARTICIPANT_LIMIT_UPDATE_REQUIRED"})
        if any(value is None for value in attrs.values()):
            raise serializers.ValidationError({"code": "PARTICIPANT_LIMIT_CLEAR_NOT_ALLOWED"})
        return attrs


class AdminResponsibleStatusSerializer(ResponsibleStatusSerializer):
    participant_id = serializers.UUIDField()
    administrative_block_until = serializers.DateTimeField(allow_null=True)
    administrative_block_reason = serializers.CharField(allow_blank=True)
    reviewed_by = serializers.UUIDField(allow_null=True)
    reviewed_at = serializers.DateTimeField(allow_null=True)


class ResponsibleOrderBlockedResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
    code = serializers.CharField()
    allowed = serializers.BooleanField()
    reason_codes = serializers.ListField(child=serializers.CharField())
    next_actions = serializers.ListField(child=serializers.CharField())
    utilization = serializers.DictField()
