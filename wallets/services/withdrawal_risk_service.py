"""Risk-based automatic approval for wallet withdrawals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from wallets.models import WithdrawalRequest

POLICY_VERSION = "withdrawal-auto-v1"


@dataclass(frozen=True)
class WithdrawalRiskDecision:
    risk_status: str
    auto_approve: bool
    reasons: tuple[str, ...]
    policy_version: str = POLICY_VERSION


class WithdrawalRiskService:
    """Evaluate whether a reserved withdrawal may skip manual approval."""

    @staticmethod
    def _canonical_destination(destination: dict) -> str:
        return json.dumps(
            destination,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def _has_known_destination(cls, withdrawal) -> bool:
        target = cls._canonical_destination(withdrawal.destination)

        previous = (
            WithdrawalRequest.objects.filter(
                wallet__user=withdrawal.wallet.user,
                status=WithdrawalRequest.Status.COMPLETED,
            )
            .exclude(pk=withdrawal.pk)
            .values_list("destination", flat=True)
        )

        return any(cls._canonical_destination(destination) == target for destination in previous)

    @classmethod
    def evaluate(
        cls,
        withdrawal: WithdrawalRequest,
    ) -> WithdrawalRiskDecision:
        now = timezone.now()
        user = withdrawal.wallet.user
        amount = Decimal(withdrawal.amount)

        reasons: list[str] = []

        if not user.is_active:
            reasons.append("ACCOUNT_INACTIVE")

        if not user.is_verified:
            reasons.append("IDENTITY_NOT_VERIFIED")

        if withdrawal.wallet.status != withdrawal.wallet.Status.ACTIVE:
            reasons.append("WALLET_NOT_ACTIVE")

        if amount > settings.WALLET_WITHDRAWAL_AUTO_APPROVAL_MAX_SINGLE_UGX:
            reasons.append("AMOUNT_ABOVE_AUTO_APPROVAL_LIMIT")

        prior_24h = WithdrawalRequest.objects.filter(
            wallet__user=user,
            created_at__gte=now - timezone.timedelta(hours=24),
        ).exclude(pk=withdrawal.pk)

        prior_24h_count = prior_24h.count()

        if prior_24h_count + 1 > settings.WALLET_WITHDRAWAL_AUTO_APPROVAL_MAX_24H_COUNT:
            reasons.append("WITHDRAWAL_COUNT_24H_LIMIT")

        prior_24h_total = prior_24h.aggregate(total=Sum("amount"))["total"] or Decimal("0")

        if prior_24h_total + amount > settings.WALLET_WITHDRAWAL_AUTO_APPROVAL_MAX_24H_UGX:
            reasons.append("WITHDRAWAL_VALUE_24H_LIMIT")

        prior_7d = WithdrawalRequest.objects.filter(
            wallet__user=user,
            created_at__gte=now - timezone.timedelta(days=7),
        ).exclude(pk=withdrawal.pk)

        prior_7d_total = prior_7d.aggregate(total=Sum("amount"))["total"] or Decimal("0")

        if prior_7d_total + amount > settings.WALLET_WITHDRAWAL_AUTO_APPROVAL_MAX_7D_UGX:
            reasons.append("WITHDRAWAL_VALUE_7D_LIMIT")

        require_known_destination = (
            settings.WALLET_WITHDRAWAL_AUTO_APPROVAL_REQUIRE_KNOWN_DESTINATION
        )

        if require_known_destination and not cls._has_known_destination(withdrawal):
            reasons.append("NEW_WITHDRAWAL_DESTINATION")

        recent_failed = (
            WithdrawalRequest.objects.filter(
                wallet__user=user,
                status=WithdrawalRequest.Status.FAILED,
                created_at__gte=now - timezone.timedelta(days=7),
            )
            .exclude(pk=withdrawal.pk)
            .exists()
        )

        if recent_failed:
            reasons.append("RECENT_FAILED_WITHDRAWAL")

        risk_status = (
            WithdrawalRequest.RiskStatus.FLAGGED if reasons else WithdrawalRequest.RiskStatus.PASSED
        )

        auto_approve = (
            bool(settings.WALLET_WITHDRAWAL_AUTO_APPROVAL_ENABLED)
            and risk_status == WithdrawalRequest.RiskStatus.PASSED
        )

        return WithdrawalRiskDecision(
            risk_status=risk_status,
            auto_approve=auto_approve,
            reasons=tuple(reasons),
        )
