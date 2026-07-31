from django.core.exceptions import ValidationError
from django.db import transaction

from markets.models import (
    Market,
    MarketOutcome,
)


class MarketCatalogService:
    @classmethod
    @transaction.atomic
    def create_market(
        cls,
        *,
        yes_label: str = "Yes",
        no_label: str = "No",
        **market_data,
    ) -> Market:
        market = Market(**market_data)
        market.full_clean()
        market.save()

        outcome_values = [
            {
                "side": MarketOutcome.Side.YES,
                "position": 1,
                "label": yes_label,
            },
            {
                "side": MarketOutcome.Side.NO,
                "position": 2,
                "label": no_label,
            },
        ]

        for outcome_data in outcome_values:
            outcome = MarketOutcome(
                market=market,
                **outcome_data,
            )
            outcome.full_clean()
            outcome.save()

        cls.validate_market_ready(market)

        return market

    @staticmethod
    def validate_market_ready(
        market: Market,
    ) -> None:
        if not market.has_complete_outcomes:
            raise ValidationError(
                {"outcomes": ("A market requires exactly one " "YES outcome and one NO outcome.")}
            )
