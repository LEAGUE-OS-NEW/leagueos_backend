from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from accounts.models import User
from clubs.models import MerchandiseProduct, StoreOrder, StoreOrderItem
from clubs.services.store_service import StoreService
from profiles.models import Club
from wallets.models import WalletTransaction
from wallets.services.wallet_service import WalletService


@pytest.fixture
def checkout_data(db):
    user = User.objects.create_user(username="buyer", email="buyer@example.com", password="x")
    first_club = Club.objects.create(name="First Club", slug="first-club")
    second_club = Club.objects.create(name="Second Club", slug="second-club")
    first = MerchandiseProduct.objects.create(
        club=first_club,
        name="Jersey",
        sku=" shirt-1 ",
        price=Decimal("100.00"),
        stock=2,
        status=MerchandiseProduct.Status.ACTIVE,
    )
    second = MerchandiseProduct.objects.create(
        club=second_club,
        name="Scarf",
        sku="SCARF-1",
        price=Decimal("50.00"),
        stock=2,
        status=MerchandiseProduct.Status.ACTIVE,
    )
    WalletService.credit(
        user=user, currency="UGX", amount=Decimal("1000.00"), idempotency_reference=uuid4()
    )
    return user, first, second


@pytest.mark.django_db
def test_checkout_is_server_priced_multiclub_and_idempotent(checkout_data):
    user, first, second = checkout_data
    key = uuid4()
    items = [{"product": first.id, "quantity": 1}, {"product": second.id, "quantity": 2}]
    orders = StoreService.checkout(user=user, items_data=items, idempotency_key=key)
    replay = StoreService.checkout(user=user, items_data=items, idempotency_key=key)
    assert len(orders) == 2
    assert {order.total_amount for order in orders} == {Decimal("100.00")}
    assert {order.id for order in replay} == {order.id for order in orders}
    assert WalletTransaction.objects.filter(reference=f"SPEND-{key.hex}").count() == 1
    assert StoreOrder.objects.count() == 2


@pytest.mark.django_db
def test_multiclub_failure_rolls_back_wallet_orders_and_stock(checkout_data):
    user, first, second = checkout_data
    wallet = user.wallets.get(currency="UGX")
    original_balance = wallet.available_balance
    real_create = StoreOrderItem.objects.create
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("forced second-club failure")
        return real_create(*args, **kwargs)

    with patch.object(StoreOrderItem.objects, "create", side_effect=fail_second):
        with pytest.raises(RuntimeError):
            StoreService.checkout(
                user=user,
                items_data=[
                    {"product": first.id, "quantity": 1},
                    {"product": second.id, "quantity": 1},
                ],
                idempotency_key=uuid4(),
            )
    wallet.refresh_from_db()
    first.refresh_from_db()
    second.refresh_from_db()
    assert wallet.available_balance == original_balance
    assert StoreOrder.objects.count() == 0
    assert first.reserved_stock == second.reserved_stock == 0


@pytest.mark.django_db
def test_duplicate_normalized_sku_and_no_funds_are_rejected(checkout_data):
    user, first, _ = checkout_data
    with pytest.raises(IntegrityError), transaction.atomic():
        MerchandiseProduct.objects.create(
            club=first.club, name="Duplicate", sku="shirt-1", price=1, stock=1
        )
    with pytest.raises(ValidationError):
        StoreService.checkout(
            user=user, items_data=[{"product": first.id, "quantity": 999}], idempotency_key=uuid4()
        )
    assert not StoreOrder.objects.exists()


@pytest.mark.django_db
def test_paid_cancellation_refunds_once_and_releases_inventory(checkout_data):
    user, product, _ = checkout_data
    order = StoreService.checkout(
        user=user,
        items_data=[{"product": product.id, "quantity": 1}],
        idempotency_key=uuid4(),
    )[0]
    wallet = user.wallets.get(currency="UGX")
    balance_after_purchase = wallet.available_balance

    cancelled = StoreService.transition_order(
        order=order, actor=user, new_status=StoreOrder.OrderStatus.CANCELLED
    )
    wallet.refresh_from_db()
    product.refresh_from_db()
    assert wallet.available_balance == balance_after_purchase + order.total_amount
    assert product.reserved_stock == 0
    assert cancelled.refund_transaction.reference == f"STORE-REFUND-{order.id.hex}"

    with pytest.raises(ValidationError):
        StoreService.transition_order(
            order=cancelled, actor=user, new_status=StoreOrder.OrderStatus.CANCELLED
        )
    wallet.refresh_from_db()
    assert wallet.available_balance == balance_after_purchase + order.total_amount
    assert WalletTransaction.objects.filter(reference=f"STORE-REFUND-{order.id.hex}").count() == 1


@pytest.mark.django_db
def test_inactive_product_and_invalid_variant_are_rejected(checkout_data):
    user, product, _ = checkout_data
    product.metadata = {"sizes": ["M", "L"]}
    product.save(update_fields=["metadata"])
    with pytest.raises(ValidationError):
        StoreService.checkout(
            user=user,
            items_data=[{"product": product.id, "quantity": 1, "size": "XS"}],
            idempotency_key=uuid4(),
        )
    product.status = MerchandiseProduct.Status.ARCHIVED
    product.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        StoreService.checkout(
            user=user,
            items_data=[{"product": product.id, "quantity": 1, "size": "M"}],
            idempotency_key=uuid4(),
        )
