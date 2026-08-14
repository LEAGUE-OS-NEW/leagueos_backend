import logging
from django.conf import settings
from django.core.signing import TimestampSigner
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import permissions, serializers, status, throttling
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import AuditLog
from accounts.serializers import build_response
from kyc.models import KYCVerification, KYCVerificationAttempt, KYCConfiguration
from kyc.serializers import (
    AdminKYCReviewActionSerializer,
    AdminKYCVerificationDetailSerializer,
    KYCStatusResponseSerializer,
    KYCSubmissionSerializer,
)
from kyc.tasks import process_kyc_attempt
from markets.services.compliance_service import MarketComplianceService
from markets.services.kyc_service import KYCService

logger = logging.getLogger(__name__)
signer = TimestampSigner()


def log_kyc_audit(user, action, resource_id=None, metadata=None, request=None):
    ip_address = None
    user_agent = ""
    if request:
        x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        ip_address = x_forwarded.split(",")[0] if x_forwarded else request.META.get("REMOTE_ADDR")
        user_agent = request.META.get("HTTP_USER_AGENT", "")

    AuditLog.objects.create(
        user=user,
        action=action,
        resource_type="KYCVerification",
        resource_id=resource_id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata=metadata or {},
    )


class KYCSubmissionRateThrottle(throttling.UserRateThrottle):
    rate = "5/hour"
    scope = "kyc_submission"


class FanKYCSubmitView(APIView):
    """Submits a new KYC verification attempt (document + live selfie)."""

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [KYCSubmissionRateThrottle]
    serializer_class = KYCSubmissionSerializer

    @extend_schema(
        request=KYCSubmissionSerializer,
        responses={202: dict, 400: dict, 429: dict},
    )
    def post(self, request):
        if not getattr(settings, "KYC_ENABLED", True):
            return Response(
                build_response(False, "KYC verification service is currently disabled."),
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = KYCSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        config = KYCConfiguration.load()

        with transaction.atomic():
            verification, _ = KYCVerification.objects.select_for_update().get_or_create(
                user=user,
                defaults={"status": KYCVerification.Status.PENDING},
            )

            # Enforce max attempt limit
            current_attempts = verification.attempts.count()
            if current_attempts >= config.max_attempts:
                return Response(
                    build_response(
                        False,
                        f"Maximum allowed KYC verification attempts "
                        f"({config.max_attempts}) reached.",
                    ),
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if verification.status == KYCVerification.Status.VERIFIED:
                return Response(
                    build_response(False, "Your identity is already verified."),
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if verification.status == KYCVerification.Status.PROCESSING:
                return Response(
                    build_response(False, "Your KYC verification is currently being processed."),
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Create attempt record
            attempt_number = current_attempts + 1
            attempt = KYCVerificationAttempt.objects.create(
                kyc_verification=verification,
                attempt_number=attempt_number,
                status=KYCVerificationAttempt.Status.PENDING,
                document_type=serializer.validated_data["document_type"],
                document_country=serializer.validated_data["document_country"],
                document_image=serializer.validated_data["document_image"],
                selfie_image=serializer.validated_data["selfie_image"],
            )

            verification.status = KYCVerification.Status.PENDING
            verification.document_type = serializer.validated_data["document_type"]
            verification.document_country = serializer.validated_data["document_country"]
            verification.save()

        log_kyc_audit(
            user=user,
            action="KYC_SUBMITTED",
            resource_id=verification.id,
            metadata={"attempt_number": attempt_number},
            request=request,
        )

        # Trigger processing task (asynchronously or inline fallback)
        try:
            process_kyc_attempt.delay(str(attempt.id))
        except Exception as exc:
            logger.warning(
                "Celery queue unavailable, executing process_kyc_attempt inline: %s", exc
            )
            process_kyc_attempt(str(attempt.id))

        return Response(
            build_response(
                True,
                "KYC verification submitted successfully and processing started.",
                data={
                    "status": KYCVerification.Status.PROCESSING,
                    "kyc_id": str(verification.id),
                    "attempt_id": str(attempt.id),
                },
            ),
            status=status.HTTP_202_ACCEPTED,
        )


class FanKYCStatusView(APIView):
    """Fetches the current authenticated fan's KYC status and submission metadata."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: KYCStatusResponseSerializer})
    def get(self, request):
        verification, _ = KYCVerification.objects.get_or_create(
            user=request.user,
            defaults={"status": KYCVerification.Status.NOT_STARTED},
        )

        serializer = KYCStatusResponseSerializer(verification)
        return Response(
            build_response(
                True,
                "KYC status fetched successfully.",
                data=serializer.data,
            ),
            status=status.HTTP_200_OK,
        )


class FanKYCRetryView(APIView):
    """Allows an authenticated fan to request a retry if previous attempt
    received RETRY_REQUIRED."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = serializers.Serializer

    @extend_schema(
        request=None,
        responses={200: dict, 400: dict},
        tags=["KYC"],
    )
    def post(self, request):
        user = request.user
        config = KYCConfiguration.load()

        verification = KYCVerification.objects.filter(user=user).first()
        if not verification or verification.status != KYCVerification.Status.RETRY_REQUIRED:
            return Response(
                build_response(False, "No KYC submission currently requires retry."),
                status=status.HTTP_400_BAD_REQUEST,
            )

        if verification.attempts.count() >= config.max_attempts:
            return Response(
                build_response(False, "Maximum verification attempts reached."),
                status=status.HTTP_400_BAD_REQUEST,
            )

        log_kyc_audit(
            user=user,
            action="KYC_RETRY_REQUESTED",
            resource_id=verification.id,
            request=request,
        )

        return Response(
            build_response(
                True,
                "KYC retry eligible. Please upload a clear document image and live selfie.",
                data={
                    "can_retry": True,
                    "attempts_remaining": config.max_attempts - verification.attempts.count(),
                },
            ),
            status=status.HTTP_200_OK,
        )


class AdminKYCListView(APIView):
    """Admin endpoint to list and filter KYC verifications."""

    permission_classes = [permissions.IsAdminUser]

    @extend_schema(
        parameters=[
            OpenApiParameter("status", type=str, description="Filter by verification status"),
            OpenApiParameter("document_type", type=str, description="Filter by document type"),
            OpenApiParameter("risk_level", type=str, description="Filter by risk level"),
            OpenApiParameter("country", type=str, description="Filter by country"),
        ],
        responses={200: AdminKYCVerificationDetailSerializer(many=True)},
    )
    def get(self, request):
        qs = (
            KYCVerification.objects.select_related("user")
            .prefetch_related("checks", "attempts")
            .all()
        )

        status_param = request.query_params.get("status")
        doc_type_param = request.query_params.get("document_type")
        risk_param = request.query_params.get("risk_level")
        country_param = request.query_params.get("country")

        if status_param:
            qs = qs.filter(status=status_param.upper())
        if doc_type_param:
            qs = qs.filter(document_type=doc_type_param.upper())
        if risk_param:
            qs = qs.filter(risk_level=risk_param.upper())
        if country_param:
            qs = qs.filter(document_country=country_param.upper())

        serializer = AdminKYCVerificationDetailSerializer(qs[:100], many=True)
        return Response(
            build_response(
                True, "KYC verifications fetched.", data={"verifications": serializer.data}
            ),
            status=status.HTTP_200_OK,
        )


class AdminKYCDetailView(APIView):
    """Admin endpoint to view detailed check results for a single KYC verification."""

    permission_classes = [permissions.IsAdminUser]

    @extend_schema(responses={200: AdminKYCVerificationDetailSerializer})
    def get(self, request, verification_id):
        verification = (
            KYCVerification.objects.filter(id=verification_id)
            .select_related("user")
            .prefetch_related("checks", "attempts")
            .first()
        )
        if not verification:
            return Response(
                build_response(False, "KYC verification record not found."),
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = AdminKYCVerificationDetailSerializer(verification)
        return Response(
            build_response(True, "KYC verification details fetched.", data=serializer.data),
            status=status.HTTP_200_OK,
        )


class AdminKYCDocumentUrlView(APIView):
    """Generates a temporary signed access URL for viewing private document or selfie images."""

    permission_classes = [permissions.IsAdminUser]
    serializer_class = serializers.Serializer

    @extend_schema(
        parameters=[
            OpenApiParameter("verification_id", type={"type": "string", "format": "uuid"}),
            OpenApiParameter("target", type=str, description="document or selfie"),
        ],
        responses={200: dict, 404: dict},
        tags=["KYC"],
    )
    def get(self, request, verification_id):
        verification = KYCVerification.objects.filter(id=verification_id).first()
        if not verification:
            return Response(
                build_response(False, "KYC verification record not found."),
                status=status.HTTP_404_NOT_FOUND,
            )

        target = request.query_params.get("target", "document")  # document or selfie
        latest_attempt = verification.attempts.order_by("-attempt_number").first()

        if not latest_attempt:
            return Response(
                build_response(False, "No uploaded documents found for this verification."),
                status=status.HTTP_404_NOT_FOUND,
            )

        file_obj = (
            latest_attempt.selfie_image if target == "selfie" else latest_attempt.document_image
        )
        if not file_obj or not file_obj.name:
            return Response(
                build_response(False, "Requested file not found."), status=status.HTTP_404_NOT_FOUND
            )

        # Generate signed token valid for 5 minutes
        signed_token = signer.sign(f"{verification.id}:{target}:{latest_attempt.id}")

        log_kyc_audit(
            user=request.user,
            action="KYC_DOCUMENT_ACCESSED",
            resource_id=verification.id,
            metadata={"target": target, "attempt_id": str(latest_attempt.id)},
            request=request,
        )

        return Response(
            build_response(
                True,
                "Temporary document access URL generated.",
                data={
                    "token": signed_token,
                    "target": target,
                    "expires_in_seconds": 300,
                },
            ),
            status=status.HTTP_200_OK,
        )


class AdminKYCReviewActionView(APIView):
    """Admin endpoint to perform manual review decision override on REVIEW state verifications."""

    permission_classes = [permissions.IsAdminUser]
    serializer_class = AdminKYCReviewActionSerializer

    @extend_schema(request=AdminKYCReviewActionSerializer, responses={200: dict})
    def post(self, request, verification_id):
        verification = KYCVerification.objects.filter(id=verification_id).first()
        if not verification:
            return Response(
                build_response(False, "KYC verification record not found."),
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = AdminKYCReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        decision = serializer.validated_data["decision"]
        notes = serializer.validated_data.get("notes", "")

        with transaction.atomic():
            # 1. Update the canonical KYC record (kyc app).
            verification.status = decision
            if decision == KYCVerification.Status.VERIFIED:
                verification.verified_at = timezone.now()
                user = verification.user
                user.is_verified = True
                user.save(update_fields=["is_verified", "updated_at"])
            elif decision == KYCVerification.Status.REJECTED:
                verification.rejection_reason = (
                    f"Manual admin rejection: {notes}" if notes else "Manual admin rejection"
                )
            verification.save()

            # 2. Map the decision to the markets compliance kyc_status and
            #    persist it on MarketParticipantCompliance so that
            #    MarketEligibilityService.evaluate() sees the updated state.
            #    REVIEW stays as PENDING in the compliance system — the
            #    participant is not yet verified but not blocked either.
            _COMPLIANCE_STATUS_MAP = {
                KYCVerification.Status.VERIFIED: "VERIFIED",
                KYCVerification.Status.REJECTED: "REJECTED",
                KYCVerification.Status.REVIEW: "PENDING",
            }
            compliance_kyc_status = _COMPLIANCE_STATUS_MAP.get(decision)
            if compliance_kyc_status:
                MarketComplianceService.update(
                    participant=verification.user,
                    actor=request.user,
                    source="ADMIN",
                    changes={"kyc_status": compliance_kyc_status},
                    reason=notes or f"Admin KYC review decision: {decision}",
                )

            # 3. Transition any open KYCVerificationSession (markets app) to
            #    the same terminal state so the admin queue and session list
            #    reflect the manual decision.
            if decision in (
                KYCVerification.Status.VERIFIED,
                KYCVerification.Status.REJECTED,
            ):
                KYCService.admin_decide(
                    participant=verification.user,
                    decision=decision,
                    actor=request.user,
                    notes=notes,
                )

        log_kyc_audit(
            user=request.user,
            action=(
                "KYC_REVIEW_REQUIRED"
                if decision == "REVIEW"
                else ("KYC_VERIFIED" if decision == "VERIFIED" else "KYC_REJECTED")
            ),
            resource_id=verification.id,
            metadata={"admin_decision": decision, "notes": notes},
            request=request,
        )

        return Response(
            build_response(True, f"Verification marked as {decision}.", data={"status": decision}),
            status=status.HTTP_200_OK,
        )
