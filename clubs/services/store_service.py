"""Store service for club merchandise management."""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from clubs.models import (
    ClubAuditLog,
    MerchandiseProduct,
    ProductCategory,
    StoreOrder,
    StoreOrderItem,
)

logger = logging.getLogger(__name__)


class StoreService:
    """Service for store operations."""

    @staticmethod
    def create_category(club, user, **kwargs):
        """Create a new product category."""
        category = ProductCategory.objects.create(
            club=club,
            **kwargs,
        )
        return category

    @staticmethod
    def create_product(club, user, **kwargs):
        """Create a new merchandise product."""
        product = MerchandiseProduct.objects.create(
            club=club,
            created_by=user,
            **kwargs,
        )

        ClubAuditLog.objects.create(
            club=club,
            user=user,
            action="PRODUCT_CREATED",
            entity_type="MerchandiseProduct",
            entity_id=product.id,
            metadata={"name": product.name, "price": str(product.price)},
        )

        return product

    @staticmethod
    def publish_product(product, user):
        """Publish a merchandise product."""
        if product.status == MerchandiseProduct.Status.ACTIVE:
            return product

        product.status = MerchandiseProduct.Status.ACTIVE
        product.published_at = timezone.now()
        product.published_by = user
        product.save(update_fields=["status", "published_at", "published_by"])

        ClubAuditLog.objects.create(
            club=product.club,
            user=user,
            action="PRODUCT_CREATED",
            entity_type="MerchandiseProduct",
            entity_id=product.id,
            metadata={"action": "published", "name": product.name},
        )

        return product

    @staticmethod
    def create_order(user, club, items_data):
        """Create a merchandise order."""
        with transaction.atomic():
            order = StoreOrder.objects.create(
                user=user,
                club=club,
                total_amount=0,
            )

            total = Decimal("0.00")
            for item_data in items_data:
                product = item_data["product"]
                quantity = item_data["quantity"]

                # Validate stock
                if product.available_stock < quantity:
                    raise ValueError(f"Insufficient stock for {product.name}")

                unit_price = product.price
                item_total = unit_price * quantity
                total += item_total

                StoreOrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=quantity,
                    unit_price=unit_price,
                    total_price=item_total,
                )

                # Reserve stock
                product.reserved_stock += quantity
                product.save(update_fields=["reserved_stock"])

            order.total_amount = total
            order.save(update_fields=["total_amount"])

            return order

    @staticmethod
    def fulfill_order(order, user):
        """Fulfill a store order."""
        if order.status == StoreOrder.OrderStatus.FULFILLED:
            return order

        with transaction.atomic():
            order.status = StoreOrder.OrderStatus.FULFILLED
            order.fulfilled_at = timezone.now()
            order.save(update_fields=["status", "fulfilled_at"])

            # Deduct stock
            for item in order.items.select_related("product"):
                product = item.product
                product.reserved_stock -= item.quantity
                product.stock -= item.quantity
                product.save(update_fields=["reserved_stock", "stock"])

            ClubAuditLog.objects.create(
                club=order.club,
                user=user,
                action="PRODUCT_CREATED",
                entity_type="StoreOrder",
                entity_id=order.id,
                metadata={"action": "fulfilled"},
            )

        return order


store_service = StoreService()
