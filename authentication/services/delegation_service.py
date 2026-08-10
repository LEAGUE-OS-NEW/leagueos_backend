import logging

from django.db import models
from accounts.models import User
from authentication.models import Permission, Role
from authentication.services.permission_service import PermissionService
from authentication.services.role_service import RoleService
from clubs.models import ClubWorkspace, WorkspaceMembership

logger = logging.getLogger(__name__)


class DelegationService:
    """Validates if an administrator can delegate roles and permissions."""

    @staticmethod
    def can_delegate_role(admin: User, target_role: Role) -> bool:
        """Check if an admin can assign a specific role.

        Rules:
        1. The target role must exist and be assignable.
        2. A Super Admin can delegate any non-Super Admin role.
        3. A Club Admin can only delegate club-scoped roles.
        4. No admin can create another Super Admin.
        """
        if target_role.name == "Super Admin":
            return False

        admin_roles = RoleService.get_user_roles(admin)
        is_super_admin = any(r.name == "Super Admin" for r in admin_roles)

        if is_super_admin:
            return True

        is_club_admin = any(r.name == "Club Admin" for r in admin_roles)
        if is_club_admin:
            # Club Admins can only delegate roles with CLUB scope.
            return target_role.scope == Role.Scope.CLUB

        # Other admin roles might have specific delegation rules in the future.
        # For now, we deny by default.
        return False

    @staticmethod
    def can_delegate_permission(admin: User, permission: Permission) -> bool:
        """Check if an admin can grant a specific permission.

        Rules:
        1. The permission must be active and delegatable.
        2. The admin must possess the permission they are trying to delegate.
        3. A Club Admin cannot delegate platform-scoped permissions.
        """
        if not permission.active or not permission.delegatable:
            return False

        # Admin must have the permission to be able to delegate it.
        if not PermissionService.has_permission(admin, permission.code):
            return False

        admin_roles = RoleService.get_user_roles(admin)
        is_club_admin = any(r.name == "Club Admin" for r in admin_roles)

        if is_club_admin and permission.scope == Permission.Scope.PLATFORM:
            return False

        return True

    @staticmethod
    def get_manageable_workspaces(admin: User) -> models.QuerySet[ClubWorkspace]:
        """Get the workspaces an admin has authority over."""
        admin_roles = RoleService.get_user_roles(admin)
        is_super_admin = any(r.name == "Super Admin" for r in admin_roles)

        if is_super_admin:
            return ClubWorkspace.objects.all()

        # For other admins (like Club Admin), they can manage workspaces they are members of.
        return ClubWorkspace.objects.filter(
            workspace_memberships__user=admin,
            workspace_memberships__role__in=["ADMIN", "STAFF"],  # Assuming these roles grant management
        ).distinct()

    @staticmethod
    def can_delegate_to_workspace(admin: User, workspace: ClubWorkspace) -> bool:
        """Check if an admin can assign a user to a specific workspace.

        Rules:
        1. A Super Admin can assign to any workspace.
        2. A Club Admin can only assign to workspaces they are a member of.
        """
        admin_roles = RoleService.get_user_roles(admin)
        is_super_admin = any(r.name == "Super Admin" for r in admin_roles)

        if is_super_admin:
            return True

        return DelegationService.get_manageable_workspaces(admin).filter(id=workspace.id).exists()

    @staticmethod
    def can_manage_user(actor: User, target_user: User) -> bool:
        """Check if an admin can manage a target user.

        Rules:
        1. An admin cannot manage themselves.
        2. No one can manage a superuser.
        3. A Super Admin can manage any non-superuser.
        4. A Club Admin can only manage users who are members of at least one
           of the Club Admin's manageable workspaces.
        """
        if actor.id == target_user.id:
            return False

        if target_user.is_superuser:
            return False

        actor_roles = RoleService.get_user_roles(actor)
        is_super_admin = any(r.name == "Super Admin" for r in actor_roles)

        if is_super_admin:
            return True

        manageable_workspaces = DelegationService.get_manageable_workspaces(actor)
        return target_user.workspace_memberships.filter(workspace__in=manageable_workspaces).exists()

    @staticmethod
    def get_delegatable_roles(admin: User) -> list[Role]:
        """Get a list of roles an admin is allowed to delegate."""
        all_roles = Role.objects.filter(is_system=False).order_by("name")
        return [role for role in all_roles if DelegationService.can_delegate_role(admin, role)]

    @staticmethod
    def get_delegatable_permissions(admin: User) -> list[Permission]:
        """Get a list of permissions an admin is allowed to delegate."""
        # Start with permissions the admin possesses.
        admin_perms = PermissionService.get_user_permissions(admin)
        
        # An admin can only delegate permissions they have, which are active and delegatable.
        delegatable_perms = Permission.objects.filter(
            code__in=admin_perms,
            active=True,
            delegatable=True
        ).order_by("category", "name")

        admin_roles = RoleService.get_user_roles(admin)
        is_club_admin = any(r.name == "Club Admin" for r in admin_roles)

        # Further filter for Club Admins to prevent platform perm delegation.
        if is_club_admin:
            delegatable_perms = delegatable_perms.filter(scope=Permission.Scope.CLUB)

        return list(delegatable_perms)