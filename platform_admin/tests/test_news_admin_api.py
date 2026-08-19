"""Tests for the news moderation admin API (queue, edit, approve, reject,
set-featured, set-trending, compose)."""

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from authentication.models import Role
from authentication.services.role_service import RoleService
from discovery.models import News
from discovery.tests.factories import NewsCategoryFactory, NewsFactory

from .factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def plain_user(db):
    return UserFactory(is_active=True, is_verified=True)


@pytest.fixture
def super_admin_user(db):
    return UserFactory(is_active=True, is_verified=True, is_superuser=True)


@pytest.fixture
def seeded_roles(db):
    call_command("seed_roles", verbosity=0)


@pytest.fixture
def sports_data_admin_user(db, seeded_roles):
    user = UserFactory(is_active=True, is_verified=True)
    role = Role.objects.get(name="Sports Data & Statistics Admin")
    RoleService.assign_role(user, role)
    return user


def authenticate(client, user):
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


class TestQueueAndPublishedList:
    def test_plain_user_forbidden(self, api_client, plain_user):
        authenticate(api_client, plain_user)
        resp = api_client.get("/api/v1/admin/news/queue/")
        assert resp.status_code == 403

    def test_sports_data_admin_sees_queue(self, api_client, sports_data_admin_user):
        NewsFactory(title="Pending story", status=News.Status.PENDING_APPROVAL)
        NewsFactory(title="Live story", status=News.Status.PUBLISHED, is_verified=True)
        authenticate(api_client, sports_data_admin_user)

        resp = api_client.get("/api/v1/admin/news/queue/")
        assert resp.status_code == 200
        titles = {item["title"] for item in resp.data}
        assert "Pending story" in titles
        assert "Live story" not in titles

    def test_super_admin_sees_published_list(self, api_client, super_admin_user):
        NewsFactory(title="Live story", status=News.Status.PUBLISHED, is_verified=True)
        authenticate(api_client, super_admin_user)

        resp = api_client.get("/api/v1/admin/news/published/")
        assert resp.status_code == 200
        assert {item["title"] for item in resp.data} == {"Live story"}


class TestEditStory:
    def test_edit_updates_content(self, api_client, sports_data_admin_user):
        news = NewsFactory(title="Old title", status=News.Status.PENDING_APPROVAL)
        authenticate(api_client, sports_data_admin_user)

        resp = api_client.patch(
            f"/api/v1/admin/news/{news.id}/", {"title": "New title"}, format="json"
        )
        assert resp.status_code == 200
        assert resp.data["title"] == "New title"
        news.refresh_from_db()
        assert news.title == "New title"

    def test_edit_requires_manage_permission(self, api_client, plain_user):
        news = NewsFactory(status=News.Status.PENDING_APPROVAL)
        authenticate(api_client, plain_user)

        resp = api_client.patch(f"/api/v1/admin/news/{news.id}/", {"title": "x"}, format="json")
        assert resp.status_code == 403


class TestApproveAndReject:
    def test_approve_as_top_story_and_trending(self, api_client, sports_data_admin_user):
        news = NewsFactory(status=News.Status.PENDING_APPROVAL, is_verified=False)
        authenticate(api_client, sports_data_admin_user)

        resp = api_client.post(
            f"/api/v1/admin/news/{news.id}/approve/",
            {"is_top_story": True, "is_trending": True},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["status"] == News.Status.PUBLISHED
        assert resp.data["is_featured"] is True
        assert resp.data["is_trending"] is True

        public_resp = APIClient().get("/api/v1/news/")
        titles = {item["title"] for item in public_resp.data["results"]}
        assert news.title in titles

    def test_approve_over_trending_cap_returns_400(self, api_client, sports_data_admin_user):
        for _ in range(5):
            NewsFactory(status=News.Status.PUBLISHED, is_verified=True, is_trending=True)
        news = NewsFactory(status=News.Status.PENDING_APPROVAL, is_verified=False)
        authenticate(api_client, sports_data_admin_user)

        resp = api_client.post(
            f"/api/v1/admin/news/{news.id}/approve/",
            {"is_trending": True},
            format="json",
        )
        assert resp.status_code == 400
        news.refresh_from_db()
        assert news.status == News.Status.PENDING_APPROVAL

    def test_reject_with_reason(self, api_client, sports_data_admin_user):
        news = NewsFactory(
            title="Bad story", status=News.Status.PENDING_APPROVAL, is_verified=False
        )
        authenticate(api_client, sports_data_admin_user)

        resp = api_client.post(
            f"/api/v1/admin/news/{news.id}/reject/", {"reason": "Not accurate."}, format="json"
        )
        assert resp.status_code == 200
        assert resp.data["status"] == News.Status.REJECTED

        public_resp = APIClient().get("/api/v1/news/")
        titles = {item["title"] for item in public_resp.data["results"]}
        assert "Bad story" not in titles

    def test_reject_requires_reason(self, api_client, sports_data_admin_user):
        news = NewsFactory(status=News.Status.PENDING_APPROVAL, is_verified=False)
        authenticate(api_client, sports_data_admin_user)

        resp = api_client.post(
            f"/api/v1/admin/news/{news.id}/reject/", {"reason": ""}, format="json"
        )
        assert resp.status_code == 400

    def test_approve_requires_manage_permission(self, api_client, plain_user):
        news = NewsFactory(status=News.Status.PENDING_APPROVAL)
        authenticate(api_client, plain_user)

        resp = api_client.post(f"/api/v1/admin/news/{news.id}/approve/", {}, format="json")
        assert resp.status_code == 403


class TestSetFeaturedAndTrending:
    def test_set_featured_toggle(self, api_client, sports_data_admin_user):
        news = NewsFactory(status=News.Status.PUBLISHED, is_verified=True, is_featured=False)
        authenticate(api_client, sports_data_admin_user)

        resp = api_client.post(
            f"/api/v1/admin/news/{news.id}/set-featured/", {"is_featured": True}, format="json"
        )
        assert resp.status_code == 200
        assert resp.data["is_featured"] is True

    def test_set_trending_over_cap_returns_400(self, api_client, sports_data_admin_user):
        for _ in range(5):
            NewsFactory(status=News.Status.PUBLISHED, is_verified=True, is_trending=True)
        extra = NewsFactory(status=News.Status.PUBLISHED, is_verified=True, is_trending=False)
        authenticate(api_client, sports_data_admin_user)

        resp = api_client.post(
            f"/api/v1/admin/news/{extra.id}/set-trending/", {"is_trending": True}, format="json"
        )
        assert resp.status_code == 400


class TestCompose:
    def test_compose_publishes_immediately(self, api_client, sports_data_admin_user):
        category = NewsCategoryFactory()
        authenticate(api_client, sports_data_admin_user)

        resp = api_client.post(
            "/api/v1/admin/news/",
            {
                "title": "Staff written story",
                "summary": "Summary",
                "body": "Body",
                "category": str(category.id),
            },
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["status"] == News.Status.PUBLISHED

        public_resp = APIClient().get("/api/v1/news/")
        titles = {item["title"] for item in public_resp.data["results"]}
        assert "Staff written story" in titles

    def test_compose_requires_manage_permission(self, api_client, plain_user):
        category = NewsCategoryFactory()
        authenticate(api_client, plain_user)

        resp = api_client.post(
            "/api/v1/admin/news/",
            {"title": "x", "summary": "s", "body": "b", "category": str(category.id)},
            format="json",
        )
        assert resp.status_code == 403
