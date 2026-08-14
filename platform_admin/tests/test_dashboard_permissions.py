import pytest
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APIClient

from authentication.models import Role, UserRole
from platform_admin.tests.factories import UserFactory


@pytest.mark.django_db
class TestAdminDashboardPermissions:
    @pytest.fixture(autouse=True)
    def seed(self):
        call_command("seed_roles", verbosity=0)
        self.client = APIClient()

    def response_for(self, role_name):
        user = UserFactory()
        role = Role.objects.get(name=role_name)
        UserRole.objects.create(user=user, role=role)
        self.client.force_authenticate(user)
        return self.client.get(reverse("platform_admin:dashboard-summary"))

    def test_market_operations_receives_only_market_summary(self):
        response = self.response_for("Market Operations & Approval Admin")
        assert response.status_code == 200
        assert {"pending_markets", "published_markets", "suspended_markets"} <= set(response.data)
        assert "active_administrators" not in response.data
        assert "role_distribution" not in response.data

    def test_result_verification_receives_result_summary_only(self):
        response = self.response_for("Result Verification Admin")
        assert response.status_code == 200
        assert set(response.data) == {"pending_result_verification"}

    def test_compliance_receives_compliance_summary_only(self):
        response = self.response_for("Compliance Admin")
        assert response.status_code == 200
        assert set(response.data) == {"compliance_cases"}

    def test_super_admin_retains_full_summary(self):
        response = self.response_for("Super Admin")
        assert response.status_code == 200
        expected = {
            "active_administrators",
            "role_distribution",
            "pending_markets",
            "pending_result_verification",
            "compliance_cases",
        }
        assert expected <= set(response.data)

    def test_role_without_dashboard_permission_is_forbidden(self):
        response = self.response_for("Fan")
        assert response.status_code == 403
