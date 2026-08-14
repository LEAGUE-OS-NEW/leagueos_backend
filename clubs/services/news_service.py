"""News service for club news management."""

from __future__ import annotations

import logging

from django.utils import timezone

from clubs.models import ClubAuditLog, ClubNews
from clubs.services.sanitisation import sanitise_html

logger = logging.getLogger(__name__)


class NewsService:
    """Service for club news operations."""

    @staticmethod
    def create_news(club, user, **kwargs):
        """Create new club news article."""
        if "body" in kwargs and kwargs["body"]:
            kwargs["body"] = sanitise_html(kwargs["body"])
        if "summary" in kwargs and kwargs["summary"]:
            kwargs["summary"] = sanitise_html(kwargs["summary"])

        news = ClubNews.objects.create(
            club=club,
            created_by=user,
            **kwargs,
        )

        ClubAuditLog.objects.create(
            club=club,
            user=user,
            action="NEWS_PUBLISHED",
            entity_type="ClubNews",
            entity_id=news.id,
            metadata={"title": news.title, "status": news.status},
        )

        return news

    @staticmethod
    def publish_news(news, user):
        """Publish club news."""
        if news.status == ClubNews.Status.PUBLISHED:
            return news

        news.status = ClubNews.Status.PUBLISHED
        news.published_at = timezone.now()
        news.published_by = user
        news.scheduled_at = None
        news.save(update_fields=["status", "published_at", "published_by", "scheduled_at"])

        ClubAuditLog.objects.create(
            club=news.club,
            user=user,
            action="NEWS_PUBLISHED",
            entity_type="ClubNews",
            entity_id=news.id,
            metadata={"title": news.title},
        )

        NewsService._emit_notification(news, user)

        return news

    @staticmethod
    def schedule_news(news, scheduled_at, user):
        """Schedule news for future publication."""
        news.scheduled_at = scheduled_at
        news.status = ClubNews.Status.PENDING_APPROVAL
        news.save(update_fields=["scheduled_at", "status"])

        ClubAuditLog.objects.create(
            club=news.club,
            user=user,
            action="NEWS_PUBLISHED",
            entity_type="ClubNews",
            entity_id=news.id,
            metadata={"action": "scheduled", "scheduled_at": scheduled_at.isoformat()},
        )

        return news

    @staticmethod
    def get_scheduled_news():
        """Return news scheduled for publication that are due."""
        now = timezone.now()
        return ClubNews.objects.filter(
            status=ClubNews.Status.PENDING_APPROVAL,
            scheduled_at__lte=now,
        )

    @staticmethod
    def _emit_notification(news, user):
        """Emit notification when news is published."""
        try:
            from notifications.services.notification_service import NotificationService

            NotificationService.create(
                recipient=user,
                category_code="CLUB_NEWS",
                event_type="club.news.published",
                title=f"News published: {news.title}",
                message=f"New article published for {news.club.name}: {news.title}",
                deduplication_key=f"club-news-published-{news.id}",
                data={
                    "club_id": str(news.club_id),
                    "news_id": str(news.id),
                    "category_id": str(news.category_id) if news.category_id else None,
                },
            )
        except Exception:
            logger.exception("Failed to emit news published notification")


news_service = NewsService()
