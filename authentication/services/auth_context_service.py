from authentication.models import RolePermission
from authentication.services.role_service import RoleService

# Maps backend Role.name strings to the frontend's DashboardIdentifier values.
# The frontend validates dashboard_access entitlements against this exact set:
# FAN, CLUB_ADMIN, TICKETING_OFFICER, SPORTS_DATA_STATISTICS_ADMIN,
# MARKET_OPERATIONS_ADMIN, RESULT_VERIFICATION_ADMIN, COMPLIANCE_ADMIN,
# FINANCE_ADMIN, CUSTOMER_SUPPORT_ADMIN, SUPER_ADMIN
# (see src/types/dashboardAccess.ts DASHBOARD_IDENTIFIERS).
_ROLE_NAME_TO_DASHBOARD_IDENTIFIER = {
    "Super Admin": "SUPER_ADMIN",
    "Sports Data & Statistics Admin": "SPORTS_DATA_STATISTICS_ADMIN",
    "Market Operations & Approval Admin": "MARKET_OPERATIONS_ADMIN",
    "Result Verification Admin": "RESULT_VERIFICATION_ADMIN",
    "Compliance Admin": "COMPLIANCE_ADMIN",
    "Finance Admin": "FINANCE_ADMIN",
    "Customer Support Admin": "CUSTOMER_SUPPORT_ADMIN",
    "Club Admin": "CLUB_ADMIN",
    "Club Specialist Staff": "CLUB_ADMIN",
    "Fan": "FAN",
}

# Maps DashboardIdentifier → canonical frontend dashboard route.
# All admin-side identifiers share the unified admin shell at /dashboard/admin.
_DASHBOARD_IDENTIFIER_TO_ROUTE = {
    "SUPER_ADMIN": "/dashboard/admin",
    "SPORTS_DATA_STATISTICS_ADMIN": "/dashboard/admin",
    "MARKET_OPERATIONS_ADMIN": "/dashboard/admin",
    "RESULT_VERIFICATION_ADMIN": "/dashboard/admin",
    "COMPLIANCE_ADMIN": "/dashboard/admin",
    "FINANCE_ADMIN": "/dashboard/admin",
    "CUSTOMER_SUPPORT_ADMIN": "/dashboard/admin",
    "CLUB_ADMIN": "/dashboard/club-admin",
    "FAN": "/dashboard/fan",
}


class AuthContextService:
    """Build the single authenticated-user contract used by auth endpoints."""

    @staticmethod
    def _build_dashboard_access(roles, permissions_by_role_id: dict) -> dict:
        """
        Build the dashboard_access contract that the frontend's
        validateDashboardAccess() accepts.

        Shape required by the frontend (src/utils/dashboardAccess.ts):
          {
            version: 1,
            default_entitlement_id: "<string>",
            entitlements: [
              {
                id: "<string>",
                dashboard: "<DashboardIdentifier>",
                route: "<string starting with />",
                scope_type: null,
                scope_id: null,
                workspace_role: null,
                permissions: ["<string>", ...],
              }
            ]
          }
        """
        entitlements = []
        seen_dashboards: set[str] = set()

        for role in roles:
            dashboard = _ROLE_NAME_TO_DASHBOARD_IDENTIFIER.get(role.name)
            if not dashboard:
                # Roles without a frontend dashboard (e.g. Visitor, Ticket
                # Holder) produce no entitlement — the frontend has no route
                # for them.
                continue
            # Deduplicate: multiple roles that map to the same dashboard
            # (e.g. Club Admin + Club Specialist Staff → CLUB_ADMIN) only
            # produce one entitlement.  The first (highest-priority) wins.
            if dashboard in seen_dashboards:
                continue
            seen_dashboards.add(dashboard)

            route = _DASHBOARD_IDENTIFIER_TO_ROUTE.get(dashboard, "")
            entitlement_id = f"{dashboard.lower()}-{str(role.id)[:8]}"
            role_permissions = permissions_by_role_id.get(role.id, [])

            entitlements.append(
                {
                    "id": entitlement_id,
                    "dashboard": dashboard,
                    "route": route,
                    "scope_type": None,
                    "scope_id": None,
                    "workspace_role": None,
                    "permissions": role_permissions,
                }
            )

        if not entitlements:
            return {
                "version": 1,
                "default_entitlement_id": None,
                "entitlements": [],
            }

        # Prefer the highest-priority admin entitlement as the default;
        # fall back to the first one.
        priority_order = [
            "SUPER_ADMIN",
            "SPORTS_DATA_STATISTICS_ADMIN",
            "MARKET_OPERATIONS_ADMIN",
            "RESULT_VERIFICATION_ADMIN",
            "COMPLIANCE_ADMIN",
            "FINANCE_ADMIN",
            "CUSTOMER_SUPPORT_ADMIN",
            "CLUB_ADMIN",
            "FAN",
        ]
        default_entitlement = next(
            (e for p in priority_order for e in entitlements if e["dashboard"] == p),
            entitlements[0],
        )

        return {
            "version": 1,
            "default_entitlement_id": default_entitlement["id"],
            "entitlements": entitlements,
        }

    @staticmethod
    def user_context(user) -> dict:
        roles = RoleService.get_user_roles(user)
        role_ids = [role.id for role in roles]

        # Fetch all permissions for this user's roles in one query, grouped
        # by role id so _build_dashboard_access can embed them per-entitlement.
        raw_perms = (
            RolePermission.objects.filter(role_id__in=role_ids)
            .values("role_id", "permission__name")
            .order_by("permission__name")
        )
        permissions_by_role_id: dict = {}
        all_permissions: set[str] = set()
        for row in raw_perms:
            permissions_by_role_id.setdefault(row["role_id"], []).append(row["permission__name"])
            all_permissions.add(row["permission__name"])

        permissions = sorted(all_permissions)
        onboarding = getattr(user, "onboarding", None)
        kyc = getattr(user, "kyc_verification", None)
        kyc_status = kyc.status if kyc else "NOT_STARTED"

        return {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone_number": user.phone_number,
            "is_verified": user.is_verified,
            "kyc_status": kyc_status,
            "roles": [role.name for role in roles],
            "permissions": permissions,
            "club": AuthContextService._active_club(user),
            "dashboard_access": AuthContextService._build_dashboard_access(
                roles, permissions_by_role_id
            ),
            "onboarding": {
                "completed": bool(onboarding and onboarding.completed),
                "current_step": onboarding.current_step if onboarding else None,
            },
        }

    @staticmethod
    def _active_club(user) -> dict | None:
        """The frontend's legacy dashboard-access fallback (authStore.ts's
        getLegacyClubId) already expects to read user.club.id — it just
        never had a real value to read, and defaulted to a hardcoded demo
        club instead. Populate it from the user's active ClubWorkspace."""
        from clubs.models import ClubWorkspace

        workspace = (
            ClubWorkspace.objects.filter(user=user, is_active=True).select_related("club").first()
        )
        if not workspace:
            return None
        return {"id": str(workspace.club.id), "name": workspace.club.name}

    @classmethod
    def authenticated_data(cls, user, access=None, refresh=None) -> dict:
        data = {"user": cls.user_context(user)}
        if access is not None:
            data["access"] = access
        if refresh is not None:
            data["refresh"] = refresh
        return data
