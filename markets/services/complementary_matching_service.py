from decimal import Decimal
from uuid import uuid5

from django.db import transaction
from django.db.models import F

from markets.models import (
    MarketCompleteSetIssuance,
    MarketFeeLedgerEntry,
    MarketOrder,
    MarketOutcome,
    MarketPosition,
)
from markets.services.fee_service import MarketFeeService
from markets.services.fill_service import MarketFillService
from markets.services.liquidity_service import MarketLiquidityService
from wallets.services.wallet_service import WalletService


class ComplementaryBuyMatchingService:
    @classmethod
    @transaction.atomic
    def match(cls, order_id):
        taker = (
            MarketOrder.objects.select_for_update()
            .select_related("market", "outcome", "user")
            .get(pk=order_id)
        )
        if (
            taker.side != MarketOrder.Side.BUY
            or taker.status not in MarketFillService.FILLABLE_STATUSES
        ):
            return []
        opposite = (
            MarketOutcome.Side.NO
            if taker.outcome.side == MarketOutcome.Side.YES
            else MarketOutcome.Side.YES
        )
        candidates = list(
            MarketOrder.objects.filter(
                market=taker.market,
                outcome__side=opposite,
                side=MarketOrder.Side.BUY,
                status__in=MarketFillService.FILLABLE_STATUSES,
                quantity__gt=F("filled_quantity"),
            )
            .exclude(user=taker.user)
            .exclude(pk=taker.pk)
            .order_by("created_at", "id")
            .values_list("id", flat=True)
        )
        executions = []
        for candidate_id in candidates:
            if taker.status not in MarketFillService.FILLABLE_STATUSES:
                break
            maker = (
                MarketOrder.objects.select_for_update()
                .select_related("outcome", "user")
                .get(pk=candidate_id)
            )
            maker_price = maker.limit_price
            taker_price = (Decimal("1.00000") - maker_price).quantize(Decimal("0.00001"))
            if taker_price <= 0 or taker_price >= 1 or taker_price > taker.limit_price:
                continue
            quantity = min(
                taker.quantity - taker.filled_quantity, maker.quantity - maker.filled_quantity
            )
            if quantity <= 0:
                continue
            reference = uuid5(
                taker.id, f"complement:{maker.id}:{taker.filled_quantity}:{maker.filled_quantity}"
            )
            existing = MarketCompleteSetIssuance.objects.filter(
                idempotency_reference=reference
            ).first()
            if existing:
                executions.append(existing)
                continue
            yes_order = maker if maker.outcome.side == MarketOutcome.Side.YES else taker
            no_order = maker if maker.outcome.side == MarketOutcome.Side.NO else taker
            yes_price = maker_price if yes_order.pk == maker.pk else taker_price
            no_price = maker_price if no_order.pk == maker.pk else taker_price
            issuance = MarketCompleteSetIssuance(
                market=taker.market,
                issuance_type=MarketCompleteSetIssuance.IssuanceType.COMPLEMENTARY_BUYS,
                quantity=quantity,
                collateral_amount=quantity,
                yes_execution_price=yes_price,
                no_execution_price=no_price,
                yes_order=yes_order,
                no_order=no_order,
                idempotency_reference=reference,
            )
            issuance.full_clean()
            issuance.save(force_insert=True)
            schedule, rates = MarketFeeService.rates(market=taker.market)
            for order, price, role in (
                (maker, maker_price, "maker"),
                (taker, taker_price, "taker"),
            ):
                gross = MarketFillService._quantize_money(quantity * price)
                fee = MarketFeeService.calculate_fee(gross, rates[role])
                actual, improvement, top_up = MarketFillService._calculate_buy_wallet_settlement(
                    buy_order=order, quantity=quantity, price=price, actual_fee=fee
                )
                MarketFillService._apply_fill_to_order(order=order, quantity=quantity, price=price)
                position, _ = MarketPosition.objects.select_for_update().get_or_create(
                    user=order.user,
                    market=order.market,
                    outcome=order.outcome,
                    defaults={
                        "quantity": 0,
                        "reserved_quantity": 0,
                        "average_entry_price": 0,
                        "total_cost": 0,
                    },
                )
                MarketFillService._apply_buy_to_position(
                    position=position, quantity=quantity, price=price
                )
                order.full_clean()
                position.full_clean()
                MarketFillService._save_order(order)
                MarketFillService._save_position(position)
                if actual:
                    WalletService.consume_reserved(
                        user=order.user,
                        currency="UGX",
                        amount=actual,
                        idempotency_reference=uuid5(issuance.id, f"{role}-consume"),
                        market=order.market,
                        order=order,
                    )
                if improvement:
                    WalletService.release(
                        user=order.user,
                        currency="UGX",
                        amount=improvement,
                        idempotency_reference=uuid5(issuance.id, f"{role}-improvement"),
                        market=order.market,
                        order=order,
                    )
                if top_up:
                    WalletService.reserve(
                        user=order.user,
                        currency="UGX",
                        amount=top_up,
                        idempotency_reference=uuid5(issuance.id, f"{role}-topup"),
                        market=order.market,
                        order=order,
                    )
                MarketFeeService.record_fee(
                    parent_id=issuance.id,
                    market=order.market,
                    participant=order.user,
                    fee_type=(
                        MarketFeeLedgerEntry.FeeType.MAKER
                        if role == "maker"
                        else MarketFeeLedgerEntry.FeeType.TAKER
                    ),
                    rate_bps=rates[role],
                    gross=gross,
                    order=order,
                    schedule=schedule,
                )
            MarketLiquidityService.lock_complementary_collateral(
                market=taker.market, issuance=issuance, amount=quantity
            )
            executions.append(issuance)
            taker.refresh_from_db()
        return executions
