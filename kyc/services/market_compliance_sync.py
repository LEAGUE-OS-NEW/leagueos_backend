from django.db import transaction

from kyc.models import KYCVerification
from markets.models import MarketComplianceReview, MarketParticipantCompliance


class KYCMarketComplianceSyncService:
    """Project canonical KYC state into the Markets eligibility record."""

    STATUS_MAP = {
        KYCVerification.Status.NOT_STARTED: MarketParticipantCompliance.KYCStatus.NOT_STARTED,
        KYCVerification.Status.PENDING: MarketParticipantCompliance.KYCStatus.PENDING,
        KYCVerification.Status.PROCESSING: MarketParticipantCompliance.KYCStatus.PENDING,
        KYCVerification.Status.REVIEW: MarketParticipantCompliance.KYCStatus.PENDING,
        KYCVerification.Status.RETRY_REQUIRED: MarketParticipantCompliance.KYCStatus.PENDING,
        KYCVerification.Status.VERIFIED: MarketParticipantCompliance.KYCStatus.VERIFIED,
        KYCVerification.Status.REJECTED: MarketParticipantCompliance.KYCStatus.REJECTED,
        KYCVerification.Status.EXPIRED: MarketParticipantCompliance.KYCStatus.EXPIRED,
    }

    @classmethod
    @transaction.atomic
    def sync(cls, *, verification, actor=None, reason=""):
        target_status = cls.STATUS_MAP[verification.status]
        compliance, _ = MarketParticipantCompliance.objects.select_for_update().get_or_create(
            participant=verification.user
        )
        if compliance.kyc_status == target_status:
            return compliance, False

        previous_status = compliance.kyc_status
        compliance.kyc_status = target_status
        compliance.save(update_fields=["kyc_status", "updated_at"])
        MarketComplianceReview.objects.create(
            participant=verification.user,
            actor=actor,
            source=(
                MarketComplianceReview.Source.ADMIN
                if actor
                else MarketComplianceReview.Source.SYSTEM
            ),
            previous_kyc_status=previous_status,
            new_kyc_status=target_status,
            previous_restriction_status=compliance.restriction_status,
            new_restriction_status=compliance.restriction_status,
            previous_jurisdiction_override=compliance.jurisdiction_override,
            new_jurisdiction_override=compliance.jurisdiction_override,
            reason=reason or f"Canonical KYC status changed to {verification.status}.",
            notes_snapshot=f"kyc_verification_id={verification.id}",
        )
        return compliance, True
