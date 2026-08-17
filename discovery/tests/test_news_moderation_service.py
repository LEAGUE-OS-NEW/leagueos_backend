"""Tests for NewsModerationService — the submit -> review -> publish pipeline."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from discovery.models import News
from discovery.services.news_moderation_service import MAX_TRENDING, news_moderation_service
from discovery.tests.factories import ClubFactory, NewsCategoryFactory, NewsFactory, UserFactory

pytestmark = pytest.mark.django_db


class TestSubmitForReview:
    def test_creates_pending_unverified_article(self):
        club = ClubFactory()
        category = NewsCategoryFactory()
        user = UserFactory()

        news = news_moderation_service.submit_for_review(
            club=club,
            title="Vipers SC sign new striker",
            summary="A short summary.",
            body="The full story.",
            category=category,
            created_by=user,
        )

        assert news.status == News.Status.PENDING_APPROVAL
        assert news.is_verified is False
        assert news.club_id == club.id
        assert news.created_by_id == user.id

    def test_not_visible_on_public_feed(self, client=None):
        club = ClubFactory()
        category = NewsCategoryFactory()
        user = UserFactory()

        news_moderation_service.submit_for_review(
            club=club,
            title="Pending story",
            summary="s",
            body="b",
            category=category,
            created_by=user,
        )

        from rest_framework.test import APIClient

        resp = APIClient().get("/api/v1/news/")
        titles = {item["title"] for item in resp.data["results"]}
        assert "Pending story" not in titles


class TestListQueue:
    def test_only_pending_articles(self):
        NewsFactory(title="Pending", status=News.Status.PENDING_APPROVAL)
        NewsFactory(title="Published", status=News.Status.PUBLISHED, is_verified=True)

        queue_titles = {n.title for n in news_moderation_service.list_queue()}
        assert "Pending" in queue_titles
        assert "Published" not in queue_titles


class TestApprove:
    def test_publishes_and_verifies(self):
        news = NewsFactory(status=News.Status.PENDING_APPROVAL, is_verified=False)
        user = UserFactory()

        approved = news_moderation_service.approve(news=news, actor=user)

        assert approved.status == News.Status.PUBLISHED
        assert approved.is_verified is True
        assert approved.published_at is not None
        assert approved.is_featured is False
        assert approved.is_trending is False

    def test_now_visible_on_public_feed(self):
        news = NewsFactory(
            title="Now public", status=News.Status.PENDING_APPROVAL, is_verified=False
        )
        user = UserFactory()

        news_moderation_service.approve(news=news, actor=user)

        from rest_framework.test import APIClient

        resp = APIClient().get("/api/v1/news/")
        titles = {item["title"] for item in resp.data["results"]}
        assert "Now public" in titles

    def test_top_story_unfeatures_others(self):
        already_featured = NewsFactory(
            status=News.Status.PUBLISHED, is_verified=True, is_featured=True
        )
        pending = NewsFactory(status=News.Status.PENDING_APPROVAL, is_verified=False)
        user = UserFactory()

        news_moderation_service.approve(news=pending, actor=user, is_top_story=True)

        already_featured.refresh_from_db()
        pending.refresh_from_db()
        assert already_featured.is_featured is False
        assert pending.is_featured is True

    def test_trending_cap_enforced(self):
        for _ in range(MAX_TRENDING):
            NewsFactory(status=News.Status.PUBLISHED, is_verified=True, is_trending=True)
        pending = NewsFactory(status=News.Status.PENDING_APPROVAL, is_verified=False)
        user = UserFactory()

        with pytest.raises(ValidationError):
            news_moderation_service.approve(news=pending, actor=user, is_trending=True)

        pending.refresh_from_db()
        assert pending.status == News.Status.PENDING_APPROVAL


class TestReject:
    def test_rejects_with_reason(self):
        news = NewsFactory(status=News.Status.PENDING_APPROVAL, is_verified=False)
        user = UserFactory()

        rejected = news_moderation_service.reject(news=news, actor=user, reason="Not newsworthy.")

        assert rejected.status == News.Status.REJECTED
        assert rejected.rejection_reason == "Not newsworthy."

    def test_rejected_never_public(self):
        news = NewsFactory(
            title="Rejected story", status=News.Status.PENDING_APPROVAL, is_verified=False
        )
        user = UserFactory()

        news_moderation_service.reject(news=news, actor=user, reason="No.")

        from rest_framework.test import APIClient

        resp = APIClient().get("/api/v1/news/")
        titles = {item["title"] for item in resp.data["results"]}
        assert "Rejected story" not in titles


class TestSetFeaturedAndTrending:
    def test_set_featured_unfeatures_others(self):
        first = NewsFactory(status=News.Status.PUBLISHED, is_verified=True, is_featured=True)
        second = NewsFactory(status=News.Status.PUBLISHED, is_verified=True, is_featured=False)

        news_moderation_service.set_featured(news=second, is_featured=True)

        first.refresh_from_db()
        second.refresh_from_db()
        assert first.is_featured is False
        assert second.is_featured is True

    def test_set_trending_respects_cap(self):
        for _ in range(MAX_TRENDING):
            NewsFactory(status=News.Status.PUBLISHED, is_verified=True, is_trending=True)
        extra = NewsFactory(status=News.Status.PUBLISHED, is_verified=True, is_trending=False)

        with pytest.raises(ValidationError):
            news_moderation_service.set_trending(news=extra, is_trending=True)

    def test_set_trending_off_never_blocked_by_cap(self):
        news = NewsFactory(status=News.Status.PUBLISHED, is_verified=True, is_trending=True)

        result = news_moderation_service.set_trending(news=news, is_trending=False)

        assert result.is_trending is False
