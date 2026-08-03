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
    def update(cls, *, participant, actor, changes):
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
        MarketComplianceReview.objects.create(
            participant=participant,
            actor=actor,
            previous_kyc_status=before["kyc_status"],
            new_kyc_status=compliance.kyc_status,
            previous_restriction_status=before["restriction_status"],
            new_restriction_status=compliance.restriction_status,
            previous_jurisdiction_override=before["jurisdiction_override"],
            new_jurisdiction_override=compliance.jurisdiction_override,
            reason=compliance.jurisdiction_override_reason,
            notes_snapshot=compliance.internal_review_notes,
        )
        return compliance
