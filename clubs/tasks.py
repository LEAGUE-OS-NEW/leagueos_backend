"""Celery tasks for club management."""

from __future__ import annotations

import logging

from clubs.services.club_profile_service import ClubProfileService
from clubs.services.media_service import MediaService
from clubs.services.news_service import NewsService

logger = logging.getLogger(__name__)


def publish_scheduled_content():
    """Publish scheduled club content that is due."""

    # Publish scheduled profiles
    for profile in ClubProfileService.get_scheduled_profiles():
        try:
            ClubProfileService.publish_profile(profile, profile.created_by)
        except Exception:
            logger.exception("Failed to publish scheduled profile %s", profile.id)

    # Publish scheduled media
    for media in MediaService.get_scheduled_media():
        try:
            MediaService.publish_media(media, media.uploaded_by)
        except Exception:
            logger.exception("Failed to publish scheduled media %s", media.id)

    # Publish scheduled news
    for news in NewsService.get_scheduled_news():
        try:
            NewsService.publish_news(news, news.created_by)
        except Exception:
            logger.exception("Failed to publish scheduled news %s", news.id)
