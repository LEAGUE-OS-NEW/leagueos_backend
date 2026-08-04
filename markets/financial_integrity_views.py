import csv

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from markets.financial_integrity_serializers import (
    AdjustmentDecisionSerializer,
    AdjustmentProposalSerializer,
    AdjustmentSerializer,
    FeePreviewSerializer,
    FeeScheduleSerializer,
    ReconciliationMismatchSerializer,
    ReconciliationRunSerializer,
    ReconciliationStartSerializer,
)
from markets.models import (
    Market,
    MarketFeeSchedule,
    MarketFinancialAdjustment,
    MarketFinancialAdjustmentApproval,
    MarketReconciliationMismatch,
    MarketReconciliationRun,
)
from markets.permissions import HasApproveMarketPermission, HasManageMarketPermission
from markets.services.fee_service import MarketFeeService
from markets.services.financial_adjustment_service import MarketFinancialAdjustmentService
from markets.services.reconciliation_service import MarketReconciliationService
from system.pagination import PublicCatalogPagination
from wallets.models import Wallet


class FeePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, market_id):
        market = get_object_or_404(Market, id=market_id)
        serializer = FeePreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = MarketFeeService.preview(
            market=market,
            quantity=serializer.validated_data["quantity"],
            limit_price=serializer.validated_data["limit_price"],
        )
        return Response(data)


class FeeScheduleListCreateView(APIView):
    permission_classes = [IsAuthenticated, HasManageMarketPermission]

    def get(self, request):
        queryset = MarketFeeSchedule.objects.select_related("market").all()
        return Response(FeeScheduleSerializer(queryset, many=True).data)

    def post(self, request):
        serializer = FeeScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        market = data.pop("market", None)
        schedule = MarketFeeService.create_draft(actor=request.user, market=market, **data)
        return Response(FeeScheduleSerializer(schedule).data, status=status.HTTP_201_CREATED)


class FeeScheduleDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated, HasManageMarketPermission]
    serializer_class = FeeScheduleSerializer
    queryset = MarketFeeSchedule.objects.all()
    lookup_url_kwarg = "schedule_id"


class FeeScheduleDecisionView(APIView):
    permission_classes = [IsAuthenticated, HasApproveMarketPermission]
    action = None

    def post(self, request, schedule_id):
        schedule = getattr(MarketFeeService, self.action)(
            schedule_id=schedule_id, actor=request.user
        )
        return Response(FeeScheduleSerializer(schedule).data)


class FeeScheduleActivateView(FeeScheduleDecisionView):
    action = "activate"


class FeeScheduleRetireView(FeeScheduleDecisionView):
    action = "retire"


class ReconciliationRunListView(ListAPIView):
    permission_classes = [IsAuthenticated, HasManageMarketPermission]
    serializer_class = ReconciliationRunSerializer
    pagination_class = PublicCatalogPagination
    queryset = MarketReconciliationRun.objects.all()


class ReconciliationRunDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated, HasManageMarketPermission]
    serializer_class = ReconciliationRunSerializer
    queryset = MarketReconciliationRun.objects.all()
    lookup_url_kwarg = "run_id"


class ReconciliationStartView(APIView):
    permission_classes = [IsAuthenticated, HasManageMarketPermission]

    def post(self, request):
        serializer = ReconciliationStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        market = get_object_or_404(Market, id=data["market_id"]) if data.get("market_id") else None
        wallet = get_object_or_404(Wallet, id=data["wallet_id"]) if data.get("wallet_id") else None
        run = MarketReconciliationService.run(
            run_date=data.get("run_date"),
            market=market,
            wallet=wallet,
            actor=request.user,
        )
        return Response(ReconciliationRunSerializer(run).data, status=status.HTTP_201_CREATED)


class ReconciliationMismatchListView(ListAPIView):
    permission_classes = [IsAuthenticated, HasManageMarketPermission]
    serializer_class = ReconciliationMismatchSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        queryset = MarketReconciliationMismatch.objects.all()
        for field in ("run_id", "code", "severity", "resolution_status"):
            value = self.request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{field: value})
        return queryset.order_by("-detected_at", "-id")


class ReconciliationMismatchDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated, HasManageMarketPermission]
    serializer_class = ReconciliationMismatchSerializer
    queryset = MarketReconciliationMismatch.objects.all()
    lookup_url_kwarg = "mismatch_id"


class ReconciliationExportView(APIView):
    permission_classes = [IsAuthenticated, HasManageMarketPermission]

    def get(self, request, run_id):
        run = get_object_or_404(MarketReconciliationRun, id=run_id)
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="reconciliation-{run.id}.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "code",
                "severity",
                "market_id",
                "order_id",
                "fill_id",
                "expected",
                "actual",
                "unit",
                "detected_at",
            ]
        )
        for row in run.mismatches.order_by("detected_at", "id"):
            writer.writerow(
                [
                    row.code,
                    row.severity,
                    row.market_id_snapshot,
                    row.order_id_snapshot,
                    row.fill_id_snapshot,
                    row.expected_value,
                    row.actual_value,
                    row.unit,
                    row.detected_at.isoformat(),
                ]
            )
        return response


class AdjustmentListView(ListAPIView):
    permission_classes = [IsAuthenticated, HasManageMarketPermission]
    serializer_class = AdjustmentSerializer
    pagination_class = PublicCatalogPagination
    queryset = MarketFinancialAdjustment.objects.prefetch_related("lines").all()


class AdjustmentDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated, HasManageMarketPermission]
    serializer_class = AdjustmentSerializer
    queryset = MarketFinancialAdjustment.objects.prefetch_related("lines").all()
    lookup_url_kwarg = "adjustment_id"


class AdjustmentProposeView(APIView):
    permission_classes = [IsAuthenticated, HasManageMarketPermission]

    def post(self, request):
        serializer = AdjustmentProposalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        market = get_object_or_404(Market, id=data.pop("market")) if data.get("market") else None
        mismatch = (
            get_object_or_404(MarketReconciliationMismatch, id=data.pop("mismatch"))
            if data.get("mismatch")
            else None
        )
        adjustment = MarketFinancialAdjustmentService.propose(
            actor=request.user, market=market, mismatch=mismatch, **data
        )
        return Response(AdjustmentSerializer(adjustment).data, status=status.HTTP_201_CREATED)


class AdjustmentDecisionView(APIView):
    permission_classes = [IsAuthenticated, HasApproveMarketPermission]
    decision = None

    def post(self, request, adjustment_id):
        serializer = AdjustmentDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        adjustment = MarketFinancialAdjustmentService.decide(
            adjustment_id=adjustment_id,
            actor=request.user,
            decision=self.decision,
            notes=serializer.validated_data.get("notes", ""),
        )
        return Response(AdjustmentSerializer(adjustment).data)


class AdjustmentApproveView(AdjustmentDecisionView):
    decision = MarketFinancialAdjustmentApproval.Decision.APPROVED


class AdjustmentRejectView(AdjustmentDecisionView):
    decision = MarketFinancialAdjustmentApproval.Decision.REJECTED
