"""Serializers for Finance Admin wallet workflows."""

from rest_framework import serializers

from wallets.models import WithdrawalRequest


class AdminWithdrawalReadSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    wallet_id = serializers.UUIDField()
    user_id = serializers.UUIDField(
        source="wallet.user_id",
        read_only=True,
    )
    user_email = serializers.SerializerMethodField()

    amount = serializers.DecimalField(
        max_digits=16,
        decimal_places=4,
    )
    currency = serializers.SerializerMethodField()
    destination = serializers.JSONField()

    status = serializers.CharField()
    risk_status = serializers.CharField()
    risk_reasons = serializers.JSONField()

    approval_mode = serializers.CharField()
    approval_policy_version = serializers.CharField()
    approved_at = serializers.DateTimeField(
        allow_null=True,
    )
    approved_by_id = serializers.UUIDField(
        allow_null=True,
    )
    approved_by_email = serializers.SerializerMethodField()

    rejection_reason = serializers.CharField()
    failure_reason = serializers.CharField()

    transaction_id = serializers.UUIDField(
        allow_null=True,
    )
    transaction_status = serializers.SerializerMethodField()
    provider_reference = serializers.SerializerMethodField()

    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_user_email(self, withdrawal: WithdrawalRequest) -> str:
        return withdrawal.wallet.user.email

    def get_currency(self, withdrawal: WithdrawalRequest) -> str:
        return withdrawal.wallet.currency

    def get_approved_by_email(self, withdrawal: WithdrawalRequest) -> str | None:
        if withdrawal.approved_by_id is None:
            return None

        return withdrawal.approved_by.email

    def get_transaction_status(self, withdrawal: WithdrawalRequest) -> str | None:
        if withdrawal.transaction_id is None:
            return None

        return withdrawal.transaction.status

    def get_provider_reference(self, withdrawal: WithdrawalRequest) -> str:
        if withdrawal.transaction_id is None:
            return ""

        return withdrawal.transaction.provider_reference


class AdminWithdrawalReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
        max_length=1000,
    )


class AdminWithdrawalCompleteSerializer(serializers.Serializer):
    provider_reference = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
        max_length=255,
    )


class AdminWithdrawalFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=WithdrawalRequest.Status.choices,
        required=False,
    )
    currency = serializers.CharField(
        max_length=3,
        required=False,
    )
    created_from = serializers.DateTimeField(
        required=False,
    )
    created_to = serializers.DateTimeField(
        required=False,
    )

    def validate(self, attrs):
        created_from = attrs.get("created_from")
        created_to = attrs.get("created_to")

        if created_from and created_to and created_from > created_to:
            raise serializers.ValidationError(
                {"created_from": ("Must be earlier than or equal " "to created_to.")}
            )

        currency = attrs.get("currency")
        if currency:
            attrs["currency"] = currency.strip().upper()

        return attrs
