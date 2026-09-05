"""Store service for club merchandise management."""

from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID, uuid5

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from clubs.models import (
    ClubAuditLog,
    MerchandiseProduct,
    ProductCategory,
    StoreOrder,
    StoreOrderItem,
    StoreOrderStatusHistory,
)
from wallets.services.wallet_service import WalletService
from wallets.models import LedgerEntry, WalletTransaction

logger = logging.getLogger(__name__)


class StoreService:
    """Service for store operations."""

    CHECKOUT_NAMESPACE = UUID("542584c2-980e-49c5-a7b7-2bbad8445b2b")

    @classmethod
    @transaction.atomic
    def checkout(cls, *, user, items_data, idempotency_key, shipping_address=None, metadata=None):
        key = UUID(str(idempotency_key))
        existing = list(
            StoreOrder.objects.filter(user=user, checkout_idempotency_key=key)
            .select_related("payment_transaction", "club")
            .prefetch_related("items__product")
        )
        if existing:
            return existing

        quantities = {}
        variants = {}
        for item in items_data:
            product_id = item["product"]
            quantities[product_id] = quantities.get(product_id, 0) + item["quantity"]
            variants[product_id] = item.get("size", "")
        products = list(
            MerchandiseProduct.objects.select_for_update()
            .select_related("club")
            .filter(id__in=quantities)
            .order_by("id")
        )
        if len(products) != len(quantities):
            raise ValidationError({"items": "One or more products do not exist."})
        grouped = {}
        total = Decimal("0.00")
        for product in products:
            quantity = quantities[product.id]
            if product.status != MerchandiseProduct.Status.ACTIVE or not product.club.is_active:
                raise ValidationError({"items": f"{product.name} is not orderable."})
            allowed_sizes = product.metadata.get("sizes", [])
            if allowed_sizes and variants[product.id] not in allowed_sizes:
                raise ValidationError({"items": f"Select a valid variant for {product.name}."})
            if product.available_stock < quantity:
                raise ValidationError({"items": f"Insufficient stock for {product.name}."})
            grouped.setdefault(product.club, []).append((product, quantity))
            total += product.price * quantity

        payment = WalletService.spend_available_balance(
            user=user,
            amount=total,
            currency="UGX",
            idempotency_key=key,
            description=f"Store checkout {key}",
        )
        orders = []
        for club, lines in grouped.items():
            order = StoreOrder.objects.create(
                user=user,
                club=club,
                status=StoreOrder.OrderStatus.PAID,
                total_amount=sum((p.price * q for p, q in lines), Decimal("0.00")),
                shipping_address=shipping_address or {},
                metadata=metadata or {},
                checkout_idempotency_key=key,
                checkout_group=key,
                payment_transaction=payment,
            )
            for product, quantity in lines:
                StoreOrderItem.objects.create(
                    order=order, product=product, quantity=quantity, unit_price=product.price
                )
                product.reserved_stock += quantity
                product.save(update_fields=["reserved_stock", "updated_at"])
            StoreOrderStatusHistory.objects.create(
                order=order,
                changed_by=user,
                previous_status=StoreOrder.OrderStatus.PENDING,
                new_status=StoreOrder.OrderStatus.PAID,
                note="Authoritative wallet checkout",
            )
            orders.append(order)
        return orders

    TRANSITIONS = {
        "PAID": {"PROCESSING", "CANCELLED"},
        "PROCESSING": {"READY_FOR_COLLECTION", "SHIPPED", "CANCELLED"},
        "READY_FOR_COLLECTION": {"DELIVERED", "CANCELLED"},
        "SHIPPED": {"DELIVERED"},
    }

    @classmethod
    @transaction.atomic
    def transition_order(cls, *, order, actor, new_status, note="", delivery_reference=""):
        order = StoreOrder.objects.select_for_update().get(pk=order.pk)
        if new_status not in cls.TRANSITIONS.get(order.status, set()):
            raise ValidationError({"status": f"Cannot transition {order.status} to {new_status}."})
        previous = order.status
        order.status = new_status
        if delivery_reference:
            order.delivery_reference = delivery_reference
        if new_status == StoreOrder.OrderStatus.DELIVERED:
            order.fulfilled_at = timezone.now()
            for item in order.items.select_related("product"):
                product = MerchandiseProduct.objects.select_for_update().get(pk=item.product_id)
                product.reserved_stock -= item.quantity
                product.stock -= item.quantity
                product.save(update_fields=["reserved_stock", "stock", "updated_at"])
        elif new_status == StoreOrder.OrderStatus.CANCELLED:
            if not order.payment_transaction_id:
                raise ValidationError({"payment": "A paid order requires its original payment."})
            refund_reference = f"STORE-REFUND-{order.id.hex}"
            refund_transaction, created = WalletTransaction.objects.get_or_create(
                reference=refund_reference,
                defaults={
                    "wallet": order.payment_transaction.wallet,
                    "transaction_type": WalletTransaction.TransactionType.ADJUSTMENT,
                    "amount": order.total_amount,
                    "currency": order.currency,
                    "status": WalletTransaction.Status.COMPLETED,
                    "description": f"Store order refund {order.id}",
                    "completed_at": timezone.now(),
                },
            )
            if not created and (
                refund_transaction.wallet.user_id != order.user_id
                or refund_transaction.amount != order.total_amount
                or refund_transaction.currency != order.currency
            ):
                raise ValidationError({"payment": "The refund reference is inconsistent."})
            WalletService.credit(
                user=order.user,
                currency=order.currency,
                amount=order.total_amount,
                idempotency_reference=uuid5(order.id, "store-order-refund"),
                transaction=refund_transaction,
                counterparty_account=LedgerEntry.AccountType.REVENUE,
            )
            order.refund_transaction = refund_transaction
            order.cancelled_at = timezone.now()
            for item in order.items.select_related("product"):
                product = MerchandiseProduct.objects.select_for_update().get(pk=item.product_id)
                product.reserved_stock -= item.quantity
                product.save(update_fields=["reserved_stock", "updated_at"])
        order.save(
            update_fields=[
                "status",
                "delivery_reference",
                "fulfilled_at",
                "cancelled_at",
                "refund_transaction",
                "updated_at",
            ]
        )
        StoreOrderStatusHistory.objects.create(
            order=order,
            changed_by=actor,
            previous_status=previous,
            new_status=new_status,
            note=note,
        )
        return order

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
    def create_order(
        user,
        club,
        items_data,
        *,
        shipping_address=None,
        metadata=None,
        status=None,
    ):
        """Create a merchandise order."""
        with transaction.atomic():
            order = StoreOrder.objects.create(
                user=user,
                club=club,
                total_amount=0,
                shipping_address=shipping_address or {},
                metadata=metadata or {},
                status=status or StoreOrder.OrderStatus.PENDING,
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
