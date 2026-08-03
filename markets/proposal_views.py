from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
    RetrieveUpdateAPIView,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from authentication.services.permission_service import PermissionService
from markets.models import MarketProposal, MarketProposalReview
from markets.permissions import HasAnyMarketPermission, HasMarketAdminAccess
from markets.proposal_serializers import (
    MarketProposalAdminQuerySerializer,
    MarketProposalAdminSerializer,
    MarketProposalErrorSerializer,
    MarketProposalParticipantSerializer,
    MarketProposalReviewActionSerializer,
    MarketProposalReviewSerializer,
)
from markets.services.proposal_service import MarketProposalDuplicateConflict, MarketProposalService
from system.pagination import PublicCatalogPagination


class MarketProposalListCreateView(ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MarketProposalParticipantSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        return (
            MarketProposal.objects.filter(proposer=self.request.user)
            .select_related("category", "sporting_event", "proposed_event_group")
            .order_by("-submitted_at", "-id")
        )


class MarketProposalDetailView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MarketProposalParticipantSerializer
    lookup_url_kwarg = "proposal_id"
    lookup_field = "id"
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return MarketProposal.objects.filter(proposer=self.request.user).select_related(
            "category", "sporting_event", "proposed_event_group"
        )


class MarketProposalWithdrawView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MarketProposalParticipantSerializer

    def post(self, request, proposal_id):
        try:
            proposal = MarketProposalService.withdraw(
                proposal_id=proposal_id, proposer=request.user
            )
        except DjangoValidationError as error:
            return Response(error.message_dict, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            MarketProposalParticipantSerializer(proposal, context={"request": request}).data
        )


class AdminProposalMixin:
    permission_classes = [IsAuthenticated, HasMarketAdminAccess]

    def base_queryset(self):
        return MarketProposal.objects.select_related(
            "category",
            "sporting_event",
            "proposed_event_group",
            "proposer",
            "reviewed_by",
            "approved_market",
        )


class AdminMarketProposalListView(AdminProposalMixin, ListAPIView):
    serializer_class = MarketProposalAdminSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        query = MarketProposalAdminQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        qs = self.base_queryset()
        for field in (
            "status",
            "duplicate_status",
            "category_id",
            "sporting_event_id",
            "proposer_id",
        ):
            if value := values.get(field):
                qs = qs.filter(**{field: value})
        if value := values.get("submitted_from"):
            qs = qs.filter(submitted_at__gte=value)
        if value := values.get("submitted_to"):
            qs = qs.filter(submitted_at__lte=value)
        if value := values.get("search"):
            qs = qs.filter(Q(question__icontains=value) | Q(description__icontains=value))
        return qs.order_by("-submitted_at", "-id")


class AdminMarketProposalDetailView(AdminProposalMixin, RetrieveAPIView):
    serializer_class = MarketProposalAdminSerializer
    lookup_url_kwarg = "proposal_id"
    lookup_field = "id"

    def get_queryset(self):
        return self.base_queryset()


class AdminMarketProposalReviewView(APIView):
    permission_classes = [IsAuthenticated, HasAnyMarketPermission]
    serializer_class = MarketProposalReviewActionSerializer

    @extend_schema(
        responses={
            200: MarketProposalAdminSerializer,
            400: MarketProposalErrorSerializer,
            403: MarketProposalErrorSerializer,
            404: MarketProposalErrorSerializer,
            409: MarketProposalErrorSerializer,
        }
    )
    def post(self, request, proposal_id):
        serializer = MarketProposalReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data["action"]
        required = (
            "approve_market"
            if action
            in (
                MarketProposalReview.Action.APPROVE,
                MarketProposalReview.Action.REJECT,
                MarketProposalReview.Action.MARK_DUPLICATE,
            )
            else "manage_market"
        )
        if not PermissionService.has_permission(request.user, required):
            return Response(
                {"detail": "You do not have permission."}, status=status.HTTP_403_FORBIDDEN
            )
        try:
            proposal = MarketProposalService.review(
                proposal_id=proposal_id, actor=request.user, **serializer.validated_data
            )
        except MarketProposalDuplicateConflict:
            return Response(
                {"code": "market_proposal_duplicate_conflict"}, status=status.HTTP_409_CONFLICT
            )
        except DjangoValidationError as error:
            return Response(error.message_dict, status=status.HTTP_400_BAD_REQUEST)
        return Response(MarketProposalAdminSerializer(proposal).data)


class AdminMarketProposalReviewListView(ListAPIView):
    permission_classes = [IsAuthenticated, HasMarketAdminAccess]
    serializer_class = MarketProposalReviewSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        return MarketProposalReview.objects.filter(proposal_id=self.kwargs["proposal_id"]).order_by(
            "-created_at", "-id"
        )
