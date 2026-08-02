"""Dashboard aggregation service.

Orchestrates data gathering from multiple modules with graceful degradation.
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import get_user_model

from dashboard.aggregators import (
    BaseAggregator,
    FavouritesAggregator,
    FixturesAggregator,
    MarketsAggregator,
    NotificationsAggregator,
    ProfileAggregator,
    WalletAggregator,
)

User = get_user_model()
logger = logging.getLogger(__name__)


class DashboardAggregationService:
    """Service for aggregating dashboard data from multiple modules.

    Coordinates data gathering from all modules while ensuring graceful
    degradation - if one module fails, the dashboard continues loading.
    """

    # List of aggregators to run for the dashboard
    AGGREGATORS = [
        ProfileAggregator,
        NotificationsAggregator,
        FavouritesAggregator,
        FixturesAggregator,
        MarketsAggregator,
        WalletAggregator,
    ]

    @classmethod
    def get_aggregated_data(cls, user: User) -> dict[str, Any]:
        """Get aggregated dashboard data from all modules.

        Args:
            user: The user to get dashboard data for

        Returns:
            Dictionary with module data and overall status
        """
        results = {}
        failed_modules = []

        # Run each aggregator independently
        for aggregator_class in cls.AGGREGATORS:
            aggregator: BaseAggregator = aggregator_class()
            try:
                result = aggregator.aggregate(user)
                module_code = aggregator.module_code
                results[module_code] = result

                if result.get("status") == "unavailable":
                    failed_modules.append(module_code)

            except Exception as e:  # noqa: BLE001
                logger.error(
                    "Aggregator %s failed for user %s: %s",
                    aggregator.module_code,
                    user.id,
                    str(e),
                )
                results[aggregator.module_code] = {
                    "status": "unavailable",
                    "module": aggregator.module_code,
                    "message": f"{aggregator.module_name} service temporarily unavailable.",
                }
                failed_modules.append(aggregator.module_code)

        # Build response
        response = {
            "modules": results,
            "metadata": {
                "total_modules": len(cls.AGGREGATORS),
                "successful_modules": len(cls.AGGREGATORS) - len(failed_modules),
                "failed_modules": failed_modules,
                "has_failures": bool(failed_modules),
            },
        }

        if failed_modules:
            logger.warning(
                "Dashboard partial failure for user %s: %d modules failed",
                user.id,
                len(failed_modules),
            )

        return response