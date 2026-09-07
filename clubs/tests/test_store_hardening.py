from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from clubs.models import ClubWorkspace, MerchandiseProduct, StoreOrder, StoreOrderItem
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


@pytest.mark.django_db
def test_insufficient_wallet_and_same_sku_in_different_clubs(checkout_data):
    user, first, second = checkout_data
    same_sku_other_club = MerchandiseProduct.objects.create(
        club=second.club,
        name="Other club shirt",
        sku=first.sku,
        price=Decimal("2000.00"),
        stock=1,
        status=MerchandiseProduct.Status.ACTIVE,
    )
    assert same_sku_other_club.sku == first.sku
    with pytest.raises(ValidationError):
        StoreService.checkout(
            user=user,
            items_data=[{"product": same_sku_other_club.id, "quantity": 1}],
            idempotency_key=uuid4(),
        )
    assert not StoreOrder.objects.exists()


@pytest.mark.django_db
def test_checkout_api_ignores_client_price_and_status(checkout_data):
    user, product, _ = checkout_data
    api = APIClient()
    api.force_authenticate(user)
    response = api.post(
        reverse("clubs:public-store-order-create"),
        {
            "idempotency_key": str(uuid4()),
            "status": "PAID",
            "total_amount": "0.01",
            "items": [{"product": str(product.id), "quantity": 1, "unit_price": "0.01"}],
        },
        format="json",
    )
    assert response.status_code == 201
    order = StoreOrder.objects.get()
    assert order.total_amount == Decimal("100.00")
    assert order.items.get().unit_price == Decimal("100.00")
    assert order.payment_transaction_id is not None


@pytest.mark.django_db
def test_club_admin_fulfilment_authorized_and_cross_club_denied(checkout_data):
    buyer, product, other_product = checkout_data
    order = StoreService.checkout(
        user=buyer, items_data=[{"product": product.id, "quantity": 1}], idempotency_key=uuid4()
    )[0]
    club_admin = User.objects.create_user(
        username="club-admin", email="club-admin@example.com", password="x"
    )
    ClubWorkspace.objects.create(
        user=club_admin, club=product.club, role=ClubWorkspace.WorkspaceRole.ADMIN
    )
    api = APIClient()
    api.force_authenticate(club_admin)
    url = reverse(
        "clubs:store-order-fulfilment", kwargs={"club_pk": product.club_id, "pk": order.id}
    )
    response = api.post(url, {"status": "PROCESSING", "note": "Admin packed"}, format="json")
    assert response.status_code == 200
    assert response.data["status"] == "PROCESSING"
    cross_club_url = reverse(
        "clubs:store-order-fulfilment",
        kwargs={"club_pk": other_product.club_id, "pk": order.id},
    )
    assert api.post(cross_club_url, {"status": "SHIPPED"}, format="json").status_code == 403
    invalid = api.post(url, {"status": "DELIVERED"}, format="json")
    assert invalid.status_code == 400


@pytest.mark.django_db(transaction=True)
def test_true_concurrent_last_stock_checkout_charges_exactly_one_buyer():
    """Separate PostgreSQL connections contend for the same select_for_update row."""
    assert connection.vendor == "postgresql"
    club = Club.objects.create(name="Concurrency Club", slug="concurrency-club")
    product = MerchandiseProduct.objects.create(
        club=club,
        name="Last Shirt",
        sku="LAST-1",
        price=Decimal("75.25"),
        stock=1,
        status=MerchandiseProduct.Status.ACTIVE,
    )
    buyers = [
        User.objects.create_user(
            username=f"buyer-{index}", email=f"buyer-{index}@example.com", password="x"
        )
        for index in range(2)
    ]
    for buyer in buyers:
        WalletService.credit(
            user=buyer, currency="UGX", amount=Decimal("100.00"), idempotency_reference=uuid4()
        )
    opening = {buyer.id: buyer.wallets.get(currency="UGX").available_balance for buyer in buyers}
    barrier = Barrier(2)

    def attempt(user_id):
        close_old_connections()
        barrier.wait(timeout=10)
        try:
            orders = StoreService.checkout(
                user=User.objects.get(id=user_id),
                items_data=[{"product": product.id, "quantity": 1}],
                idempotency_key=uuid4(),
            )
            return "success", orders[0].user_id
        except ValidationError:
            return "unavailable", user_id
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, [buyer.id for buyer in buyers]))

    assert [result[0] for result in results].count("success") == 1
    assert [result[0] for result in results].count("unavailable") == 1
    product.refresh_from_db()
    assert product.stock == 1
    assert product.reserved_stock == 1
    assert product.available_stock == 0
    assert StoreOrder.objects.count() == 1
    winner_id = next(user_id for outcome, user_id in results if outcome == "success")
    loser_id = next(user_id for outcome, user_id in results if outcome == "unavailable")
    assert User.objects.get(id=winner_id).wallets.get(currency="UGX").available_balance == Decimal(
        "24.75"
    )
    assert (
        User.objects.get(id=loser_id).wallets.get(currency="UGX").available_balance
        == opening[loser_id]
    )
    assert WalletTransaction.objects.filter(reference__startswith="SPEND-").count() == 1
    assert StoreOrder.objects.exclude(payment_transaction=None).count() == 1


@pytest.mark.django_db
def test_super_admin_store_acceptance_order_detail_and_refund_linkage(checkout_data):
    """Acceptance 10 exercises checkout, fulfilment, reporting, detail, and refund."""
    user, product, _ = checkout_data
    order = StoreService.checkout(
        user=user,
        items_data=[{"product": product.id, "quantity": 1}],
        idempotency_key=uuid4(),
        shipping_address={"city": "Kampala"},
    )[0]
    order = StoreService.transition_order(
        order=order,
        actor=user,
        new_status=StoreOrder.OrderStatus.PROCESSING,
        note="Packed",
    )
    order = StoreService.transition_order(
        order=order,
        actor=user,
        new_status=StoreOrder.OrderStatus.SHIPPED,
        note="Courier collected",
        delivery_reference="TRACK-ACCEPT-10",
    )
    administrator = User.objects.create_superuser(
        username="store-admin", email="store-admin@example.com", password="x"
    )
    api = APIClient()
    api.force_authenticate(administrator)
    listing = api.get(
        "/api/v1/admin/store/", {"resource": "deliveries", "search": "TRACK-ACCEPT-10"}
    )
    assert listing.status_code == 200
    assert listing.data["overview"]["total_orders"] == 1
    assert listing.data["overview"]["sales"] == "100.00"
    assert listing.data["results"][0]["payment_reference"] == order.payment_transaction.reference
    detail = api.get(f"/api/v1/admin/store/orders/{order.id}/")
    assert detail.status_code == 200
    assert str(detail.data["user"]) == str(user.id)
    assert str(detail.data["club"]) == str(product.club_id)
    assert detail.data["items"][0]["unit_price"] == "100.00"
    assert detail.data["total_amount"] == "100.00"
    assert detail.data["payment"]["ledger_entries"]
    assert detail.data["delivery_reference"] == "TRACK-ACCEPT-10"
    assert len(detail.data["status_history"]) == 3

    fan_api = APIClient()
    fan_api.force_authenticate(user)
    assert fan_api.get("/api/v1/admin/store/").status_code == 403
    assert fan_api.get(f"/api/v1/admin/store/orders/{order.id}/").status_code == 403

    # A shipped order is intentionally not cancellable. Use a second paid order
    # to prove canonical cancellation/refund reporting linkage.
    product.stock = 2
    product.reserved_stock = 1
    product.save(update_fields=["stock", "reserved_stock"])
    refundable = StoreService.checkout(
        user=user, items_data=[{"product": product.id, "quantity": 1}], idempotency_key=uuid4()
    )[0]
    refundable = StoreService.transition_order(
        order=refundable,
        actor=user,
        new_status=StoreOrder.OrderStatus.CANCELLED,
    )
    refunded_detail = api.get(f"/api/v1/admin/store/orders/{refundable.id}/")
    assert refunded_detail.data["refund_reference"] == refundable.refund_transaction.reference
    assert refunded_detail.data["refund"]["ledger_entries"]
