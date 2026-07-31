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
    MarketStatusTransition,
)


class MarketLifecycleService:
    MANAGE_PERMISSION = "manage_market"
    APPROVE_PERMISSION = "approve_market"

    @classmethod
    @transaction.atomic
    def submit(
        cls,
        *,
        market_id,
        actor,
        notes: str,
    ) -> Market:
        cls._require_permission(
            actor,
            cls.MANAGE_PERMISSION,
        )

        market = cls._get_locked_market(market_id)

        cls._require_status(
            market,
            {
                Market.Status.DRAFT,
                Market.Status.REJECTED,
            },
            action="submit",
        )

        clean_notes = cls._clean_notes(notes)
        errors = {}

        if not market.resolution_source.strip():
            errors["resolution_source"] = "A resolution source is required " "before submission."

        if not market.resolution_criteria.strip():
            errors["resolution_criteria"] = "Resolution criteria are required " "before submission."

        if not market.rules.strip():
            errors["rules"] = "Market rules are required " "before submission."

        if not market.has_complete_outcomes:
            errors["outcomes"] = "The market requires one YES outcome " "and one NO outcome."

        if errors:
            raise ValidationError(errors)

        return cls._apply_transition(
            market=market,
            actor=actor,
            action=MarketStatusTransition.Action.SUBMIT,
            to_status=Market.Status.PENDING_APPROVAL,
            notes=clean_notes,
            market_updates={
                "approved_by": None,
                "approved_at": None,
                "approval_notes": "",
            },
        )

    @classmethod
    @transaction.atomic
    def approve(
        cls,
        *,
        market_id,
        actor,
        notes: str,
    ) -> Market:
        cls._require_permission(
            actor,
            cls.APPROVE_PERMISSION,
        )

        market = cls._get_locked_market(market_id)

        cls._require_status(
            market,
            {
                Market.Status.PENDING_APPROVAL,
            },
            action="approve",
        )
        cls._require_independent_approver(
            market,
            actor,
        )

        clean_notes = cls._clean_notes(notes)
        now = timezone.now()

        return cls._apply_transition(
            market=market,
            actor=actor,
            action=MarketStatusTransition.Action.APPROVE,
            to_status=Market.Status.APPROVED,
            notes=clean_notes,
            market_updates={
                "approved_by": actor,
                "approved_at": now,
                "approval_notes": clean_notes,
            },
        )

    @classmethod
    @transaction.atomic
    def reject(
        cls,
        *,
        market_id,
        actor,
        notes: str,
    ) -> Market:
        cls._require_permission(
            actor,
            cls.APPROVE_PERMISSION,
        )

        market = cls._get_locked_market(market_id)

        cls._require_status(
            market,
            {
                Market.Status.PENDING_APPROVAL,
            },
            action="reject",
        )
        cls._require_independent_approver(
            market,
            actor,
        )

        clean_notes = cls._clean_notes(notes)

        return cls._apply_transition(
            market=market,
            actor=actor,
            action=MarketStatusTransition.Action.REJECT,
            to_status=Market.Status.REJECTED,
            notes=clean_notes,
            market_updates={
                "approved_by": None,
                "approved_at": None,
                "approval_notes": clean_notes,
            },
        )

    @classmethod
    @transaction.atomic
    def open(
        cls,
        *,
        market_id,
        actor,
        notes: str,
    ) -> Market:
        cls._require_permission(
            actor,
            cls.APPROVE_PERMISSION,
        )

        market = cls._get_locked_market(market_id)

        cls._require_status(
            market,
            {
                Market.Status.APPROVED,
            },
            action="open",
        )

        clean_notes = cls._clean_notes(notes)

        cls._validate_active_window(market)

        if not market.has_complete_outcomes:
            raise ValidationError(
                {"outcomes": ("The market requires one YES " "and one NO outcome.")}
            )

        return cls._apply_transition(
            market=market,
            actor=actor,
            action=MarketStatusTransition.Action.OPEN,
            to_status=Market.Status.OPEN,
            notes=clean_notes,
        )

    @classmethod
    @transaction.atomic
    def suspend(
        cls,
        *,
        market_id,
        actor,
        notes: str,
    ) -> Market:
        cls._require_permission(
            actor,
            cls.APPROVE_PERMISSION,
        )

        market = cls._get_locked_market(market_id)

        cls._require_status(
            market,
            {
                Market.Status.OPEN,
            },
            action="suspend",
        )

        clean_notes = cls._clean_notes(notes)

        return cls._apply_transition(
            market=market,
            actor=actor,
            action=MarketStatusTransition.Action.SUSPEND,
            to_status=Market.Status.SUSPENDED,
            notes=clean_notes,
        )

    @classmethod
    @transaction.atomic
    def reopen(
        cls,
        *,
        market_id,
        actor,
        notes: str,
    ) -> Market:
        cls._require_permission(
            actor,
            cls.APPROVE_PERMISSION,
        )

        market = cls._get_locked_market(market_id)

        cls._require_status(
            market,
            {
                Market.Status.SUSPENDED,
            },
            action="reopen",
        )

        clean_notes = cls._clean_notes(notes)

        cls._validate_active_window(market)

        return cls._apply_transition(
            market=market,
            actor=actor,
            action=MarketStatusTransition.Action.REOPEN,
            to_status=Market.Status.OPEN,
            notes=clean_notes,
        )

    @classmethod
    @transaction.atomic
    def close(
        cls,
        *,
        market_id,
        actor,
        notes: str,
    ) -> Market:
        cls._require_permission(
            actor,
            cls.APPROVE_PERMISSION,
        )

        market = cls._get_locked_market(market_id)

        cls._require_status(
            market,
            {
                Market.Status.OPEN,
                Market.Status.SUSPENDED,
            },
            action="close",
        )

        clean_notes = cls._clean_notes(notes)

        return cls._apply_transition(
            market=market,
            actor=actor,
            action=MarketStatusTransition.Action.CLOSE,
            to_status=Market.Status.CLOSED,
            notes=clean_notes,
        )

    @staticmethod
    def _get_locked_market(market_id) -> Market:
        return (
            Market.objects.select_for_update(
                of=("self",),
            )
            .select_related(
                "created_by",
                "sport",
                "category",
                "template",
                "sporting_event",
                "competition",
                "participant",
            )
            .get(id=market_id)
        )

    @staticmethod
    def _require_permission(
        actor,
        permission_name: str,
    ) -> None:
        if not PermissionService.has_permission(
            actor,
            permission_name,
        ):
            raise PermissionDenied("You do not have the " f"{permission_name} permission.")

    @staticmethod
    def _require_independent_approver(
        market: Market,
        actor,
    ) -> None:
        if market.created_by_id is not None and market.created_by_id == actor.id:
            raise PermissionDenied("Market creators cannot approve " "or reject their own markets.")

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
    def _clean_notes(notes: str) -> str:
        clean_notes = (notes or "").strip()

        if not clean_notes:
            raise ValidationError({"notes": ("Transition notes are required.")})

        return clean_notes

    @staticmethod
    def _validate_active_window(
        market: Market,
    ) -> None:
        now = timezone.now()
        errors = {}

        if market.opens_at is None:
            errors["opens_at"] = "An opening time is required."
        elif market.opens_at > now:
            errors["opens_at"] = "The market opening time " "has not been reached."

        if market.closes_at is None:
            errors["closes_at"] = "A closing time is required."
        elif market.closes_at <= now:
            errors["closes_at"] = "The market trading window " "has already closed."

        if errors:
            raise ValidationError(errors)

    @classmethod
    def _apply_transition(
        cls,
        *,
        market: Market,
        actor,
        action: str,
        to_status: str,
        notes: str,
        market_updates: dict | None = None,
    ) -> Market:
        from_status = market.status

        for field_name, value in (market_updates or {}).items():
            setattr(
                market,
                field_name,
                value,
            )

        market.status = to_status
        market.full_clean()

        update_fields = {
            "status",
            "updated_at",
        }
        update_fields.update((market_updates or {}).keys())

        market.save(update_fields=sorted(update_fields))

        MarketStatusTransition.objects.create(
            market=market,
            action=action,
            from_status=from_status,
            to_status=to_status,
            actor=actor,
            actor_email=actor.email,
            notes=notes,
        )

        return market
