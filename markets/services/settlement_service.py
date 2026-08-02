from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid5

from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from authentication.services.permission_service import PermissionService
from markets.models import (
    Market,
    MarketOrder,
    MarketPosition,
    MarketPositionSettlement,
    MarketSettlement,
)
from wallets.services.wallet_service import WalletService


class MarketSettlementService:
    APPROVE_PERMISSION = "approve_market"
    MARKET_CURRENCY = "UGX"
    PAYOUT_PER_UNIT = Decimal("1.0000")
    QUANTITY_QUANTUM = Decimal("0.0001")
    MONEY_QUANTUM = Decimal("0.0001")
    PRICE_QUANTUM = Decimal("0.00000")
    PAYOUT_NAMESPACE = UUID("69953729-07b6-4a88-a853-0e2b77d3aa3a")

    @classmethod
    @transaction.atomic
    def settle_market(cls, *, market_id, actor) -> MarketSettlement:
        cls._require_permission(actor)
        market = (
            Market.objects.select_for_update(of=("self",))
            .select_related("winning_outcome")
            .get(id=market_id)
        )

        existing = cls._existing_settlement(market)
        if existing is not None:
            return existing

        cls._require_settleable_market(market)
        cls._lock_and_require_no_outstanding_orders(market)
        positions = cls._lock_positions(market)
        cls._require_no_position_reservations(positions)

        positive_positions = [
            position for position in positions if position.quantity > Decimal("0.0000")
        ]
        winners = [
            position
            for position in positive_positions
            if position.outcome_id == market.winning_outcome_id
        ]
        winning_quantity = cls._quantity(
            sum((position.quantity for position in winners), Decimal("0.0000"))
        )
        total_payout = cls._money(winning_quantity * cls.PAYOUT_PER_UNIT)

        settlement = MarketSettlement.objects.create(
            market=market,
            winning_outcome=market.winning_outcome,
            payout_per_unit=cls.PAYOUT_PER_UNIT,
            settlement_currency=cls.MARKET_CURRENCY,
            total_position_count=len(positive_positions),
            winning_position_count=len(winners),
            losing_position_count=len(positive_positions) - len(winners),
            total_winning_quantity=winning_quantity,
            total_payout_amount=total_payout,
            executed_by=actor,
        )

        for position in positive_positions:
            cls._settle_position(
                settlement=settlement,
                market=market,
                position=position,
            )

        return settlement

    @classmethod
    def _settle_position(cls, *, settlement, market, position) -> None:
        quantity = cls._quantity(position.quantity)
        cost_basis = cls._money(position.total_cost)
        was_winner = position.outcome_id == market.winning_outcome_id
        payout_amount = (
            cls._money(quantity * cls.PAYOUT_PER_UNIT) if was_winner else Decimal("0.0000")
        )
        realized_delta = cls._money(payout_amount - cost_basis)
        ledger_entry = None

        if payout_amount > Decimal("0.0000"):
            ledger_entry = WalletService.credit(
                user=position.user,
                currency=cls.MARKET_CURRENCY,
                amount=payout_amount,
                idempotency_reference=cls.payout_idempotency_reference(
                    market_id=market.id,
                    position_id=position.id,
                    winning_outcome_id=market.winning_outcome_id,
                    payout_per_unit=cls.PAYOUT_PER_UNIT,
                ),
                market=market,
            )

        MarketPositionSettlement.objects.create(
            market_settlement=settlement,
            market_position=position,
            participant=position.user,
            outcome=position.outcome,
            was_winner=was_winner,
            settled_quantity=quantity,
            payout_per_unit=cls.PAYOUT_PER_UNIT,
            payout_amount=payout_amount,
            cost_basis=cost_basis,
            realized_pnl_delta=realized_delta,
            wallet_ledger_entry=ledger_entry,
        )

        position.quantity = Decimal("0.0000")
        position.reserved_quantity = Decimal("0.0000")
        position.average_entry_price = Decimal("0.00000")
        position.total_cost = Decimal("0.0000")
        position.realized_pnl = cls._money(position.realized_pnl + realized_delta)
        position.save(
            update_fields=[
                "quantity",
                "reserved_quantity",
                "average_entry_price",
                "total_cost",
                "realized_pnl",
                "updated_at",
            ]
        )

    @classmethod
    def payout_idempotency_reference(
        cls, *, market_id, position_id, winning_outcome_id, payout_per_unit
    ):
        stable_value = ":".join(
            (
                "market-settlement-v1",
                str(market_id),
                str(position_id),
                str(winning_outcome_id),
                format(Decimal(str(payout_per_unit)), ".4f"),
            )
        )
        return uuid5(cls.PAYOUT_NAMESPACE, stable_value)

    @staticmethod
    def _existing_settlement(market):
        return (
            MarketSettlement.objects.select_related("market", "winning_outcome", "executed_by")
            .filter(market=market)
            .first()
        )

    @classmethod
    def _require_permission(cls, actor):
        if not PermissionService.has_permission(actor, cls.APPROVE_PERMISSION):
            raise PermissionDenied("You do not have the approve_market permission.")

    @staticmethod
    def _require_settleable_market(market):
        errors = {}
        if market.status != Market.Status.RESOLVED:
            errors["status"] = "Only a resolved market can be settled."
        if not market.winning_outcome_id:
            errors["winning_outcome"] = "A confirmed winning outcome is required."
        elif market.winning_outcome.market_id != market.id:
            errors["winning_outcome"] = "The winning outcome must belong to the market."
        if errors:
            raise ValidationError(errors)

    @staticmethod
    def _lock_and_require_no_outstanding_orders(market):
        outstanding = list(
            MarketOrder.objects.select_for_update(of=("self",))
            .filter(
                market=market,
                status__in=(MarketOrder.Status.OPEN, MarketOrder.Status.PARTIALLY_FILLED),
            )
            .order_by("id")
            .values_list("id", flat=True)
        )
        if outstanding:
            raise ValidationError(
                {
                    "commitments": (
                        "Outstanding trading commitments must be cleared before settlement."
                    )
                }
            )

    @staticmethod
    def _lock_positions(market):
        return list(
            MarketPosition.objects.select_for_update(of=("self",))
            .select_related("user", "outcome")
            .filter(market=market)
            .order_by("id")
        )

    @staticmethod
    def _require_no_position_reservations(positions):
        if any(position.reserved_quantity > Decimal("0.0000") for position in positions):
            raise ValidationError(
                {
                    "commitments": (
                        "Outstanding trading commitments must be cleared before settlement."
                    )
                }
            )

    @classmethod
    def _quantity(cls, value):
        return Decimal(value).quantize(cls.QUANTITY_QUANTUM, rounding=ROUND_HALF_UP)

    @classmethod
    def _money(cls, value):
        return Decimal(value).quantize(cls.MONEY_QUANTUM, rounding=ROUND_HALF_UP)
