from decimal import ROUND_HALF_UP, Decimal
from uuid import NAMESPACE_URL, uuid5

from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from markets.models import (
    MarketFeeLedgerEntry,
    MarketFill,
    MarketFinancialAdjustmentLine,
    MarketOrder,
    MarketPosition,
    MarketPositionSettlement,
    MarketPositionVoidRefund,
    MarketReconciliationMismatch,
    MarketReconciliationRun,
)
from markets.services.fee_service import MarketFeeService
from markets.services.order_financials import calculate_buy_commitment
from markets.services.settlement_service import MarketSettlementService
from markets.services.void_refund_service import MarketVoidRefundService
from wallets.models import LedgerEntry, Wallet


class MarketReconciliationService:
    MONEY = Decimal("0.0001")
    ACTIVE = (MarketOrder.Status.OPEN, MarketOrder.Status.PARTIALLY_FILLED)

    @classmethod
    def run(cls, *, run_date=None, market=None, wallet=None, actor=None):
        run_date = run_date or timezone.localdate()
        scope = f"{run_date}:{getattr(market, 'id', '')}:{getattr(wallet, 'id', '')}"
        reference = uuid5(NAMESPACE_URL, f"leagueos:market-reconciliation:{scope}")
        existing = MarketReconciliationRun.objects.filter(reference=reference).first()
        if existing:
            return existing
        run = MarketReconciliationRun.objects.create(
            reference=reference,
            run_date=run_date,
            market=market,
            wallet=wallet,
            initiated_by=actor,
            status=MarketReconciliationRun.Status.RUNNING,
            started_at=timezone.now(),
        )
        try:
            with transaction.atomic():
                run = MarketReconciliationRun._base_manager.select_for_update(of=("self",)).get(
                    pk=run.pk
                )
                scoped = cls._scope(run)
                cls._detect(run, scoped)
                run.order_count = scoped["orders"].count()
                run.fill_count = scoped["fills"].count()
                run.mismatch_count = run.mismatches.count()
                run.total_fee_amount = scoped["fees"].aggregate(total=Sum("fee_amount"))[
                    "total"
                ] or Decimal("0.0000")
                run.status = MarketReconciliationRun.Status.COMPLETED
                run.completed_at = timezone.now()
                run.save(
                    update_fields=[
                        "order_count",
                        "fill_count",
                        "mismatch_count",
                        "total_fee_amount",
                        "status",
                        "completed_at",
                        "updated_at",
                    ],
                    _service_transition=True,
                )
        except Exception:
            run.refresh_from_db()
            run.status = MarketReconciliationRun.Status.FAILED
            run.completed_at = timezone.now()
            run.save(
                update_fields=["status", "completed_at", "updated_at"],
                _service_transition=True,
            )
            raise
        if run.mismatch_count:
            from notifications.services.operational_alert_service import OperationalAlertService

            OperationalAlertService.create(
                permissions=("manage_market", "approve_market"),
                event_type="RECONCILIATION_MISMATCHES",
                title="Reconciliation mismatches detected",
                message=f"A reconciliation run found {run.mismatch_count} mismatches.",
                source_key=f"market-reconciliation:{run.id}:mismatches",
                data={"run_id": str(run.id), "mismatch_count": run.mismatch_count},
                severity="CRITICAL",
            )
        return run

    @classmethod
    def _scope(cls, run):
        orders = MarketOrder.objects.select_related("market", "user")
        fills = MarketFill.objects.select_related(
            "market", "buy_order__user", "sell_order__user", "maker_order", "taker_order"
        )
        positions = MarketPosition.objects.select_related("user", "market", "outcome")
        fees = MarketFeeLedgerEntry.objects.select_related(
            "schedule", "participant", "order", "fill"
        )
        settlements = MarketPositionSettlement.objects.select_related(
            "market_settlement__market",
            "market_settlement__winning_outcome",
            "market_position",
            "participant",
            "wallet_ledger_entry",
        )
        refunds = MarketPositionVoidRefund.objects.select_related(
            "market_void_refund__market",
            "market_position",
            "participant",
            "wallet_credit_ledger_entry",
        )
        adjustments = MarketFinancialAdjustmentLine.objects.select_related(
            "adjustment", "wallet", "wallet_ledger_entry"
        )
        wallets = Wallet.objects.select_related("user")
        if run.market_id:
            orders = orders.filter(market_id=run.market_id)
            fills = fills.filter(market_id=run.market_id)
            positions = positions.filter(market_id=run.market_id)
            fees = fees.filter(market_id=run.market_id)
            settlements = settlements.filter(market_settlement__market_id=run.market_id)
            refunds = refunds.filter(market_void_refund__market_id=run.market_id)
            adjustments = adjustments.filter(adjustment__market_id=run.market_id)
            user_ids = set(orders.values_list("user_id", flat=True))
            user_ids.update(fees.values_list("participant_id", flat=True))
            user_ids.update(settlements.values_list("participant_id", flat=True))
            user_ids.update(refunds.values_list("participant_id", flat=True))
            wallets = wallets.filter(user_id__in=user_ids)
        if run.wallet_id:
            user_id = run.wallet.user_id
            wallets = wallets.filter(id=run.wallet_id)
            orders = orders.filter(user_id=user_id)
            fills = fills.filter(Q(buy_order__user_id=user_id) | Q(sell_order__user_id=user_id))
            positions = positions.filter(user_id=user_id)
            fees = fees.filter(participant_id=user_id)
            settlements = settlements.filter(participant_id=user_id)
            refunds = refunds.filter(participant_id=user_id)
            adjustments = adjustments.filter(wallet_id=run.wallet_id)
        return {
            "wallets": wallets,
            "orders": orders,
            "fills": fills,
            "positions": positions,
            "fees": fees,
            "settlements": settlements,
            "refunds": refunds,
            "adjustments": adjustments,
        }

    @classmethod
    def _detect(cls, run, scoped=None):
        scoped = scoped or cls._scope(run)
        for wallet in scoped["wallets"].filter(
            Q(available_balance__lt=0) | Q(reserved_balance__lt=0)
        ):
            cls._add(run, "NEGATIVE_WALLET_BALANCE", "CRITICAL", wallet=wallet)
        cls._orders(run, scoped)
        cls._fills(run, scoped)
        cls._settlements(run, scoped)
        cls._refunds(run, scoped)
        cls._adjustments(run, scoped)
        cls._positions(run, scoped)

    @classmethod
    def _orders(cls, run, scoped):
        orders, positions = scoped["orders"], scoped["positions"]
        for order in orders.filter(filled_quantity__gt=F("quantity")):
            cls._add(
                run,
                "ORDER_OVERFILLED",
                "CRITICAL",
                order=order,
                expected=order.quantity,
                actual=order.filled_quantity,
                unit="QUANTITY",
            )
        for order in orders.filter(status__in=cls.ACTIVE, side=MarketOrder.Side.BUY):
            expected = calculate_buy_commitment(
                quantity=order.quantity - order.filled_quantity,
                limit_price=order.limit_price,
                maximum_fee_bps=order.maximum_fee_bps,
            )
            actual = cls._reserved_effect(order)
            if actual != expected:
                cls._add(
                    run,
                    "OPEN_BUY_RESERVATION_MISMATCH",
                    "ERROR",
                    order=order,
                    expected=expected,
                    actual=actual,
                    unit="UGX",
                )
        for order in orders.exclude(status__in=cls.ACTIVE).filter(side=MarketOrder.Side.BUY):
            actual = cls._reserved_effect(order)
            if actual:
                cls._add(
                    run,
                    "TERMINAL_BUY_RESERVATION_MISMATCH",
                    "ERROR",
                    order=order,
                    expected=0,
                    actual=actual,
                    unit="UGX",
                )
        expected_by_position = {}
        for order in orders.filter(status__in=cls.ACTIVE, side=MarketOrder.Side.SELL):
            key = (order.user_id, order.market_id, order.outcome_id)
            expected_by_position[key] = expected_by_position.get(key, Decimal("0")) + (
                order.quantity - order.filled_quantity
            )
        keys = set(expected_by_position)
        keys.update(
            orders.filter(side=MarketOrder.Side.SELL).values_list(
                "user_id", "market_id", "outcome_id"
            )
        )
        position_map = {
            (p.user_id, p.market_id, p.outcome_id): p
            for p in positions.filter(user_id__in={key[0] for key in keys})
        }
        for key in keys:
            expected = expected_by_position.get(key, Decimal("0.0000"))
            actual = position_map[key].reserved_quantity if key in position_map else Decimal("0")
            if actual != expected:
                code = (
                    "OPEN_SELL_RESERVATION_MISMATCH"
                    if expected
                    else "TERMINAL_SELL_RESERVATION_MISMATCH"
                )
                order = orders.filter(
                    user_id=key[0],
                    market_id=key[1],
                    outcome_id=key[2],
                    side=MarketOrder.Side.SELL,
                ).first()
                cls._add(
                    run,
                    code,
                    "ERROR",
                    order=order,
                    participant_id=key[0],
                    expected=expected,
                    actual=actual,
                    unit="QUANTITY",
                )
        for order in orders.exclude(status__in=cls.ACTIVE):
            releases = order.ledger_entries.filter(
                entry_type=LedgerEntry.EntryType.RELEASE, fill__isnull=True
            ).count()
            if releases > 1:
                cls._add(
                    run,
                    "DUPLICATE_ORDER_RELEASE_EFFECT",
                    "CRITICAL",
                    order=order,
                    expected=1,
                    actual=releases,
                    unit="COUNT",
                )

    @staticmethod
    def _reserved_effect(order):
        total = order.ledger_entries.aggregate(
            value=Sum(F("reserved_balance_after") - F("reserved_balance_before"))
        )["value"]
        return (total or Decimal("0.0000")).quantize(Decimal("0.0001"))

    @classmethod
    def _fills(cls, run, scoped):
        for fill in scoped["fills"]:
            if fill.quantity <= 0 or fill.price <= 0:
                cls._add(run, "INVALID_FILL_VALUE", "CRITICAL", fill=fill)
                continue
            gross = cls._money(fill.quantity * fill.price)
            entries = list(fill.fee_entries.select_related("schedule", "order"))
            if len(entries) != 2:
                cls._add(
                    run,
                    "FILL_FEE_RECORD_COUNT_MISMATCH",
                    "ERROR",
                    fill=fill,
                    expected=2,
                    actual=len(entries),
                    unit="COUNT",
                )
            fees = {}
            for order in (fill.buy_order, fill.sell_order):
                fee_type = (
                    MarketFeeLedgerEntry.FeeType.MAKER
                    if order.id == fill.maker_order_id
                    else MarketFeeLedgerEntry.FeeType.TAKER
                )
                fees[order.id] = cls._fill_fee(run, fill, order, fee_type, gross, entries)
            cls._fill_wallets(
                run,
                fill,
                gross,
                fees.get(fill.buy_order_id, Decimal("0")),
                fees.get(fill.sell_order_id, Decimal("0")),
            )

    @classmethod
    def _fill_fee(cls, run, fill, order, fee_type, gross, entries):
        matches = [e for e in entries if e.participant_id == order.user_id]
        if len(matches) != 1:
            cls._add(
                run,
                "FILL_FEE_PARTICIPANT_MISMATCH",
                "ERROR",
                fill=fill,
                participant_id=order.user_id,
                expected=1,
                actual=len(matches),
                unit="COUNT",
            )
            return Decimal("0")
        entry = matches[0]
        rate = 0
        version = 0
        if entry.schedule_id:
            version = entry.schedule.version
            rate = (
                entry.schedule.maker_fee_bps
                if fee_type == MarketFeeLedgerEntry.FeeType.MAKER
                else entry.schedule.taker_fee_bps
            )
        checks = (
            ("FILL_FEE_ORDER_MISMATCH", entry.order_id == order.id),
            ("FILL_FEE_TYPE_MISMATCH", entry.fee_type == fee_type),
            ("FILL_FEE_RATE_MISMATCH", entry.rate_bps == rate),
            ("FILL_FEE_GROSS_MISMATCH", entry.gross_amount == gross),
            ("FILL_FEE_SCHEDULE_VERSION_MISMATCH", entry.schedule_version == version),
            ("FILL_FEE_CURRENCY_MISMATCH", entry.currency == MarketFeeService.CURRENCY),
        )
        for code, valid in checks:
            if not valid:
                cls._add(run, code, "ERROR", fill=fill, participant_id=order.user_id)
        fee = MarketFeeService.calculate_fee(gross, rate)
        if entry.fee_amount != fee:
            cls._add(
                run,
                "FILL_FEE_AMOUNT_MISMATCH",
                "ERROR",
                fill=fill,
                participant_id=order.user_id,
                expected=fee,
                actual=entry.fee_amount,
                unit="UGX",
            )
        if entry.net_amount != gross - fee:
            cls._add(
                run,
                "FILL_FEE_NET_MISMATCH",
                "ERROR",
                fill=fill,
                participant_id=order.user_id,
                expected=gross - fee,
                actual=entry.net_amount,
                unit="UGX",
            )
        return entry.fee_amount

    @classmethod
    def _fill_wallets(cls, run, fill, gross, buy_fee, sell_fee):
        expected = (
            (
                "FILL_BUY",
                uuid5(fill.id, "buyer-reserved-consumption"),
                fill.buy_order.user_id,
                gross + buy_fee,
                LedgerEntry.EntryType.DEBIT,
                True,
            ),
            (
                "FILL_SELL",
                uuid5(fill.id, "seller-proceeds-credit"),
                fill.sell_order.user_id,
                gross - sell_fee,
                LedgerEntry.EntryType.CREDIT,
                False,
            ),
        )
        for prefix, reference, user_id, amount, entry_type, reserved in expected:
            entries = list(LedgerEntry.objects.filter(idempotency_reference=reference))
            cls._wallet_effect(
                run,
                prefix,
                entries,
                user_id,
                amount,
                entry_type,
                fill=fill,
                market_id=fill.market_id,
                reserved=reserved,
            )
        buyer_count = fill.ledger_entries.filter(
            wallet__user_id=fill.buy_order.user_id, entry_type=LedgerEntry.EntryType.DEBIT
        ).count()
        seller_count = fill.ledger_entries.filter(
            wallet__user_id=fill.sell_order.user_id, entry_type=LedgerEntry.EntryType.CREDIT
        ).count()
        if buyer_count != 1:
            cls._add(
                run,
                "FILL_BUY_EFFECT_COUNT_MISMATCH",
                "CRITICAL",
                fill=fill,
                expected=1,
                actual=buyer_count,
                unit="COUNT",
            )
        if seller_count != 1:
            cls._add(
                run,
                "FILL_SELL_EFFECT_COUNT_MISMATCH",
                "CRITICAL",
                fill=fill,
                expected=1,
                actual=seller_count,
                unit="COUNT",
            )

    @classmethod
    def _wallet_effect(
        cls,
        run,
        prefix,
        entries,
        user_id,
        amount,
        entry_type,
        *,
        fill=None,
        market_id=None,
        reserved=False,
    ):
        if len(entries) != 1:
            cls._add(
                run,
                f"{prefix}_EFFECT_COUNT_MISMATCH",
                "CRITICAL",
                fill=fill,
                participant_id=user_id,
                expected=1,
                actual=len(entries),
                unit="COUNT",
                market_id=market_id,
            )
            return
        entry = entries[0]
        valid = (
            entry.wallet.user_id == user_id
            and entry.entry_type == entry_type
            and entry.amount == amount
            and entry.market_id == market_id
        )
        if reserved:
            valid = valid and (
                entry.reserved_balance_after == entry.reserved_balance_before - entry.amount
                and entry.available_balance_after == entry.available_balance_before
            )
        elif entry_type == LedgerEntry.EntryType.CREDIT:
            valid = valid and (
                entry.available_balance_after == entry.available_balance_before + entry.amount
                and entry.reserved_balance_after == entry.reserved_balance_before
            )
        if not valid:
            cls._add(
                run,
                f"{prefix}_EFFECT_MISMATCH",
                "CRITICAL",
                fill=fill,
                participant_id=user_id,
                expected=amount,
                actual=entry.amount,
                unit=entry.wallet.currency,
                market_id=market_id,
            )

    @classmethod
    def _settlements(cls, run, scoped):
        for record in scoped["settlements"]:
            market = record.market_settlement.market
            gross = (
                cls._money(record.settled_quantity * record.payout_per_unit)
                if record.was_winner
                else Decimal("0.0000")
            )
            fees = cls._final_fee_entries(
                record.market_position_id, record.participant_id, "SETTLEMENT"
            )
            rate = fees[0].rate_bps if len(fees) == 1 else 0
            fee = MarketFeeService.calculate_fee(gross, rate)
            cls._final_values(
                run,
                "SETTLEMENT",
                record.participant_id,
                market.id,
                (
                    (record.payout_amount, gross),
                    (record.payout_fee_amount, fee),
                    (record.net_payout_amount, gross - fee),
                ),
            )
            expected_fee_count = 1 if gross else 0
            if len(fees) != expected_fee_count:
                cls._add(
                    run,
                    "SETTLEMENT_FEE_RECORD_COUNT_MISMATCH",
                    "ERROR",
                    participant_id=record.participant_id,
                    expected=expected_fee_count,
                    actual=len(fees),
                    unit="COUNT",
                    market_id=market.id,
                )
            if fees:
                cls._final_fee(run, "SETTLEMENT", fees[0], record.participant_id, gross, market.id)
            reference = MarketSettlementService.payout_idempotency_reference(
                market_id=market.id,
                position_id=record.market_position_id,
                winning_outcome_id=record.market_settlement.winning_outcome_id,
                payout_per_unit=record.payout_per_unit,
            )
            entries = list(LedgerEntry.objects.filter(idempotency_reference=reference))
            expected_count = 1 if gross - fee > 0 else 0
            if expected_count:
                cls._wallet_effect(
                    run,
                    "SETTLEMENT_WALLET",
                    entries,
                    record.participant_id,
                    gross - fee,
                    LedgerEntry.EntryType.CREDIT,
                    market_id=market.id,
                )
            elif entries:
                cls._add(
                    run,
                    "SETTLEMENT_WALLET_EFFECT_COUNT_MISMATCH",
                    "CRITICAL",
                    participant_id=record.participant_id,
                    expected=0,
                    actual=len(entries),
                    unit="COUNT",
                    market_id=market.id,
                )
            if record.wallet_ledger_entry_id != (entries[0].id if len(entries) == 1 else None):
                cls._add(
                    run,
                    "SETTLEMENT_LEDGER_LINK_MISMATCH",
                    "ERROR",
                    participant_id=record.participant_id,
                    market_id=market.id,
                )

        groups = (
            scoped["settlements"]
            .values_list("market_settlement__market_id", "participant_id")
            .distinct()
        )
        for market_id, participant_id in groups:
            expected = (
                scoped["settlements"]
                .filter(
                    market_settlement__market_id=market_id,
                    participant_id=participant_id,
                    net_payout_amount__gt=0,
                )
                .count()
            )
            actual = LedgerEntry.objects.filter(
                market_id=market_id,
                wallet__user_id=participant_id,
                entry_type=LedgerEntry.EntryType.CREDIT,
                fill__isnull=True,
                order__isnull=True,
            ).count()
            if actual != expected:
                cls._add(
                    run,
                    "DUPLICATE_SETTLEMENT_FINAL_EFFECT",
                    "CRITICAL",
                    participant_id=participant_id,
                    expected=expected,
                    actual=actual,
                    unit="COUNT",
                    market_id=market_id,
                )

    @classmethod
    def _refunds(cls, run, scoped):
        for record in scoped["refunds"]:
            market = record.market_void_refund.market
            gross = record.cost_basis
            fees = cls._final_fee_entries(
                record.market_position_id, record.participant_id, "REFUND"
            )
            rate = fees[0].rate_bps if len(fees) == 1 else 0
            fee = MarketFeeService.calculate_fee(gross, rate)
            cls._final_values(
                run,
                "VOID_REFUND",
                record.participant_id,
                market.id,
                (
                    (record.refund_amount, gross),
                    (record.refund_fee_amount, fee),
                    (record.net_refund_amount, gross - fee),
                ),
            )
            if len(fees) != (1 if gross else 0):
                cls._add(
                    run,
                    "VOID_REFUND_FEE_RECORD_COUNT_MISMATCH",
                    "ERROR",
                    participant_id=record.participant_id,
                    expected=1 if gross else 0,
                    actual=len(fees),
                    unit="COUNT",
                    market_id=market.id,
                )
            if fees:
                cls._final_fee(run, "VOID_REFUND", fees[0], record.participant_id, gross, market.id)
            settlement_fees = MarketFeeLedgerEntry.objects.filter(
                market_id=market.id,
                participant_id=record.participant_id,
                fee_type=MarketFeeLedgerEntry.FeeType.SETTLEMENT,
            ).count()
            if settlement_fees:
                cls._add(
                    run,
                    "VOID_MARKET_SETTLEMENT_FEE_PRESENT",
                    "CRITICAL",
                    participant_id=record.participant_id,
                    expected=0,
                    actual=settlement_fees,
                    unit="COUNT",
                    market_id=market.id,
                )
            reference = MarketVoidRefundService.position_refund_idempotency_reference(
                market_id=market.id,
                position_id=record.market_position_id,
                participant_id=record.participant_id,
                cost_basis=gross,
                currency=record.market_void_refund.refund_currency,
            )
            entries = list(LedgerEntry.objects.filter(idempotency_reference=reference))
            if gross - fee > 0:
                cls._wallet_effect(
                    run,
                    "VOID_REFUND_WALLET",
                    entries,
                    record.participant_id,
                    gross - fee,
                    LedgerEntry.EntryType.CREDIT,
                    market_id=market.id,
                )
            elif entries:
                cls._add(
                    run,
                    "VOID_REFUND_WALLET_EFFECT_COUNT_MISMATCH",
                    "CRITICAL",
                    participant_id=record.participant_id,
                    expected=0,
                    actual=len(entries),
                    unit="COUNT",
                    market_id=market.id,
                )
            if record.wallet_credit_ledger_entry_id != (
                entries[0].id if len(entries) == 1 else None
            ):
                cls._add(
                    run,
                    "VOID_REFUND_LEDGER_LINK_MISMATCH",
                    "ERROR",
                    participant_id=record.participant_id,
                    market_id=market.id,
                )

        groups = (
            scoped["refunds"]
            .values_list("market_void_refund__market_id", "participant_id")
            .distinct()
        )
        for market_id, participant_id in groups:
            expected = (
                scoped["refunds"]
                .filter(
                    market_void_refund__market_id=market_id,
                    participant_id=participant_id,
                    net_refund_amount__gt=0,
                )
                .count()
            )
            actual = LedgerEntry.objects.filter(
                market_id=market_id,
                wallet__user_id=participant_id,
                entry_type=LedgerEntry.EntryType.CREDIT,
                fill__isnull=True,
                order__isnull=True,
            ).count()
            if actual != expected:
                cls._add(
                    run,
                    "DUPLICATE_VOID_REFUND_FINAL_EFFECT",
                    "CRITICAL",
                    participant_id=participant_id,
                    expected=expected,
                    actual=actual,
                    unit="COUNT",
                    market_id=market_id,
                )

    @staticmethod
    def _final_fee_entries(position_id, participant_id, fee_type):
        return list(
            MarketFeeLedgerEntry.objects.filter(
                idempotency_reference=uuid5(position_id, f"fee:{fee_type}:{participant_id}")
            ).select_related("schedule")
        )

    @classmethod
    def _final_values(cls, run, prefix, participant_id, market_id, values):
        for suffix, (actual, expected) in zip(
            ("GROSS_MISMATCH", "FEE_AMOUNT_MISMATCH", "NET_MISMATCH"), values, strict=True
        ):
            if actual != expected:
                cls._add(
                    run,
                    f"{prefix}_{suffix}",
                    "ERROR",
                    participant_id=participant_id,
                    expected=expected,
                    actual=actual,
                    unit="UGX",
                    market_id=market_id,
                )

    @classmethod
    def _final_fee(cls, run, prefix, entry, participant_id, gross, market_id):
        rate = 0
        version = 0
        if entry.schedule_id:
            version = entry.schedule.version
            rate = (
                entry.schedule.settlement_fee_bps
                if prefix == "SETTLEMENT"
                else entry.schedule.refund_fee_bps
            )
        fee_type = (
            MarketFeeLedgerEntry.FeeType.SETTLEMENT
            if prefix == "SETTLEMENT"
            else MarketFeeLedgerEntry.FeeType.REFUND
        )
        fee = MarketFeeService.calculate_fee(gross, rate)
        valid = (
            entry.participant_id == participant_id
            and entry.market_id == market_id
            and entry.fee_type == fee_type
            and entry.rate_bps == rate
            and entry.schedule_version == version
            and entry.gross_amount == gross
            and entry.fee_amount == fee
            and entry.net_amount == gross - fee
            and entry.currency == MarketFeeService.CURRENCY
        )
        if not valid:
            cls._add(
                run,
                f"{prefix}_FEE_SNAPSHOT_MISMATCH",
                "ERROR",
                participant_id=participant_id,
                expected=fee,
                actual=entry.fee_amount,
                unit=entry.currency,
                market_id=market_id,
            )

    @classmethod
    def _adjustments(cls, run, scoped):
        for line in scoped["adjustments"]:
            entries = list(
                LedgerEntry.objects.filter(idempotency_reference=line.idempotency_reference)
            )
            approved = line.adjustment.status == line.adjustment.Status.APPROVED
            if approved and (
                len(entries) != 1
                or line.wallet_ledger_entry_id != (entries[0].id if entries else None)
            ):
                cls._add(
                    run,
                    "ADJUSTMENT_LEDGER_EFFECT_MISMATCH",
                    "CRITICAL",
                    wallet=line.wallet,
                    expected=1,
                    actual=len(entries),
                    unit="COUNT",
                    market_id=line.adjustment.market_id,
                )
            if not approved and entries:
                cls._add(
                    run,
                    "UNAPPROVED_ADJUSTMENT_EFFECT",
                    "CRITICAL",
                    wallet=line.wallet,
                    expected=0,
                    actual=len(entries),
                    unit="COUNT",
                    market_id=line.adjustment.market_id,
                )

    @classmethod
    def _positions(cls, run, scoped):
        for position in scoped["positions"]:
            if (
                position.quantity < 0
                or position.reserved_quantity < 0
                or position.reserved_quantity > position.quantity
            ):
                cls._add(
                    run,
                    "POSITION_QUANTITY_INCONSISTENT",
                    "CRITICAL",
                    participant_id=position.user_id,
                    expected=position.quantity,
                    actual=position.reserved_quantity,
                    unit="QUANTITY",
                    market_id=position.market_id,
                )
            if position.total_cost < 0 or position.average_entry_price < 0:
                cls._add(
                    run,
                    "POSITION_COST_BASIS_NEGATIVE",
                    "CRITICAL",
                    participant_id=position.user_id,
                    actual=position.total_cost,
                    unit="UGX",
                    market_id=position.market_id,
                )
            expected_cost = (
                Decimal("0.0000")
                if position.quantity == 0
                else cls._money(position.quantity * position.average_entry_price)
            )
            if abs(position.total_cost - expected_cost) > cls.MONEY:
                cls._add(
                    run,
                    "POSITION_TOTAL_COST_MISMATCH",
                    "ERROR",
                    participant_id=position.user_id,
                    expected=expected_cost,
                    actual=position.total_cost,
                    unit="UGX",
                    market_id=position.market_id,
                )
            if position.quantity == 0 and position.average_entry_price != Decimal("0.00000"):
                cls._add(
                    run,
                    "POSITION_AVERAGE_PRICE_MISMATCH",
                    "ERROR",
                    participant_id=position.user_id,
                    expected=0,
                    actual=position.average_entry_price,
                    unit="PRICE",
                    market_id=position.market_id,
                )
            # Realized P&L cannot be safely reconstructed for positions that
            # predate immutable opening snapshots; wallet/finalization effects
            # are reconciled instead.

    @classmethod
    def _add(
        cls,
        run,
        code,
        severity,
        *,
        order=None,
        fill=None,
        wallet=None,
        expected=None,
        actual=None,
        unit="",
        participant_id=None,
        market_id=None,
    ):
        MarketReconciliationMismatch.objects.create(
            run=run,
            code=code,
            severity=severity,
            market_id_snapshot=(
                market_id
                or getattr(order, "market_id", None)
                or getattr(fill, "market_id", None)
                or run.market_id
            ),
            participant_id_snapshot=(
                participant_id
                or getattr(order, "user_id", None)
                or getattr(wallet, "user_id", None)
            ),
            wallet_id_snapshot=getattr(wallet, "id", None),
            order_id_snapshot=getattr(order, "id", None),
            fill_id_snapshot=getattr(fill, "id", None),
            expected_value=cls._decimal(expected),
            actual_value=cls._decimal(actual),
            unit=unit,
            explanation=f"Reconciliation detected {code.lower().replace('_', ' ')}.",
        )

    @classmethod
    def _money(cls, value):
        return Decimal(value).quantize(cls.MONEY, rounding=ROUND_HALF_UP)

    @staticmethod
    def _decimal(value):
        if value is None:
            return None
        try:
            return Decimal(value)
        except (TypeError, ValueError):
            return None
