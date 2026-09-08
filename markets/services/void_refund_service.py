from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid5

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from authentication.services.permission_service import PermissionService
from markets.models import (
    Market,
    MarketCollateralEntry,
    MarketCollateralPool,
    MarketFeeLedgerEntry,
    MarketOrder,
    MarketPosition,
    MarketPositionVoidRefund,
    MarketSettlement,
    MarketVoidOrderCancellation,
    MarketVoidRefund,
)
from markets.services.fee_service import MarketFeeService
from markets.services.market_notification_service import MarketNotificationService
from markets.services.participation_service import MarketParticipationService
from markets.services.provisional_result_service import (
    MarketProvisionalResultService,
)
from markets.services.result_dispute_service import (
    MarketResultDisputeService,
)
from wallets.models import WalletTransaction
from wallets.services.wallet_service import WalletService


class MarketVoidRefundService:
    APPROVE_PERMISSION = "approve_market"
    MARKET_CURRENCY = MarketParticipationService.MARKET_CURRENCY
    QUANTITY_QUANTUM = Decimal("0.0001")
    MONEY_QUANTUM = Decimal("0.0001")
    POSITION_REFUND_NAMESPACE = UUID("869ce764-f25c-4ba9-b998-cb27027898fc")

    @classmethod
    @transaction.atomic
    def refund_void_market(cls, *, market_id, actor) -> MarketVoidRefund:
        cls._require_permission(actor)
        market = (
            Market.objects.select_for_update(of=("self",))
            .select_related("winning_outcome")
            .get(id=market_id)
        )

        existing = cls._existing_refund(market)
        if existing is not None:
            return existing
        if MarketSettlement.objects.filter(market=market).exists():
            raise ValidationError(
                {"finalization": "A normally settled market cannot be void-refunded."}
            )
        cls._require_refundable_market(market)
        MarketProvisionalResultService.require_dispute_window_closed(market)
        MarketResultDisputeService.require_no_open_disputes(market)

        orders = cls._lock_orders(market)
        positions = cls._lock_positions(market)
        refund = MarketVoidRefund.objects.create(
            market=market,
            refund_currency=cls.MARKET_CURRENCY,
            executed_by=actor,
        )

        buy_count = 0
        sell_count = 0
        released_buy = Decimal("0.0000")
        released_sell = Decimal("0.0000")
        for order in orders:
            result = MarketParticipationService.cancel_locked_order(order=order)
            cancellation = MarketVoidOrderCancellation.objects.create(
                market_void_refund=refund,
                market_order=order,
                order_side=order.side,
                remaining_quantity_cancelled=cls._quantity(result["remaining_quantity"]),
                released_wallet_reservation_amount=cls._money(result["released_wallet_amount"]),
                released_position_reservation_quantity=cls._quantity(
                    result["released_position_quantity"]
                ),
                wallet_release_ledger_entry=result["wallet_entry"],
            )
            MarketNotificationService.schedule(
                recipient=order.user,
                category="MARKET_ORDERS",
                event_type="MARKET_VOID_ORDER_CANCELLED",
                title="Order cancelled for void market",
                message=(
                    f"The remaining quantity {cancellation.remaining_quantity_cancelled} "
                    "was cancelled."
                ),
                key=f"market-void-cancellation:{cancellation.id}",
                market_id=market.id,
                data={
                    "cancellation_id": str(cancellation.id),
                    "remaining_quantity": str(cancellation.remaining_quantity_cancelled),
                },
            )
            if order.side == MarketOrder.Side.BUY:
                buy_count += 1
                released_buy += result["released_wallet_amount"]
            else:
                sell_count += 1
                released_sell += result["released_position_quantity"]

        # SELL cancellation locks and updates position rows. Reload the already
        # locked set so validation and refunding use those current values.
        positions = cls._lock_positions(market)
        cls._require_consistent_positions(positions)
        positive_positions = [
            position for position in positions if position.quantity > Decimal("0.0000")
        ]
        refunded_quantity = Decimal("0.0000")
        refunded_amount = Decimal("0.0000")
        for position in positive_positions:
            quantity = cls._quantity(position.quantity)
            cost_basis = cls._money(position.total_cost)
            fee_schedule, fee_rates = MarketFeeService.rates(market=market)
            refund_fee = MarketFeeService.calculate_fee(cost_basis, fee_rates["refund"])
            net_refund = cost_basis - refund_fee
            ledger_entry = None
            if net_refund > Decimal("0.0000"):
                refund_reference = cls.position_refund_idempotency_reference(
                    market_id=market.id,
                    position_id=position.id,
                    participant_id=position.user_id,
                    cost_basis=cost_basis,
                    currency=cls.MARKET_CURRENCY,
                )
                wallet_transaction = WalletTransaction.objects.create(
                    wallet=WalletService.get_or_create_wallet(position.user, cls.MARKET_CURRENCY),
                    reference=str(refund_reference),
                    transaction_type=WalletTransaction.TransactionType.VOID_REFUND,
                    amount=net_refund,
                    currency=cls.MARKET_CURRENCY,
                    status=WalletTransaction.Status.COMPLETED,
                    completed_at=timezone.now(),
                    description=f"Void refund — {market.question}",
                )
                ledger_entry = WalletService.credit(
                    user=position.user,
                    currency=cls.MARKET_CURRENCY,
                    amount=net_refund,
                    idempotency_reference=refund_reference,
                    market=market,
                    transaction=wallet_transaction,
                )
            if cost_basis > Decimal("0.0000"):
                MarketFeeService.record_fee(
                    parent_id=position.id,
                    market=market,
                    participant=position.user,
                    fee_type=MarketFeeLedgerEntry.FeeType.REFUND,
                    rate_bps=fee_rates["refund"],
                    gross=cost_basis,
                    schedule=fee_schedule,
                )

            position_refund = MarketPositionVoidRefund.objects.create(
                market_void_refund=refund,
                market_position=position,
                participant=position.user,
                outcome=position.outcome,
                refunded_quantity=quantity,
                cost_basis=cost_basis,
                refund_amount=cost_basis,
                refund_fee_amount=refund_fee,
                net_refund_amount=net_refund,
                realized_pnl_delta=Decimal("0.0000"),
                wallet_credit_ledger_entry=ledger_entry,
            )
            MarketNotificationService.refund(position_refund)
            position.quantity = Decimal("0.0000")
            position.reserved_quantity = Decimal("0.0000")
            position.total_cost = Decimal("0.0000")
            position.average_entry_price = Decimal("0.00000")
            position.save(
                update_fields=[
                    "quantity",
                    "reserved_quantity",
                    "total_cost",
                    "average_entry_price",
                    "updated_at",
                ]
            )
            refunded_quantity += quantity
            refunded_amount += cost_basis

        totals = {
            "total_cancelled_order_count": len(orders),
            "cancelled_buy_order_count": buy_count,
            "cancelled_sell_order_count": sell_count,
            "total_released_buy_reservation_amount": cls._money(released_buy),
            "total_released_sell_reservation_quantity": cls._quantity(released_sell),
            "refunded_position_count": len(positive_positions),
            "total_refunded_position_quantity": cls._quantity(refunded_quantity),
            "total_position_refund_amount": cls._money(refunded_amount),
        }
        MarketVoidRefund.objects.filter(pk=refund.pk).update(**totals)
        for field, value in totals.items():
            setattr(refund, field, value)
        pool = MarketCollateralPool.objects.select_for_update().filter(market=market).first()
        if pool is not None and pool.locked_collateral > Decimal("0.0000"):
            released = cls._money(pool.locked_collateral)
            pool.locked_collateral = Decimal("0.0000")
            pool.released_collateral += released
            pool.status = MarketCollateralPool.Status.RELEASED
            pool.save(
                update_fields=["locked_collateral", "released_collateral", "status", "updated_at"]
            )
            MarketCollateralEntry.objects.create(
                pool=pool,
                market=market,
                entry_type=MarketCollateralEntry.EntryType.VOID_RELEASE,
                amount=released,
                idempotency_reference=uuid5(refund.id, "collateral-void-release"),
                actor=actor,
                metadata={"position_refund_amount": str(totals["total_position_refund_amount"])},
            )
        return refund

    @classmethod
    def position_refund_idempotency_reference(
        cls, *, market_id, position_id, participant_id, cost_basis, currency
    ):
        stable_value = ":".join(
            (
                "market-void-refund-v1",
                str(market_id),
                str(position_id),
                str(participant_id),
                format(cls._money(cost_basis), ".4f"),
                str(currency).upper(),
            )
        )
        return uuid5(cls.POSITION_REFUND_NAMESPACE, stable_value)

    @classmethod
    def _require_permission(cls, actor):
        if not PermissionService.has_permission(actor, cls.APPROVE_PERMISSION):
            raise PermissionDenied("You do not have the approve_market permission.")

    @staticmethod
    def _existing_refund(market):
        return (
            MarketVoidRefund.objects.select_related("market", "executed_by")
            .filter(market=market)
            .first()
        )

    @staticmethod
    def _require_refundable_market(market):
        errors = {}
        if market.status != Market.Status.VOIDED:
            errors["status"] = "Only a voided market can be refunded."
        if market.winning_outcome_id:
            errors["winning_outcome"] = "A voided market cannot have a winning outcome."
        if errors:
            raise ValidationError(errors)

    @staticmethod
    def _lock_orders(market):
        return list(
            MarketOrder.objects.select_for_update(of=("self",))
            .select_related("user", "market", "outcome")
            .filter(
                market=market,
                status__in=(MarketOrder.Status.OPEN, MarketOrder.Status.PARTIALLY_FILLED),
            )
            .order_by("id")
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
    def _require_consistent_positions(positions):
        for position in positions:
            errors = {}
            if position.quantity < Decimal("0.0000"):
                errors["quantity"] = "Position quantity cannot be negative."
            if position.total_cost < Decimal("0.0000"):
                errors["total_cost"] = "Position total cost cannot be negative."
            if position.reserved_quantity > position.quantity:
                errors["reserved_quantity"] = (
                    "Reserved quantity cannot exceed the position quantity."
                )
            if position.quantity == Decimal("0.0000") and (
                position.total_cost != Decimal("0.0000")
                or position.reserved_quantity != Decimal("0.0000")
            ):
                errors["position"] = "A zero position cannot retain cost or reservations."
            if errors:
                raise ValidationError(errors)

    @classmethod
    def _quantity(cls, value):
        return Decimal(value).quantize(cls.QUANTITY_QUANTUM, rounding=ROUND_HALF_UP)

    @classmethod
    def _money(cls, value):
        return Decimal(value).quantize(cls.MONEY_QUANTUM, rounding=ROUND_HALF_UP)
