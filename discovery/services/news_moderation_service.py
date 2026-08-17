"""News moderation service — the write-side counterpart to the read-only
NewsService. Owns the submit -> review -> publish/reject lifecycle for
discovery.News, including the Top Story (is_featured) and Trending
(is_trending) curation rules."""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from discovery.models import News

logger = logging.getLogger(__name__)

MAX_TRENDING = 5


class NewsModerationService:
    """Service for news submission and moderation."""

    @staticmethod
    def submit_for_review(
        *, club, title, summary, body, category, created_by, sport=None, competition=None
    ):
        """Create a club-submitted article awaiting Sports Data / Super Admin review."""
        news = News(
            title=title,
            summary=summary,
            body=body,
            category=category,
            sport=sport,
            competition=competition,
            club=club,
            created_by=created_by,
            status=News.Status.PENDING_APPROVAL,
            is_verified=False,
        )
        news.full_clean()
        news.save()
        return news

    @staticmethod
    def compose_and_publish(
        *, title, summary, body, category, created_by, sport=None, competition=None
    ):
        """Staff (Sports Data / Super Admin) writing and publishing an
        original article directly — no club, no review step."""
        news = News(
            title=title,
            summary=summary,
            body=body,
            category=category,
            sport=sport,
            competition=competition,
            created_by=created_by,
            status=News.Status.PUBLISHED,
            is_verified=True,
            published_at=timezone.now(),
        )
        news.full_clean()
        news.save()
        return news

    @staticmethod
    def list_queue():
        """Return articles awaiting review, oldest first so the queue works FIFO."""
        return (
            News.objects.filter(status=News.Status.PENDING_APPROVAL)
            .select_related("category", "sport", "competition", "club")
            .order_by("created_at")
        )

    @staticmethod
    def list_published():
        """Return live articles, most recently published first."""
        return (
            News.objects.filter(status=News.Status.PUBLISHED)
            .select_related("category", "sport", "competition", "club")
            .order_by("-published_at")
        )

    @staticmethod
    def update_story(*, news, **fields):
        """Edit an article's content/classification — used by the Edit Story flow
        before approval, and can also correct an already-published article."""
        for field in ("title", "summary", "body", "category", "sport", "competition"):
            if field in fields:
                setattr(news, field, fields[field])
        news.full_clean()
        news.save()
        return news

    @staticmethod
    def _unfeature_others(exclude_id):
        """Only one Top Story at a time."""
        News.objects.filter(is_featured=True).exclude(id=exclude_id).update(is_featured=False)

    @staticmethod
    def _assert_trending_capacity(news, is_trending):
        if is_trending and not news.is_trending:
            already_trending = News.objects.filter(is_trending=True).exclude(id=news.id).count()
            if already_trending >= MAX_TRENDING:
                raise ValidationError(
                    f"Only {MAX_TRENDING} stories can be marked Trending at once — "
                    "untrend one first."
                )

    @classmethod
    @transaction.atomic
    def approve(cls, *, news, actor, is_top_story=False, is_trending=False):
        """Publish a pending article, optionally as Top Story and/or Trending."""
        cls._assert_trending_capacity(news, is_trending)
        if is_top_story:
            cls._unfeature_others(news.id)

        news.status = News.Status.PUBLISHED
        news.is_verified = True
        news.is_featured = bool(is_top_story)
        news.is_trending = bool(is_trending)
        news.rejection_reason = ""
        news.published_at = timezone.now()
        news.full_clean()
        news.save()
        return news

    @staticmethod
    def reject(*, news, actor, reason):
        """Reject a pending article — it never appears on the public feed."""
        news.status = News.Status.REJECTED
        news.rejection_reason = reason
        news.full_clean()
        news.save()
        return news

    @classmethod
    @transaction.atomic
    def set_featured(cls, *, news, is_featured):
        """Standalone Top Story toggle for an already-published article."""
        if is_featured:
            cls._unfeature_others(news.id)
        news.is_featured = is_featured
        news.save(update_fields=["is_featured", "updated_at"])
        return news

    @classmethod
    @transaction.atomic
    def set_trending(cls, *, news, is_trending):
        """Standalone Trending toggle for an already-published article."""
        cls._assert_trending_capacity(news, is_trending)
        news.is_trending = is_trending
        news.save(update_fields=["is_trending", "updated_at"])
        return news


news_moderation_service = NewsModerationService()
