from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import uuid5

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from authentication.services.permission_service import PermissionService
from markets.models import (
    MarketFinancialAdjustment,
    MarketFinancialAdjustmentApproval,
    MarketFinancialAdjustmentLine,
)
from wallets.models import Wallet
from wallets.services.wallet_service import WalletService


class MarketFinancialAdjustmentService:
    CURRENCY = "UGX"
    MONEY_QUANTUM = Decimal("0.0001")

    @classmethod
    @transaction.atomic
    def propose(
        cls,
        *,
        actor,
        reason,
        evidence_reference,
        currency,
        lines,
        market=None,
        mismatch=None,
    ):
        cls._permission(actor, "manage_market")
        reason = str(reason or "").strip()
        evidence_reference = str(evidence_reference or "").strip()
        currency = str(currency or "").strip().upper()
        if not reason:
            raise ValidationError({"reason": "A reason is required."})
        if not evidence_reference:
            raise ValidationError({"evidence_reference": "Evidence is required."})
        if currency != cls.CURRENCY:
            raise ValidationError({"currency": f"Only {cls.CURRENCY} adjustments are supported."})
        normalized_lines = cls._validate_lines(lines)
        wallet_ids = [line["wallet_id"] for line in normalized_lines]
        if len(wallet_ids) != len(set(wallet_ids)):
            raise ValidationError({"lines": "Each wallet may appear only once."})
        if mismatch and market and mismatch.market_id_snapshot not in (None, market.id):
            raise ValidationError({"mismatch": "Mismatch and adjustment market scopes differ."})

        wallets = list(
            Wallet.objects.select_for_update()
            .select_related("user")
            .filter(id__in=wallet_ids)
            .order_by("id")
        )
        if len(wallets) != len(wallet_ids):
            raise ValidationError({"lines": "Every adjustment wallet must exist."})
        if any(wallet.currency != currency for wallet in wallets):
            raise ValidationError({"currency": "Every wallet must match the adjustment currency."})
        wallets_by_id = {wallet.id: wallet for wallet in wallets}

        adjustment = MarketFinancialAdjustment.objects.create(
            reason=reason,
            evidence_reference=evidence_reference,
            currency=currency,
            market=market,
            mismatch=mismatch,
            proposed_by=actor,
        )
        for index, line in enumerate(normalized_lines):
            MarketFinancialAdjustmentLine.objects.create(
                adjustment=adjustment,
                wallet=wallets_by_id[line["wallet_id"]],
                direction=line["direction"],
                amount=line["amount"],
                idempotency_reference=uuid5(adjustment.id, f"line:{index}"),
            )
        from notifications.services.operational_alert_service import OperationalAlertService

        OperationalAlertService.create(
            permissions=("approve_market",),
            event_type="FINANCIAL_ADJUSTMENT_PENDING",
            title="Financial adjustment awaiting approval",
            message="A financial adjustment requires independent approval.",
            source_key=f"market-adjustment:{adjustment.id}:pending",
            data={"adjustment_id": str(adjustment.id)},
            severity="CRITICAL",
        )
        return adjustment

    @classmethod
    @transaction.atomic
    def decide(cls, *, adjustment_id, actor, decision, notes=""):
        cls._permission(actor, "approve_market")
        adjustment = (
            MarketFinancialAdjustment._base_manager.select_for_update(of=("self",))
            .select_related("proposed_by")
            .get(id=adjustment_id)
        )
        if adjustment.status != MarketFinancialAdjustment.Status.PENDING:
            if hasattr(adjustment, "approval") and adjustment.approval.decision == decision:
                return adjustment
            raise ValidationError({"status": "This adjustment has already been decided."})
        if adjustment.proposed_by_id == actor.id:
            raise ValidationError({"actor": "The proposer cannot decide their own adjustment."})
        if decision not in MarketFinancialAdjustmentApproval.Decision.values:
            raise ValidationError({"decision": "A valid decision is required."})

        lines = list(
            MarketFinancialAdjustmentLine._base_manager.select_for_update()
            .select_related("wallet", "wallet__user")
            .filter(adjustment=adjustment)
            .order_by("wallet_id", "id")
        )
        cls._lock_wallets(lines)
        if decision == MarketFinancialAdjustmentApproval.Decision.APPROVED:
            cls._execute(adjustment, lines)
            adjustment.status = MarketFinancialAdjustment.Status.APPROVED
            adjustment.executed_at = timezone.now()
        else:
            adjustment.status = MarketFinancialAdjustment.Status.REJECTED
        adjustment.save(
            update_fields=["status", "executed_at", "updated_at"],
            _service_transition=True,
        )
        MarketFinancialAdjustmentApproval.objects.create(
            adjustment=adjustment,
            decided_by=actor,
            decision=decision,
            notes=str(notes or "").strip(),
        )
        if decision == MarketFinancialAdjustmentApproval.Decision.APPROVED:
            from markets.services.market_notification_service import MarketNotificationService

            for line in lines:
                MarketNotificationService.schedule(
                    recipient=line.wallet.user,
                    category="MARKET_SETTLEMENTS",
                    event_type="FINANCIAL_ADJUSTMENT_APPROVED",
                    title="Financial adjustment completed",
                    message=(
                        f"An approved {line.direction.lower()} adjustment "
                        f"of {line.amount} was applied."
                    ),
                    key=f"market-adjustment:{adjustment.id}:participant:{line.wallet.user_id}",
                    market_id=adjustment.market_id,
                    data={
                        "adjustment_id": str(adjustment.id),
                        "direction": line.direction,
                        "amount": str(line.amount),
                    },
                    mandatory=True,
                )
        return adjustment

    @staticmethod
    def _lock_wallets(lines):
        wallet_ids = sorted({line.wallet_id for line in lines})
        locked = list(
            Wallet.objects.select_for_update()
            .filter(id__in=wallet_ids)
            .order_by("id")
            .values_list("id", flat=True)
        )
        if locked != wallet_ids:
            raise ValidationError({"lines": "An adjustment wallet no longer exists."})

    @staticmethod
    def _execute(adjustment, lines):
        for line in lines:
            kwargs = {
                "user": line.wallet.user,
                "currency": adjustment.currency,
                "amount": line.amount,
                "idempotency_reference": line.idempotency_reference,
            }
            if line.direction == MarketFinancialAdjustmentLine.Direction.DEBIT:
                entry = WalletService.debit_available(**kwargs)
            else:
                entry = WalletService.credit(**kwargs)
            line.wallet_ledger_entry = entry
            line.save(
                update_fields=["wallet_ledger_entry", "updated_at"],
                _service_link=True,
            )

    @classmethod
    def _validate_lines(cls, lines):
        if not isinstance(lines, list) or len(lines) < 2:
            raise ValidationError({"lines": "At least two balanced lines are required."})
        debits = credits = Decimal("0.0000")
        normalized = []
        for line in lines:
            if not isinstance(line, dict) or "wallet_id" not in line:
                raise ValidationError({"lines": "Each line requires a wallet."})
            amount = cls._amount(line.get("amount"))
            direction = line.get("direction")
            if direction == MarketFinancialAdjustmentLine.Direction.DEBIT:
                debits += amount
            elif direction == MarketFinancialAdjustmentLine.Direction.CREDIT:
                credits += amount
            else:
                raise ValidationError({"lines": "Line direction must be DEBIT or CREDIT."})
            normalized.append(
                {"wallet_id": line["wallet_id"], "direction": direction, "amount": amount}
            )
        if debits != credits:
            raise ValidationError({"lines": "Total debits and credits must balance."})
        return normalized

    @classmethod
    def _amount(cls, value):
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValidationError({"lines": "Line amounts must be valid decimals."}) from error
        if not amount.is_finite() or amount <= 0:
            raise ValidationError({"lines": "Line amounts must be positive."})
        return amount.quantize(cls.MONEY_QUANTUM, rounding=ROUND_HALF_UP)

    @staticmethod
    def _permission(actor, name):
        if not PermissionService.has_permission(actor, name):
            raise PermissionDenied(f"You do not have the {name} permission.")
