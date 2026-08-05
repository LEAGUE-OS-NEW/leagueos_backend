from rest_framework import serializers

from markets.models import KYCVerificationSession


class KYCStartSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(max_length=128)
    verification_level = serializers.CharField(max_length=50, default="STANDARD")


class KYCSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = KYCVerificationSession
        fields = (
            "id",
            "provider_code",
            "status",
            "provider_status",
            "verification_level",
            "initiated_at",
            "expires_at",
            "completed_at",
            "last_event_at",
            "continuation_url",
            "failure_code",
            "status_message",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class KYCCallbackResponseSerializer(serializers.Serializer):
    accepted = serializers.BooleanField()
    duplicate = serializers.BooleanField()
    status = serializers.CharField()
