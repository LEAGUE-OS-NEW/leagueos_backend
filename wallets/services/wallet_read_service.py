from django.core.exceptions import ValidationError

from wallets.models import LedgerEntry, Wallet


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
        if filters.get("created_from"):
            queryset = queryset.filter(created_at__gte=filters["created_from"])
        if filters.get("created_to"):
            queryset = queryset.filter(created_at__lte=filters["created_to"])

        return wallet, queryset.order_by("-created_at", "-id")
