from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from markets.admin_views import MarketAdminQuerysetMixin
from markets.models import Market, MarketProvisionalResult, MarketResultDevelopmentAcceleration
from markets.permissions import HasResultVerificationPermission
from markets.result_verification_serializers import (
    MarketResultAccelerationRequestSerializer,
    MarketResultAccelerationResponseSerializer,
    MarketResultVerificationSerializer,
)


class MarketResultVerificationQueueView(MarketAdminQuerysetMixin, ListAPIView):
    permission_classes = [IsAuthenticated, HasResultVerificationPermission]
    serializer_class = MarketResultVerificationSerializer
    pagination_class = None

    def get_queryset(self):
        return (
            self.get_admin_queryset()
            .filter(status__in=[Market.Status.CLOSED, Market.Status.RESOLVED, Market.Status.VOIDED])
            .select_related("provisional_result", "settlement", "void_refund")
            .prefetch_related(
                "provisional_result__evidence_items",
                "provisional_result__disputes",
                "provisional_result__decisions",
                "provisional_result__development_acceleration",
            )
            .order_by("closes_at", "created_at")
        )


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
