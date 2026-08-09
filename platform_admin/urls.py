from django.urls import path

from platform_admin.views import (
    AdminAuditLogListView,
    AdminDashboardSummaryView,
    AdminInvitationListView,
    AdminInvitationRevokeView,
    AdminMePermissionsView,
    AdminMeRolesView,
    AdminMeView,
    AdminPermissionListView,
    AdminRoleDetailView,
    AdminRoleListView,
    AdminUserDetailView,
    AdminUserListView,
    AdminUserRoleAssignView,
    AdminUserRoleListView,
    AdminUserRoleRevokeView,
)

app_name = "platform_admin"

urlpatterns = [
    path("me/", AdminMeView.as_view(), name="me"),
    path("me/roles/", AdminMeRolesView.as_view(), name="me-roles"),
    path("me/permissions/", AdminMePermissionsView.as_view(), name="me-permissions"),
    path("users/", AdminUserListView.as_view(), name="user-list"),
    path("users/<uuid:user_id>/", AdminUserDetailView.as_view(), name="user-detail"),
    path("users/<uuid:user_id>/roles/", AdminUserRoleListView.as_view(), name="user-role-list"),
    path(
        "users/<uuid:user_id>/roles/assign/",
        AdminUserRoleAssignView.as_view(),
        name="user-role-assign",
    ),
    path(
        "users/<uuid:user_id>/roles/<uuid:role_id>/",
        AdminUserRoleRevokeView.as_view(),
        name="user-role-revoke",
    ),
    path("roles/", AdminRoleListView.as_view(), name="role-list"),
    path("roles/<uuid:role_id>/", AdminRoleDetailView.as_view(), name="role-detail"),
    path("permissions/", AdminPermissionListView.as_view(), name="permission-list"),
    path("invitations/", AdminInvitationListView.as_view(), name="invitation-list"),
    path(
        "invitations/<uuid:invitation_id>/revoke/",
        AdminInvitationRevokeView.as_view(),
        name="invitation-revoke",
    ),
    path("audit/", AdminAuditLogListView.as_view(), name="audit-list"),
    path("dashboard/", AdminDashboardSummaryView.as_view(), name="dashboard-summary"),
]
