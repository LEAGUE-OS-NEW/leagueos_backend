import hashlib

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import GenericAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from markets.kyc_serializers import (
    KYCCallbackResponseSerializer,
    KYCSessionSerializer,
    KYCStartSerializer,
)
from markets.models import KYCVerificationSession
from markets.services.eligibility_service import MarketEligibilityService
from markets.services.kyc_service import InvalidCallback, KYCError, KYCService
from system.pagination import PublicCatalogPagination


class KYCSessionListStartView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = KYCSessionSerializer

    @extend_schema(
        request=KYCStartSerializer,
        responses={201: KYCSessionSerializer, 200: KYCSessionSerializer},
        operation_id="market_kyc_start",
    )
    def post(self, request):
        serializer = KYCStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session, created = KYCService.start(
            participant=request.user, initiated_by=request.user, **serializer.validated_data
        )
        return Response(
            KYCSessionSerializer(session).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(responses=KYCSessionSerializer(many=True), operation_id="market_kyc_list")
    def get(self, request):
        queryset = KYCVerificationSession.objects.filter(participant=request.user)
        page = PublicCatalogPagination().paginate_queryset(queryset, request)
        return Response(KYCSessionSerializer(page, many=True).data)


class KYCSessionDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = KYCSessionSerializer
    lookup_url_kwarg = "session_id"

    def get_queryset(self):
        return KYCVerificationSession.objects.filter(participant=self.request.user)


class KYCSessionCancelView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = KYCSessionSerializer

    @extend_schema(request=None, responses=KYCSessionSerializer, operation_id="market_kyc_cancel")
    def post(self, request, session_id):
        session = get_object_or_404(KYCVerificationSession, id=session_id, participant=request.user)
        return Response(
            KYCSessionSerializer(KYCService.cancel(session=session, actor=request.user)).data
        )


class KYCComplianceSummaryView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=dict, operation_id="market_kyc_compliance_summary")
    def get(self, request):
        return Response(MarketEligibilityService.evaluate(participant=request.user).as_dict())


class KYCCallbackView(GenericAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = KYCCallbackResponseSerializer

    @extend_schema(
        request=None,
        responses=KYCCallbackResponseSerializer,
        operation_id="market_kyc_provider_callback",
        auth=[],
    )
    def post(self, request, provider):
        try:
            session, event, created = KYCService.handle_callback(
                provider=provider,
                body=request.body,
                timestamp=request.headers.get("X-KYC-Timestamp"),
                signature=request.headers.get("X-KYC-Signature"),
            )
        except KYCVerificationSession.DoesNotExist:
            return Response({"detail": "Unknown verification session."}, status=404)
        except (InvalidCallback, KYCError) as exc:
            reason = (
                "UNSUPPORTED_PROVIDER"
                if "provider" in str(exc).lower()
                else "INVALID_SIGNATURE"
                if "signature" in str(exc).lower()
                else "INVALID_CALLBACK"
            )
            from notifications.services.operational_alert_service import OperationalAlertService

            digest = hashlib.sha256(request.body).hexdigest()
            OperationalAlertService.create(
                permissions=("manage_compliance",),
                event_type="KYC_CALLBACK_REJECTED",
                title="KYC callback rejected",
                message=f"A {provider} callback was rejected ({reason}).",
                source_key=f"kyc-callback:{provider}:{reason}:{digest}",
                data={
                    "provider_code": provider[:64],
                    "reason_code": reason,
                    "event_digest": digest,
                    "occurred_at": timezone.now().isoformat(),
                },
            )
            return Response({"detail": str(exc)}, status=400)
        return Response({"accepted": True, "duplicate": not created, "status": session.status})
