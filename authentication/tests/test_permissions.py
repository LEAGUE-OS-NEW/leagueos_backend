from django.core.management import call_command
from django.test import override_settings
from django.urls import path
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.test import APITestCase
from rest_framework.views import APIView

from authentication.models import Permission, Role, RolePermission
from authentication.permissions import HasPermission
from authentication.services.permission_service import PermissionService
from authentication.services.role_service import RoleService
from authentication.tests.factories import UserFactory


class ApproveMarketProtectedView(APIView):
    permission_classes = [
        permissions.IsAuthenticated,
        HasPermission,
    ]
    required_permission = "approve_market"

    def get(self, request):
        return Response(
            {
                "success": True,
                "message": "Market approval access granted.",
            },
            status=status.HTTP_200_OK,
        )


urlpatterns = [
    path(
        "test/approve-market/",
        ApproveMarketProtectedView.as_view(),
        name="test-approve-market",
    ),
]


@override_settings(ROOT_URLCONF=__name__)
class DatabaseBackedPermissionTests(APITestCase):
    def setUp(self):
        self.user = UserFactory(
            is_active=True,
            is_verified=True,
        )
        self.url = "/test/approve-market/"

    def test_unauthenticated_user_is_rejected(self):
        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
            response.data,
        )

    def test_authenticated_user_without_permission_is_forbidden(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
            response.data,
        )

    def test_user_with_database_permission_is_allowed(self):
        role = Role.objects.create(
            name="Market Approval Admin",
            display_name="Market Approval Admin",
            description="Approves markets.",
            dashboard_url="/admin/market-approval",
            is_system=True,
        )
        permission = Permission.objects.create(
            name="approve_market",
            resource="market",
            action="approve",
            description="Approve market items.",
        )

        RoleService.assign_role(
            user=self.user,
            role=role,
        )
        RolePermission.objects.create(
            role=role,
            permission=permission,
        )

        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

    def test_superuser_bypasses_role_assignment(self):
        superuser = UserFactory(
            is_staff=True,
            is_superuser=True,
            is_active=True,
            is_verified=True,
        )

        self.client.force_authenticate(user=superuser)

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

    def test_inactive_user_has_no_database_permissions(self):
        role = Role.objects.create(
            name="Market Approval Admin",
            display_name="Market Approval Admin",
        )
        permission = Permission.objects.create(
            name="approve_market",
            resource="market",
            action="approve",
        )

        RoleService.assign_role(
            user=self.user,
            role=role,
        )
        RolePermission.objects.create(
            role=role,
            permission=permission,
        )

        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        self.assertFalse(
            PermissionService.has_permission(
                self.user,
                "approve_market",
            )
        )

    def test_permission_names_are_returned_without_duplicates(self):
        first_role = Role.objects.create(
            name="First Approval Role",
            display_name="First Approval Role",
        )
        second_role = Role.objects.create(
            name="Second Approval Role",
            display_name="Second Approval Role",
        )
        permission = Permission.objects.create(
            name="approve_market",
            resource="market",
            action="approve",
        )

        RoleService.assign_role(self.user, first_role)
        RoleService.assign_role(self.user, second_role)

        RolePermission.objects.create(
            role=first_role,
            permission=permission,
        )
        RolePermission.objects.create(
            role=second_role,
            permission=permission,
        )

        permission_names = PermissionService.get_user_permissions(
            self.user,
        )

        self.assertEqual(
            permission_names,
            ["approve_market"],
        )


class RoleServiceTests(APITestCase):
    def test_get_user_roles_returns_role_objects(self):
        user = UserFactory()
        role = Role.objects.create(
            name="Fan",
            display_name="Fan",
        )

        RoleService.assign_role(user, role)

        roles = RoleService.get_user_roles(user)

        self.assertEqual(roles, [role])
        self.assertIsInstance(roles[0], Role)

    def test_highest_priority_role_returns_role_object(self):
        user = UserFactory()

        fan_role = Role.objects.create(
            name="Fan",
            display_name="Fan",
            dashboard_url="/fan",
        )
        market_admin_role = Role.objects.create(
            name="Market Operations Admin",
            display_name="Market Operations Admin",
            dashboard_url="/admin/market",
        )

        RoleService.assign_role(user, fan_role)
        RoleService.assign_role(user, market_admin_role)

        highest_role = RoleService.get_highest_priority_role(user)

        self.assertEqual(highest_role, market_admin_role)
        self.assertEqual(
            highest_role.dashboard_url,
            "/admin/market",
        )


class SeedRolesCommandTests(APITestCase):
    def test_seed_roles_creates_market_permission_mappings(self):
        call_command("seed_roles", verbosity=0)

        expected_mappings = {
            "Market Operations Admin": {
                "manage_market",
            },
            "Market Approval Admin": {
                "approve_market",
            },
            "Result Verification Admin": {
                "verify_results",
            },
            "Compliance Admin": {
                "manage_compliance",
            },
            "Finance Admin": {
                "manage_finance",
            },
            "Verified Market User": {
                "participate_market",
            },
        }

        for role_name, permission_names in expected_mappings.items():
            with self.subTest(role=role_name):
                actual_names = set(
                    RolePermission.objects.filter(
                        role__name=role_name,
                    ).values_list(
                        "permission__name",
                        flat=True,
                    )
                )

                self.assertTrue(
                    permission_names.issubset(actual_names),
                    {
                        "role": role_name,
                        "expected": permission_names,
                        "actual": actual_names,
                    },
                )

    def test_seed_roles_gives_super_admin_all_permissions(self):
        call_command("seed_roles", verbosity=0)

        all_permission_names = set(
            Permission.objects.values_list(
                "name",
                flat=True,
            )
        )
        super_admin_permission_names = set(
            RolePermission.objects.filter(
                role__name="Super Admin",
            ).values_list(
                "permission__name",
                flat=True,
            )
        )

        self.assertEqual(
            super_admin_permission_names,
            all_permission_names,
        )

    def test_seed_roles_is_idempotent(self):
        call_command("seed_roles", verbosity=0)

        first_role_count = Role.objects.count()
        first_permission_count = Permission.objects.count()
        first_mapping_count = RolePermission.objects.count()

        call_command("seed_roles", verbosity=0)

        self.assertEqual(
            Role.objects.count(),
            first_role_count,
        )
        self.assertEqual(
            Permission.objects.count(),
            first_permission_count,
        )
        self.assertEqual(
            RolePermission.objects.count(),
            first_mapping_count,
        )
