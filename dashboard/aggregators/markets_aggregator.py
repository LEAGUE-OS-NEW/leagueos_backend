"""Markets aggregator for gathering betting markets data."""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

from dashboard.aggregators.base_aggregator import BaseAggregator

User = get_user_model()
logger = logging.getLogger(__name__)


class MarketsAggregator(BaseAggregator):
    """Aggregates betting markets for the dashboard."""

    module_code = "markets"
    module_name = "Betting Markets"

    def aggregate(self, user: User) -> dict:
        """Aggregate markets data for the user.

        Args:
            user: The user to get markets for

        Returns:
            Markets data dictionary
        """
        try:
            # Check if markets app is available
            try:
                from markets.models import Market
            except ImportError:
                return self._error_response("Markets module not available.")

            # Get featured/open markets
            markets = (
                Market.objects.filter(
                    status__in=["OPEN", "APPROVED"],
                    is_featured=True,
                )
                .select_related("sport", "category")
                .order_by("-created_at")[:10]
            )

            markets_data = [
                {
                    "id": str(market.id),
                    "question": market.question,
                    "sport": market.sport.name,
                    "category": market.category.name if market.category else None,
                    "status": market.status,
                    "closes_at": market.closes_at.isoformat() if market.closes_at else None,
                }
                for market in markets
            ]

            data = {
                "featured_markets": markets_data,
                "count": len(markets_data),
            }

            if not markets_data:
                return self._empty_response(data)

            return self._success_response(data)

        except Exception as e:  # noqa: BLE001
            logger.error("Markets aggregation failed for user %s: %s", user.id, str(e))
            return self._error_response("Markets service temporarily unavailable.")
