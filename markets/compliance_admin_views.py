from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.generics import GenericAPIView, ListAPIView, RetrieveAPIView
from rest_framework.response import Response

from markets.compliance_admin_serializers import (
    ComplianceDecisionSerializer,
    DecisionProposalRequestSerializer,
    DecisionRequestSerializer,
    ReassessmentRequestSerializer,
    RiskAssessmentSerializer,
    RiskProfileSerializer,
)
from markets.models import (
    ComplianceDecisionProposal,
    MarketRiskAssessment,
    MarketRiskProfile,
)
from markets.permissions import HasManageCompliancePermission
from markets.services.compliance_decision_service import ComplianceDecisionService
from markets.services.risk_service import MarketRiskService
from system.pagination import PublicCatalogPagination


class FilterValidationMixin:
    def validate_choice(self, name, choices):
        value = self.request.query_params.get(name)
        if value and value not in choices:
            raise serializers.ValidationError({name: "Invalid filter value."})
        return value


class AdminRiskProfileListView(FilterValidationMixin, ListAPIView):
    permission_classes = [HasManageCompliancePermission]
    serializer_class = RiskProfileSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        q = MarketRiskProfile.objects.all().order_by("-last_assessed_at", "-id")
        p = self.request.query_params
        band = self.validate_choice("band", MarketRiskProfile.Band.values)
        if band:
            q = q.filter(risk_band=band)
        if p.get("restriction"):
            q = q.filter(restriction_recommendation=p["restriction"])
        if p.get("override"):
            q = q.filter(manual_override_state=p["override"])
        return q


class AdminRiskProfileDetailView(RetrieveAPIView):
    permission_classes = [HasManageCompliancePermission]
    serializer_class = RiskProfileSerializer
    queryset = MarketRiskProfile.objects.all()
    lookup_url_kwarg = "profile_id"


class AdminRiskAssessmentListView(ListAPIView):
    permission_classes = [HasManageCompliancePermission]
    serializer_class = RiskAssessmentSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        q = MarketRiskAssessment.objects.all().order_by("-created_at", "-id")
        participant = self.request.query_params.get("participant")
        if participant:
            participant = serializers.UUIDField().run_validation(participant)
            return q.filter(participant_id=participant)
        return q


class AdminRiskReassessView(GenericAPIView):
    permission_classes = [HasManageCompliancePermission]
    serializer_class = ReassessmentRequestSerializer

    @extend_schema(operation_id="admin_market_risk_reassess", responses=RiskAssessmentSerializer)
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        participant = get_object_or_404(
            get_user_model(), pk=serializer.validated_data["participant_id"]
        )
        _, assessment, _ = MarketRiskService.assess(
            participant=participant, source="ADMIN", actor=request.user
        )
        return Response(RiskAssessmentSerializer(assessment).data)


class AdminComplianceDecisionListCreateView(ListAPIView):
    permission_classes = [HasManageCompliancePermission]
    serializer_class = ComplianceDecisionSerializer
    pagination_class = PublicCatalogPagination
    queryset = ComplianceDecisionProposal.objects.all()

    @extend_schema(
        operation_id="admin_compliance_decision_propose",
        request=DecisionProposalRequestSerializer,
        responses=ComplianceDecisionSerializer,
    )
    def post(self, request):
        serializer = DecisionProposalRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        participant = get_object_or_404(get_user_model(), pk=values.pop("participant_id"))
        proposal = ComplianceDecisionService.propose(
            participant=participant, actor=request.user, **values
        )
        return Response(ComplianceDecisionSerializer(proposal).data, status=201)


class AdminComplianceDecisionDetailView(RetrieveAPIView):
    permission_classes = [HasManageCompliancePermission]
    serializer_class = ComplianceDecisionSerializer
    queryset = ComplianceDecisionProposal.objects.all()
    lookup_url_kwarg = "proposal_id"


class AdminComplianceDecisionDecideView(GenericAPIView):
    permission_classes = [HasManageCompliancePermission]
    serializer_class = DecisionRequestSerializer

    @extend_schema(
        operation_id="admin_compliance_decision_decide",
        request=DecisionRequestSerializer,
        responses=ComplianceDecisionSerializer,
    )
    def post(self, request, proposal_id):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        get_object_or_404(ComplianceDecisionProposal, pk=proposal_id)
        proposal, _ = ComplianceDecisionService.decide(
            proposal_id=proposal_id, actor=request.user, **serializer.validated_data
        )
        return Response(ComplianceDecisionSerializer(proposal).data)
