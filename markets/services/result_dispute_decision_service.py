from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from authentication.services.permission_service import (
    PermissionService,
)
from markets.models import (
    MarketOutcome,
    MarketProvisionalResult,
    MarketResultDispute,
    MarketResultDisputeDecision,
)
from markets.services.resolution_service import (
    MarketResolutionService,
)


class MarketResultDisputeDecisionService:
    RESULT_VERIFICATION_PERMISSIONS = (
        "approve_market",
        "verify_results",
        "reject_result",
    )

    MIN_REVIEW_EXTENSION_HOURS = 1
    MAX_REVIEW_EXTENSION_HOURS = 168

    FINAL_DECISION_TYPES = {
        MarketResultDisputeDecision.DecisionType.CONFIRM,
        MarketResultDisputeDecision.DecisionType.CORRECT,
        MarketResultDisputeDecision.DecisionType.VOID,
    }

    @classmethod
    @transaction.atomic
    def decide(
        cls,
        *,
        market_id,
        actor,
        decision_type,
        winning_outcome_id=None,
        review_extension_hours=None,
        notes,
        evidence,
    ) -> MarketResultDisputeDecision:
        cls._require_permission(actor)

        provisional_result = cls._get_locked_provisional_result(market_id)
        market = provisional_result.market

        cls._require_no_final_decision(provisional_result)
        cls._require_independent_actor(
            provisional_result=provisional_result,
            actor=actor,
        )

        disputes = MarketResultDispute.objects.select_for_update().filter(
            provisional_result=provisional_result,
        )
        dispute_count = disputes.count()

        if dispute_count == 0:
            raise ValidationError(
                {"disputes": ("A dispute decision requires at least " "one submitted dispute.")}
            )

        decided_at = timezone.now()

        if decided_at < provisional_result.dispute_deadline and not hasattr(
            provisional_result, "development_acceleration"
        ):
            raise ValidationError(
                {
                    "dispute_window": (
                        "A final review decision cannot be made "
                        "before the participant dispute window closes."
                    )
                }
            )

        cls._require_no_active_review_extension(
            provisional_result=provisional_result,
            at=decided_at,
        )

        clean_type = cls._validate_decision_type(decision_type)
        clean_notes = cls._clean_required_text(
            notes,
            field_name="notes",
            message="Decision notes are required.",
        )
        clean_evidence = cls._clean_required_text(
            evidence,
            field_name="evidence",
            message="Decision evidence is required.",
        )

        sequence = cls._next_sequence(provisional_result)

        if clean_type == MarketResultDisputeDecision.DecisionType.EXTEND_REVIEW:
            extension_hours = cls._validate_review_extension(review_extension_hours)

            if winning_outcome_id is not None:
                raise ValidationError(
                    {"winning_outcome": ("A review extension cannot have " "a winning outcome.")}
                )

            return cls._create_decision(
                provisional_result=provisional_result,
                sequence=sequence,
                decision_type=clean_type,
                winning_outcome=None,
                review_extended_until=(decided_at + timedelta(hours=extension_hours)),
                dispute_count=dispute_count,
                notes=clean_notes,
                evidence=clean_evidence,
                actor=actor,
                decided_at=decided_at,
            )

        if review_extension_hours is not None:
            raise ValidationError(
                {
                    "review_extension_hours": (
                        "A final decision cannot include " "a review extension."
                    )
                }
            )

        winner = cls._resolve_decision_outcome(
            provisional_result=provisional_result,
            decision_type=clean_type,
            winning_outcome_id=winning_outcome_id,
        )

        if clean_type == (MarketResultDisputeDecision.DecisionType.VOID):
            MarketResolutionService.void(
                market_id=market.id,
                actor=actor,
                notes=clean_notes,
                evidence=clean_evidence,
                _trusted_dispute_decision=True,
            )
        else:
            MarketResolutionService.resolve(
                market_id=market.id,
                actor=actor,
                winning_outcome_id=winner.id,
                notes=clean_notes,
                evidence=clean_evidence,
            )

        return cls._create_decision(
            provisional_result=provisional_result,
            sequence=sequence,
            decision_type=clean_type,
            winning_outcome=winner,
            review_extended_until=None,
            dispute_count=dispute_count,
            notes=clean_notes,
            evidence=clean_evidence,
            actor=actor,
            decided_at=decided_at,
        )

    @staticmethod
    def _get_locked_provisional_result(
        market_id,
    ) -> MarketProvisionalResult:
        try:
            return (
                MarketProvisionalResult.objects.select_for_update(of=("self",))
                .select_related(
                    "market",
                    "market__created_by",
                    "winning_outcome",
                    "published_by",
                )
                .get(
                    market_id=market_id,
                )
            )
        except MarketProvisionalResult.DoesNotExist as error:
            raise ValidationError(
                {"provisional_result": ("This market does not have a " "provisional result.")}
            ) from error

    @classmethod
    def _require_permission(cls, actor) -> None:
        if not PermissionService.has_any_permission(
            actor,
            cls.RESULT_VERIFICATION_PERMISSIONS,
        ):
            raise PermissionDenied("You do not have permission to verify or reject results.")

    @staticmethod
    def _require_independent_actor(
        *,
        provisional_result,
        actor,
    ) -> None:
        market = provisional_result.market

        if market.created_by_id is not None and market.created_by_id == actor.id:
            raise PermissionDenied("The market creator cannot decide its disputes.")

        if provisional_result.published_by_id == actor.id:
            raise PermissionDenied(
                "The provisional-result publisher cannot " "decide its disputes."
            )

        if MarketResultDispute.objects.filter(
            provisional_result=provisional_result,
            participant=actor,
        ).exists():
            raise PermissionDenied(
                "A disputing participant cannot decide " "the same result dispute."
            )

    @classmethod
    def _require_no_final_decision(
        cls,
        provisional_result,
    ) -> None:
        if MarketResultDisputeDecision.objects.filter(
            provisional_result=provisional_result,
            decision_type__in=cls.FINAL_DECISION_TYPES,
        ).exists():
            raise ValidationError(
                {"decision": ("This provisional result already has " "a final dispute decision.")}
            )

    @staticmethod
    def _require_no_active_review_extension(
        *,
        provisional_result,
        at,
    ) -> None:
        latest_extension = (
            MarketResultDisputeDecision.objects.filter(
                provisional_result=provisional_result,
                decision_type=(MarketResultDisputeDecision.DecisionType.EXTEND_REVIEW),
            )
            .order_by(
                "-sequence",
                "-id",
            )
            .first()
        )

        if (
            latest_extension is not None
            and latest_extension.review_extended_until is not None
            and at < latest_extension.review_extended_until
        ):
            raise ValidationError(
                {
                    "review_window": (
                        "The independent review extension remains "
                        "open until "
                        f"{latest_extension.review_extended_until.isoformat()}."
                    )
                }
            )

    @staticmethod
    def _validate_decision_type(value) -> str:
        cleaned = str(value or "").strip().upper()
        allowed = {choice for choice, _label in (MarketResultDisputeDecision.DecisionType.choices)}

        if cleaned not in allowed:
            raise ValidationError({"decision_type": ("Select a valid dispute decision type.")})

        return cleaned

    @classmethod
    def _resolve_decision_outcome(
        cls,
        *,
        provisional_result,
        decision_type,
        winning_outcome_id,
    ):
        if decision_type == (MarketResultDisputeDecision.DecisionType.CONFIRM):
            if winning_outcome_id is not None:
                raise ValidationError(
                    {
                        "winning_outcome": (
                            "A confirmed decision automatically "
                            "uses the provisional winning outcome."
                        )
                    }
                )

            return provisional_result.winning_outcome

        if decision_type == (MarketResultDisputeDecision.DecisionType.VOID):
            if winning_outcome_id is not None:
                raise ValidationError(
                    {"winning_outcome": ("A void decision cannot have " "a winning outcome.")}
                )

            return None

        if decision_type != (MarketResultDisputeDecision.DecisionType.CORRECT):
            raise ValidationError(
                {"decision_type": ("This decision type cannot produce " "a final market result.")}
            )

        if winning_outcome_id is None:
            raise ValidationError(
                {"winning_outcome": ("A corrected decision requires " "a winning outcome.")}
            )

        try:
            winner = MarketOutcome.objects.select_for_update().get(
                id=winning_outcome_id,
                market_id=provisional_result.market_id,
            )
        except MarketOutcome.DoesNotExist as error:
            raise ValidationError(
                {
                    "winning_outcome": (
                        "The corrected winning outcome does not " "belong to this market."
                    )
                }
            ) from error

        if winner.id == provisional_result.winning_outcome_id:
            raise ValidationError(
                {
                    "winning_outcome": (
                        "A corrected decision must differ from " "the provisional winning outcome."
                    )
                }
            )

        return winner

    @classmethod
    def _validate_review_extension(cls, value) -> int:
        if isinstance(value, bool):
            raise ValidationError(
                {
                    "review_extension_hours": (
                        "The review extension must be a whole " "number of hours."
                    )
                }
            )

        try:
            clean_value = int(value)
        except (TypeError, ValueError) as error:
            raise ValidationError(
                {
                    "review_extension_hours": (
                        "The review extension must be a whole " "number of hours."
                    )
                }
            ) from error

        if not (cls.MIN_REVIEW_EXTENSION_HOURS <= clean_value <= cls.MAX_REVIEW_EXTENSION_HOURS):
            raise ValidationError(
                {
                    "review_extension_hours": (
                        "The review extension must be between "
                        f"{cls.MIN_REVIEW_EXTENSION_HOURS} and "
                        f"{cls.MAX_REVIEW_EXTENSION_HOURS} hours."
                    )
                }
            )

        return clean_value

    @staticmethod
    def _next_sequence(provisional_result) -> int:
        current = (
            MarketResultDisputeDecision.objects.filter(
                provisional_result=provisional_result,
            ).aggregate(maximum=Max("sequence"),)["maximum"]
            or 0
        )

        return current + 1

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
    def _create_decision(
        *,
        provisional_result,
        sequence,
        decision_type,
        winning_outcome,
        review_extended_until,
        dispute_count,
        notes,
        evidence,
        actor,
        decided_at,
    ) -> MarketResultDisputeDecision:
        decision = MarketResultDisputeDecision.objects.create(
            provisional_result=provisional_result,
            sequence=sequence,
            decision_type=decision_type,
            winning_outcome=winning_outcome,
            review_extended_until=review_extended_until,
            covered_dispute_count=dispute_count,
            notes=notes,
            evidence=evidence,
            decided_by=actor,
            decision_maker_email=actor.email,
            decided_at=decided_at,
        )

        from markets.services.market_notification_service import MarketNotificationService

        for dispute in provisional_result.disputes.select_related("participant"):
            MarketNotificationService.schedule(
                recipient=dispute.participant,
                category="MARKET_DISPUTES",
                event_type="RESULT_DISPUTE_DECIDED",
                title="Result dispute decided",
                message="A decision was recorded for your market result dispute.",
                key=f"market-dispute-decision:{decision.id}:participant:{dispute.participant_id}",
                market_id=provisional_result.market_id,
                data={"decision_id": str(decision.id), "dispute_id": str(dispute.id)},
            )

        return MarketResultDisputeDecision.objects.select_related(
            "provisional_result",
            "provisional_result__market",
            "winning_outcome",
            "decided_by",
        ).get(pk=decision.pk)
