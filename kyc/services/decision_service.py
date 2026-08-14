import logging
from django.db import transaction
from django.utils import timezone
from typing import TYPE_CHECKING

from kyc.models import KYCCheckResult, KYCConfiguration, KYCVerification
from kyc.services.market_compliance_sync import KYCMarketComplianceSyncService

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from kyc.models import KYCVerificationAttempt


class KYCDecisionService:
    """Orchestrates final KYC decision engine and atomic status transitions."""

    @staticmethod
    @transaction.atomic
    def make_decision(
        attempt: "KYCVerificationAttempt",
        final_status: str,
        reason_code: str | None = None,
    ) -> KYCVerification:
        verification = attempt.kyc_verification
        now = timezone.now()

        # Update attempt record
        attempt.status = (
            attempt.Status.COMPLETED
            if final_status in [KYCVerification.Status.VERIFIED, KYCVerification.Status.REVIEW]
            else attempt.Status.FAILED
        )
        attempt.completed_at = now
        attempt.failure_reason = (
            reason_code
            if final_status
            in [KYCVerification.Status.REJECTED, KYCVerification.Status.RETRY_REQUIRED]
            else ""
        )
        attempt.retry_reason = (
            reason_code if final_status == KYCVerification.Status.RETRY_REQUIRED else ""
        )
        attempt.save(update_fields=["status", "completed_at", "failure_reason", "retry_reason"])

        # Update verification record
        verification.status = final_status
        verification.verification_completed_at = now

        if final_status == KYCVerification.Status.VERIFIED:
            verification.verified_at = now
            verification.rejection_reason = ""
            verification.retry_reason = ""
            # Set user account verified flag if applicable
            user = verification.user
            if not user.is_verified:
                user.is_verified = True
                user.save(update_fields=["is_verified", "updated_at"])
        elif final_status == KYCVerification.Status.RETRY_REQUIRED:
            verification.retry_reason = reason_code
        elif final_status == KYCVerification.Status.REJECTED:
            verification.rejection_reason = reason_code

        verification.save()
        KYCMarketComplianceSyncService.sync(
            verification=verification,
            reason=f"Automated KYC decision: {final_status} ({reason_code or 'no reason code'}).",
        )

        logger.info(
            "KYC verification %s for user %s transition to %s (reason: %s).",
            verification.id,
            verification.user_id,
            final_status,
            reason_code,
        )

        return verification

    @classmethod
    def run_decision_engine(cls, attempt: "KYCVerificationAttempt") -> KYCVerification:
        """Evaluates check results, attempt limits, and risk levels to issue automated decision."""
        verification = attempt.kyc_verification
        config = KYCConfiguration.load()

        checks_by_type = {c.check_type: c for c in attempt.checks.all()}

        # 1. Hard Rejections
        dup_check = checks_by_type.get(KYCCheckResult.CheckType.DUPLICATE_IDENTITY)
        if dup_check and dup_check.status == KYCCheckResult.Status.FAILED:
            return cls.make_decision(
                attempt, KYCVerification.Status.REJECTED, "duplicate_identity_detected"
            )

        tamper_check = checks_by_type.get(KYCCheckResult.CheckType.DOCUMENT_MANIPULATION)
        if tamper_check and tamper_check.status == KYCCheckResult.Status.FAILED:
            return cls.make_decision(
                attempt, KYCVerification.Status.REJECTED, "document_tampering_detected"
            )

        exp_check = checks_by_type.get(KYCCheckResult.CheckType.DOCUMENT_EXPIRY)
        if exp_check and exp_check.status == KYCCheckResult.Status.FAILED:
            return cls.make_decision(attempt, KYCVerification.Status.REJECTED, "expired_document")

        liveness_check = checks_by_type.get(KYCCheckResult.CheckType.LIVENESS)
        if liveness_check and liveness_check.status == KYCCheckResult.Status.FAILED:
            return cls.make_decision(attempt, KYCVerification.Status.REJECTED, "liveness_failed")

        face_match = checks_by_type.get(KYCCheckResult.CheckType.FACE_MATCH)
        if face_match and face_match.status == KYCCheckResult.Status.FAILED:
            return cls.make_decision(attempt, KYCVerification.Status.REJECTED, "face_mismatch")

        if verification.risk_level == KYCVerification.RiskLevel.CRITICAL:
            return cls.make_decision(
                attempt, KYCVerification.Status.REJECTED, "critical_risk_level"
            )

        # 2. Temporary Retry Required (Image Quality / Face Detection / Unclear Capture)
        quality_check = checks_by_type.get(KYCCheckResult.CheckType.IMAGE_QUALITY)
        if quality_check and quality_check.status == KYCCheckResult.Status.FAILED:
            if attempt.attempt_number >= config.max_attempts:
                return cls.make_decision(
                    attempt, KYCVerification.Status.REJECTED, "max_attempts_exceeded_quality"
                )
            return cls.make_decision(
                attempt, KYCVerification.Status.RETRY_REQUIRED, "poor_image_quality"
            )

        face_det = checks_by_type.get(KYCCheckResult.CheckType.FACE_DETECTION)
        if face_det and face_det.status == KYCCheckResult.Status.FAILED:
            if attempt.attempt_number >= config.max_attempts:
                return cls.make_decision(
                    attempt, KYCVerification.Status.REJECTED, "max_attempts_exceeded_face"
                )
            return cls.make_decision(
                attempt, KYCVerification.Status.RETRY_REQUIRED, "selfie_face_not_detected"
            )

        # 3. Review Exception State (Borderline results / High Risk / Uncertain checks)
        if verification.risk_level == KYCVerification.RiskLevel.HIGH:
            return cls.make_decision(attempt, KYCVerification.Status.REVIEW, "high_risk_flagged")

        if face_match and face_match.status == KYCCheckResult.Status.UNCERTAIN:
            return cls.make_decision(
                attempt, KYCVerification.Status.REVIEW, "borderline_face_match"
            )

        # 4. Successful Automated Verification
        required_passed = (
            quality_check
            and quality_check.status == KYCCheckResult.Status.PASSED
            and face_det
            and face_det.status == KYCCheckResult.Status.PASSED
            and face_match
            and face_match.status == KYCCheckResult.Status.PASSED
        )

        if required_passed and verification.risk_level in [
            KYCVerification.RiskLevel.LOW,
            KYCVerification.RiskLevel.MEDIUM,
        ]:
            return cls.make_decision(
                attempt, KYCVerification.Status.VERIFIED, "automated_checks_passed"
            )

        # Fallback to REVIEW if incomplete
        return cls.make_decision(
            attempt, KYCVerification.Status.REVIEW, "inconclusive_automated_evidence"
        )
