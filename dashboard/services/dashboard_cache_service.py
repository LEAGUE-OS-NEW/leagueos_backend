"""Dashboard caching service using Redis.

Provides high-performance caching for dashboard data with automatic
invalidation based on user preferences and module updates.
"""

from __future__ import annotations

import logging
import hashlib
import json

from django.core.cache import cache
from django.contrib.auth import get_user_model

User = get_user_model()
logger = logging.getLogger(__name__)


class DashboardCacheService:
    """Service for caching dashboard data in Redis.

    Uses per-user cache keys with configurable TTL.
    Automatically invalidates cache when user preferences change.
    """

    @staticmethod
    def _generate_cache_key(user_id: str, namespace: str, suffix: str = "") -> str:
        """Generate a cache key for the given user and namespace.

        Args:
            user_id: The user's UUID
            namespace: Cache namespace (e.g., 'dashboard', 'navigation')
            suffix: Optional suffix for specific cache entries

        Returns:
            Formatted cache key string
        """
        key = f"dashboard:{namespace}:{user_id}"
        if suffix:
            key = f"{key}:{suffix}"
        return key

    @staticmethod
    def _hash_data(data: dict) -> str:
        """Generate a hash of the data for cache invalidation.

        Args:
            data: Dictionary to hash

        Returns:
            MD5 hash string
        """
        json_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.md5(json_str.encode()).hexdigest()  # noqa: S324

    @classmethod
    def get_dashboard(cls, user: User) -> dict | None:
        """Get cached dashboard data for the user.

        Args:
            user: The user to get dashboard data for

        Returns:
            Cached dashboard data or None if not cached
        """
        cache_key = cls._generate_cache_key(str(user.id), "dashboard")
        cached_data = cache.get(cache_key)

        if cached_data is not None:
            logger.debug("Dashboard cache hit for user %s", user.id)
            return cached_data

        logger.debug("Dashboard cache miss for user %s", user.id)
        return None

    @classmethod
    def set_dashboard(cls, user: User, data: dict, timeout: int = 300) -> None:
        """Cache dashboard data for the user.

        Args:
            user: The user to cache data for
            data: Dashboard data to cache
            timeout: Cache timeout in seconds (default: 300)
        """
        cache_key = cls._generate_cache_key(str(user.id), "dashboard")
        cache.set(cache_key, data, timeout=timeout)
        logger.debug("Dashboard cached for user %s (TTL: %ds)", user.id, timeout)

    @classmethod
    def invalidate_dashboard(cls, user: User) -> None:
        """Invalidate cached dashboard data for the user.

        Args:
            user: The user to invalidate cache for
        """
        cache_key = cls._generate_cache_key(str(user.id), "dashboard")
        cache.delete(cache_key)
        logger.debug("Dashboard cache invalidated for user %s", user.id)

    @classmethod
    def get_navigation(cls, user: User) -> dict | None:
        """Get cached navigation data for the user.

        Args:
            user: The user to get navigation data for

        Returns:
            Cached navigation data or None if not cached
        """
        cache_key = cls._generate_cache_key(str(user.id), "navigation")
        cached_data = cache.get(cache_key)

        if cached_data is not None:
            logger.debug("Navigation cache hit for user %s", user.id)
            return cached_data

        logger.debug("Navigation cache miss for user %s", user.id)
        return None

    @classmethod
    def set_navigation(cls, user: User, data: dict, timeout: int = 3600) -> None:
        """Cache navigation data for the user.

        Args:
            user: The user to cache data for
            data: Navigation data to cache
            timeout: Cache timeout in seconds (default: 3600)
        """
        cache_key = cls._generate_cache_key(str(user.id), "navigation")
        cache.set(cache_key, data, timeout=timeout)
        logger.debug("Navigation cached for user %s (TTL: %ds)", user.id, timeout)

    @classmethod
    def invalidate_navigation(cls, user: User) -> None:
        """Invalidate cached navigation data for the user.

        Args:
            user: The user to invalidate cache for
        """
        cache_key = cls._generate_cache_key(str(user.id), "navigation")
        cache.delete(cache_key)
        logger.debug("Navigation cache invalidated for user %s", user.id)

    @classmethod
    def get_widgets(cls, user: User) -> list | None:
        """Get cached widgets data for the user.

        Args:
            user: The user to get widgets data for

        Returns:
            Cached widgets data or None if not cached
        """
        cache_key = cls._generate_cache_key(str(user.id), "widgets")
        cached_data = cache.get(cache_key)

        if cached_data is not None:
            logger.debug("Widgets cache hit for user %s", user.id)
            return cached_data

        logger.debug("Widgets cache miss for user %s", user.id)
        return None

    @classmethod
    def set_widgets(cls, user: User, data: list, timeout: int = 600) -> None:
        """Cache widgets data for the user.

        Args:
            user: The user to cache data for
            data: Widgets data to cache
            timeout: Cache timeout in seconds (default: 600)
        """
        cache_key = cls._generate_cache_key(str(user.id), "widgets")
        cache.set(cache_key, data, timeout=timeout)
        logger.debug("Widgets cached for user %s (TTL: %ds)", user.id, timeout)

    @classmethod
    def invalidate_widgets(cls, user: User) -> None:
        """Invalidate cached widgets data for the user.

        Args:
            user: The user to invalidate cache for
        """
        cache_key = cls._generate_cache_key(str(user.id), "widgets")
        cache.delete(cache_key)
        logger.debug("Widgets cache invalidated for user %s", user.id)

    @classmethod
    def invalidate_all(cls, user: User) -> None:
        """Invalidate all cached dashboard data for the user.

        Call this when user preferences or profile data changes.

        Args:
            user: The user to invalidate all cache for
        """
        namespaces = ["dashboard", "navigation", "widgets"]
        for namespace in namespaces:
            cache_key = cls._generate_cache_key(str(user.id), namespace)
            cache.delete(cache_key)

        logger.debug("All dashboard cache invalidated for user %s", user.id)