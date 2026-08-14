from collections.abc import Iterable

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from authentication.services.permission_service import (
    PermissionService,
)
from markets.models import (
    Market,
    MarketOutcome,
    MarketStatusTransition,
)


class MarketResolutionService:
    RESULT_VERIFICATION_PERMISSIONS = (
        "approve_market",
        "verify_results",
        "reject_result",
    )

    VOIDABLE_STATUSES = {
        Market.Status.APPROVED,
        Market.Status.OPEN,
        Market.Status.SUSPENDED,
        Market.Status.CLOSED,
    }

    @classmethod
    @transaction.atomic
    def resolve(
        cls,
        *,
        market_id,
        actor,
        winning_outcome_id,
        notes: str,
        evidence: str,
    ) -> Market:
        cls._require_permission(actor)

        market = cls._get_locked_market(market_id)

        cls._require_independent_resolver(
            market,
            actor,
        )
        cls._require_status(
            market,
            {
                Market.Status.CLOSED,
            },
            action="resolve",
        )

        clean_notes = cls._clean_required_text(
            notes,
            field_name="notes",
            message="Resolution notes are required.",
        )
        clean_evidence = cls._clean_required_text(
            evidence,
            field_name="evidence",
            message=("Resolution evidence is required."),
        )

        try:
            winner = MarketOutcome.objects.select_for_update().get(
                id=winning_outcome_id,
                market_id=market.id,
            )
        except MarketOutcome.DoesNotExist as error:
            raise ValidationError(
                {
                    "winning_outcome": (
                        "The selected winning outcome " "does not belong to this market."
                    )
                }
            ) from error

        return cls._apply_terminal_transition(
            market=market,
            actor=actor,
            action=(MarketStatusTransition.Action.RESOLVE),
            to_status=Market.Status.RESOLVED,
            notes=clean_notes,
            evidence=clean_evidence,
            winning_outcome=winner,
            metadata={
                "winning_outcome_id": str(winner.id),
                "winning_side": winner.side,
                "evidence": clean_evidence,
            },
        )

    @classmethod
    @transaction.atomic
    def void(
        cls,
        *,
        market_id,
        actor,
        notes: str,
        evidence: str,
    ) -> Market:
        cls._require_permission(actor)

        market = cls._get_locked_market(market_id)

        cls._require_independent_resolver(
            market,
            actor,
        )
        cls._require_status(
            market,
            cls.VOIDABLE_STATUSES,
            action="void",
        )

        clean_notes = cls._clean_required_text(
            notes,
            field_name="notes",
            message="Void notes are required.",
        )
        clean_evidence = cls._clean_required_text(
            evidence,
            field_name="evidence",
            message="Void evidence is required.",
        )

        return cls._apply_terminal_transition(
            market=market,
            actor=actor,
            action=(MarketStatusTransition.Action.VOID),
            to_status=Market.Status.VOIDED,
            notes=clean_notes,
            evidence=clean_evidence,
            winning_outcome=None,
            metadata={
                "evidence": clean_evidence,
            },
        )

    @staticmethod
    def _get_locked_market(
        market_id,
    ) -> Market:
        return (
            Market.objects.select_for_update(
                of=("self",),
            )
            .select_related(
                "created_by",
                "winning_outcome",
                "sport",
                "category",
                "template",
                "sporting_event",
                "competition",
                "participant",
            )
            .get(id=market_id)
        )

    @classmethod
    def _require_permission(
        cls,
        actor,
    ) -> None:
        if not PermissionService.has_any_permission(
            actor,
            cls.RESULT_VERIFICATION_PERMISSIONS,
        ):
            raise PermissionDenied("You do not have permission to verify or reject results.")

    @staticmethod
    def _require_independent_resolver(
        market: Market,
        actor,
    ) -> None:
        if market.created_by_id is not None and market.created_by_id == actor.id:
            raise PermissionDenied("Market creators cannot resolve " "or void their own markets.")

    @staticmethod
    def _require_status(
        market: Market,
        allowed_statuses: Iterable[str],
        *,
        action: str,
    ) -> None:
        allowed = set(allowed_statuses)

        if market.status not in allowed:
            expected = ", ".join(sorted(allowed))

            raise ValidationError(
                {
                    "status": (
                        f"Cannot {action} a market "
                        f"from {market.status}. "
                        f"Expected: {expected}."
                    )
                }
            )

    @staticmethod
    def _clean_required_text(
        value: str,
        *,
        field_name: str,
        message: str,
    ) -> str:
        cleaned = (value or "").strip()

        if not cleaned:
            raise ValidationError(
                {
                    field_name: message,
                }
            )

        return cleaned

    @staticmethod
    def _apply_terminal_transition(
        *,
        market: Market,
        actor,
        action: str,
        to_status: str,
        notes: str,
        evidence: str,
        winning_outcome: MarketOutcome | None,
        metadata: dict,
    ) -> Market:
        from_status = market.status
        resolved_at = timezone.now()

        market.status = to_status
        market.winning_outcome = winning_outcome
        market.resolved_by = actor
        market.resolved_at = resolved_at
        market.resolution_notes = notes
        market.resolution_evidence = evidence

        market.full_clean()

        market.save(
            update_fields=[
                "status",
                "winning_outcome",
                "resolved_by",
                "resolved_at",
                "resolution_notes",
                "resolution_evidence",
                "updated_at",
            ]
        )

        MarketStatusTransition.objects.create(
            market=market,
            action=action,
            from_status=from_status,
            to_status=to_status,
            actor=actor,
            actor_email=actor.email,
            notes=notes,
            metadata=metadata,
        )

        return market
