"""Enterprise search service.

Implements a pluggable search provider behind a common interface
(Open/Closed principle).  The default provider is PostgreSQL
Full-Text Search.  Future providers (Elasticsearch, OpenSearch,
Meilisearch, Algolia) can be added without changing API endpoints or
business logic.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Any

from django.core.cache import cache
from django.db import connection
from django.db.models import Q, QuerySet

from discovery.models import AuditLog, SearchAnalytics, SearchSuggestion
from profiles.models import Club
from sports.models import Competition, Participant, SportingEvent

logger = logging.getLogger(__name__)

# Sanitization: strip control characters and collapse whitespace.
_WHITESPACE_RE = re.compile(r"\s+")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

# Default query limits (configurable via settings).
MAX_QUERY_LENGTH = 200
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20
MAX_RESULT_COUNT = 1000

# Entity -> (queryset, model, searchable fields)
SEARCH_ENTITIES = {
    "club": (Club.objects.all(), Club, ("name", "slug")),
    "player": (
        Participant.objects.filter(kind=Participant.Kind.ATHLETE),
        Participant,
        ("name", "short_name", "slug"),
    ),
    "competition": (
        Competition.objects.all(),
        Competition,
        ("name", "slug", "country_code"),
    ),
    "fixture": (
        SportingEvent.objects.all(),
        SportingEvent,
        ("name", "venue"),
    ),
    "news": (None, None, ()),  # handled separately
    "venue": (None, None, ()),  # handled separately
}


def sanitize_query(raw: str | None) -> str:
    """Sanitize and normalize a search query.

    Strips control characters, collapses whitespace, and enforces a
    maximum length.  Prevents regex/DoS and overly long queries.
    """
    if raw is None:
        return ""
    cleaned = _CONTROL_RE.sub("", raw)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned[:MAX_QUERY_LENGTH]


class SearchProvider(ABC):
    """Abstract search provider interface."""

    @abstractmethod
    def search(
        self,
        query: str,
        entity_type: str | None = None,
        filters: dict[str, Any] | None = None,
        ordering: str = "relevance",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """Execute a search and return paginated results."""


class PostgresFullTextSearchProvider(SearchProvider):
    """PostgreSQL Full-Text Search provider."""

    def search(
        self,
        query: str,
        entity_type: str | None = None,
        filters: dict[str, Any] | None = None,
        ordering: str = "relevance",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:

        filters = filters or {}
        results: list[dict[str, Any]] = []
        total = 0

        if entity_type and entity_type != "all":
            results, total = self._search_entity(
                query, entity_type, filters, ordering, page, page_size
            )
        else:
            for ent_type in ("club", "player", "competition", "fixture"):
                ent_results, ent_total = self._search_entity(
                    query, ent_type, filters, ordering, page, page_size
                )
                results.extend(ent_results)
                total += ent_total

        return {
            "results": results,
            "count": total,
            "page": page,
            "page_size": page_size,
        }

    def _search_entity(
        self,
        query: str,
        entity_type: str,
        filters: dict[str, Any],
        ordering: str,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector

        if entity_type not in SEARCH_ENTITIES:
            return [], 0

        base_qs, model, fields = SEARCH_ENTITIES[entity_type]
        if base_qs is None:
            return [], 0

        # Build a document vector from the searchable fields.
        vector = SearchVector(*fields)
        query_obj = SearchQuery(query)
        qs = base_qs.annotate(rank=SearchRank(vector, query_obj)).filter(rank__gt=0)

        qs = self._apply_filters(qs, model, entity_type, filters)

        if ordering == "relevance":
            qs = qs.order_by("-rank")
        elif ordering == "name":
            qs = qs.order_by("name")
        elif ordering == "-created_at":
            qs = qs.order_by("-created_at")
        else:
            qs = qs.order_by("-rank")

        total = qs.count()
        start = (page - 1) * page_size
        end = start + page_size
        entities = qs[start:end]

        return (
            [self._serialize(entity_type, obj) for obj in entities],
            total,
        )

    def _apply_filters(
        self,
        qs: QuerySet,
        model: type,
        entity_type: str,
        filters: dict[str, Any],
    ) -> QuerySet:
        sport_id = filters.get("sport")
        competition_id = filters.get("competition")
        country = filters.get("country")
        club_id = filters.get("club")
        season_id = filters.get("season")
        status = filters.get("status")
        date_from = filters.get("date_from")
        date_to = filters.get("date_to")

        if sport_id and hasattr(model, "sport_id"):
            qs = qs.filter(sport_id=sport_id)
        if competition_id and hasattr(model, "competition_id"):
            qs = qs.filter(competition_id=competition_id)
        if country and hasattr(model, "country_code"):
            qs = qs.filter(country_code=country)
        if club_id and hasattr(model, "club_id"):
            qs = qs.filter(club_id=club_id)
        if season_id and hasattr(model, "season_id"):
            qs = qs.filter(season_id=season_id)
        if status and hasattr(model, "status"):
            qs = qs.filter(status=status)
        if date_from and entity_type == "fixture" and hasattr(model, "starts_at"):
            qs = qs.filter(starts_at__gte=date_from)
        if date_to and entity_type == "fixture" and hasattr(model, "starts_at"):
            qs = qs.filter(starts_at__lte=date_to)

        return qs

    def _serialize(self, entity_type: str, obj: Any) -> dict[str, Any]:
        return {
            "id": str(obj.id),
            "entity_type": entity_type,
            "display_name": getattr(obj, "name", str(obj)),
            "slug": getattr(obj, "slug", ""),
            "country_code": getattr(obj, "country_code", ""),
            "sport": str(getattr(obj, "sport_id", "") or ""),
            "competition": str(getattr(obj, "competition_id", "") or ""),
            "status": getattr(obj, "status", ""),
            "starts_at": (obj.starts_at.isoformat() if getattr(obj, "starts_at", None) else None),
            "logo": "",
        }


class FallbackSearchProvider(SearchProvider):
    """Fallback provider using icontains (works on SQLite)."""

    def search(
        self,
        query: str,
        entity_type: str | None = None,
        filters: dict[str, Any] | None = None,
        ordering: str = "relevance",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        filters = filters or {}
        results: list[dict[str, Any]] = []
        total = 0

        entities = ["club", "player", "competition", "fixture"]
        if entity_type and entity_type != "all":
            entities = [entity_type]

        for ent_type in entities:
            ent_results, ent_total = self._search_entity(
                query, ent_type, filters, ordering, page, page_size
            )
            results.extend(ent_results)
            total += ent_total

        return {
            "results": results,
            "count": total,
            "page": page,
            "page_size": page_size,
        }

    def _search_entity(
        self,
        query: str,
        entity_type: str,
        filters: dict[str, Any],
        ordering: str,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        if entity_type not in SEARCH_ENTITIES:
            return [], 0

        base_qs, model, fields = SEARCH_ENTITIES[entity_type]
        if base_qs is None:
            return [], 0

        q_filter = Q()
        for field in fields:
            q_filter |= Q(**{f"{field}__icontains": query})
        qs = base_qs.filter(q_filter)

        qs = self._apply_filters(qs, model, entity_type, filters)

        if ordering == "name":
            qs = qs.order_by("name")
        elif ordering == "-created_at":
            qs = qs.order_by("-created_at")
        else:
            qs = qs.order_by("name")

        total = qs.count()
        start = (page - 1) * page_size
        end = start + page_size
        entities = qs[start:end]

        return (
            [self._serialize(entity_type, obj) for obj in entities],
            total,
        )

    def _apply_filters(
        self,
        qs: QuerySet,
        model: type,
        entity_type: str,
        filters: dict[str, Any],
    ) -> QuerySet:
        sport_id = filters.get("sport")
        competition_id = filters.get("competition")
        country = filters.get("country")
        club_id = filters.get("club")
        season_id = filters.get("season")
        status = filters.get("status")
        date_from = filters.get("date_from")
        date_to = filters.get("date_to")

        if sport_id and hasattr(model, "sport_id"):
            qs = qs.filter(sport_id=sport_id)
        if competition_id and hasattr(model, "competition_id"):
            qs = qs.filter(competition_id=competition_id)
        if country and hasattr(model, "country_code"):
            qs = qs.filter(country_code=country)
        if club_id and hasattr(model, "club_id"):
            qs = qs.filter(club_id=club_id)
        if season_id and hasattr(model, "season_id"):
            qs = qs.filter(season_id=season_id)
        if status and hasattr(model, "status"):
            qs = qs.filter(status=status)
        if date_from and entity_type == "fixture" and hasattr(model, "starts_at"):
            qs = qs.filter(starts_at__gte=date_from)
        if date_to and entity_type == "fixture" and hasattr(model, "starts_at"):
            qs = qs.filter(starts_at__lte=date_to)

        return qs

    def _serialize(self, entity_type: str, obj: Any) -> dict[str, Any]:
        return {
            "id": str(obj.id),
            "entity_type": entity_type,
            "display_name": getattr(obj, "name", str(obj)),
            "slug": getattr(obj, "slug", ""),
            "country_code": getattr(obj, "country_code", ""),
            "sport": str(getattr(obj, "sport_id", "") or ""),
            "competition": str(getattr(obj, "competition_id", "") or ""),
            "status": getattr(obj, "status", ""),
            "starts_at": (obj.starts_at.isoformat() if getattr(obj, "starts_at", None) else None),
            "logo": "",
        }


class SearchService:
    """Facade for enterprise search.

    Selects the provider based on the database backend.  The provider
    can be swapped without affecting API endpoints or business logic.
    """

    def __init__(self) -> None:
        self.provider = self._get_provider()

    @staticmethod
    def _get_provider() -> SearchProvider:
        vendor = connection.vendor
        if vendor == "postgresql":
            return PostgresFullTextSearchProvider()
        return FallbackSearchProvider()

    @staticmethod
    def _cache_key(query: str, entity_type: str, filters: dict, page: int, page_size: int) -> str:
        raw = f"{query}|{entity_type}|{sorted(filters.items())}|{page}|{page_size}"
        digest = hashlib.md5(raw.encode()).hexdigest()  # noqa: S324
        return f"search:{digest}"

    def search(
        self,
        query: str,
        entity_type: str | None = None,
        filters: dict[str, Any] | None = None,
        ordering: str = "relevance",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        user=None,
        request=None,
    ) -> dict[str, Any]:
        """Execute a search with caching, analytics, and audit logging."""
        start = time.perf_counter()
        sanitized = sanitize_query(query)
        filters = filters or {}

        if not sanitized:
            return {
                "results": [],
                "count": 0,
                "page": page,
                "page_size": page_size,
            }

        cache_key = self._cache_key(sanitized, entity_type or "all", filters, page, page_size)
        cached = cache.get(cache_key)
        if cached is not None:
            duration_ms = int((time.perf_counter() - start) * 1000)
            self._record_analytics(
                sanitized, user, request, duration_ms, len(cached.get("results", [])), filters
            )
            return cached

        try:
            result = self.provider.search(
                sanitized,
                entity_type=entity_type,
                filters=filters,
                ordering=ordering,
                page=page,
                page_size=page_size,
            )
            cache.set(cache_key, result, timeout=300)
            duration_ms = int((time.perf_counter() - start) * 1000)
            self._record_analytics(
                sanitized, user, request, duration_ms, result.get("count", 0), filters
            )
            self._record_audit(sanitized, user, request, filters)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.exception("Search failed for query %r", sanitized)
            duration_ms = int((time.perf_counter() - start) * 1000)
            self._record_analytics(
                sanitized, user, request, duration_ms, 0, filters, is_failed=True, error=str(exc)
            )
            return {
                "results": [],
                "count": 0,
                "page": page,
                "page_size": page_size,
            }

    def _record_analytics(
        self,
        query: str,
        user,
        request,
        duration_ms: int,
        result_count: int,
        filters: dict,
        is_failed: bool = False,
        error: str = "",
    ) -> None:
        try:
            SearchAnalytics.objects.create(
                query=query,
                user=user if user and user.is_authenticated else None,
                duration_ms=duration_ms,
                result_count=result_count,
                applied_filters=filters,
                is_empty=result_count == 0,
                is_failed=is_failed,
                error_message=error,
                ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to record search analytics")

    def _record_audit(self, query: str, user, request, filters: dict) -> None:
        try:
            AuditLog.objects.create(
                user=user if user and user.is_authenticated else None,
                action="SEARCH_PERFORMED",
                entity_type="search",
                metadata={"query": query, "filters": filters},
                ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"),
                user_agent=getattr(request, "META", {}).get("HTTP_USER_AGENT", ""),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to record search audit log")

    def autocomplete(
        self,
        query: str,
        entity_type: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Provide autocomplete suggestions across clubs, players, competitions, venues."""
        sanitized = sanitize_query(query)
        if not sanitized:
            return []

        limit = max(1, min(limit, 20))
        results: list[dict[str, Any]] = []

        entities = ["club", "player", "competition"]
        if entity_type and entity_type != "all":
            entities = [entity_type]

        for ent_type in entities:
            base_qs, model, fields = SEARCH_ENTITIES[ent_type]
            if base_qs is None:
                continue
            q_filter = Q()
            for field in fields:
                q_filter |= Q(**{f"{field}__icontains": sanitized})
            objs = base_qs.filter(q_filter)[:limit]
            for obj in objs:
                results.append(
                    {
                        "uuid": str(obj.id),
                        "display_name": getattr(obj, "name", str(obj)),
                        "entity_type": ent_type,
                        "logo": "",
                    }
                )
                if len(results) >= limit:
                    break

        # Venues (from discovery)
        from discovery.models import Venue

        venue_qs = Venue.objects.filter(is_active=True, is_verified=True)
        venue_objs = venue_qs.filter(name__icontains=sanitized)[:limit]
        for obj in venue_objs:
            results.append(
                {
                    "uuid": str(obj.id),
                    "display_name": obj.name,
                    "entity_type": "venue",
                    "logo": "",
                }
            )

        return results[:limit]

    def suggestions(self, user=None, limit: int = 10) -> list[dict]:
        """Return database-driven search suggestions."""
        limit = max(1, min(limit, 20))

        suggestions = SearchSuggestion.objects.filter(is_active=True)
        if user and user.is_authenticated:
            suggestions = suggestions.filter(Q(user=user) | Q(user__isnull=True))
        else:
            suggestions = suggestions.filter(user__isnull=True)

        return [
            {
                "suggestion_type": s.suggestion_type,
                "entity_type": s.entity_type,
                "entity_id": str(s.entity_id),
                "display_name": s.display_name,
            }
            for s in suggestions.order_by("-score")[:limit]
        ]


search_service = SearchService()
