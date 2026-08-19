"""Tests for club management views."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from clubs.models import (
    ClubAuditLog,
    ClubMedia,
    ClubProfileVersion,
    ClubWorkspace,
    MembershipPlan,
    MerchandiseProduct,
    StaffInvitation,
    StoreOrder,
    StoreOrderItem,
    TicketProduct,
)
from profiles.models import Club


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
        first_name="Test",
        last_name="User",
    )


@pytest.fixture
def club(db):
    return Club.objects.create(name="Test Club", slug="test-club")


@pytest.fixture
def admin_workspace(db, user, club):
    return ClubWorkspace.objects.create(
        user=user,
        club=club,
        role=ClubWorkspace.WorkspaceRole.ADMIN,
        is_active=True,
    )


class TestClubWorkspaceViewSet:
    def test_list_workspaces(self, api_client, user, club, admin_workspace):
        api_client.force_authenticate(user=user)
        url = reverse("clubs:club-workspace-list", kwargs={"club_pk": club.id})
        response = api_client.get(url)
        assert response.status_code == 200
        assert len(response.data) == 1

    def test_create_workspace(self, api_client, user, club, admin_workspace):
        api_client.force_authenticate(user=user)
        new_user = User.objects.create_user(
            username="staffuser",
            email="staff@example.com",
            password="staffpass123",
            first_name="Staff",
            last_name="User",
        )
        url = reverse("clubs:club-workspace-list", kwargs={"club_pk": club.id})
        data = {
            "user": new_user.id,
            "role": ClubWorkspace.WorkspaceRole.STAFF,
            "permissions": ["memberships.read"],
        }
        response = api_client.post(url, data, format="json")
        print(response.data)
        assert response.status_code == 201
        assert ClubWorkspace.objects.count() == 2

    def test_create_workspace_denied_for_non_admin(self, api_client, user, club):
        # No admin_workspace fixture here — `user` has no workspace at all
        # for this club, so this must be rejected before an object even
        # exists to check `has_object_permission` against.
        api_client.force_authenticate(user=user)
        new_user = User.objects.create_user(
            username="staffuser2",
            email="staff2@example.com",
            password="staffpass123",
            first_name="Staff",
            last_name="User",
        )
        url = reverse("clubs:club-workspace-list", kwargs={"club_pk": club.id})
        data = {
            "user": new_user.id,
            "role": ClubWorkspace.WorkspaceRole.STAFF,
            "permissions": ["memberships.read"],
        }
        response = api_client.post(url, data, format="json")
        assert response.status_code == 403
        assert ClubWorkspace.objects.count() == 0

    def test_list_workspaces_denied_for_non_admin(self, api_client, user, club):
        api_client.force_authenticate(user=user)
        url = reverse("clubs:club-workspace-list", kwargs={"club_pk": club.id})
        response = api_client.get(url)
        assert response.status_code == 403


class TestClubProfileVersionViewSet:
    def test_create_profile(self, api_client, user, club, admin_workspace):
        api_client.force_authenticate(user=user)
        url = reverse("clubs:club-profile-list", kwargs={"club_pk": club.id})
        data = {
            "display_name": "Test Club FC",
            "tagline": "We are the best",
            "description": "A test club",
        }
        response = api_client.post(url, data, format="json")
        assert response.status_code == 201
        assert ClubProfileVersion.objects.count() == 1
        assert response.data["version"] == 1


class TestClubMediaViewSet:
    def test_upload_media(self, api_client, user, club, admin_workspace):
        api_client.force_authenticate(user=user)
        url = reverse("clubs:club-media-list", kwargs={"club_pk": club.id})
        data = {
            "media_type": ClubMedia.MediaType.IMAGE,
            "title": "Test Image",
        }
        response = api_client.post(url, data, format="json")
        assert response.status_code == 201
        assert ClubMedia.objects.count() == 1


class TestMembershipPlanViewSet:
    def test_create_plan(self, api_client, user, club, admin_workspace):
        api_client.force_authenticate(user=user)
        url = reverse("clubs:membership-plan-list", kwargs={"club_pk": club.id})
        data = {
            "name": "Gold Membership",
            "description": "Premium membership",
            "price": "50000.00",
            "billing_period": MembershipPlan.BillingPeriod.MONTHLY,
            "duration_days": 30,
        }
        response = api_client.post(url, data, format="json")
        assert response.status_code == 201
        assert MembershipPlan.objects.count() == 1
        assert response.data["price"] == "50000.00"


class TestTicketProductViewSet:
    def test_create_ticket(self, api_client, user, club, admin_workspace):
        api_client.force_authenticate(user=user)
        url = reverse("clubs:ticket-product-list", kwargs={"club_pk": club.id})
        data = {
            "name": "Final Match Ticket",
            "description": "Ticket for the final match",
            "price": "10000.00",
            "capacity": 1000,
        }
        response = api_client.post(url, data, format="json")
        assert response.status_code == 201
        assert TicketProduct.objects.count() == 1


class TestMerchandiseProductViewSet:
    def test_create_product(self, api_client, user, club, admin_workspace):
        api_client.force_authenticate(user=user)
        url = reverse("clubs:merchandise-list", kwargs={"club_pk": club.id})
        data = {
            "name": "Club Jersey",
            "description": "Home jersey 2024",
            "price": "75000.00",
            "stock": 100,
            "sku": "JERSEY-2024",
        }
        response = api_client.post(url, data, format="json")
        assert response.status_code == 201
        assert MerchandiseProduct.objects.count() == 1


class TestPublicMerchandiseProductListView:
    def test_list_public_products_without_authentication(self, api_client, club):
        MerchandiseProduct.objects.create(
            club=club,
            name="Public Jersey",
            description="Visible to fans",
            price="75000.00",
            stock=100,
            sku="PUBLIC-2026",
            status=MerchandiseProduct.Status.ACTIVE,
        )
        MerchandiseProduct.objects.create(
            club=club,
            name="Draft Jersey",
            description="Hidden from fans",
            price="75000.00",
            stock=100,
            sku="DRAFT-2026",
            status=MerchandiseProduct.Status.DRAFT,
        )

        url = reverse("clubs:public-merchandise-list")
        response = api_client.get(url)

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["name"] == "Public Jersey"
        assert response.data[0]["club_slug"] == club.slug


class TestPublicStoreOrderCreateView:
    def test_create_paid_store_order(self, api_client, user, club):
        api_client.force_authenticate(user=user)
        product = MerchandiseProduct.objects.create(
            club=club,
            name="Public Jersey",
            description="Visible to fans",
            price="75000.00",
            stock=100,
            sku="PUBLIC-2026",
            status=MerchandiseProduct.Status.ACTIVE,
        )

        url = reverse("clubs:public-store-order-create")
        response = api_client.post(
            url,
            {
                "items": [{"product": str(product.id), "quantity": 2, "size": "M"}],
                "metadata": {"walletIdempotencyKey": "cart-key"},
            },
            format="json",
        )

        assert response.status_code == 201
        assert StoreOrder.objects.count() == 1
        assert StoreOrderItem.objects.count() == 1
        order = StoreOrder.objects.get()
        assert order.status == StoreOrder.OrderStatus.PAID
        assert order.total_amount == product.price * 2
        product.refresh_from_db()
        assert product.reserved_stock == 2
        assert response.data["items"][0]["product_name"] == "Public Jersey"

    def test_rejects_mixed_club_order(self, api_client, user, club):
        other_club = Club.objects.create(name="Other Club", slug="other-club")
        api_client.force_authenticate(user=user)
        first = MerchandiseProduct.objects.create(
            club=club,
            name="Home Jersey",
            price="75000.00",
            stock=100,
            status=MerchandiseProduct.Status.ACTIVE,
        )
        second = MerchandiseProduct.objects.create(
            club=other_club,
            name="Away Jersey",
            price="75000.00",
            stock=100,
            status=MerchandiseProduct.Status.ACTIVE,
        )

        url = reverse("clubs:public-store-order-create")
        response = api_client.post(
            url,
            {
                "items": [
                    {"product": str(first.id), "quantity": 1},
                    {"product": str(second.id), "quantity": 1},
                ],
            },
            format="json",
        )

        assert response.status_code == 400
        assert StoreOrder.objects.count() == 0


class TestStaffInvitationViewSet:
    def test_invite_staff(self, api_client, user, club, admin_workspace):
        api_client.force_authenticate(user=user)
        url = reverse("clubs:staff-invitation-list", kwargs={"club_pk": club.id})
        data = {
            "email": "newstaff@example.com",
            "role": ClubWorkspace.WorkspaceRole.STAFF,
            "permissions": ["media.read"],
        }
        response = api_client.post(url, data, format="json")
        assert response.status_code == 201
        assert StaffInvitation.objects.count() == 1


class TestClubAuditLogViewSet:
    def test_list_audit_logs(self, api_client, user, club, admin_workspace):
        ClubAuditLog.objects.create(
            club=club,
            user=user,
            action="WORKSPACE_SWITCHED",
            entity_type="Club",
            entity_id=club.id,
        )
        api_client.force_authenticate(user=user)
        url = reverse("clubs:club-audit-log-list", kwargs={"club_pk": club.id})
        response = api_client.get(url)
        assert response.status_code == 200
        assert len(response.data) == 1
