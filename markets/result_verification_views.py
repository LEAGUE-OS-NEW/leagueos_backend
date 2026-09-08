from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from markets.admin_views import MarketAdminQuerysetMixin
from markets.models import (
    Market,
    MarketPosition,
    MarketProvisionalResult,
    MarketResultDevelopmentAcceleration,
)
from markets.permissions import HasResultVerificationPermission
from markets.result_verification_serializers import (
    MarketResultAccelerationRequestSerializer,
    MarketResultAccelerationResponseSerializer,
    MarketResultExposureResponseSerializer,
    MarketResultVerificationSerializer,
)


class MarketResultVerificationQueueView(MarketAdminQuerysetMixin, ListAPIView):
    permission_classes = [IsAuthenticated, HasResultVerificationPermission]
    serializer_class = MarketResultVerificationSerializer
    pagination_class = None

    def get_queryset(self):
        return (
            self.get_admin_queryset()
            .filter(
                Q(status__in=[Market.Status.CLOSED, Market.Status.RESOLVED, Market.Status.VOIDED])
                | Q(
                    status__in=[Market.Status.OPEN, Market.Status.SUSPENDED],
                    closes_at__lte=timezone.now(),
                )
            )
            .select_related("provisional_result", "settlement", "void_refund")
            .prefetch_related(
                "provisional_result__evidence_items",
                "provisional_result__disputes",
                "provisional_result__decisions",
                "provisional_result__development_acceleration",
            )
            .order_by("closes_at", "created_at")
        )


class MarketResultExposureView(APIView):
    """Per-outcome position count and stake for a market still awaiting a
    result decision, so an admin can see who's on each side before picking
    the winning outcome. Only reflects live, unsettled exposure — positions
    are zeroed on settlement, so this is meaningless (and excluded) once a
    market has actually been settled."""

    permission_classes = [IsAuthenticated, HasResultVerificationPermission]

    @extend_schema(responses={200: MarketResultExposureResponseSerializer})
    def get(self, request, market_id):
        get_object_or_404(Market, id=market_id)

        rows = (
            MarketPosition.objects.filter(market_id=market_id, quantity__gt=0)
            .values("outcome_id", "outcome__side", "outcome__label")
            .annotate(
                position_count=Count("id"),
                total_quantity=Sum("quantity"),
                total_stake=Sum("total_cost"),
            )
            .order_by("outcome__side")
        )

        outcomes = [
            {
                "outcome_id": row["outcome_id"],
                "side": row["outcome__side"],
                "label": row["outcome__label"],
                "position_count": row["position_count"],
                "total_quantity": row["total_quantity"],
                "total_stake": row["total_stake"],
            }
            for row in rows
        ]

        serializer = MarketResultExposureResponseSerializer({"outcomes": outcomes})
        return Response(serializer.data)


class MarketResultDevelopmentAcceleratorView(APIView):
    permission_classes = [IsAuthenticated, HasResultVerificationPermission]
    serializer_class = MarketResultAccelerationRequestSerializer

    @extend_schema(
        request=MarketResultAccelerationRequestSerializer,
        responses={200: MarketResultAccelerationResponseSerializer},
    )
    def post(self, request, market_id):
        local_enabled = settings.DEBUG and getattr(
            settings, "DEV_RESULT_ACCELERATOR_ENABLED", False
        )
        review_enabled = getattr(settings, "REVIEW_WORKFLOW_TOOLS_ENABLED", False)
        if not (local_enabled or review_enabled):
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not request.user.email.lower().endswith("@leagueos.test"):
            return Response(status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            provisional = get_object_or_404(
                MarketProvisionalResult.objects.select_for_update().select_related("market"),
                market_id=market_id,
            )
            creator = provisional.market.created_by
            if creator is None or not creator.email.lower().endswith("@leagueos.test"):
                return Response(status=status.HTTP_404_NOT_FOUND)
            acceleration, created = MarketResultDevelopmentAcceleration.objects.get_or_create(
                provisional_result=provisional,
                defaults={"accelerated_by": request.user},
            )

        return Response(
            {
                "development_only": True,
                "created": created,
                "effective_dispute_window_closed": True,
                "accelerated_at": acceleration.accelerated_at,
                "message": "Dispute window ended for local development testing only.",
            }
        )
