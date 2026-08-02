from decimal import (
    ROUND_CEILING,
    Decimal,
)

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from authentication.services.permission_service import (
    PermissionService,
)
from markets.models import (
    Market,
    MarketOrder,
    MarketOutcome,
)
from wallets.services.wallet_service import (
    WalletService,
)


class MarketParticipationService:
    PARTICIPATE_PERMISSION = "participate_market"
    MARKET_CURRENCY = "UGX"
    WALLET_AMOUNT_QUANTUM = Decimal("0.0001")

    @classmethod
    @transaction.atomic
    def place_order(
        cls,
        *,
        user,
        market_id,
        outcome_id,
        side: str,
        quantity: Decimal,
        limit_price: Decimal,
    ) -> MarketOrder:
        cls._require_permission(user)
        cls._require_verified_user(user)

        market = cls._get_locked_market(market_id)

        cls._require_open_market(market)
        cls._require_active_trading_window(market)

        outcome = cls._get_locked_outcome(
            market=market,
            outcome_id=outcome_id,
        )

        order = MarketOrder(
            user=user,
            market=market,
            outcome=outcome,
            side=side,
            quantity=quantity,
            limit_price=limit_price,
            filled_quantity=Decimal("0"),
            average_fill_price=None,
            status=MarketOrder.Status.OPEN,
        )

        order.full_clean()
        order.save(force_insert=True)

        if order.side == MarketOrder.Side.BUY:
            reservation_amount = cls._calculate_buy_reservation(order)

            WalletService.reserve(
                user=user,
                currency=cls.MARKET_CURRENCY,
                amount=reservation_amount,
                idempotency_reference=order.id,
                market=market,
                order=order,
            )

        return order

    @classmethod
    @transaction.atomic
    def cancel_order(
        cls,
        *,
        user,
        order_id,
    ) -> MarketOrder:
        cls._require_permission(user)
        cls._require_verified_user(user)

        order = cls._get_locked_order(order_id)

        cls._require_order_owner(
            order=order,
            user=user,
        )
        cls._require_cancellable_order(order)

        order.status = MarketOrder.Status.CANCELLED
        order.full_clean()
        order.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        return order

    @classmethod
    def _calculate_buy_reservation(
        cls,
        order: MarketOrder,
    ) -> Decimal:
        maximum_cost = order.quantity * order.limit_price

        return maximum_cost.quantize(
            cls.WALLET_AMOUNT_QUANTUM,
            rounding=ROUND_CEILING,
        )

    @staticmethod
    def _get_locked_order(
        order_id,
    ) -> MarketOrder:
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
    def _require_order_owner(
        *,
        order: MarketOrder,
        user,
    ) -> None:
        if order.user_id != user.id:
            raise PermissionDenied("You may only cancel your own " "market orders.")

    @staticmethod
    def _require_cancellable_order(
        order: MarketOrder,
    ) -> None:
        cancellable_statuses = {
            MarketOrder.Status.OPEN,
            MarketOrder.Status.PARTIALLY_FILLED,
        }

        if order.status not in cancellable_statuses:
            raise ValidationError(
                {"status": ("Only open or partially " "filled orders can be " "cancelled.")}
            )

    @classmethod
    def _require_permission(
        cls,
        user,
    ) -> None:
        if not PermissionService.has_permission(
            user,
            cls.PARTICIPATE_PERMISSION,
        ):
            raise PermissionDenied("You do not have the " "participate_market permission.")

    @staticmethod
    def _require_verified_user(
        user,
    ) -> None:
        if not user.is_verified:
            raise PermissionDenied("Account verification is required " "to participate in markets.")

    @staticmethod
    def _get_locked_market(
        market_id,
    ) -> Market:
        return (
            Market.objects.select_for_update(
                of=("self",),
            )
            .select_related(
                "sport",
                "category",
                "sporting_event",
                "competition",
                "participant",
            )
            .get(id=market_id)
        )

    @staticmethod
    def _require_open_market(
        market: Market,
    ) -> None:
        if market.status != Market.Status.OPEN:
            raise ValidationError({"status": ("Orders can only be placed " "on open markets.")})

    @staticmethod
    def _require_active_trading_window(
        market: Market,
    ) -> None:
        now = timezone.now()
        errors = {}

        if market.opens_at is not None and now < market.opens_at:
            errors["opens_at"] = "The market trading window " "has not opened."

        if market.closes_at is not None and now >= market.closes_at:
            errors["closes_at"] = "The market trading window " "has closed."

        if errors:
            raise ValidationError(errors)

    @staticmethod
    def _get_locked_outcome(
        *,
        market: Market,
        outcome_id,
    ) -> MarketOutcome:
        try:
            return MarketOutcome.objects.select_for_update().get(
                id=outcome_id,
                market_id=market.id,
            )
        except MarketOutcome.DoesNotExist as error:
            raise ValidationError(
                {"outcome": ("The selected outcome does " "not belong to this market.")}
            ) from error
