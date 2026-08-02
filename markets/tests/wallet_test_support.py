from decimal import Decimal

from wallets.models import Wallet


def fund_market_wallet(user) -> Wallet:
    return Wallet.objects.create(
        user=user,
        currency="UGX",
        available_balance=Decimal("1000000.0000"),
        reserved_balance=Decimal("0.0000"),
    )
