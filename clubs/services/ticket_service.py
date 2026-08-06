"""Ticket service for club ticket management."""

from __future__ import annotations

import logging

from django.utils import timezone

from clubs.models import ClubAuditLog, TicketOrder, TicketProduct

logger = logging.getLogger(__name__)


class TicketService:
    """Service for ticket operations."""

    @staticmethod
    def create_product(club, user, **kwargs):
        """Create a new ticket product."""
        product = TicketProduct.objects.create(
            club=club,
            created_by=user,
            **kwargs,
        )

        ClubAuditLog.objects.create(
            club=club,
            user=user,
            action="TICKET_CREATED",
            entity_type="TicketProduct",
            entity_id=product.id,
            metadata={"name": product.name, "price": str(product.price)},
        )

        return product

    @staticmethod
    def publish_product(product, user):
        """Publish a ticket product."""
        if product.status == TicketProduct.Status.ACTIVE:
            return product

        product.status = TicketProduct.Status.ACTIVE
        product.published_at = timezone.now()
        product.published_by = user
        product.save(update_fields=["status", "published_at", "published_by"])

        ClubAuditLog.objects.create(
            club=product.club,
            user=user,
            action="TICKET_CREATED",
            entity_type="TicketProduct",
            entity_id=product.id,
            metadata={"action": "published", "name": product.name},
        )

        return product

    @staticmethod
    def create_order(user, product, quantity=1):
        """Create a ticket order."""
        unit_price = product.price
        total_amount = unit_price * quantity

        order = TicketOrder.objects.create(
            user=user,
            product=product,
            quantity=quantity,
            unit_price=unit_price,
            total_amount=total_amount,
            currency=product.currency,
        )

        # Update sold count
        product.sold += quantity
        if product.capacity and product.sold >= product.capacity:
            product.status = TicketProduct.Status.SOLD_OUT
        product.save(update_fields=["sold", "status"])

        ClubAuditLog.objects.create(
            club=product.club,
            user=user,
            action="TICKET_CREATED",
            entity_type="TicketOrder",
            entity_id=order.id,
            metadata={"product": product.name, "quantity": quantity},
        )

        return order

    @staticmethod
    def validate_sale(product, quantity=1):
        """Validate if product can be sold."""
        if product.status != TicketProduct.Status.ACTIVE:
            raise ValueError("Product is not active.")

        if product.capacity and (product.sold + quantity) > product.capacity:
            raise ValueError("Not enough capacity.")

        now = timezone.now()
        if product.sales_start and now < product.sales_start:
            raise ValueError("Sales have not started.")
        if product.sales_end and now > product.sales_end:
            raise ValueError("Sales have ended.")

        return True


ticket_service = TicketService()
