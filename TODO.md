# League OS Admin, Role, Permission, Club Workspace & Subordinate User Management

## Goal
Implement production-ready, database-backed administrator hierarchy, granular RBAC,
club workspace security, subordinate user account management, invitation/setup flow,
password change/reset, delegation rules and comprehensive audit + test coverage.

## Reuse (do NOT duplicate)
- `accounts.User`, `authentication.Role/Permission/RolePermission/UserRole/AdminInvitation/UserSession`
- `RoleService`, `PermissionService`, `InvitationService`, `SessionService`,
  `PasswordResetService`, `EmailService`, `AuditService`, `TokenService`, `AuthenticationService`
- `platform_admin` app views/serializers, `seed_roles` command
- `clubs.ClubWorkspace/StaffInvitation`, `ClubWorkspaceService`, `StaffService`, `profiles.Club`

## Steps
- [ ] 1. Reconcile broken migration state: add `AccountSetupToken` + `UserPermission` to
       `authentication/models.py` (match applied migration 0004). No destructive migration.
- [ ] 2. Extend `Permission` with `code`, `category`, `scope`, `active`, `delegatable`.
- [ ] 3. Extend `Role` with `scope`, `category` (platform/club) for delegation.
- [ ] 4. Add `AccountStatus` field to `accounts.User`
       (PENDING_INVITATION/ACTIVE/SUSPENDED/DEACTIVATED/INVITATION_EXPIRED).
- [ ] 5. Create new non-destructive migrations for models and run migrate.
- [ ] 6. Update `PermissionService` to union role permissions + direct user permissions
       (`UserPermission`) and expose delegation helpers.
- [ ] 7. Extend `seed_roles` with full club roles + granular `club.*` permissions and
       platform permissions (category/scope/delegatable metadata).
- [ ] 8. Extend `InvitationService`/`AccountSetupService` to support workspace + permission
       assignment and secure single-use setup tokens.
- [ ] 9. Add `DelegationService` for server-side role/permission delegation validation.
- [ ] 10. Add `UserAdminService` for user creation, lifecycle (activate/suspend/deactivate),
        permission grant/revoke, workspace assignment, audit logging.
- [ ] 11. Add `POST /api/v1/auth/change-password/` endpoint + serializer + service.
- [ ] 12. Add platform_admin serializers: create user, permission grant/revoke,
        available roles/permissions, lifecycle, workspace.
- [ ] 13. Add platform_admin views + urls: available-roles, available-permissions,
        create user, user permissions CRUD, activate/suspend/deactivate.
- [x] 14. Add `bootstrap_admins` management command (idempotent, env overrides, dev-only fallback).
- [ ] 15. Add comprehensive pytest coverage (bootstrap, super admin, club admin,
        subordinate, password, invitation, security, audit).
- [ ] 16. Run `python manage.py check`, `makemigrations --check`, `migrate`.
- [ ] 17. Run `ruff check --no-cache .` and `black --check --diff .`, fix issues.
- [ ] 18. Validate OpenAPI schema generation.
- [ ] 19. Run pytest and fix failures (report pre-existing unrelated failures separately).
- [ ] 20. Review git diff (no credentials, no hard-coded IDs, no unrelated changes).
