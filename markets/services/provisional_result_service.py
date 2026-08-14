from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from authentication.services.permission_service import PermissionService
from markets.models import (
    Market,
    MarketOutcome,
    MarketPosition,
    MarketProvisionalEvidence,
    MarketProvisionalResult,
)
from markets.services.market_notification_service import MarketNotificationService


class MarketProvisionalResultService:
    RESULT_VERIFICATION_PERMISSIONS = (
        "approve_market",
        "verify_results",
        "reject_result",
    )

    DEFAULT_DISPUTE_WINDOW_HOURS = 48
    MIN_DISPUTE_WINDOW_HOURS = 1
    MAX_DISPUTE_WINDOW_HOURS = 168

    @classmethod
    @transaction.atomic
    def publish(
        cls,
        *,
        market_id,
        actor,
        winning_outcome_id,
        notes,
        evidence_items,
        dispute_window_hours=DEFAULT_DISPUTE_WINDOW_HOURS,
    ) -> MarketProvisionalResult:
        cls._require_permission(actor)

        market = (
            Market.objects.select_for_update(of=("self",))
            .select_related("created_by")
            .get(id=market_id)
        )

        cls._require_independent_actor(market, actor)
        cls._require_closed_market(market)
        cls._require_no_existing_result(market)

        clean_notes = cls._clean_required_text(
            notes,
            field_name="notes",
            message="Provisional result notes are required.",
        )
        clean_window = cls._validate_window(dispute_window_hours)
        clean_evidence = cls._validate_evidence_items(evidence_items)

        try:
            winning_outcome = MarketOutcome.objects.select_for_update().get(
                id=winning_outcome_id,
                market_id=market.id,
            )
        except MarketOutcome.DoesNotExist as error:
            raise ValidationError(
                {
                    "winning_outcome": (
                        "The selected provisional outcome does not belong " "to this market."
                    )
                }
            ) from error

        published_at = timezone.now()
        dispute_deadline = published_at + timedelta(hours=clean_window)

        provisional_result = MarketProvisionalResult.objects.create(
            market=market,
            winning_outcome=winning_outcome,
            notes=clean_notes,
            published_by=actor,
            publisher_email=actor.email,
            published_at=published_at,
            dispute_deadline=dispute_deadline,
        )

        for item in clean_evidence:
            MarketProvisionalEvidence.objects.create(
                provisional_result=provisional_result,
                evidence_type=item["evidence_type"],
                label=item["label"],
                reference=item["reference"],
                recorded_by=actor,
                recorder_email=actor.email,
                recorded_at=published_at,
            )

        for participant in (
            MarketPosition.objects.filter(market=market).values_list("user", flat=True).distinct()
        ):
            from django.contrib.auth import get_user_model

            MarketNotificationService.schedule(
                recipient=get_user_model().objects.get(pk=participant),
                category="MARKET_RESULTS",
                event_type="PROVISIONAL_RESULT_PUBLISHED",
                title="Provisional result published",
                message="A provisional market result is available for review.",
                key=f"market-provisional-result:{provisional_result.id}:participant:{participant}",
                market_id=market.id,
                data={"provisional_result_id": str(provisional_result.id)},
            )

        return (
            MarketProvisionalResult.objects.select_related(
                "market",
                "winning_outcome",
                "published_by",
            )
            .prefetch_related("evidence_items")
            .get(pk=provisional_result.pk)
        )

    @classmethod
    def require_dispute_window_closed(cls, market) -> None:
        try:
            provisional_result = market.provisional_result
        except MarketProvisionalResult.DoesNotExist:
            # Backward compatibility for terminal markets created before the
            # provisional-result workflow was introduced.
            return

        if timezone.now() < provisional_result.dispute_deadline:
            raise ValidationError(
                {
                    "dispute_window": (
                        "Financial finalisation is blocked until the "
                        "provisional-result dispute window closes."
                    )
                }
            )

    @classmethod
    def _require_permission(cls, actor) -> None:
        if not PermissionService.has_any_permission(
            actor,
            cls.RESULT_VERIFICATION_PERMISSIONS,
        ):
            raise PermissionDenied("You do not have permission to verify or reject results.")

    @staticmethod
    def _require_independent_actor(market, actor) -> None:
        if market.created_by_id is not None and market.created_by_id == actor.id:
            raise PermissionDenied(
                "Market creators cannot publish provisional results " "for their own markets."
            )

    @staticmethod
    def _require_closed_market(market) -> None:
        if market.status != Market.Status.CLOSED:
            raise ValidationError(
                {"status": ("A provisional result can only be published " "for a closed market.")}
            )

    @staticmethod
    def _require_no_existing_result(market) -> None:
        if MarketProvisionalResult.objects.filter(market=market).exists():
            raise ValidationError(
                {"provisional_result": ("This market already has a provisional result.")}
            )

    @classmethod
    def _validate_window(cls, value) -> int:
        try:
            clean_value = int(value)
        except (TypeError, ValueError) as error:
            raise ValidationError(
                {"dispute_window_hours": ("The dispute window must be a whole number of hours.")}
            ) from error

        if not (cls.MIN_DISPUTE_WINDOW_HOURS <= clean_value <= cls.MAX_DISPUTE_WINDOW_HOURS):
            raise ValidationError(
                {
                    "dispute_window_hours": (
                        "The dispute window must be between "
                        f"{cls.MIN_DISPUTE_WINDOW_HOURS} and "
                        f"{cls.MAX_DISPUTE_WINDOW_HOURS} hours."
                    )
                }
            )

        return clean_value

    @classmethod
    def _validate_evidence_items(cls, evidence_items) -> list[dict]:
        if not isinstance(evidence_items, list | tuple) or not evidence_items:
            raise ValidationError(
                {"evidence_items": ("At least one approved evidence item is required.")}
            )

        allowed_types = {
            choice for choice, _label in MarketProvisionalEvidence.EvidenceType.choices
        }
        cleaned = []

        for index, item in enumerate(evidence_items):
            if not isinstance(item, dict):
                raise ValidationError(
                    {"evidence_items": (f"Evidence item {index + 1} must be an object.")}
                )

            evidence_type = item.get("evidence_type")
            label = cls._clean_optional_text(item.get("label"))
            reference = cls._clean_optional_text(item.get("reference"))

            if evidence_type not in allowed_types:
                raise ValidationError(
                    {"evidence_items": (f"Evidence item {index + 1} has an invalid type.")}
                )

            if not label:
                raise ValidationError(
                    {"evidence_items": (f"Evidence item {index + 1} requires a label.")}
                )

            if not reference:
                raise ValidationError(
                    {"evidence_items": (f"Evidence item {index + 1} requires a reference.")}
                )

            cleaned.append(
                {
                    "evidence_type": evidence_type,
                    "label": label,
                    "reference": reference,
                }
            )

        return cleaned

    @staticmethod
    def _clean_required_text(value, *, field_name, message) -> str:
        cleaned = (value or "").strip()

        if not cleaned:
            raise ValidationError({field_name: message})

        return cleaned

    @staticmethod
    def _clean_optional_text(value) -> str:
        return str(value or "").strip()
