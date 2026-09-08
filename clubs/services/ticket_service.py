"""Ticket service for club ticket management."""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from clubs.models import ClubAuditLog, TicketOrder, TicketProduct
from wallets.services.wallet_service import WalletService

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
            action="TICKET_PUBLISHED",
            entity_type="TicketProduct",
            entity_id=product.id,
            metadata={"name": product.name},
        )

        return product

    @classmethod
    def create_order(cls, user, product, quantity=1):
        """Create a ticket order and pay for it from the buyer's wallet."""
        with transaction.atomic():
            locked_product = TicketProduct.objects.select_for_update().get(pk=product.pk)
            cls.validate_sale(locked_product, quantity)

            unit_price = locked_product.price
            total_amount = unit_price * quantity

            order = TicketOrder.objects.create(
                user=user,
                product=locked_product,
                quantity=quantity,
                unit_price=unit_price,
                total_amount=total_amount,
                currency=locked_product.currency,
            )

            ClubAuditLog.objects.create(
                club=locked_product.club,
                user=user,
                action="TICKET_ORDER_CREATED",
                entity_type="TicketOrder",
                entity_id=order.id,
                metadata={"product": locked_product.name, "quantity": quantity},
            )

        # Payment runs in its own transaction: a decline must cancel the
        # order, not roll it out of existence along with the audit trail.
        try:
            WalletService.debit_available(
                user=user,
                currency=order.currency,
                amount=order.total_amount,
                idempotency_reference=order.id,
            )
        except ValidationError:
            order.status = TicketOrder.OrderStatus.CANCELLED
            order.cancelled_at = timezone.now()
            order.save(update_fields=["status", "cancelled_at"])
            raise

        with transaction.atomic():
            order.status = TicketOrder.OrderStatus.PAID
            order.save(update_fields=["status"])

            locked_product = TicketProduct.objects.select_for_update().get(pk=product.pk)
            locked_product.sold += quantity
            if locked_product.capacity and locked_product.sold >= locked_product.capacity:
                locked_product.status = TicketProduct.Status.SOLD_OUT
            locked_product.save(update_fields=["sold", "status"])

            ClubAuditLog.objects.create(
                club=locked_product.club,
                user=user,
                action="TICKET_ORDER_PAID",
                entity_type="TicketOrder",
                entity_id=order.id,
                metadata={"product": locked_product.name, "amount": str(order.total_amount)},
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

    @staticmethod
    def check_in(order, user):
        """Redeem a ticket order at the door."""
        if order.status not in (TicketOrder.OrderStatus.PAID, TicketOrder.OrderStatus.FULFILLED):
            raise ValueError("Ticket order has not been paid for.")

        if order.checked_in_at is not None:
            raise ValueError("Ticket has already been checked in.")

        order.checked_in_at = timezone.now()
        order.checked_in_by = user
        order.status = TicketOrder.OrderStatus.FULFILLED
        order.fulfilled_at = order.checked_in_at
        order.save(update_fields=["checked_in_at", "checked_in_by", "status", "fulfilled_at"])

        ClubAuditLog.objects.create(
            club=order.product.club,
            user=user,
            action="TICKET_SCANNED",
            entity_type="TicketOrder",
            entity_id=order.id,
            metadata={"product": order.product.name, "code": order.code},
        )

        return order


ticket_service = TicketService()
