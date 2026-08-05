from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from markets.models import (
    MarketPosition,
    MarketProvisionalResult,
    MarketResultDispute,
    MarketResultDisputeDecision,
    MarketResultDisputeEvidence,
)


class MarketResultDisputeService:
    @classmethod
    @transaction.atomic
    def submit(
        cls,
        *,
        market_id,
        actor,
        category,
        explanation,
        evidence_items,
    ) -> MarketResultDispute:
        provisional_result = cls._get_locked_provisional_result(market_id)

        cls._require_open_window(provisional_result)
        cls._require_market_participant(
            market_id=market_id,
            actor=actor,
        )
        cls._require_no_existing_dispute(
            provisional_result=provisional_result,
            actor=actor,
        )

        clean_category = cls._validate_category(category)
        clean_explanation = cls._clean_required_text(
            explanation,
            field_name="explanation",
            message="A dispute explanation is required.",
        )
        clean_evidence = cls._validate_evidence_items(evidence_items)

        submitted_at = timezone.now()

        dispute = MarketResultDispute.objects.create(
            provisional_result=provisional_result,
            participant=actor,
            participant_email=actor.email,
            category=clean_category,
            explanation=clean_explanation,
            submitted_at=submitted_at,
        )

        for item in clean_evidence:
            MarketResultDisputeEvidence.objects.create(
                dispute=dispute,
                label=item["label"],
                reference=item["reference"],
                recorded_at=submitted_at,
            )

        return (
            MarketResultDispute.objects.select_related(
                "provisional_result",
                "provisional_result__market",
                "participant",
            )
            .prefetch_related(
                "evidence_items",
            )
            .get(pk=dispute.pk)
        )

    @staticmethod
    def require_no_open_disputes(market) -> None:
        try:
            provisional_result = market.provisional_result
        except MarketProvisionalResult.DoesNotExist:
            return

        has_disputes = MarketResultDispute.objects.filter(
            provisional_result=provisional_result,
        ).exists()

        if not has_disputes:
            return

        has_final_decision = MarketResultDisputeDecision.objects.filter(
            provisional_result=provisional_result,
            decision_type__in=[
                (MarketResultDisputeDecision.DecisionType.CONFIRM),
                (MarketResultDisputeDecision.DecisionType.CORRECT),
                (MarketResultDisputeDecision.DecisionType.VOID),
            ],
        ).exists()

        if has_final_decision:
            return

        raise ValidationError(
            {
                "disputes": (
                    "Financial finalisation is blocked until "
                    "all result disputes have been decided."
                )
            }
        )

    @staticmethod
    def _get_locked_provisional_result(
        market_id,
    ) -> MarketProvisionalResult:
        try:
            return (
                MarketProvisionalResult.objects.select_for_update()
                .select_related(
                    "market",
                    "winning_outcome",
                )
                .get(
                    market_id=market_id,
                )
            )
        except MarketProvisionalResult.DoesNotExist as error:
            raise ValidationError(
                {"provisional_result": ("This market does not have a provisional result.")}
            ) from error

    @staticmethod
    def _require_open_window(
        provisional_result: MarketProvisionalResult,
    ) -> None:
        if timezone.now() >= provisional_result.dispute_deadline:
            raise ValidationError(
                {"dispute_window": ("The provisional-result dispute window " "has closed.")}
            )

    @staticmethod
    def _require_market_participant(
        *,
        market_id,
        actor,
    ) -> None:
        participated = MarketPosition.objects.filter(
            market_id=market_id,
            user=actor,
        ).exists()

        if not participated:
            raise PermissionDenied(
                "Only a participant in this market may "
                "submit a result dispute.",
                code="not_market_participant",
            )

    @staticmethod
    def _require_no_existing_dispute(
        *,
        provisional_result,
        actor,
    ) -> None:
        if MarketResultDispute.objects.filter(
            provisional_result=provisional_result,
            participant=actor,
        ).exists():
            raise ValidationError(
                {
                    "dispute": (
                        "You have already submitted a dispute " "for this provisional result."
                    )
                }
            )

    @staticmethod
    def _validate_category(value) -> str:
        cleaned = str(value or "").strip().upper()

        allowed = {choice for choice, _label in (MarketResultDispute.Category.choices)}

        if cleaned not in allowed:
            raise ValidationError({"category": ("Select a valid result dispute category.")})

        return cleaned

    @classmethod
    def _validate_evidence_items(
        cls,
        evidence_items,
    ) -> list[dict]:
        if not isinstance(evidence_items, list | tuple) or not evidence_items:
            raise ValidationError(
                {"evidence_items": ("At least one dispute evidence item " "is required.")}
            )

        cleaned = []

        for index, item in enumerate(evidence_items):
            if not isinstance(item, dict):
                raise ValidationError(
                    {"evidence_items": (f"Evidence item {index + 1} " "must be an object.")}
                )

            label = cls._clean_optional_text(item.get("label"))
            reference = cls._clean_optional_text(item.get("reference"))

            if not label:
                raise ValidationError(
                    {"evidence_items": (f"Evidence item {index + 1} " "requires a label.")}
                )

            if not reference:
                raise ValidationError(
                    {"evidence_items": (f"Evidence item {index + 1} " "requires a reference.")}
                )

            cleaned.append(
                {
                    "label": label,
                    "reference": reference,
                }
            )

        return cleaned

    @staticmethod
    def _clean_required_text(
        value,
        *,
        field_name,
        message,
    ) -> str:
        cleaned = str(value or "").strip()

        if not cleaned:
            raise ValidationError(
                {
                    field_name: message,
                }
            )

        return cleaned

    @staticmethod
    def _clean_optional_text(value) -> str:
        return str(value or "").strip()
