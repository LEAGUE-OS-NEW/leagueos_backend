"""Wallet aggregator for gathering wallet/balance data."""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

from dashboard.aggregators.base_aggregator import BaseAggregator

User = get_user_model()
logger = logging.getLogger(__name__)


class WalletAggregator(BaseAggregator):
    """Aggregates wallet information for the dashboard."""

    module_code = "wallet"
    module_name = "Wallet"

    def aggregate(self, user: User) -> dict:
        """Aggregate wallet data for the user.

        Args:
            user: The user to get wallet data for

        Returns:
            Wallet data dictionary
        """
        try:
            # Check if wallet model exists (for future wallet module)
            wallet_data = {
                "balance": None,
                "currency": "USD",
                "transactions_count": 0,
            }

            # Try to get wallet if available
            if hasattr(user, "wallet"):
                wallet = user.wallet
                wallet_data = {
                    "balance": str(wallet.balance) if hasattr(wallet, "balance") else None,
                    "currency": getattr(wallet, "currency", "USD"),
                    "transactions_count": getattr(wallet, "transactions_count", 0),
                }
            # Future: Add integration with actual wallet module
            # For now, return empty structure
            data = wallet_data

            return self._success_response(data)

        except Exception as e:  # noqa: BLE001
            logger.error("Wallet aggregation failed for user %s: %s", user.id, str(e))
            return self._error_response("Wallet service temporarily unavailable.")
