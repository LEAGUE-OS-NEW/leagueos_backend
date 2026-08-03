"""Base aggregator class for dashboard data aggregation.

All module aggregators inherit from this base class to ensure
consistent behavior and error handling.
"""

from __future__ import annotations

import logging
from abc import ABC
from typing import Any

from django.contrib.auth import get_user_model

User = get_user_model()
logger = logging.getLogger(__name__)


class BaseAggregator(ABC):  # noqa: B024
    """Base class for all dashboard aggregators.

    Provides common functionality for aggregating data from different modules.
    Each module-specific aggregator should inherit from this class.
    """

    module_code: str = ""
    module_name: str = ""

    def aggregate(self, user: User) -> dict[str, Any]:
        """Aggregate data for the module.

        Args:
            user: The user to aggregate data for

        Returns:
            Dictionary with aggregated data and status
        """
        return self._error_response("Aggregation not implemented for this module.")

    def _success_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """Build successful response.

        Args:
            data: The aggregated data

        Returns:
            Response dictionary with success status
        """
        return {
            "status": "success",
            "module": self.module_code,
            "data": data,
        }

    def _error_response(self, message: str) -> dict[str, Any]:
        """Build error response.

        Args:
            message: Error message

        Returns:
            Response dictionary with error status
        """
        logger.error("Module %s failed: %s", self.module_code, message)
        return {
            "status": "unavailable",
            "module": self.module_code,
            "message": message,
        }

    def _empty_response(self, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build empty response for when module has no data.

        Args:
            data: Optional empty data dictionary

        Returns:
            Response dictionary with empty status
        """
        return {
            "status": "success",
            "module": self.module_code,
            "data": data or {},
            "empty": True,
        }
