"""Inventory service for club merchandise inventory management."""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import F

from clubs.models import ClubAuditLog, InventoryAdjustment, MerchandiseProduct

logger = logging.getLogger(__name__)


class InventoryService:
    """Service for inventory operations."""

    @staticmethod
    def adjust_stock(product, adjustment_type, quantity_change, user, reason=""):
        """Adjust product stock."""
        if quantity_change == 0:
            raise ValueError("Quantity change cannot be zero.")

        previous_stock = product.stock
        new_stock = previous_stock + quantity_change

        if new_stock < 0:
            raise ValueError("New stock cannot be negative.")

        with transaction.atomic():
            adjustment = InventoryAdjustment.objects.create(
                product=product,
                adjustment_type=adjustment_type,
                quantity_change=quantity_change,
                previous_stock=previous_stock,
                new_stock=new_stock,
                reason=reason,
                performed_by=user,
            )

            product.stock = new_stock
            product.save(update_fields=["stock"])

            ClubAuditLog.objects.create(
                club=product.club,
                user=user,
                action="INVENTORY_UPDATED",
                entity_type="InventoryAdjustment",
                entity_id=adjustment.id,
                metadata={
                    "product": product.name,
                    "type": adjustment_type,
                    "change": quantity_change,
                    "new_stock": new_stock,
                },
            )

        return adjustment

    @staticmethod
    def get_stock_levels(club):
        """Get stock levels for all products in a club."""
        return MerchandiseProduct.objects.filter(club=club).select_related("category")

    @staticmethod
    def get_low_stock_products(club):
        """Get products with low stock."""
        return MerchandiseProduct.objects.filter(
            club=club,
            available_stock__lte=F("low_stock_threshold"),
        )

    @staticmethod
    def get_inventory_history(product):
        """Get adjustment history for a product."""
        return InventoryAdjustment.objects.filter(product=product).order_by("-created_at")


inventory_service = InventoryService()
