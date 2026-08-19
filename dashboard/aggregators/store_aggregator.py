"""Store aggregator for fan dashboard merchandise picks."""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.db.models import F

from clubs.models import MerchandiseProduct
from dashboard.aggregators.base_aggregator import BaseAggregator

User = get_user_model()
logger = logging.getLogger(__name__)


class StoreAggregator(BaseAggregator):
    """Aggregates public merchandise picks for the dashboard."""

    module_code = "store"
    module_name = "Store Picks"

    def aggregate(self, user: User) -> dict:
        try:
            followed_club_ids = []
            if hasattr(user, "club_preferences"):
                followed_club_ids = list(
                    user.club_preferences.values_list("club_id", flat=True)[:20]
                )

            queryset = MerchandiseProduct.objects.filter(
                status=MerchandiseProduct.Status.ACTIVE,
                stock__gt=F("reserved_stock"),
                club__is_active=True,
            ).select_related("club")

            followed_products = []
            if followed_club_ids:
                followed_products = list(
                    queryset.filter(club_id__in=followed_club_ids).order_by(
                        "-is_featured", "-created_at"
                    )[:4]
                )

            products = followed_products or list(
                queryset.order_by("-is_featured", "-created_at")[:4]
            )

            picks = [
                {
                    "id": str(product.id),
                    "name": product.name,
                    "price": str(product.price),
                    "currency": product.currency,
                    "image": product.metadata.get("image") or "",
                    "club": product.club.name,
                    "club_slug": product.club.slug,
                }
                for product in products
            ]

            data = {"picks": picks}
            if not picks:
                return self._empty_response(data)

            return self._success_response(data)
        except Exception as e:  # noqa: BLE001
            logger.error("Store aggregation failed for user %s: %s", user.id, str(e))
            return self._error_response("Store service temporarily unavailable.")
