from decimal import ROUND_CEILING, Decimal

MONEY_QUANTUM = Decimal("0.0001")


def calculate_buy_commitment(*, quantity, limit_price):
    return (Decimal(quantity) * Decimal(limit_price)).quantize(
        MONEY_QUANTUM,
        rounding=ROUND_CEILING,
    )
