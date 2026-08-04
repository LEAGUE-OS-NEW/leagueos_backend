"""News service."""

from __future__ import annotations

import logging

from django.db.models import Q

from discovery.models import AuditLog, News

logger = logging.getLogger(__name__)


class NewsService:
    """Service for news operations."""

    @classmethod
    def get_public_news(
        cls,
        category=None,
        sport=None,
        competition=None,
        club=None,
        featured=None,
        search=None,
        ordering="-published_at",
    ):
        """Return approved and published news only."""
        qs = News.objects.filter(
            status=News.Status.PUBLISHED,
            is_verified=True,
        ).select_related("category", "sport", "competition", "club")

        if category:
            qs = qs.filter(category_id=category)
        if sport:
            qs = qs.filter(sport_id=sport)
        if competition:
            qs = qs.filter(competition_id=competition)
        if club:
            qs = qs.filter(club_id=club)
        if featured is not None:
            qs = qs.filter(is_featured=featured)
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(summary__icontains=search))

        return qs.order_by(ordering)

    @staticmethod
    def record_view(news_id: str, user=None, request=None) -> None:
        """Record a news view audit log."""
        try:
            AuditLog.objects.create(
                user=user if user and user.is_authenticated else None,
                action="NEWS_VIEWED",
                entity_type="news",
                entity_id=news_id,
                ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"),
                user_agent=getattr(request, "META", {}).get("HTTP_USER_AGENT", ""),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to record news view audit log")


news_service = NewsService()
