from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from markets.models import MarketComplianceReview, MarketParticipantCompliance


class MarketComplianceService:
    FIELDS = (
        "kyc_status",
        "restriction_status",
        "jurisdiction_override",
        "jurisdiction_override_reason",
        "internal_review_notes",
    )

    @classmethod
    @transaction.atomic
    def update(cls, *, participant, actor, changes, source="ADMIN", reason=""):
        participant = get_user_model().objects.select_for_update().get(pk=participant.pk)
        try:
            compliance = MarketParticipantCompliance.objects.select_for_update().get(
                participant=participant
            )
        except MarketParticipantCompliance.DoesNotExist:
            try:
                with transaction.atomic():
                    compliance = MarketParticipantCompliance.objects.create(participant=participant)
            except IntegrityError:
                compliance = MarketParticipantCompliance.objects.select_for_update().get(
                    participant=participant
                )
        before = {field: getattr(compliance, field) for field in cls.FIELDS}
        for field, value in changes.items():
            setattr(compliance, field, value)
        changed = any(getattr(compliance, field) != before[field] for field in cls.FIELDS)
        if not changed:
            return compliance
        compliance.reviewed_by = actor
        compliance.reviewed_at = timezone.now()
        compliance.full_clean()
        compliance.save()
        review = MarketComplianceReview.objects.create(
            participant=participant,
            actor=actor,
            source=source,
            previous_kyc_status=before["kyc_status"],
            new_kyc_status=compliance.kyc_status,
            previous_restriction_status=before["restriction_status"],
            new_restriction_status=compliance.restriction_status,
            previous_jurisdiction_override=before["jurisdiction_override"],
            new_jurisdiction_override=compliance.jurisdiction_override,
            reason=reason or compliance.jurisdiction_override_reason,
            notes_snapshot=compliance.internal_review_notes,
        )
        if compliance.restriction_status != before["restriction_status"]:
            from markets.services.market_notification_service import MarketNotificationService

            applied = compliance.restriction_status != "CLEAR"
            MarketNotificationService.schedule(
                recipient=participant,
                category="MARKET_COMPLIANCE",
                event_type=(
                    "COMPLIANCE_RESTRICTION_APPLIED"
                    if applied
                    else "COMPLIANCE_RESTRICTION_REMOVED"
                ),
                title="Compliance restriction updated",
                message=(
                    "A market compliance restriction was applied."
                    if applied
                    else "Your market compliance restriction was removed."
                ),
                key=f"market-compliance-review:{review.id}:restriction",
                data={"restriction_status": compliance.restriction_status},
                mandatory=True,
            )
        return compliance
