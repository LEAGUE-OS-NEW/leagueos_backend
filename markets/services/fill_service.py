from decimal import (
    ROUND_CEILING,
    ROUND_HALF_UP,
    Decimal,
)
from uuid import uuid5

from django.core.exceptions import ValidationError
from django.db import (
    IntegrityError,
    transaction,
)

from markets.models import (
    MarketFeeLedgerEntry,
    MarketFill,
    MarketOrder,
    MarketPosition,
)
from markets.services.fee_service import MarketFeeService
from markets.services.market_notification_service import MarketNotificationService
from wallets.services.wallet_service import (
    WalletService,
)


class MarketFillService:
    FILLABLE_STATUSES = {
        MarketOrder.Status.OPEN,
        MarketOrder.Status.PARTIALLY_FILLED,
    }
    PRICE_QUANTUM = Decimal("0.00001")
    QUANTITY_QUANTUM = Decimal("0.0001")
    MONEY_QUANTUM = Decimal("0.0001")
    MARKET_CURRENCY = "UGX"

    @classmethod
    @transaction.atomic
    def execute_fill(
        cls,
        *,
        execution_reference,
        buy_order_id,
        sell_order_id,
        maker_order_id,
        taker_order_id,
        quantity: Decimal,
        price: Decimal,
    ) -> MarketFill:
        quantity = Decimal(str(quantity))
        price = Decimal(str(price))

        existing_fill = cls._get_existing_fill(execution_reference)

        if existing_fill is not None:
            cls._require_matching_replay(
                fill=existing_fill,
                buy_order_id=buy_order_id,
                sell_order_id=sell_order_id,
                maker_order_id=maker_order_id,
                taker_order_id=taker_order_id,
                quantity=quantity,
                price=price,
            )
            return existing_fill

        buy_order, sell_order = cls._get_locked_orders(
            buy_order_id=buy_order_id,
            sell_order_id=sell_order_id,
        )

        # A concurrent transaction may have
        # completed this execution while this
        # transaction waited for the order locks.
        existing_fill = cls._get_existing_fill(execution_reference)

        if existing_fill is not None:
            cls._require_matching_replay(
                fill=existing_fill,
                buy_order_id=buy_order_id,
                sell_order_id=sell_order_id,
                maker_order_id=maker_order_id,
                taker_order_id=taker_order_id,
                quantity=quantity,
                price=price,
            )
            return existing_fill

        cls._require_order_sides(
            buy_order=buy_order,
            sell_order=sell_order,
        )
        cls._require_fillable_orders(
            buy_order=buy_order,
            sell_order=sell_order,
        )
        cls._require_matching_contract(
            buy_order=buy_order,
            sell_order=sell_order,
        )
        cls._require_distinct_users(
            buy_order=buy_order,
            sell_order=sell_order,
        )
        cls._require_valid_quantity(
            quantity=quantity,
            buy_order=buy_order,
            sell_order=sell_order,
        )
        cls._require_valid_execution_price(
            price=price,
            buy_order=buy_order,
            sell_order=sell_order,
        )

        maker_order, taker_order = cls._resolve_order_roles(
            buy_order=buy_order,
            sell_order=sell_order,
            maker_order_id=maker_order_id,
            taker_order_id=taker_order_id,
        )

        fee_schedule, fee_rates = MarketFeeService.rates(market=buy_order.market)
        buy_role = "maker" if maker_order.id == buy_order.id else "taker"
        sell_role = "maker" if maker_order.id == sell_order.id else "taker"
        gross_notional = cls._quantize_money(quantity * price)
        buyer_fee = MarketFeeService.calculate_fee(gross_notional, fee_rates[buy_role])
        seller_fee = MarketFeeService.calculate_fee(gross_notional, fee_rates[sell_role])
        buyer_position, seller_position = cls._get_locked_positions(
            buy_order=buy_order,
            sell_order=sell_order,
        )
        cls._require_sufficient_seller_position(
            seller_position=seller_position,
            quantity=quantity,
        )

        fill = MarketFill(
            execution_reference=(execution_reference),
            market=buy_order.market,
            outcome=buy_order.outcome,
            buy_order=buy_order,
            sell_order=sell_order,
            maker_order=maker_order,
            taker_order=taker_order,
            quantity=quantity,
            price=price,
        )
        fill.full_clean()

        (
            actual_cost,
            price_improvement_release,
            reservation_rounding_top_up,
        ) = cls._calculate_buy_wallet_settlement(
            buy_order=buy_order,
            quantity=quantity,
            price=price,
            actual_fee=buyer_fee,
        )

        cls._apply_fill_to_order(
            order=buy_order,
            quantity=quantity,
            price=price,
        )
        cls._apply_fill_to_order(
            order=sell_order,
            quantity=quantity,
            price=price,
        )
        cls._apply_buy_to_position(
            position=buyer_position,
            quantity=quantity,
            price=price,
        )
        cls._apply_sell_to_position(
            position=seller_position,
            quantity=quantity,
            price=price,
        )

        buy_order.full_clean()
        sell_order.full_clean()
        buyer_position.full_clean()
        seller_position.full_clean()

        cls._save_order(buy_order)
        cls._save_order(sell_order)

        # Saving the seller first lets a failure
        # during buyer creation prove that all prior
        # mutations are rolled back atomically.
        cls._save_position(seller_position)
        cls._save_position(buyer_position)

        try:
            fill.save(force_insert=True)
        except IntegrityError as error:
            raise ValidationError(
                {"execution_reference": ("This execution reference " "has already been used.")}
            ) from error

        cls._settle_buy_wallet(
            fill=fill,
            buy_order=buy_order,
            actual_cost=actual_cost,
            price_improvement_release=(price_improvement_release),
            reservation_rounding_top_up=(reservation_rounding_top_up),
        )
        cls._credit_seller_wallet(
            fill=fill,
            sell_order=sell_order,
            proceeds=gross_notional - seller_fee,
        )
        MarketFeeService.record_fee(
            parent_id=fill.id,
            market=fill.market,
            participant=buy_order.user,
            fee_type=(
                MarketFeeLedgerEntry.FeeType.MAKER
                if buy_role == "maker"
                else MarketFeeLedgerEntry.FeeType.TAKER
            ),
            rate_bps=fee_rates[buy_role],
            gross=gross_notional,
            order=buy_order,
            fill=fill,
            schedule=fee_schedule,
        )
        MarketFeeService.record_fee(
            parent_id=fill.id,
            market=fill.market,
            participant=sell_order.user,
            fee_type=(
                MarketFeeLedgerEntry.FeeType.MAKER
                if sell_role == "maker"
                else MarketFeeLedgerEntry.FeeType.TAKER
            ),
            rate_bps=fee_rates[sell_role],
            gross=gross_notional,
            order=sell_order,
            fill=fill,
            schedule=fee_schedule,
        )

        MarketNotificationService.fill(fill)

        return fill

    @classmethod
    def _calculate_buy_wallet_settlement(
        cls,
        *,
        buy_order: MarketOrder,
        quantity: Decimal,
        price: Decimal,
        actual_fee: Decimal = Decimal("0.0000"),
    ) -> tuple[
        Decimal,
        Decimal,
        Decimal,
    ]:
        remaining_before = buy_order.quantity - buy_order.filled_quantity
        remaining_after = remaining_before - quantity

        multiplier = Decimal("1") + Decimal(buy_order.maximum_fee_bps) / Decimal("10000")
        reservation_before = cls._quantize_reservation(
            remaining_before * buy_order.limit_price * multiplier
        )
        reservation_after = cls._quantize_reservation(
            remaining_after * buy_order.limit_price * multiplier
        )

        reservation_reduction = reservation_before - reservation_after
        actual_cost = cls._quantize_money(quantity * price) + actual_fee

        reconciliation = reservation_reduction - actual_cost

        price_improvement_release = max(
            reconciliation,
            Decimal("0.0000"),
        )
        reservation_rounding_top_up = max(
            -reconciliation,
            Decimal("0.0000"),
        )

        return (
            actual_cost,
            price_improvement_release,
            reservation_rounding_top_up,
        )

    @classmethod
    def _settle_buy_wallet(
        cls,
        *,
        fill: MarketFill,
        buy_order: MarketOrder,
        actual_cost: Decimal,
        price_improvement_release: Decimal,
        reservation_rounding_top_up: Decimal,
    ) -> None:
        if actual_cost > Decimal("0.0000"):
            WalletService.consume_reserved(
                user=buy_order.user,
                currency=cls.MARKET_CURRENCY,
                amount=actual_cost,
                idempotency_reference=uuid5(
                    fill.id,
                    "buyer-reserved-consumption",
                ),
                market=fill.market,
                order=buy_order,
                fill=fill,
            )

        if price_improvement_release > Decimal("0.0000"):
            WalletService.release(
                user=buy_order.user,
                currency=cls.MARKET_CURRENCY,
                amount=(price_improvement_release),
                idempotency_reference=uuid5(
                    fill.id,
                    ("buyer-price-" "improvement-release"),
                ),
                market=fill.market,
                order=buy_order,
                fill=fill,
            )

        if reservation_rounding_top_up > Decimal("0.0000"):
            WalletService.reserve(
                user=buy_order.user,
                currency=cls.MARKET_CURRENCY,
                amount=(reservation_rounding_top_up),
                idempotency_reference=uuid5(
                    fill.id,
                    ("buyer-reservation-" "rounding-top-up"),
                ),
                market=fill.market,
                order=buy_order,
                fill=fill,
            )

    @classmethod
    def _quantize_reservation(
        cls,
        value: Decimal,
    ) -> Decimal:
        return value.quantize(
            cls.MONEY_QUANTUM,
            rounding=ROUND_CEILING,
        )

    @classmethod
    def _credit_seller_wallet(
        cls,
        *,
        fill: MarketFill,
        sell_order: MarketOrder,
        proceeds: Decimal,
    ) -> None:
        WalletService.credit(
            user=sell_order.user,
            currency=cls.MARKET_CURRENCY,
            amount=proceeds,
            idempotency_reference=uuid5(
                fill.id,
                "seller-proceeds-credit",
            ),
            market=fill.market,
            order=sell_order,
            fill=fill,
        )

    @staticmethod
    def _get_existing_fill(
        execution_reference,
    ) -> MarketFill | None:
        return (
            MarketFill.objects.select_related(
                "market",
                "outcome",
                "buy_order",
                "sell_order",
                "maker_order",
                "taker_order",
            )
            .filter(execution_reference=(execution_reference))
            .first()
        )

    @staticmethod
    def _require_matching_replay(
        *,
        fill: MarketFill,
        buy_order_id,
        sell_order_id,
        maker_order_id,
        taker_order_id,
        quantity: Decimal,
        price: Decimal,
    ) -> None:
        matches_existing_fill = all(
            [
                fill.buy_order_id == buy_order_id,
                fill.sell_order_id == sell_order_id,
                fill.maker_order_id == maker_order_id,
                fill.taker_order_id == taker_order_id,
                fill.quantity == quantity,
                fill.price == price,
            ]
        )

        if not matches_existing_fill:
            raise ValidationError(
                {
                    "execution_reference": (
                        "This execution reference " "belongs to a different fill."
                    )
                }
            )

    @staticmethod
    def _get_locked_orders(
        *,
        buy_order_id,
        sell_order_id,
    ) -> tuple[MarketOrder, MarketOrder]:
        if buy_order_id == sell_order_id:
            raise ValidationError(
                {"sell_order": ("Buy and sell orders must " "be different orders.")}
            )

        order_ids = {
            buy_order_id,
            sell_order_id,
        }

        orders = list(
            MarketOrder.objects.select_for_update(
                of=("self",),
            )
            .select_related(
                "user",
                "market",
                "outcome",
            )
            .filter(
                id__in=order_ids,
            )
            .order_by("id")
        )

        if len(orders) != 2:
            raise ValidationError({"orders": ("Both market orders must " "exist.")})

        orders_by_id = {order.id: order for order in orders}

        return (
            orders_by_id[buy_order_id],
            orders_by_id[sell_order_id],
        )

    @staticmethod
    def _require_order_sides(
        *,
        buy_order: MarketOrder,
        sell_order: MarketOrder,
    ) -> None:
        errors = {}

        if buy_order.side != MarketOrder.Side.BUY:
            errors["buy_order"] = "The buy order must have BUY side."

        if sell_order.side != MarketOrder.Side.SELL:
            errors["sell_order"] = "The sell order must have " "SELL side."

        if errors:
            raise ValidationError(errors)

    @classmethod
    def _require_fillable_orders(
        cls,
        *,
        buy_order: MarketOrder,
        sell_order: MarketOrder,
    ) -> None:
        if (
            buy_order.status not in cls.FILLABLE_STATUSES
            or sell_order.status not in cls.FILLABLE_STATUSES
        ):
            raise ValidationError({"status": ("Both orders must be open " "or partially filled.")})

    @staticmethod
    def _require_matching_contract(
        *,
        buy_order: MarketOrder,
        sell_order: MarketOrder,
    ) -> None:
        errors = {}

        if buy_order.market_id != sell_order.market_id:
            errors["market"] = "Both orders must belong to the " "same market."

        if buy_order.outcome_id != sell_order.outcome_id:
            errors["outcome"] = "Both orders must belong to the " "same outcome."

        if errors:
            raise ValidationError(errors)

    @staticmethod
    def _require_distinct_users(
        *,
        buy_order: MarketOrder,
        sell_order: MarketOrder,
    ) -> None:
        if buy_order.user_id == sell_order.user_id:
            raise ValidationError({"sell_order": ("Self-trading is not " "allowed.")})

    @staticmethod
    def _require_valid_quantity(
        *,
        quantity: Decimal,
        buy_order: MarketOrder,
        sell_order: MarketOrder,
    ) -> None:
        if quantity <= Decimal("0.0000"):
            raise ValidationError({"quantity": ("Fill quantity must be " "positive.")})

        buy_remaining = buy_order.quantity - buy_order.filled_quantity
        sell_remaining = sell_order.quantity - sell_order.filled_quantity

        if quantity > buy_remaining or quantity > sell_remaining:
            raise ValidationError(
                {
                    "quantity": (
                        "Fill quantity cannot " "exceed either order's " "remaining quantity."
                    )
                }
            )

    @staticmethod
    def _require_valid_execution_price(
        *,
        price: Decimal,
        buy_order: MarketOrder,
        sell_order: MarketOrder,
    ) -> None:
        if price <= Decimal("0.00000") or price >= Decimal("1.00000"):
            raise ValidationError(
                {"price": ("Execution price must be " "greater than zero and " "less than one.")}
            )

        if price > buy_order.limit_price or price < sell_order.limit_price:
            raise ValidationError({"price": ("Execution price must " "respect both order limits.")})

    @staticmethod
    def _resolve_order_roles(
        *,
        buy_order: MarketOrder,
        sell_order: MarketOrder,
        maker_order_id,
        taker_order_id,
    ) -> tuple[MarketOrder, MarketOrder]:
        orders_by_id = {
            buy_order.id: buy_order,
            sell_order.id: sell_order,
        }
        errors = {}

        maker_order = orders_by_id.get(maker_order_id)
        taker_order = orders_by_id.get(taker_order_id)

        if maker_order is None:
            errors["maker_order"] = "The maker must be one of the " "fill orders."

        if taker_order is None:
            errors["taker_order"] = "The taker must be one of the " "fill orders."

        if maker_order_id == taker_order_id and maker_order is not None and taker_order is not None:
            errors["taker_order"] = "Maker and taker must be " "different fill orders."

        if errors:
            raise ValidationError(errors)

        return maker_order, taker_order

    @staticmethod
    def _get_locked_positions(
        *,
        buy_order: MarketOrder,
        sell_order: MarketOrder,
    ) -> tuple[
        MarketPosition,
        MarketPosition,
    ]:
        positions = list(
            MarketPosition.objects.select_for_update(
                of=("self",),
            )
            .filter(
                user_id__in={
                    buy_order.user_id,
                    sell_order.user_id,
                },
                market_id=buy_order.market_id,
                outcome_id=buy_order.outcome_id,
            )
            .order_by("user_id")
        )

        positions_by_user = {position.user_id: position for position in positions}

        seller_position = positions_by_user.get(sell_order.user_id)

        if seller_position is None:
            raise ValidationError(
                {"position": ("The seller does not have " "a position in this outcome.")}
            )

        buyer_position = positions_by_user.get(buy_order.user_id)

        if buyer_position is None:
            buyer_position = MarketPosition(
                user_id=buy_order.user_id,
                market_id=buy_order.market_id,
                outcome_id=buy_order.outcome_id,
                quantity=Decimal("0.0000"),
                average_entry_price=Decimal("0.00000"),
                total_cost=Decimal("0.0000"),
                realized_pnl=Decimal("0.0000"),
            )

        return (
            buyer_position,
            seller_position,
        )

    @staticmethod
    def _require_sufficient_seller_position(
        *,
        seller_position: MarketPosition,
        quantity: Decimal,
    ) -> None:
        if seller_position.quantity < quantity:
            raise ValidationError(
                {"position": ("The seller's position " "cannot cover this fill.")}
            )
        if seller_position.reserved_quantity < quantity:
            raise ValidationError(
                {"position": ("The seller's reserved position " "cannot cover this fill.")}
            )

    @classmethod
    def _apply_fill_to_order(
        cls,
        *,
        order: MarketOrder,
        quantity: Decimal,
        price: Decimal,
    ) -> None:
        previous_quantity = order.filled_quantity
        previous_average = order.average_fill_price or Decimal("0.00000")
        new_quantity = previous_quantity + quantity

        weighted_total = previous_quantity * previous_average + quantity * price

        new_average = (weighted_total / new_quantity).quantize(
            cls.PRICE_QUANTUM,
            rounding=ROUND_HALF_UP,
        )

        order.filled_quantity = new_quantity
        order.average_fill_price = new_average
        order.status = (
            MarketOrder.Status.FILLED
            if new_quantity == order.quantity
            else (MarketOrder.Status.PARTIALLY_FILLED)
        )

    @classmethod
    def _apply_buy_to_position(
        cls,
        *,
        position: MarketPosition,
        quantity: Decimal,
        price: Decimal,
    ) -> None:
        fill_cost = cls._quantize_money(quantity * price)

        position.quantity = (position.quantity + quantity).quantize(
            cls.QUANTITY_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        position.total_cost = (position.total_cost + fill_cost).quantize(
            cls.MONEY_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        position.average_entry_price = (position.total_cost / position.quantity).quantize(
            cls.PRICE_QUANTUM,
            rounding=ROUND_HALF_UP,
        )

    @classmethod
    def _apply_sell_to_position(
        cls,
        *,
        position: MarketPosition,
        quantity: Decimal,
        price: Decimal,
    ) -> None:
        previous_quantity = position.quantity
        previous_cost = position.total_cost

        released_cost = cls._quantize_money(previous_cost * quantity / previous_quantity)
        proceeds = cls._quantize_money(quantity * price)
        realized_change = cls._quantize_money(proceeds - released_cost)

        remaining_quantity = (previous_quantity - quantity).quantize(
            cls.QUANTITY_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        remaining_cost = cls._quantize_money(previous_cost - released_cost)

        position.quantity = remaining_quantity
        position.reserved_quantity = (position.reserved_quantity - quantity).quantize(
            cls.QUANTITY_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        position.realized_pnl = (position.realized_pnl + realized_change).quantize(
            cls.MONEY_QUANTUM,
            rounding=ROUND_HALF_UP,
        )

        if remaining_quantity == Decimal("0.0000"):
            position.total_cost = Decimal("0.0000")
            position.average_entry_price = Decimal("0.00000")
            return

        position.total_cost = remaining_cost
        position.average_entry_price = (remaining_cost / remaining_quantity).quantize(
            cls.PRICE_QUANTUM,
            rounding=ROUND_HALF_UP,
        )

    @classmethod
    def _quantize_money(
        cls,
        value: Decimal,
    ) -> Decimal:
        return value.quantize(
            cls.MONEY_QUANTUM,
            rounding=ROUND_HALF_UP,
        )

    @staticmethod
    def _save_order(
        order: MarketOrder,
    ) -> None:
        order.save(
            update_fields=[
                "filled_quantity",
                "average_fill_price",
                "status",
                "updated_at",
            ]
        )

    @staticmethod
    def _save_position(
        position: MarketPosition,
    ) -> None:
        if position._state.adding:
            position.save(force_insert=True)
            return

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
