import logging
import secrets

from django.utils import timezone

from accounts.models import User
from authentication.models import AdminInvitation, Role

logger = logging.getLogger(__name__)


class InvitationService:
    @staticmethod
    def create_invitation(
        email: str,
        roles: list[Role],
        invited_by: User,
        expires_in_days: int = 7,
    ) -> AdminInvitation:
        email = email.lower().strip()

        duplicate = AdminInvitation.objects.filter(
            email=email,
            status=AdminInvitation.Status.PENDING,
        ).first()

        if duplicate:
            raise ValueError(
                f"A pending invitation already exists for {email}. "
                "Revoke the existing invitation before creating a new one."
            )

        token = secrets.token_urlsafe(32)
        expires_at = timezone.now() + timezone.timedelta(days=expires_in_days)

        invitation = AdminInvitation.objects.create(
            email=email,
            token=token,
            token_expires_at=expires_at,
            invited_by=invited_by,
        )
        invitation.assigned_roles.set(roles)

        logger.info(
            "Admin invitation created for %s by %s",
            email,
            invited_by.email,
        )

        return invitation

    @staticmethod
    def accept_invitation(token: str, user: User) -> AdminInvitation | None:
        invitation = (
            AdminInvitation.objects.select_related("invited_by")
            .prefetch_related("assigned_roles")
            .filter(token=token)
            .first()
        )

        if not invitation:
            logger.warning("Invitation not found for token: %s", token[:8])
            return None

        if invitation.is_expired:
            invitation.status = AdminInvitation.Status.EXPIRED
            invitation.save(update_fields=["status", "updated_at"])
            logger.warning("Expired invitation accepted: %s", invitation.id)
            return None

        if invitation.status != AdminInvitation.Status.PENDING:
            logger.warning("Non-pending invitation accepted: %s", invitation.id)
            return None

        invitation.status = AdminInvitation.Status.ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.accepted_by = user
        invitation.save(update_fields=["status", "accepted_at", "accepted_by", "updated_at"])

        from authentication.services.role_service import RoleService

        for role in invitation.assigned_roles.all():
            RoleService.assign_role(
                user=user,
                role=role,
                assigned_by=invitation.invited_by,
            )

        logger.info(
            "Invitation accepted by %s. Roles assigned: %s",
            user.email,
            list(invitation.assigned_roles.values_list("name", flat=True)),
        )

        return invitation

    @staticmethod
    def revoke_invitation(invitation: AdminInvitation, revoked_by: User) -> None:
        if invitation.status != AdminInvitation.Status.PENDING:
            raise ValueError("Only pending invitations can be revoked.")

        invitation.status = AdminInvitation.Status.REVOKED
        invitation.revoked_at = timezone.now()
        invitation.revoked_by = revoked_by
        invitation.save(update_fields=["status", "revoked_at", "revoked_by", "updated_at"])

        logger.info(
            "Invitation revoked for %s by %s",
            invitation.email,
            revoked_by.email,
        )

    @staticmethod
    def get_pending_invitations() -> list[AdminInvitation]:
        return list(
            AdminInvitation.objects.filter(status=AdminInvitation.Status.PENDING)
            .select_related("invited_by")
            .prefetch_related("assigned_roles")
            .order_by("-created_at")
        )

    @staticmethod
    def expire_old_invitations() -> int:
        expired = AdminInvitation.objects.filter(
            status=AdminInvitation.Status.PENDING,
            token_expires_at__lt=timezone.now(),
        )
        count = expired.update(status=AdminInvitation.Status.EXPIRED, updated_at=timezone.now())
        if count:
            logger.info("Expired %d old invitations", count)
        return count
