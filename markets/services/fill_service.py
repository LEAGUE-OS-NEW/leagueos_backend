from decimal import (
    ROUND_HALF_UP,
    Decimal,
)

from django.core.exceptions import ValidationError
from django.db import (
    IntegrityError,
    transaction,
)

from markets.models import (
    MarketFill,
    MarketOrder,
)


class MarketFillService:
    FILLABLE_STATUSES = {
        MarketOrder.Status.OPEN,
        MarketOrder.Status.PARTIALLY_FILLED,
    }
    PRICE_QUANTUM = Decimal("0.00001")

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

        # Check again after acquiring both row locks.
        # A concurrent transaction may have completed
        # this execution while this transaction waited.
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

        buy_order.full_clean()
        sell_order.full_clean()

        cls._save_order(buy_order)
        cls._save_order(sell_order)

        try:
            fill.save(force_insert=True)
        except IntegrityError as error:
            raise ValidationError(
                {"execution_reference": ("This execution reference " "has already been used.")}
            ) from error

        return fill

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
