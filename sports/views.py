from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny

from sports.models import (
    Competition,
    Participant,
    Sport,
    SportingEvent,
)
from sports.serializers import (
    CompetitionListQuerySerializer,
    CompetitionPublicSerializer,
    ParticipantListQuerySerializer,
    ParticipantPublicSerializer,
    SportingEventListQuerySerializer,
    SportingEventPublicSerializer,
    SportPublicSerializer,
)
from system.pagination import PublicCatalogPagination


class SportListView(ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = SportPublicSerializer
    pagination_class = PublicCatalogPagination
    queryset = Sport.objects.filter(
        is_active=True,
    ).order_by("name")

    @extend_schema(tags=["Sports"])
    def get(self, request, *args, **kwargs):
        return super().get(
            request,
            *args,
            **kwargs,
        )


class CompetitionListView(ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = CompetitionPublicSerializer
    pagination_class = PublicCatalogPagination

    @extend_schema(
        parameters=[
            CompetitionListQuerySerializer,
        ],
        tags=["Sports"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(
            request,
            *args,
            **kwargs,
        )

    def get_queryset(self):
        query = CompetitionListQuerySerializer(
            data=self.request.query_params,
        )
        query.is_valid(
            raise_exception=True,
        )
        filters = query.validated_data

        queryset = Competition.objects.filter(
            is_active=True,
            is_verified=True,
            sport__is_active=True,
        ).select_related("sport")

        if sport_id := filters.get("sport"):
            queryset = queryset.filter(
                sport_id=sport_id,
            )

        if search := filters.get("search"):
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(country_code__icontains=search)
            )

        return queryset.order_by(
            "sport__name",
            "name",
        )


class ParticipantListView(ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = ParticipantPublicSerializer
    pagination_class = PublicCatalogPagination

    @extend_schema(
        parameters=[
            ParticipantListQuerySerializer,
        ],
        tags=["Sports"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(
            request,
            *args,
            **kwargs,
        )

    def get_queryset(self):
        query = ParticipantListQuerySerializer(
            data=self.request.query_params,
        )
        query.is_valid(
            raise_exception=True,
        )
        filters = query.validated_data

        queryset = Participant.objects.filter(
            is_active=True,
            is_verified=True,
            sport__is_active=True,
        ).select_related("sport")

        if sport_id := filters.get("sport"):
            queryset = queryset.filter(
                sport_id=sport_id,
            )

        if kind := filters.get("kind"):
            queryset = queryset.filter(
                kind=kind,
            )

        if search := filters.get("search"):
            queryset = queryset.filter(Q(name__icontains=search) | Q(short_name__icontains=search))

        return queryset.order_by(
            "sport__name",
            "name",
        )


class SportingEventListView(ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = SportingEventPublicSerializer
    pagination_class = PublicCatalogPagination

    @extend_schema(
        parameters=[
            SportingEventListQuerySerializer,
        ],
        tags=["Sports"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(
            request,
            *args,
            **kwargs,
        )

    def get_queryset(self):
        query = SportingEventListQuerySerializer(
            data=self.request.query_params,
        )
        query.is_valid(
            raise_exception=True,
        )
        filters = query.validated_data

        queryset = (
            SportingEvent.objects.filter(
                is_verified=True,
                sport__is_active=True,
            )
            .select_related(
                "sport",
                "competition",
                "competition__sport",
            )
            .prefetch_related(
                "event_participants__participant",
                ("event_participants__" "participant__sport"),
            )
        )

        if sport_id := filters.get("sport"):
            queryset = queryset.filter(
                sport_id=sport_id,
            )

        if competition_id := filters.get("competition"):
            queryset = queryset.filter(
                competition_id=competition_id,
            )

        if participant_id := filters.get("participant"):
            queryset = queryset.filter(
                event_participants__participant_id=(participant_id),
            )

        if event_status := filters.get("status"):
            queryset = queryset.filter(
                status=event_status,
            )

        if event_type := filters.get("event_type"):
            queryset = queryset.filter(
                event_type=event_type,
            )

        if search := filters.get("search"):
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(venue__icontains=search)
                | Q(competition__name__icontains=(search))
                | Q(event_participants__participant__name__icontains=(search))
            )

        return queryset.distinct().order_by(
            "starts_at",
            "name",
        )
