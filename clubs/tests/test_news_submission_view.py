"""Tests for the club-side news submission endpoint (discovery.News pipeline,
distinct from ClubNewsViewSet's orphaned ClubNews model)."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from clubs.models import ClubWorkspace
from discovery.models import News
from discovery.tests.factories import NewsCategoryFactory
from profiles.models import Club

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user():
    return User.objects.create_user(
        username="staffuser",
        email="staff@example.com",
        password="testpass123",
        first_name="Staff",
        last_name="User",
    )


@pytest.fixture
def club():
    return Club.objects.create(name="Test Club", slug="test-club")


@pytest.fixture
def staff_workspace(user, club):
    return ClubWorkspace.objects.create(
        user=user,
        club=club,
        role=ClubWorkspace.WorkspaceRole.STAFF,
        is_active=True,
    )


@pytest.fixture
def category():
    return NewsCategoryFactory()


class TestNewsSubmissionCreate:
    def test_staff_can_submit(self, api_client, user, club, staff_workspace, category):
        api_client.force_authenticate(user=user)
        url = reverse("clubs:club-news-submission-list", kwargs={"club_pk": club.id})

        resp = api_client.post(
            url,
            {
                "title": "New signing",
                "summary": "Summary",
                "body": "Body",
                "category": str(category.id),
            },
            format="json",
        )

        assert resp.status_code == 201
        assert resp.data["status"] == News.Status.PENDING_APPROVAL
        news = News.objects.get(title="New signing")
        assert news.club_id == club.id
        assert news.created_by_id == user.id
        assert news.is_verified is False

    def test_submission_never_appears_on_public_feed(
        self, api_client, user, club, staff_workspace, category
    ):
        api_client.force_authenticate(user=user)
        url = reverse("clubs:club-news-submission-list", kwargs={"club_pk": club.id})
        api_client.post(
            url,
            {"title": "Not yet public", "summary": "s", "body": "b", "category": str(category.id)},
            format="json",
        )

        resp = api_client.get("/api/v1/news/")
        titles = {item["title"] for item in resp.data["results"]}
        assert "Not yet public" not in titles

    def test_non_staff_forbidden(self, api_client, user, club, category):
        # No staff_workspace fixture — user has no workspace for this club.
        api_client.force_authenticate(user=user)
        url = reverse("clubs:club-news-submission-list", kwargs={"club_pk": club.id})

        resp = api_client.post(
            url,
            {"title": "Should fail", "summary": "s", "body": "b", "category": str(category.id)},
            format="json",
        )

        assert resp.status_code == 403
        assert not News.objects.filter(title="Should fail").exists()

    def test_unauthenticated_forbidden(self, api_client, club, category):
        url = reverse("clubs:club-news-submission-list", kwargs={"club_pk": club.id})

        resp = api_client.post(
            url,
            {"title": "Should fail", "summary": "s", "body": "b", "category": str(category.id)},
            format="json",
        )

        assert resp.status_code in (401, 403)


class TestNewsSubmissionList:
    def test_lists_only_this_clubs_submissions(
        self, api_client, user, club, staff_workspace, category
    ):
        other_club = Club.objects.create(name="Other Club", slug="other-club")
        News.objects.create(
            title="Other club story", summary="s", body="b", category=category, club=other_club
        )
        News.objects.create(
            title="This club story", summary="s", body="b", category=category, club=club
        )

        api_client.force_authenticate(user=user)
        url = reverse("clubs:club-news-submission-list", kwargs={"club_pk": club.id})
        resp = api_client.get(url)

        assert resp.status_code == 200
        titles = {item["title"] for item in resp.data}
        assert "This club story" in titles
        assert "Other club story" not in titles
