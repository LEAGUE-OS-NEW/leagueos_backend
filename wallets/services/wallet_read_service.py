from django.core.exceptions import ValidationError

from wallets.models import (
    LedgerEntry,
    Receipt,
    Wallet,
    WalletTransaction,
    WithdrawalRequest,
)


class WalletReadService:
    @staticmethod
    def normalize_currency(currency) -> str:
        normalized = str(currency or "").strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValidationError(
                {"currency": "Currency must be exactly three alphabetic characters."}
            )
        return normalized

    @classmethod
    def list_wallets(cls, *, user):
        return Wallet.objects.filter(user=user).order_by("currency", "id")

    @classmethod
    def get_wallet(cls, *, user, currency):
        normalized = cls.normalize_currency(currency)
        return Wallet.objects.filter(user=user, currency=normalized).first()

    @classmethod
    def list_ledger_entries(cls, *, user, currency, filters=None):
        wallet = cls.get_wallet(user=user, currency=currency)
        if wallet is None:
            return None, LedgerEntry.objects.none()

        filters = filters or {}
        queryset = LedgerEntry.objects.filter(wallet=wallet)
        if filters.get("entry_type"):
            queryset = queryset.filter(entry_type=filters["entry_type"])
        for field in ("market_id", "order_id", "fill_id"):
            if filters.get(field):
                queryset = queryset.filter(**{field: filters[field]})
        if filters.get("debit_account"):
            queryset = queryset.filter(debit_account=filters["debit_account"])
        if filters.get("credit_account"):
            queryset = queryset.filter(credit_account=filters["credit_account"])
        if filters.get("created_from"):
            queryset = queryset.filter(created_at__gte=filters["created_from"])
        if filters.get("created_to"):
            queryset = queryset.filter(created_at__lte=filters["created_to"])

        return wallet, queryset.order_by("-created_at", "-id")

    @classmethod
    def list_transactions(cls, *, user, **filters):
        """List wallet transactions scoped to the user."""
        queryset = WalletTransaction.objects.filter(wallet__user=user).select_related(
            "provider", "wallet"
        )
        currency = filters.get("currency")
        if currency:
            normalized = cls.normalize_currency(currency)
            queryset = queryset.filter(wallet__currency=normalized)
        return queryset.order_by("-created_at")

    @classmethod
    def list_withdrawals(cls, *, user, filters=None):
        """List withdrawal requests scoped to the user."""
        filters = filters or {}

        queryset = WithdrawalRequest.objects.filter(
            wallet__user=user,
        ).select_related(
            "wallet",
            "transaction",
            "approved_by",
        )

        status = filters.get("status")
        if status:
            queryset = queryset.filter(
                status=status,
            )

        currency = filters.get("currency")
        if currency:
            normalized = cls.normalize_currency(
                currency,
            )
            queryset = queryset.filter(
                wallet__currency=normalized,
            )

        created_from = filters.get("created_from")
        if created_from:
            queryset = queryset.filter(
                created_at__gte=created_from,
            )

        created_to = filters.get("created_to")
        if created_to:
            queryset = queryset.filter(
                created_at__lte=created_to,
            )

        return queryset.order_by(
            "-created_at",
            "-id",
        )

    @classmethod
    def get_transaction(cls, *, user, transaction_id):
        """Get a transaction scoped to the user."""
        try:
            return WalletTransaction.objects.select_related("provider", "wallet").get(
                id=transaction_id,
                wallet__user=user,
            )
        except WalletTransaction.DoesNotExist:
            from django.http import Http404

            raise Http404 from None

    @classmethod
    def get_receipt_download_url(cls, *, user, transaction_id):
        """Get the download URL for a receipt scoped to the user."""
        try:
            receipt = Receipt.objects.get(
                transaction_id=transaction_id,
                transaction__wallet__user=user,
            )
        except Receipt.DoesNotExist:
            return None
        return receipt.file_url or None
