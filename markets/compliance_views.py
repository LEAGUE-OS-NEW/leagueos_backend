from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from markets.compliance_serializers import (
    AdminComplianceDetailSerializer,
    ComplianceReviewSerializer,
    ComplianceUpdateSerializer,
    EligibilityResponseSerializer,
)
from markets.models import MarketComplianceReview, MarketParticipantCompliance
from markets.permissions import HasManageCompliancePermission
from markets.services.compliance_service import MarketComplianceService
from markets.services.eligibility_service import MarketEligibilityService
from markets.services.kyc_service import KYCService
from system.pagination import PublicCatalogPagination


class MarketParticipantEligibilityView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=EligibilityResponseSerializer, tags=["Market Participation"])
    def get(self, request):
        return Response(MarketEligibilityService.evaluate(participant=request.user).as_dict())


class AdminParticipantComplianceDetailView(APIView):
    permission_classes = [IsAuthenticated, HasManageCompliancePermission]

    def participant(self, user_id):
        return get_object_or_404(
            get_user_model().objects.select_related(
                "profile__country", "market_compliance__reviewed_by"
            ),
            id=user_id,
        )

    def response_data(self, participant):
        result = MarketEligibilityService.evaluate(participant=participant).as_dict()
        try:
            compliance = participant.market_compliance
        except MarketParticipantCompliance.DoesNotExist:
            compliance = None
        result.update(
            {
                "participant_id": participant.id,
                "date_of_birth": (
                    participant.profile.date_of_birth if hasattr(participant, "profile") else None
                ),
                "reviewed_at": compliance.reviewed_at if compliance else None,
                "reviewed_by": compliance.reviewed_by_id if compliance else None,
                "jurisdiction_override_reason": (
                    compliance.jurisdiction_override_reason if compliance else ""
                ),
                "internal_review_notes": compliance.internal_review_notes if compliance else "",
            }
        )
        return result

    @extend_schema(responses=AdminComplianceDetailSerializer, tags=["Market Compliance"])
    def get(self, request, user_id):
        return Response(self.response_data(self.participant(user_id)))

    @extend_schema(
        request=ComplianceUpdateSerializer,
        responses=AdminComplianceDetailSerializer,
        tags=["Market Compliance"],
    )
    def patch(self, request, user_id):
        participant = self.participant(user_id)
        compliance = getattr(participant, "market_compliance", None)
        serializer = ComplianceUpdateSerializer(
            data=request.data, context={"compliance": compliance}
        )
        serializer.is_valid(raise_exception=True)
        MarketComplianceService.update(
            participant=participant, actor=request.user, changes=serializer.validated_data
        )
        new_kyc_status = serializer.validated_data.get("kyc_status")
        if new_kyc_status in ("VERIFIED", "REJECTED"):
            KYCService.admin_decide(
                participant=participant,
                decision=new_kyc_status,
                actor=request.user,
            )
        participant = self.participant(user_id)
        return Response(self.response_data(participant))


class AdminParticipantComplianceReviewListView(ListAPIView):
    permission_classes = [IsAuthenticated, HasManageCompliancePermission]
    serializer_class = ComplianceReviewSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        return MarketComplianceReview.objects.filter(
            participant_id=self.kwargs["user_id"]
        ).select_related("participant", "actor")
