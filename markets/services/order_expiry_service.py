from decimal import Decimal
from uuid import uuid5

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from markets.models import (
    MarketOrder,
    MarketOrderExpiryAudit,
    MarketPosition,
)
from markets.services.market_notification_service import MarketNotificationService
from markets.services.order_financials import (
    calculate_buy_commitment,
)
from wallets.services.wallet_service import WalletService


class MarketOrderExpiryService:
    MARKET_CURRENCY = "UGX"

    EXPIRABLE_STATUSES = {
        MarketOrder.Status.OPEN,
        MarketOrder.Status.PARTIALLY_FILLED,
    }

    @classmethod
    def expire_due_orders(cls, *, limit: int = 100) -> list[MarketOrderExpiryAudit]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 1000:
            raise ValidationError({"limit": "Limit must be an integer between 1 and 1000."})

        due_ids = list(
            MarketOrder.objects.filter(
                time_in_force=MarketOrder.TimeInForce.GTD,
                status__in=cls.EXPIRABLE_STATUSES,
                expires_at__lte=timezone.now(),
            )
            .order_by("expires_at", "created_at", "id")
            .values_list("id", flat=True)[:limit]
        )
        return [
            cls.expire_order(
                order_id=order_id,
                source=MarketOrderExpiryAudit.Source.SYSTEM,
                reason="GTD order deadline elapsed.",
            )
            for order_id in due_ids
        ]

    @classmethod
    @transaction.atomic
    def expire_order(
        cls,
        *,
        order_id,
        source: str,
        reason: str,
        actor=None,
    ) -> MarketOrderExpiryAudit:
        order = cls._get_locked_order(order_id)

        existing_audit = (
            MarketOrderExpiryAudit.objects.select_related(
                "market_order",
                "wallet_release_ledger_entry",
                "actor",
            )
            .filter(
                market_order=order,
            )
            .first()
        )

        if existing_audit is not None:
            return existing_audit

        normalized_reason = cls._validate_request(
            order=order,
            source=source,
            reason=reason,
            actor=actor,
        )

        current_time = timezone.now()

        cls._require_due_order(
            order=order,
            current_time=current_time,
        )

        previous_status = order.status
        remaining_quantity = order.quantity - order.filled_quantity

        if remaining_quantity <= Decimal("0.0000"):
            raise ValidationError(
                {"quantity": ("An order without an unfilled " "remainder cannot expire.")}
            )

        wallet_entry = None
        released_wallet_amount = Decimal("0.0000")
        released_position_quantity = Decimal("0.0000")

        if order.side == MarketOrder.Side.BUY:
            released_wallet_amount = calculate_buy_commitment(
                quantity=remaining_quantity,
                limit_price=order.limit_price,
                maximum_fee_bps=order.maximum_fee_bps,
            )

            wallet_entry = WalletService.release(
                user=order.user,
                currency=cls.MARKET_CURRENCY,
                amount=released_wallet_amount,
                idempotency_reference=uuid5(
                    order.id,
                    "expiry-release",
                ),
                market=order.market,
                order=order,
            )
        else:
            position = cls._get_locked_position(order)

            if position.reserved_quantity < remaining_quantity:
                raise ValidationError(
                    {
                        "position": (
                            "The reserved position quantity "
                            "is smaller than the unfilled "
                            "order remainder."
                        )
                    }
                )

            position.reserved_quantity -= remaining_quantity
            position.full_clean()
            position.save(
                update_fields=[
                    "reserved_quantity",
                    "updated_at",
                ]
            )

            released_position_quantity = remaining_quantity

        order.status = MarketOrder.Status.EXPIRED
        order.expired_at = current_time
        order.full_clean()
        order.save(
            update_fields=[
                "status",
                "expired_at",
                "updated_at",
            ]
        )

        audit = MarketOrderExpiryAudit(
            market_order=order,
            source=source,
            previous_status=previous_status,
            expired_quantity=remaining_quantity,
            released_wallet_reservation_amount=(released_wallet_amount),
            released_position_reservation_quantity=(released_position_quantity),
            wallet_release_ledger_entry=wallet_entry,
            actor=actor,
            reason=normalized_reason,
            expired_at=current_time,
        )
        audit.save(force_insert=True)
        MarketNotificationService.expired(audit)

        return audit

    @classmethod
    def _validate_request(
        cls,
        *,
        order: MarketOrder,
        source: str,
        reason: str,
        actor,
    ) -> str:
        errors = {}
        normalized_reason = str(reason or "").strip()

        if source not in MarketOrderExpiryAudit.Source.values:
            errors["source"] = "A valid expiry source is required."

        if not normalized_reason:
            errors["reason"] = "An expiry reason is required."

        if source == MarketOrderExpiryAudit.Source.ADMIN and actor is None:
            errors["actor"] = "Administrator-triggered expiry " "requires an actor."

        if order.time_in_force != MarketOrder.TimeInForce.GTD:
            errors["time_in_force"] = "Only GTD orders expire at a " "scheduled deadline."

        if order.status not in cls.EXPIRABLE_STATUSES:
            errors["status"] = "Only open or partially filled " "orders can expire."

        if errors:
            raise ValidationError(errors)

        return normalized_reason

    @staticmethod
    def _require_due_order(
        *,
        order: MarketOrder,
        current_time,
    ) -> None:
        if order.expires_at is None:
            raise ValidationError({"expires_at": ("The GTD order has no expiry time.")})

        if current_time < order.expires_at:
            raise ValidationError({"expires_at": ("The GTD order expiry time " "has not elapsed.")})

    @staticmethod
    def _get_locked_order(order_id) -> MarketOrder:
        return (
            MarketOrder.objects.select_for_update(
                of=("self",),
            )
            .select_related(
                "user",
                "market",
                "outcome",
            )
            .get(id=order_id)
        )

    @staticmethod
    def _get_locked_position(
        order: MarketOrder,
    ) -> MarketPosition:
        try:
            return MarketPosition.objects.select_for_update(
                of=("self",),
            ).get(
                user=order.user,
                market=order.market,
                outcome=order.outcome,
            )
        except MarketPosition.DoesNotExist as error:
            raise ValidationError(
                {"position": ("The SELL order position " "could not be found.")}
            ) from error
