"""Staff service for club staff management."""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from clubs.models import ClubAuditLog, ClubWorkspace, StaffInvitation

logger = logging.getLogger(__name__)


class StaffService:
    """Service for staff management."""

    @staticmethod
    def invite_staff(club, email, role, invited_by, permissions=None):
        """Invite staff to club."""
        invitation = StaffInvitation.objects.create(
            club=club,
            email=email,
            role=role,
            permissions=permissions or [],
            token=secrets.token_urlsafe(32),
            expires_at=timezone.now() + timedelta(days=7),
            invited_by=invited_by,
        )

        ClubAuditLog.objects.create(
            club=club,
            user=invited_by,
            action="STAFF_INVITED",
            entity_type="StaffInvitation",
            entity_id=invitation.id,
            metadata={"email": email, "role": role},
        )

        return invitation

    @staticmethod
    def accept_invitation(token, user):
        """Accept staff invitation."""
        try:
            invitation = StaffInvitation.objects.get(token=token)
        except StaffInvitation.DoesNotExist as err:
            raise ValueError("Invalid invitation token.") from err

        if invitation.status != StaffInvitation.Status.PENDING:
            raise ValueError("Invitation is not pending.")

        if invitation.expires_at < timezone.now():
            invitation.status = StaffInvitation.Status.EXPIRED
            invitation.save(update_fields=["status"])
            raise ValueError("Invitation has expired.")

        with transaction.atomic():
            # Create or update workspace
            workspace, created = ClubWorkspace.objects.get_or_create(
                user=user,
                club=invitation.club,
                defaults={
                    "role": invitation.role,
                    "permissions": invitation.permissions,
                    "is_active": True,
                    "invited_by": invitation.invited_by,
                    "accepted_at": timezone.now(),
                },
            )

            if not created and not workspace.is_active:
                workspace.is_active = True
                workspace.accepted_at = timezone.now()
                workspace.save(update_fields=["is_active", "accepted_at"])

            invitation.status = StaffInvitation.Status.ACCEPTED
            invitation.accepted_by = user
            invitation.accepted_at = timezone.now()
            invitation.save(update_fields=["status", "accepted_by", "accepted_at"])

            ClubAuditLog.objects.create(
                club=invitation.club,
                user=user,
                action="ROLE_GRANTED",
                entity_type="ClubWorkspace",
                entity_id=workspace.id,
                metadata={"role": invitation.role},
            )

        return workspace

    @staticmethod
    def disable_staff(workspace, user, reason=""):
        """Disable staff workspace access."""
        if not workspace.is_active:
            return workspace

        workspace.is_active = False
        workspace.disabled_at = timezone.now()
        workspace.disabled_reason = reason
        workspace.save(update_fields=["is_active", "disabled_at", "disabled_reason"])

        ClubAuditLog.objects.create(
            club=workspace.club,
            user=user,
            action="STAFF_DISABLED",
            entity_type="ClubWorkspace",
            entity_id=workspace.id,
            metadata={"email": workspace.user.email, "reason": reason},
        )

        return workspace

    @staticmethod
    def remove_staff(workspace, user):
        """Remove staff from club."""
        club = workspace.club
        email = workspace.user.email

        workspace.delete()

        ClubAuditLog.objects.create(
            club=club,
            user=user,
            action="STAFF_DISABLED",
            entity_type="ClubWorkspace",
            metadata={"email": email, "action": "removed"},
        )

    @staticmethod
    def update_permissions(workspace, user, permissions):
        """Update staff permissions."""
        workspace.permissions = permissions
        workspace.save(update_fields=["permissions"])

        ClubAuditLog.objects.create(
            club=workspace.club,
            user=user,
            action="PERMISSION_CHANGED",
            entity_type="ClubWorkspace",
            entity_id=workspace.id,
            metadata={"permissions": permissions},
        )

        return workspace


staff_service = StaffService()
