from decimal import (
    Decimal,
)
from typing import TypedDict
from uuid import uuid5

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from authentication.services.permission_service import (
    PermissionService,
)
from markets.exceptions import MarketParticipationIneligible, MarketResponsibleParticipationBlocked
from markets.models import (
    Market,
    MarketOrder,
    MarketOutcome,
    MarketParticipantCompliance,
    MarketPosition,
    MarketResponsibleParticipation,
)
from markets.services.eligibility_service import MarketEligibilityService
from markets.services.fee_service import MarketFeeService
from markets.services.market_notification_service import MarketNotificationService
from markets.services.matching_service import (
    MarketMatchingService,
)
from markets.services.order_financials import calculate_buy_commitment
from markets.services.responsible_participation_service import MarketResponsibleParticipationService
from profiles.models import Profile
from wallets.models import LedgerEntry
from wallets.services.wallet_service import (
    WalletService,
)


class LockedOrderCancellationResult(TypedDict):
    order: MarketOrder
    remaining_quantity: Decimal
    released_wallet_amount: Decimal
    released_position_quantity: Decimal
    wallet_entry: LedgerEntry | None


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
        time_in_force: str = MarketOrder.TimeInForce.GTC,
        expires_at=None,
    ) -> MarketOrder:
        cls._require_permission(user)
        cls._require_verified_user(user)

        user = get_user_model().objects.select_for_update().get(pk=user.pk)
        profile = Profile.objects.select_related("country").filter(user=user).first()
        compliance = (
            MarketParticipantCompliance.objects.select_for_update().filter(participant=user).first()
        )
        eligibility = MarketEligibilityService.evaluate(
            participant=user, profile=profile, compliance=compliance
        )
        if not eligibility.eligible:
            raise MarketParticipationIneligible(eligibility)

        responsible_controls = (
            MarketResponsibleParticipation.objects.select_for_update()
            .filter(participant=user)
            .first()
        )

        market = cls._get_locked_market(market_id)

        cls._require_open_market(market)
        cls._require_active_trading_window(market)

        outcome = cls._get_locked_outcome(
            market=market,
            outcome_id=outcome_id,
        )

        responsible = MarketResponsibleParticipationService.evaluate_order(
            participant=user,
            market=market,
            outcome=outcome,
            side=side,
            quantity=quantity,
            limit_price=limit_price,
            controls=responsible_controls,
        )
        if not responsible.allowed:
            raise MarketResponsibleParticipationBlocked(responsible)

        position = None
        if side == MarketOrder.Side.SELL:
            position = cls._get_locked_sell_position(
                user=user,
                market=market,
                outcome=outcome,
            )
            cls._reserve_sell_quantity(
                position=position,
                quantity=quantity,
            )

        fee_schedule, fee_rates = MarketFeeService.rates(market=market)

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
            time_in_force=time_in_force,
            expires_at=expires_at,
            expired_at=None,
            fee_schedule=fee_schedule,
            maximum_fee_bps=max(fee_rates["maker"], fee_rates["taker"]),
        )

        order.full_clean()

        if position is not None:
            position.full_clean()
            position.save(
                update_fields=[
                    "reserved_quantity",
                    "updated_at",
                ]
            )

        order.save(force_insert=True)
        MarketNotificationService.order_accepted(order)

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

        MarketMatchingService.match_order(order.id)
        order.refresh_from_db()
        if order.time_in_force in {
            MarketOrder.TimeInForce.IOC,
            MarketOrder.TimeInForce.FOK,
        } and cls.is_order_cancellable(order):
            order = cls._get_locked_order(order.id)
            if cls.is_order_cancellable(order):
                cls.cancel_locked_order(order=order)
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

        cls.cancel_locked_order(order=order)
        MarketNotificationService.order_cancelled(order)
        return order

    @classmethod
    def cancel_locked_order(cls, *, order: MarketOrder) -> LockedOrderCancellationResult:
        """Cancel a locked order without applying actor ownership policy."""
        cls._require_cancellable_order(order)
        remaining_quantity = order.quantity - order.filled_quantity
        wallet_entry = None
        released_wallet_amount = Decimal("0.0000")
        released_position_quantity = Decimal("0.0000")

        if order.side == MarketOrder.Side.BUY:
            release_amount = cls._calculate_buy_cancellation_release(order)

            wallet_entry = WalletService.release(
                user=order.user,
                currency=cls.MARKET_CURRENCY,
                amount=release_amount,
                idempotency_reference=uuid5(
                    order.id,
                    "cancellation-release",
                ),
                market=order.market,
                order=order,
            )
            released_wallet_amount = release_amount
        elif order.side == MarketOrder.Side.SELL:
            position = cls._get_locked_sell_position(
                user=order.user,
                market=order.market,
                outcome=order.outcome,
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

        order.status = MarketOrder.Status.CANCELLED
        order.full_clean()
        order.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        return {
            "order": order,
            "remaining_quantity": remaining_quantity,
            "released_wallet_amount": released_wallet_amount,
            "released_position_quantity": released_position_quantity,
            "wallet_entry": wallet_entry,
        }

    @classmethod
    def _calculate_buy_reservation(
        cls,
        order: MarketOrder,
    ) -> Decimal:
        return calculate_buy_commitment(
            quantity=order.quantity,
            limit_price=order.limit_price,
            maximum_fee_bps=order.maximum_fee_bps,
        )

    @staticmethod
    def _get_locked_sell_position(
        *,
        user,
        market: Market,
        outcome: MarketOutcome,
    ) -> MarketPosition:
        try:
            return MarketPosition.objects.select_for_update(
                of=("self",),
            ).get(
                user=user,
                market=market,
                outcome=outcome,
            )
        except MarketPosition.DoesNotExist as error:
            raise ValidationError(
                {"position": "A SELL order requires an owned position in this outcome."}
            ) from error

    @staticmethod
    def _reserve_sell_quantity(
        *,
        position: MarketPosition,
        quantity: Decimal,
    ) -> None:
        available_quantity = position.quantity - position.reserved_quantity

        if quantity > available_quantity:
            raise ValidationError(
                {"quantity": "SELL quantity cannot exceed available position quantity."}
            )

        position.reserved_quantity += quantity

    @classmethod
    def _calculate_buy_cancellation_release(
        cls,
        order: MarketOrder,
    ) -> Decimal:
        remaining_quantity = order.quantity - order.filled_quantity
        return calculate_buy_commitment(
            quantity=remaining_quantity,
            limit_price=order.limit_price,
            maximum_fee_bps=order.maximum_fee_bps,
        )

    @classmethod
    def calculate_buy_cancellation_release(cls, order: MarketOrder) -> Decimal:
        """Return the exact amount released if an active BUY order is cancelled."""
        return cls._calculate_buy_cancellation_release(order)

    @staticmethod
    def is_order_cancellable(order: MarketOrder) -> bool:
        return order.status in {
            MarketOrder.Status.OPEN,
            MarketOrder.Status.PARTIALLY_FILLED,
        }

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
        if not MarketParticipationService.is_order_cancellable(order):
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
