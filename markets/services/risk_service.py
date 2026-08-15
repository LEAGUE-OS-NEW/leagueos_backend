import hashlib
import json

from django.db import transaction
from django.utils import timezone

from kyc.models import KYCVerification
from markets.models import (
    MarketParticipantCompliance,
    MarketResponsibleParticipation,
    MarketRiskAssessment,
    MarketRiskProfile,
)


class MarketRiskService:
    """Deterministic rules: rejection +35, expiry +20, restriction +45,
    suspension/jurisdiction block/responsible block +70. Bands: 0-19 LOW,
    20-39 MEDIUM, 40-69 HIGH, 70-100 CRITICAL.
    """

    @classmethod
    @transaction.atomic
    def assess(cls, *, participant, source="SYSTEM", actor=None):
        compliance, _ = MarketParticipantCompliance.objects.get_or_create(participant=participant)
        try:
            responsible = participant.market_responsible_participation
        except MarketResponsibleParticipation.DoesNotExist:
            responsible = None
        score, reasons = 0, []
        kyc_verification = getattr(participant, "kyc_verification", None)
        kyc_status = (
            kyc_verification.status if kyc_verification else KYCVerification.Status.NOT_STARTED
        )
        if kyc_status == KYCVerification.Status.REJECTED:
            score += 35
            reasons.append("KYC_REJECTED")
        elif kyc_status == KYCVerification.Status.EXPIRED:
            score += 20
            reasons.append("KYC_EXPIRED")
        if compliance.restriction_status == "RESTRICTED":
            score += 45
            reasons.append("COMPLIANCE_RESTRICTED")
        elif compliance.restriction_status == "SUSPENDED":
            score += 70
            reasons.append("COMPLIANCE_SUSPENDED")
        if compliance.jurisdiction_override == "BLOCK":
            score += 70
            reasons.append("JURISDICTION_BLOCK")
        now = timezone.now()
        if responsible and (
            responsible.self_excluded_indefinitely
            or (responsible.self_exclusion_until and responsible.self_exclusion_until > now)
            or (
                responsible.administrative_block_until
                and responsible.administrative_block_until > now
            )
        ):
            score += 70
            reasons.append("RESPONSIBLE_PARTICIPATION_BLOCK")
        score = min(score, 100)
        band = (
            "LOW"
            if score < 20
            else "MEDIUM" if score < 40 else "HIGH" if score < 70 else "CRITICAL"
        )
        action = (
            "BLOCK"
            if band == "CRITICAL"
            else "REVIEW" if band == "HIGH" else "MONITOR" if band == "MEDIUM" else "NONE"
        )
        summary = {
            "kyc_status": kyc_status,
            "restriction_status": compliance.restriction_status,
            "jurisdiction_override": compliance.jurisdiction_override,
            "responsible_block": "RESPONSIBLE_PARTICIPATION_BLOCK" in reasons,
        }
        digest = hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest()
        assessment, created = MarketRiskAssessment.objects.get_or_create(
            participant=participant,
            input_digest=digest,
            defaults={
                "score": score,
                "band": band,
                "reason_codes": reasons,
                "input_summary": summary,
                "recommended_action": action,
                "assessment_source": source,
                "actor": actor,
            },
        )
        profile, _ = MarketRiskProfile.objects.select_for_update().get_or_create(
            participant=participant
        )
        if created or profile.last_assessed_at is None:
            profile.current_score, profile.risk_band = score, band
            profile.restriction_recommendation, profile.reason_codes = action, reasons
            profile.last_assessed_at, profile.assessment_source = timezone.now(), source
            profile.revision += 1
            profile.save()
        if created and band in {"HIGH", "CRITICAL"}:
            from markets.services.market_notification_service import MarketNotificationService
            from notifications.services.operational_alert_service import OperationalAlertService

            MarketNotificationService.schedule(
                recipient=participant,
                category="MARKET_COMPLIANCE",
                event_type=f"{band}_RISK_BLOCK",
                title="Market access risk review",
                message="Your market access is restricted pending a compliance review.",
                key=f"market-risk-assessment:{assessment.id}:participant",
                data={"assessment_id": str(assessment.id), "risk_band": band},
                mandatory=True,
                severity="CRITICAL" if band == "CRITICAL" else "WARNING",
            )
            OperationalAlertService.create(
                permissions=("manage_compliance",),
                event_type=f"PARTICIPANT_RISK_{band}",
                title=f"{band} participant risk",
                message=f"A participant received a {band} market risk assessment.",
                source_key=f"risk-assessment:{assessment.id}:{band.lower()}",
                data={
                    "assessment_id": str(assessment.id),
                    "participant_id": str(participant.id),
                    "risk_band": band,
                },
                severity="CRITICAL" if band == "CRITICAL" else "WARNING",
            )
        return profile, assessment, created
