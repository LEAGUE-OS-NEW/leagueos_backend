from rest_framework import serializers

from markets.models import (
    MarketFeeSchedule,
    MarketFinancialAdjustment,
    MarketFinancialAdjustmentLine,
    MarketOrder,
    MarketReconciliationMismatch,
    MarketReconciliationRun,
)


class FeeScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketFeeSchedule
        fields = (
            "id",
            "market",
            "version",
            "status",
            "maker_fee_bps",
            "taker_fee_bps",
            "settlement_fee_bps",
            "refund_fee_bps",
            "effective_at",
            "created_by",
            "activated_by",
            "activated_at",
            "retired_by",
            "retired_at",
            "created_at",
        )
        read_only_fields = (
            "id",
            "version",
            "status",
            "created_by",
            "activated_by",
            "activated_at",
            "retired_by",
            "retired_at",
            "created_at",
        )


class FeePreviewSerializer(serializers.Serializer):
    outcome_id = serializers.UUIDField()
    side = serializers.ChoiceField(choices=MarketOrder.Side.choices)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    limit_price = serializers.DecimalField(max_digits=6, decimal_places=5)
    time_in_force = serializers.ChoiceField(
        choices=MarketOrder.TimeInForce.choices,
        default=MarketOrder.TimeInForce.GTC,
    )
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class FeePreviewResponseSerializer(serializers.Serializer):
    estimated_order_notional = serializers.DecimalField(max_digits=20, decimal_places=4)
    estimated_maximum_buyer_reservation = serializers.DecimalField(max_digits=20, decimal_places=4)
    estimated_maker_fee = serializers.DecimalField(max_digits=20, decimal_places=4)
    estimated_taker_fee = serializers.DecimalField(max_digits=20, decimal_places=4)
    schedule_id = serializers.UUIDField(allow_null=True)
    schedule_version = serializers.IntegerField()
    currency = serializers.CharField()
    role_statement = serializers.CharField()


class ReconciliationStartSerializer(serializers.Serializer):
    market_id = serializers.UUIDField(required=False)
    wallet_id = serializers.UUIDField(required=False)
    run_date = serializers.DateField(required=False)


class ReconciliationRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketReconciliationRun
        fields = "__all__"
        read_only_fields = tuple(field.name for field in MarketReconciliationRun._meta.fields)


class ReconciliationMismatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketReconciliationMismatch
        fields = "__all__"
        read_only_fields = tuple(field.name for field in MarketReconciliationMismatch._meta.fields)


class AdjustmentLineInputSerializer(serializers.Serializer):
    wallet_id = serializers.UUIDField()
    direction = serializers.ChoiceField(choices=MarketFinancialAdjustmentLine.Direction.choices)
    amount = serializers.DecimalField(max_digits=20, decimal_places=4)


class AdjustmentProposalSerializer(serializers.Serializer):
    reason = serializers.CharField()
    evidence_reference = serializers.CharField()
    currency = serializers.CharField(max_length=3, default="UGX")
    market = serializers.UUIDField(required=False, allow_null=True)
    mismatch = serializers.UUIDField(required=False, allow_null=True)
    lines = AdjustmentLineInputSerializer(many=True)


class AdjustmentLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketFinancialAdjustmentLine
        fields = (
            "id",
            "wallet",
            "direction",
            "amount",
            "idempotency_reference",
            "wallet_ledger_entry",
        )


class AdjustmentSerializer(serializers.ModelSerializer):
    lines = AdjustmentLineSerializer(many=True, read_only=True)

    class Meta:
        model = MarketFinancialAdjustment
        fields = (
            "id",
            "reason",
            "evidence_reference",
            "currency",
            "market",
            "mismatch",
            "proposed_by",
            "status",
            "executed_at",
            "created_at",
            "lines",
        )
        read_only_fields = fields


class AdjustmentDecisionSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True)
