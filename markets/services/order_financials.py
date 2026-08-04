from decimal import ROUND_CEILING, Decimal

MONEY_QUANTUM = Decimal("0.0001")


def calculate_buy_commitment(*, quantity, limit_price, maximum_fee_bps=0):
    notional = Decimal(quantity) * Decimal(limit_price)
    fee = notional * Decimal(maximum_fee_bps) / Decimal("10000")
    return (notional + fee).quantize(
        MONEY_QUANTUM,
        rounding=ROUND_CEILING,
    )
