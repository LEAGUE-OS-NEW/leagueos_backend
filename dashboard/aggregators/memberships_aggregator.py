"""Platform membership aggregator for the fan dashboard."""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

from dashboard.aggregators.base_aggregator import BaseAggregator
from platform_admin.models import PlatformMembershipSubscription

User = get_user_model()
logger = logging.getLogger(__name__)


class MembershipsAggregator(BaseAggregator):
    module_code = "memberships"
    module_name = "Memberships"

    def aggregate(self, user: User) -> dict:
        try:
            subscriptions = (
                PlatformMembershipSubscription.objects.select_related("plan")
                .filter(user=user)
                .order_by("-subscribed_at")[:5]
            )
            memberships = [
                {
                    "id": str(subscription.id),
                    "club_name": "LeagueOS",
                    "tier": subscription.plan.name,
                    "status": subscription.status,
                    "starts_at": subscription.subscribed_at.isoformat(),
                    "expires_at": (
                        subscription.renews_at.isoformat() if subscription.renews_at else None
                    ),
                    "plan_id": str(subscription.plan_id),
                    "benefits": subscription.plan.benefits,
                    "billing_period": subscription.plan.billing_period,
                }
                for subscription in subscriptions
            ]

            data = {"memberships": memberships}
            if not memberships:
                return self._empty_response(data)

            return self._success_response(data)
        except Exception as e:  # noqa: BLE001
            logger.error("Membership aggregation failed for user %s: %s", user.id, str(e))
            return self._error_response("Membership service temporarily unavailable.")
