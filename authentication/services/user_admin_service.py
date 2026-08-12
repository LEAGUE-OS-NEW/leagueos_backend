import logging

from django.db import transaction

from accounts.models import User
from accounts.services.audit_service import AuditService
from accounts.services.email_service import EmailService
from authentication.models import Permission, Role, UserPermission
from authentication.services.account_setup_service import AccountSetupService
from authentication.services.delegation_service import DelegationService
from authentication.services.role_service import RoleService
from authentication.services.session_service import SessionService
from clubs.models import ClubWorkspace, WorkspaceMembership

logger = logging.getLogger(__name__)


class UserAdminService:
    """Service for administrator actions on user accounts."""

    @staticmethod
    @transaction.atomic
    def create_user(
        *,
        actor: User,
        email: str,
        first_name: str,
        last_name: str,
        role: Role,
        permissions: list[Permission] | None = None,
        workspaces: list[ClubWorkspace] | None = None,
    ) -> User:
        """Create a new subordinate user and send an invitation."""
        email = email.lower().strip()
        if User.objects.filter(email=email).exists():
            raise ValueError(f"A user with email {email} already exists.")

        # 1. Validate delegation rights
        if not DelegationService.can_delegate_role(actor, role):
            raise PermissionError(f"Admin {actor.email} cannot delegate role {role.name}.")

        for perm in permissions or []:
            if not DelegationService.can_delegate_permission(actor, perm):
                raise PermissionError(
                    f"Admin {actor.email} cannot delegate permission {perm.code}."
                )

        for workspace in workspaces or []:
            if not DelegationService.can_delegate_to_workspace(actor, workspace):
                raise PermissionError(
                    f"Admin {actor.email} cannot assign users to workspace {workspace.club.name}."
                )

        # 2. Create user in PENDING_INVITATION state
        user = User.objects.create(
            email=email,
            first_name=first_name,
            last_name=last_name,
            account_status=User.AccountStatus.PENDING_INVITATION,
            is_staff=True,  # All admin-created users are staff
        )

        # 3. Assign role, permissions, and workspaces
        RoleService.assign_role(user=user, role=role, assigned_by=actor)

        if permissions:
            for perm in permissions:
                UserPermission.objects.create(user=user, permission=perm, granted_by=actor)

        if workspaces:
            for workspace in workspaces:
                WorkspaceMembership.objects.create(
                    user=user, workspace=workspace, role="STAFF", added_by=actor
                )

        # 4. Create setup token and send invitation
        setup_token = AccountSetupService.create_setup_token(user)
        EmailService.send_account_setup_email(user, setup_token.token)

        # 5. Audit log
        AuditService.record(
            actor=actor,
            action="USER_CREATED",
            resource_type="user",
            resource_id=user.id,
            metadata={
                "target_user_id": str(user.id),
                "target_email": user.email,
                "role": role.name,
                "permissions": [p.code for p in permissions or []],
                "workspaces": [str(w.id) for w in workspaces or []],
            },
        )

        logger.info("Subordinate user %s created by %s", user.email, actor.email)
        return user

    @staticmethod
    def _change_account_status(*, actor: User, user: User, new_status: str, action: str) -> None:
        """Generic method to change a user's account status."""
        if not DelegationService.can_manage_user(actor, user):
            raise PermissionError(
                f"Admin {actor.email} does not have permission to manage user {user.email}."
            )

        if user.account_status == new_status:
            return

        old_status = user.account_status
        user.account_status = new_status
        user.save(update_fields=["account_status", "updated_at"])

        # Invalidate sessions for security-sensitive status changes
        if new_status in [
            User.AccountStatus.SUSPENDED,
            User.AccountStatus.DEACTIVATED,
        ]:
            SessionService.invalidate_user_sessions(user)

        AuditService.record(
            actor=actor,
            action=action,
            resource_type="user",
            resource_id=user.id,
            metadata={
                "target_user_id": str(user.id),
                "target_email": user.email,
            },
            previous_state={
                "account_status": old_status,
            },
            new_state={
                "account_status": new_status,
            },
        )
        logger.info(
            "User %s status changed from %s to %s by %s",
            user.email,
            old_status,
            new_status,
            actor.email,
        )

    @staticmethod
    def suspend_user(*, actor: User, user: User) -> None:
        """Suspend a user's account."""
        if user.is_superuser or user.id == actor.id:
            raise PermissionError("Cannot suspend a superuser or yourself.")
        UserAdminService._change_account_status(
            actor=actor,
            user=user,
            new_status=User.AccountStatus.SUSPENDED,
            action="ACCOUNT_SUSPENDED",
        )

    @staticmethod
    def deactivate_user(*, actor: User, user: User) -> None:
        """Deactivate a user's account."""
        if user.is_superuser or user.id == actor.id:
            raise PermissionError("Cannot deactivate a superuser or yourself.")
        UserAdminService._change_account_status(
            actor=actor,
            user=user,
            new_status=User.AccountStatus.DEACTIVATED,
            action="ACCOUNT_DEACTIVATED",
        )

    @staticmethod
    def activate_user(*, actor: User, user: User) -> None:
        """Activate a user's account from a suspended/deactivated state."""
        UserAdminService._change_account_status(
            actor=actor,
            user=user,
            new_status=User.AccountStatus.ACTIVE,
            action="ACCOUNT_REACTIVATED",
        )
