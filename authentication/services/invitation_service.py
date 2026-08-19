import logging
import secrets

from django.db import transaction
from django.utils import timezone

from accounts.models import User
from authentication.models import AccountSetupToken, AdminInvitation, Role

logger = logging.getLogger(__name__)


class InvitationService:
    @staticmethod
    @transaction.atomic
    def create_invitation(
        login_email: str,
        notify_email: str,
        roles: list[Role],
        invited_by: User,
        expires_in_days: int = 7,
    ) -> AdminInvitation:
        """Invite a platform-role admin (Compliance, Finance, Sports Data,
        Super Admin, etc). Mirrors ClubAdminInvitationService.invite()'s
        three branches, since login_email (the LeagueOS identity assigned to
        this role) and notify_email (the real inbox the invite is actually
        delivered to) are no longer assumed to be the same address:

        - No user exists at login_email yet -> create one PENDING_INVITATION,
          issue an AccountSetupToken, email the setup link to notify_email.
          The AdminInvitation row is still created (status=PENDING) so
          AccountSetupCompleteView has something to find by email and grant
          once the password is set.
        - User exists and is still PENDING_INVITATION (resend) -> reuse the
          existing pending AdminInvitation, revoke any unused setup tokens,
          issue and send a fresh one.
        - User exists and is already ACTIVE -> today's behavior: the
          AdminInvitation + its own token, emailed via ADMIN_INVITE_URL, now
          delivered to notify_email instead of login_email. Blocks a second
          invite while one is still pending, same as before.
        """
        login_email = login_email.lower().strip()
        notify_email = notify_email.lower().strip()

        from accounts.services.email_service import EmailService

        user = User.objects.filter(email=login_email).first()

        if user is not None and user.account_status == User.AccountStatus.ACTIVE:
            duplicate = AdminInvitation.objects.filter(
                email=login_email,
                status=AdminInvitation.Status.PENDING,
            ).first()
            if duplicate:
                raise ValueError(
                    f"A pending invitation already exists for {login_email}. "
                    "Revoke the existing invitation before creating a new one."
                )

            token = secrets.token_urlsafe(32)
            expires_at = timezone.now() + timezone.timedelta(days=expires_in_days)
            invitation = AdminInvitation.objects.create(
                email=login_email,
                token=token,
                token_expires_at=expires_at,
                invited_by=invited_by,
            )
            invitation.assigned_roles.set(roles)
            try:
                EmailService.send_admin_invitation_email(invitation, deliver_to=notify_email)
            except Exception:
                logger.exception("Failed to send admin invitation email to %s", notify_email)

            logger.info(
                "Admin invitation created for existing active user %s (notify: %s) by %s",
                login_email,
                notify_email,
                invited_by.email,
            )
            return invitation

        # No user yet, or still PENDING_INVITATION — mirror
        # ClubAdminInvitationService.invite(): reuse an existing pending
        # AdminInvitation for this login instead of erroring, since this is
        # the resend case, not a genuine duplicate.
        invitation = (
            AdminInvitation.objects.filter(
                email=login_email,
                status=AdminInvitation.Status.PENDING,
            )
            .order_by("-created_at")
            .first()
        )
        if invitation is None:
            token = secrets.token_urlsafe(32)
            expires_at = timezone.now() + timezone.timedelta(days=expires_in_days)
            invitation = AdminInvitation.objects.create(
                email=login_email,
                token=token,
                token_expires_at=expires_at,
                invited_by=invited_by,
            )
            invitation.assigned_roles.set(roles)

        from accounts.services.username_service import UsernameService
        from authentication.services.account_setup_service import AccountSetupService

        if user is None:
            user = User.objects.create(
                email=login_email,
                username=UsernameService.generate_unique_username(email=login_email),
                account_status=User.AccountStatus.PENDING_INVITATION,
                is_staff=True,
            )
        else:
            AccountSetupToken.objects.filter(user=user, used_at__isnull=True).update(
                used_at=timezone.now()
            )

        setup_token = AccountSetupService.create_setup_token(user, expires_in_days)
        try:
            EmailService.send_admin_invitation_setup_email(
                user=user,
                setup_token=setup_token.token,
                deliver_to=notify_email,
                role_names=[role.display_name for role in roles],
            )
        except Exception:
            logger.exception("Failed to send admin invitation setup email to %s", notify_email)

        logger.info(
            "Admin invitation created for %s (notify: %s) by %s",
            login_email,
            notify_email,
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
