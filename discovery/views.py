"""Views for the discovery module."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from discovery.serializers import (
    AutocompleteQuerySerializer,
    AutocompleteResultSerializer,
    ClubDetailResponseSerializer,
    ClubListQuerySerializer,
    CompetitionSerializer,
    DiscoveryClubSerializer,
    FixtureListQuerySerializer,
    FixtureSerializer,
    FollowSerializer,
    MatchCentreSerializer,
    NewsCategorySerializer,
    NewsListQuerySerializer,
    NewsSerializer,
    PlayerDetailResponseSerializer,
    PlayerListQuerySerializer,
    PlayerSerializer,
    SearchQuerySerializer,
    SearchResponseSerializer,
    SeasonCreateSerializer,
    SuggestionSerializer,
)
from discovery.services.club_service import club_service
from discovery.services.fixture_service import fixture_service
from discovery.services.following_service import following_service
from discovery.services.match_centre_service import match_centre_service
from discovery.services.news_service import news_service
from discovery.services.player_service import player_service
from discovery.services.search_service import search_service
from system.pagination import PublicCatalogPagination

SystemPagination = PublicCatalogPagination


# =============================================================================
# Search
# =============================================================================


@extend_schema_view(
    get=extend_schema(
        parameters=[SearchQuerySerializer],
        responses=SearchResponseSerializer,
        tags=["Discovery"],
    )
)
class SearchView(APIView):
    """Enterprise search across clubs, players, competitions, fixtures."""

    permission_classes = [AllowAny]

    def get(self, request):
        query = SearchQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data

        filters = {}
        for key in ("sport", "competition", "country", "club", "season"):
            if params.get(key):
                filters[key] = str(params[key])

        result = search_service.search(
            query=params.get("q", ""),
            filters=filters,
            ordering=params.get("ordering", "relevance"),
            page=params.get("page", 1),
            page_size=params.get("page_size", 20),
            user=request.user,
            request=request,
        )

        return Response(result)


@extend_schema_view(
    get=extend_schema(
        parameters=[AutocompleteQuerySerializer],
        responses=AutocompleteResultSerializer(many=True),
        tags=["Discovery"],
    )
)
class SearchAutocompleteView(APIView):
    """Search autocomplete for clubs, players, competitions, venues."""

    permission_classes = [AllowAny]

    def get(self, request):
        query = AutocompleteQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data

        results = search_service.autocomplete(
            query=params.get("q", ""),
            entity_type=params.get("entity_type", "all"),
            limit=params.get("limit", 10),
        )

        return Response(results)


@extend_schema_view(
    get=extend_schema(
        responses=SuggestionSerializer(many=True),
        tags=["Discovery"],
    )
)
class SearchSuggestionsView(APIView):
    """Database-driven search suggestions."""

    permission_classes = [AllowAny]

    def get(self, request):
        limit = request.query_params.get("limit", 10)
        try:
            limit = max(1, min(int(limit), 20))
        except (TypeError, ValueError):
            limit = 10

        results = search_service.suggestions(
            user=request.user,
            limit=limit,
        )
        return Response(results)


# =============================================================================
# Clubs
# =============================================================================


@extend_schema_view(
    get=extend_schema(
        parameters=[ClubListQuerySerializer],
        responses=DiscoveryClubSerializer(many=True),
        tags=["Discovery"],
    )
)
class ClubListView(ListAPIView):
    """Public club list."""

    permission_classes = [AllowAny]
    serializer_class = DiscoveryClubSerializer
    pagination_class = SystemPagination

    def get_queryset(self):
        query = ClubListQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data

        return club_service.get_public_clubs(
            sport=params.get("sport"),
            search=params.get("search"),
            ordering=params.get("ordering", "name"),
            has_admin=params.get("has_admin"),
        )


@extend_schema_view(
    get=extend_schema(
        responses=ClubDetailResponseSerializer,
        tags=["Discovery"],
    )
)
class ClubDetailView(RetrieveAPIView):
    """Public club profile detail."""

    serializer_class = ClubDetailResponseSerializer
    permission_classes = [AllowAny]
    lookup_url_kwarg = "club_id"

    def get_object(self):
        club_id = self.kwargs[self.lookup_url_kwarg]
        club = club_service.get_public_club(club_id, request=self.request)
        if club is None:
            from django.http import Http404

            raise Http404("Club not found.")
        return club

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        club_service.record_view(instance["id"], user=request.user, request=request)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


@extend_schema_view(
    get=extend_schema(
        responses=DiscoveryClubSerializer(many=True),
        tags=["Discovery"],
    )
)
class ClubMediaListView(ListAPIView):
    """Public club media list (published only)."""

    permission_classes = [AllowAny]
    pagination_class = SystemPagination

    def get_queryset(self):
        from clubs.models import ClubMedia
        from profiles.models import Club

        club_id = self.kwargs.get("club_id")
        Club.objects.filter(id=club_id, is_active=True).first()
        return ClubMedia.objects.filter(
            club_id=club_id,
            status=ClubMedia.Status.PUBLISHED,
        ).order_by("display_order", "-created_at")

    def list(self, request, *args, **kwargs):
        media = self.get_queryset()
        results = [
            {
                "id": str(m.id),
                "media_type": m.media_type,
                "title": m.title,
                "description": m.description,
                "url": m.file.url if m.file else m.url,
                "thumbnail": m.thumbnail.url if m.thumbnail else None,
                "is_featured": m.is_featured,
            }
            for m in media
        ]

        return Response({"results": results, "count": len(results)})


# =============================================================================
# Players
# =============================================================================


@extend_schema_view(
    get=extend_schema(
        parameters=[PlayerListQuerySerializer],
        responses=PlayerSerializer(many=True),
        tags=["Discovery"],
    )
)
class PlayerListView(ListAPIView):
    """Public player list."""

    permission_classes = [AllowAny]
    serializer_class = PlayerSerializer
    pagination_class = SystemPagination

    def get_queryset(self):
        query = PlayerListQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data

        return player_service.get_public_players(
            sport=params.get("sport"),
            club=params.get("club"),
            search=params.get("search"),
            ordering=params.get("ordering", "name"),
        )


@extend_schema_view(
    get=extend_schema(
        responses=PlayerDetailResponseSerializer,
        tags=["Discovery"],
    )
)
class PlayerDetailView(RetrieveAPIView):
    """Public player profile detail."""

    permission_classes = [AllowAny]
    lookup_url_kwarg = "player_id"

    def get(self, request, *args, **kwargs):
        player_id = self.kwargs["player_id"]
        data = player_service.get_public_player(player_id, request=request)
        if data is None:
            return Response(
                {"detail": "Player not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        player_service.record_view(player_id, user=request.user, request=request)
        return Response(data)


# =============================================================================
# Competitions
# =============================================================================


@extend_schema_view(
    get=extend_schema(
        responses=CompetitionSerializer(many=True),
        tags=["Discovery"],
    )
)
class CompetitionListView(ListAPIView):
    """Public competition list."""

    permission_classes = [AllowAny]
    serializer_class = CompetitionSerializer
    pagination_class = SystemPagination

    def get_queryset(self):
        from sports.models import Competition

        qs = Competition.objects.filter(
            is_active=True,
            is_verified=True,
            sport__is_active=True,
        ).select_related("sport")

        sport = self.request.query_params.get("sport")
        if sport:
            qs = qs.filter(sport_id=sport)

        return qs.order_by("sport__name", "name")


class SeasonCreateView(APIView):
    """Admin create endpoint for canonical seasons."""

    permission_classes = [IsAuthenticated]
    serializer_class = SeasonCreateSerializer

    def post(self, request):
        from authentication.services.permission_service import PermissionService

        if not PermissionService.has_permission(request.user, "admin.clubs.manage"):
            return Response(
                {"detail": "You do not have permission to manage sports data."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = SeasonCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        season = serializer.save()
        return Response(
            {
                "id": str(season.id),
                "sport": str(season.sport_id),
                "competition": str(season.competition_id) if season.competition_id else None,
                "name": season.name,
                "slug": season.slug,
                "starts_on": season.starts_on.isoformat() if season.starts_on else None,
                "ends_on": season.ends_on.isoformat() if season.ends_on else None,
                "is_active": season.is_active,
                "is_verified": season.is_verified,
            },
            status=status.HTTP_201_CREATED,
        )


# =============================================================================
# Fixtures & Results
# =============================================================================


@extend_schema_view(
    get=extend_schema(
        parameters=[FixtureListQuerySerializer],
        responses=FixtureSerializer(many=True),
        tags=["Discovery"],
    )
)
class FixtureListView(ListAPIView):
    """Public fixture list."""

    permission_classes = [AllowAny]
    serializer_class = FixtureSerializer
    pagination_class = SystemPagination

    def get_queryset(self):
        query = FixtureListQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data

        return fixture_service.get_public_fixtures(
            sport=params.get("sport"),
            competition=params.get("competition"),
            club=params.get("club"),
            status=params.get("status"),
            date_from=params.get("date_from"),
            date_to=params.get("date_to"),
            ordering=params.get("ordering", "starts_at"),
        )


@extend_schema_view(
    get=extend_schema(
        responses=FixtureSerializer,
        tags=["Discovery"],
    )
)
class FixtureDetailView(RetrieveAPIView):
    """Public fixture detail."""

    permission_classes = [AllowAny]
    serializer_class = FixtureSerializer
    lookup_url_kwarg = "fixture_id"

    def get_object(self):
        fixture_id = self.kwargs[self.lookup_url_kwarg]
        fixture = fixture_service.get_public_fixture(fixture_id, request=self.request)
        if fixture is None:
            from django.http import Http404

            raise Http404("Fixture not found.")
        return fixture

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        fixture_service.record_view(str(instance.id), user=request.user, request=request)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


@extend_schema_view(
    get=extend_schema(
        parameters=[FixtureListQuerySerializer],
        responses=FixtureSerializer(many=True),
        tags=["Discovery"],
    )
)
class ResultListView(ListAPIView):
    """Public results list (completed fixtures)."""

    permission_classes = [AllowAny]
    serializer_class = FixtureSerializer
    pagination_class = SystemPagination

    def get_queryset(self):
        query = FixtureListQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data

        return fixture_service.get_results(
            sport=params.get("sport"),
            competition=params.get("competition"),
            club=params.get("club"),
            date_from=params.get("date_from"),
            date_to=params.get("date_to"),
        )


# =============================================================================
# News
# =============================================================================


@extend_schema_view(
    get=extend_schema(
        responses=NewsCategorySerializer(many=True),
        tags=["Discovery"],
    )
)
class NewsCategoryListView(ListAPIView):
    """Public, active news categories — used to populate the submit/compose
    category picker on both the club and admin sides."""

    permission_classes = [AllowAny]
    serializer_class = NewsCategorySerializer

    def get_queryset(self):
        from discovery.models import NewsCategory

        return NewsCategory.objects.filter(is_active=True).order_by("display_order", "name")


@extend_schema_view(
    get=extend_schema(
        parameters=[NewsListQuerySerializer],
        responses=NewsSerializer(many=True),
        tags=["Discovery"],
    )
)
class NewsListView(ListAPIView):
    """Public news list (published & verified only)."""

    permission_classes = [AllowAny]
    serializer_class = NewsSerializer
    pagination_class = SystemPagination

    def get_queryset(self):
        query = NewsListQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data

        return news_service.get_public_news(
            category=params.get("category"),
            sport=params.get("sport"),
            competition=params.get("competition"),
            club=params.get("club"),
            featured=params.get("featured"),
            search=params.get("search"),
            ordering=params.get("ordering", "-published_at"),
        )


@extend_schema_view(
    get=extend_schema(
        responses=NewsSerializer,
        tags=["Discovery"],
    )
)
class NewsDetailView(RetrieveAPIView):
    """Public news article detail."""

    permission_classes = [AllowAny]
    serializer_class = NewsSerializer
    lookup_url_kwarg = "news_id"

    def get_object(self):
        from django.http import Http404

        news_id = self.kwargs[self.lookup_url_kwarg]
        article = news_service.get_public_news_detail(news_id)
        if article is None:
            raise Http404("News article not found.")
        return article


# =============================================================================
# Match Centre
# =============================================================================


@extend_schema_view(
    get=extend_schema(
        responses=MatchCentreSerializer,
        tags=["Discovery"],
    )
)
class MatchCentreView(APIView):
    """Aggregated match centre for a canonical fixture."""

    permission_classes = [AllowAny]

    def get(self, request, fixture_id):
        data = match_centre_service.get_match_centre(fixture_id, request=request)
        if data is None:
            return Response(
                {"detail": "Fixture not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        match_centre_service.record_view(fixture_id, user=request.user, request=request)
        return Response(data)


# =============================================================================
# Following
# =============================================================================


@extend_schema_view(
    post=extend_schema(
        responses=FollowSerializer,
        tags=["Discovery"],
    )
)
class ClubFollowView(APIView):
    """Follow a club."""

    permission_classes = [IsAuthenticated]
    serializer_class = FollowSerializer

    def post(self, request, club_id):
        try:
            preference = following_service.follow_club(
                request.user,
                club_id,
                request=request,
            )
        except Exception:
            return Response(
                {"detail": "Club not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            FollowSerializer(preference).data,
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request, club_id):
        removed = following_service.unfollow_club(
            request.user,
            club_id,
            request=request,
        )
        if not removed:
            return Response(
                {"detail": "Club not followed."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    get=extend_schema(
        responses=FollowSerializer(many=True),
        tags=["Discovery"],
    )
)
class FollowingListView(ListAPIView):
    """List clubs the authenticated user follows."""

    permission_classes = [IsAuthenticated]
    serializer_class = FollowSerializer
    pagination_class = SystemPagination

    def get_queryset(self):
        return following_service.get_followed_clubs(self.request.user)
