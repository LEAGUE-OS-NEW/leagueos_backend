import logging
from typing import TYPE_CHECKING, Any

from kyc.models import KYCCheckResult, KYCConfiguration, KYCVerification

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from kyc.models import KYCVerificationAttempt


class KYCRiskEngine:
    """Evaluates granular check results and computes verification risk score."""

    RISK_WEIGHTS = {
        KYCCheckResult.CheckType.DUPLICATE_IDENTITY: 0.50,
        KYCCheckResult.CheckType.DOCUMENT_MANIPULATION: 0.40,
        KYCCheckResult.CheckType.FACE_MATCH: 0.40,
        KYCCheckResult.CheckType.LIVENESS: 0.35,
        KYCCheckResult.CheckType.DOCUMENT_EXPIRY: 0.35,
        KYCCheckResult.CheckType.IMAGE_QUALITY: 0.25,
        KYCCheckResult.CheckType.FACE_DETECTION: 0.25,
        KYCCheckResult.CheckType.OCR: 0.15,
        KYCCheckResult.CheckType.MRZ: 0.15,
        KYCCheckResult.CheckType.DATA_CONSISTENCY: 0.15,
    }

    @classmethod
    def evaluate_risk(cls, attempt: "KYCVerificationAttempt") -> dict[str, Any]:
        verification = attempt.kyc_verification
        config = KYCConfiguration.load()

        checks = list(attempt.checks.all())
        total_risk_score = 0.0

        risk_signals = []

        for check in checks:
            weight = cls.RISK_WEIGHTS.get(check.check_type, 0.10)
            if check.status == KYCCheckResult.Status.FAILED:
                total_risk_score += weight
                risk_signals.append(f"FAILED:{check.check_type}")
            elif check.status == KYCCheckResult.Status.UNCERTAIN:
                total_risk_score += weight * 0.5
                risk_signals.append(f"UNCERTAIN:{check.check_type}")

        final_score = float(min(1.0, max(0.0, total_risk_score)))

        if final_score >= config.risk_reject_threshold:
            risk_level = KYCVerification.RiskLevel.CRITICAL
        elif final_score >= config.risk_review_threshold:
            risk_level = KYCVerification.RiskLevel.HIGH
        elif final_score >= 0.20:
            risk_level = KYCVerification.RiskLevel.MEDIUM
        else:
            risk_level = KYCVerification.RiskLevel.LOW

        verification.risk_score = round(final_score, 4)
        verification.risk_level = risk_level
        verification.save(update_fields=["risk_score", "risk_level", "updated_at"])

        risk_check, _ = KYCCheckResult.objects.update_or_create(
            kyc_verification=verification,
            kyc_attempt=attempt,
            check_type=KYCCheckResult.CheckType.RISK_ASSESSMENT,
            defaults={"status": KYCCheckResult.Status.PASSED},
        )
        risk_check.score = final_score
        risk_check.status = (
            KYCCheckResult.Status.FAILED
            if risk_level == KYCVerification.RiskLevel.CRITICAL
            else KYCCheckResult.Status.PASSED
        )
        risk_check.result_code = f"risk_{risk_level.lower()}"
        risk_check.details = {
            "score": final_score,
            "level": risk_level,
            "signals": risk_signals,
        }
        risk_check.save()

        return {
            "score": final_score,
            "level": risk_level,
            "signals": risk_signals,
        }
