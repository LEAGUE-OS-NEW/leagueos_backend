"""Tests for club services."""

from __future__ import annotations

from decimal import Decimal

import pytest

from accounts.models import User
from clubs.models import (
    ClubAnalytics,
    ClubAuditLog,
    ClubNews,
    ClubProfileVersion,
    ClubWorkspace,
    InventoryAdjustment,
    MembershipPlan,
    StaffInvitation,
    TicketProduct,
)
from clubs.services.analytics_service import AnalyticsService
from clubs.services.audit_service import ClubAuditService
from clubs.services.club_profile_service import ClubProfileService
from clubs.services.club_workspace_service import ClubWorkspaceService
from clubs.services.inventory_service import InventoryService
from clubs.services.media_service import MediaService
from clubs.services.membership_service import MembershipService
from clubs.services.staff_service import StaffService
from clubs.services.store_service import StoreService
from clubs.services.ticket_service import TicketService
from django.utils import timezone
from profiles.models import Club


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


class TestClubWorkspaceService:
    def test_get_active_workspace(self, user, club, admin_workspace):
        workspace = ClubWorkspaceService.get_active_workspace(user, club)
        assert workspace is not None
        assert workspace.role == ClubWorkspace.WorkspaceRole.ADMIN

    def test_get_user_clubs(self, user, club, admin_workspace):
        clubs = ClubWorkspaceService.get_user_clubs(user)
        assert clubs.count() == 1
        assert clubs.first().club == club

    def test_switch_workspace(self, user, club, admin_workspace):
        workspace, error = ClubWorkspaceService.switch_workspace(user, club)
        assert error is None
        assert workspace is not None


class TestClubProfileService:
    def test_create_profile(self, user, club, admin_workspace):
        profile = ClubProfileService.create_profile(
            club, user, display_name="Test Club FC", description="A test club"
        )
        assert profile.version == 1
        assert profile.status == ClubProfileVersion.ProfileStatus.DRAFT

    def test_publish_profile(self, user, club, admin_workspace):
        profile = ClubProfileService.create_profile(club, user)
        published = ClubProfileService.publish_profile(profile, user)
        assert published.status == ClubProfileVersion.ProfileStatus.PUBLISHED
        assert published.published_by == user

    def test_get_published_profile(self, user, club, admin_workspace):
        profile = ClubProfileService.create_profile(club, user)
        ClubProfileService.publish_profile(profile, user)
        published = ClubProfileService.get_published_profile(club)
        assert published is not None
        assert published.id == profile.id


class TestMediaService:
    def test_validate_file_size(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        file = SimpleUploadedFile("test.jpg", b"x" * (60 * 1024 * 1024), content_type="image/jpeg")
        with pytest.raises(ValueError, match="File size exceeds"):
            MediaService.validate_file(file)

    def test_validate_file_type(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        file = SimpleUploadedFile("test.exe", b"x" * 1024, content_type="application/x-msdownload")
        with pytest.raises(ValueError, match="File type"):
            MediaService.validate_file(file)


class TestMembershipService:
    def test_create_plan(self, user, club, admin_workspace):
        plan = MembershipService.create_plan(
            club,
            user,
            name="Gold Plan",
            price=Decimal("50000.00"),
            billing_period=MembershipPlan.BillingPeriod.MONTHLY,
        )
        assert plan.price == Decimal("50000.00")
        assert plan.status == MembershipPlan.Status.DRAFT

    def test_publish_plan(self, user, club, admin_workspace):
        plan = MembershipService.create_plan(
            club, user, name="Gold Plan", price=Decimal("50000.00")
        )
        published = MembershipService.publish_plan(plan, user)
        assert published.status == MembershipPlan.Status.ACTIVE


class TestTicketService:
    def test_create_product(self, user, club, admin_workspace):
        product = TicketService.create_product(
            club, user, name="Final Ticket", price=Decimal("10000.00"), capacity=1000
        )
        assert product.price == Decimal("10000.00")
        assert product.capacity == 1000

    def test_validate_sale(self, user, club, admin_workspace):
        product = TicketService.create_product(
            club, user, name="Final Ticket", price=Decimal("10000.00")
        )
        product.status = TicketProduct.Status.ACTIVE
        product.save(update_fields=["status"])
        assert TicketService.validate_sale(product, 1) is True


class TestStoreService:
    def test_create_product(self, user, club, admin_workspace):
        product = StoreService.create_product(
            club, user, name="Jersey", price=Decimal("75000.00"), stock=100
        )
        assert product.stock == 100
        assert product.available_stock == 100

    def test_create_order(self, user, club, admin_workspace):
        product = StoreService.create_product(
            club, user, name="Jersey", price=Decimal("75000.00"), stock=100
        )
        order = StoreService.create_order(user, club, [{"product": product, "quantity": 2}])
        assert order.total_amount == Decimal("150000.00")
        product.refresh_from_db()
        assert product.reserved_stock == 2


class TestInventoryService:
    def test_adjust_stock(self, user, club, admin_workspace):
        product = StoreService.create_product(
            club, user, name="Jersey", price=Decimal("75000.00"), stock=100
        )
        adjustment = InventoryService.adjust_stock(
            product, InventoryAdjustment.AdjustmentType.RESTOCK, 50, user
        )
        assert adjustment.new_stock == 150
        product.refresh_from_db()
        assert product.stock == 150

    def test_negative_stock_raises(self, user, club, admin_workspace):
        product = StoreService.create_product(
            club, user, name="Jersey", price=Decimal("75000.00"), stock=10
        )
        with pytest.raises(ValueError, match="New stock cannot be negative"):
            InventoryService.adjust_stock(
                product, InventoryAdjustment.AdjustmentType.SALE, -20, user
            )


class TestStaffService:
    def test_invite_staff(self, user, club, admin_workspace):
        invitation = StaffService.invite_staff(
            club, "staff@example.com", ClubWorkspace.WorkspaceRole.STAFF, user
        )
        assert invitation.email == "staff@example.com"
        assert invitation.status == StaffInvitation.Status.PENDING

    def test_accept_invitation(self, user, club, admin_workspace):
        invitation = StaffService.invite_staff(
            club, "staff@example.com", ClubWorkspace.WorkspaceRole.STAFF, user
        )
        new_user = User.objects.create_user(
            username="staffuser",
            email="staff@example.com",
            password="staffpass123",
            first_name="Staff",
            last_name="User",
        )
        workspace = StaffService.accept_invitation(invitation.token, new_user)
        assert workspace.user == new_user
        assert workspace.role == ClubWorkspace.WorkspaceRole.STAFF


class TestAnalyticsService:
    def test_record_metric(self, user, club, admin_workspace):
        metric = AnalyticsService.record_metric(club, ClubAnalytics.MetricType.FAN_GROWTH, 100)
        assert metric.value == 100
        assert metric.metric_type == ClubAnalytics.MetricType.FAN_GROWTH

    def test_get_fan_growth(self, user, club, admin_workspace):
        AnalyticsService.record_metric(club, ClubAnalytics.MetricType.FAN_GROWTH, 100)
        metrics = AnalyticsService.get_fan_growth(club)
        assert metrics.count() == 1


class TestClubAuditService:
    def test_record_audit(self, user, club, admin_workspace):
        audit = ClubAuditService.record(
            "WORKSPACE_SWITCHED", club, user, entity_type="Club", entity_id=club.id
        )
        assert audit is not None
        assert audit.action == "WORKSPACE_SWITCHED"

    def test_get_club_audit_logs(self, user, club, admin_workspace):
        ClubAuditLog.objects.create(
            club=club, user=user, action="WORKSPACE_SWITCHED", entity_type="Club", entity_id=club.id
        )
        logs = ClubAuditService.get_club_audit_logs(club)
        assert logs.count() == 1


class TestClubProfileServiceScheduling:
    def test_schedule_profile(self, user, club, admin_workspace):
        profile = ClubProfileService.create_profile(club, user)
        scheduled_at = timezone.now() + timezone.timedelta(days=1)
        scheduled = ClubProfileService.schedule_profile(profile, scheduled_at, user)
        assert scheduled.scheduled_at == scheduled_at
        assert scheduled.status == ClubProfileVersion.ProfileStatus.PENDING_APPROVAL

    def test_get_scheduled_profiles(self, user, club, admin_workspace):
        profile = ClubProfileService.create_profile(club, user)
        scheduled_at = timezone.now() - timezone.timedelta(hours=1)
        ClubProfileService.schedule_profile(profile, scheduled_at, user)
        scheduled = ClubProfileService.get_scheduled_profiles()
        assert scheduled.count() == 1


class TestMediaServiceSanitisation:
    def test_strip_exif_from_image(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image as PILImage
        import io

        img = PILImage.new("RGB", (100, 100), color="red")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)
        file_obj = SimpleUploadedFile("test.jpg", buf.read(), content_type="image/jpeg")

        result = MediaService._strip_exif(file_obj)
        assert result is not None
        assert result.read() != b""


class TestNewsService:
    def test_create_news(self, user, club, admin_workspace):
        from clubs.services.news_service import NewsService
        from discovery.models import NewsCategory
        from sports.models import Sport

        category = NewsCategory.objects.create(code="test", name="Test")
        sport = Sport.objects.create(name="Football", slug="football")

        news = NewsService.create_news(
            club,
            user,
            title="Test News",
            body="<script>alert('xss')</script><p>Safe content</p>",
            category=category,
            sport=sport,
        )
        assert news.title == "Test News"
        assert "<script>" not in news.body

    def test_publish_news(self, user, club, admin_workspace):
        from clubs.services.news_service import NewsService
        from discovery.models import NewsCategory
        from sports.models import Sport

        category = NewsCategory.objects.create(code="test2", name="Test 2")
        sport = Sport.objects.create(name="Rugby", slug="rugby")

        news = NewsService.create_news(
            club,
            user,
            title="Publish Test",
            body="Content to publish",
            category=category,
            sport=sport,
        )
        published = NewsService.publish_news(news, user)
        assert published.status == ClubNews.Status.PUBLISHED
        assert published.published_by == user

    def test_schedule_news(self, user, club, admin_workspace):
        from clubs.services.news_service import NewsService
        from discovery.models import NewsCategory
        from sports.models import Sport

        category = NewsCategory.objects.create(code="test3", name="Test 3")
        sport = Sport.objects.create(name="Tennis", slug="tennis")

        news = NewsService.create_news(
            club,
            user,
            title="Schedule Test",
            body="Content to schedule",
            category=category,
            sport=sport,
        )
        scheduled_at = timezone.now() + timezone.timedelta(days=1)
        scheduled = NewsService.schedule_news(news, scheduled_at, user)
        assert scheduled.scheduled_at == scheduled_at
        assert scheduled.status == ClubNews.Status.PENDING_APPROVAL


class TestSanitisationUtility:
    def test_sanitise_html_removes_script_tags(self):
        from clubs.services.sanitisation import sanitise_html

        result = sanitise_html("<script>alert('xss')</script><p>Safe</p>")
        assert "<script>" not in result
        assert "Safe" in result

    def test_sanitise_html_removes_javascript_protocol(self):
        from clubs.services.sanitisation import sanitise_html

        result = sanitise_html('<a href="javascript:alert(1)">click</a>')
        assert "javascript:" not in result

    def test_sanitise_html_allows_safe_tags(self):
        from clubs.services.sanitisation import sanitise_html

        result = sanitise_html("<p><strong>Bold</strong> text</p>")
        assert "<p>" in result
        assert "<strong>" in result

    def test_sanitise_text_escapes_html(self):
        from clubs.services.sanitisation import sanitise_text

        result = sanitise_text("<script>alert('xss')</script>")
        assert "&lt;script&gt;" in result
        assert "<script>" not in result
