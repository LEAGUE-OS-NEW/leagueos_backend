from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from accounts.models import AuditLog
from authentication.models import Role, UserRole
from kyc.models import KYCCheckResult, KYCVerification

User = get_user_model()


class KYCDevelopmentBypassTests(APITestCase):
    url = "/api/v1/fans/kyc/dev-bypass/"

    def setUp(self):
        self.fan = User.objects.create_user(
            username="synthetic-fan", email="synthetic-fan@leagueos.test"
        )

    def authenticate(self, user=None):
        self.client.force_authenticate(user or self.fan)

    @override_settings(DEBUG=False, DEV_KYC_BYPASS_ENABLED=True)
    def test_unavailable_outside_debug(self):
        self.authenticate()
        self.assertEqual(self.client.post(self.url).status_code, 404)

    @override_settings(DEBUG=True, DEV_KYC_BYPASS_ENABLED=False)
    def test_unavailable_when_flag_is_off(self):
        self.authenticate()
        self.assertEqual(self.client.post(self.url).status_code, 404)

    @override_settings(DEBUG=True, DEV_KYC_BYPASS_ENABLED=True)
    def test_unauthenticated_is_denied(self):
        self.assertIn(self.client.post(self.url).status_code, (401, 403))

    @override_settings(DEBUG=True, DEV_KYC_BYPASS_ENABLED=True)
    def test_non_synthetic_email_is_unavailable(self):
        user = User.objects.create_user(username="real-fan", email="fan@example.com")
        self.authenticate(user)
        self.assertEqual(self.client.post(self.url).status_code, 404)

    @override_settings(DEBUG=False, REVIEW_WORKFLOW_TOOLS_ENABLED=True)
    def test_review_flag_still_rejects_non_synthetic_email(self):
        user = User.objects.create_user(username="ordinary-fan", email="fan@example.com")
        self.authenticate(user)
        self.assertEqual(self.client.post(self.url).status_code, 404)

    @override_settings(DEBUG=False, REVIEW_WORKFLOW_TOOLS_ENABLED=True)
    def test_review_flag_allows_only_authenticated_synthetic_fan(self):
        self.authenticate()
        self.assertEqual(self.client.post(self.url).status_code, 200)

    @override_settings(DEBUG=True, DEV_KYC_BYPASS_ENABLED=True)
    def test_synthetic_fan_is_audited_and_canonically_synchronized(self):
        other = User.objects.create_user(username="other", email="other@leagueos.test")
        self.authenticate()

        response = self.client.post(self.url, {"user_id": str(other.id)}, format="json")

        self.assertEqual(response.status_code, 200)
        verification = KYCVerification.objects.get(user=self.fan)
        self.assertEqual(verification.status, KYCVerification.Status.VERIFIED)
        self.assertEqual(
            verification.verification_source,
            KYCVerification.VerificationSource.DEVELOPMENT_BYPASS,
        )
        self.assertFalse(KYCVerification.objects.filter(user=other).exists())
        verification.refresh_from_db()
        self.assertEqual(verification.status, KYCVerification.Status.VERIFIED)
        self.fan.refresh_from_db()
        self.assertTrue(self.fan.is_verified)
        self.assertFalse(KYCCheckResult.objects.filter(kyc_verification=verification).exists())
        audit = AuditLog.objects.get(resource_id=verification.id, action="KYC_VERIFIED")
        self.assertEqual(audit.metadata["verification_source"], "DEVELOPMENT_BYPASS")

    @override_settings(DEBUG=True, DEV_KYC_BYPASS_ENABLED=True)
    def test_synthetic_fan_is_granted_verified_market_user_role(self):
        role = Role.objects.create(name="Verified Market User", display_name="Verified Market User")
        self.authenticate()

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(UserRole.objects.filter(user=self.fan, role=role, is_active=True).exists())

    @override_settings(DEBUG=True, DEV_KYC_BYPASS_ENABLED=True)
    def test_bypass_does_not_500_when_verified_market_user_role_is_unseeded(self):
        self.assertFalse(Role.objects.filter(name="Verified Market User").exists())
        self.authenticate()

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 200)
