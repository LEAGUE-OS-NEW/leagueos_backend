"""Membership service for club membership management."""

from __future__ import annotations

import logging

from django.utils import timezone

from clubs.models import ClubAuditLog, Membership, MembershipPlan

logger = logging.getLogger(__name__)


class MembershipService:
    """Service for membership operations."""

    @staticmethod
    def create_plan(club, user, **kwargs):
        """Create a new membership plan."""
        plan = MembershipPlan.objects.create(
            club=club,
            created_by=user,
            **kwargs,
        )

        ClubAuditLog.objects.create(
            club=club,
            user=user,
            action="MEMBERSHIP_CREATED",
            entity_type="MembershipPlan",
            entity_id=plan.id,
            metadata={"name": plan.name, "price": str(plan.price)},
        )

        return plan

    @staticmethod
    def publish_plan(plan, user):
        """Publish a membership plan."""
        if plan.status == MembershipPlan.Status.ACTIVE:
            return plan

        plan.status = MembershipPlan.Status.ACTIVE
        plan.published_at = timezone.now()
        plan.published_by = user
        plan.save(update_fields=["status", "published_at", "published_by"])

        ClubAuditLog.objects.create(
            club=plan.club,
            user=user,
            action="MEMBERSHIP_CREATED",
            entity_type="MembershipPlan",
            entity_id=plan.id,
            metadata={"action": "published", "name": plan.name},
        )

        return plan

    @staticmethod
    def create_membership(user, plan):
        """Create user membership from plan."""
        now = timezone.now()
        expires_at = now + timezone.timedelta(days=plan.duration_days)

        membership = Membership.objects.create(
            user=user,
            plan=plan,
            status=Membership.Status.ACTIVE,
            starts_at=now,
            expires_at=expires_at,
        )

        ClubAuditLog.objects.create(
            club=plan.club,
            user=user,
            action="MEMBERSHIP_CREATED",
            entity_type="Membership",
            entity_id=membership.id,
            metadata={"plan": plan.name},
        )

        return membership


membership_service = MembershipService()
