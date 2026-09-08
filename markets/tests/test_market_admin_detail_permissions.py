from datetime import timedelta

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from authentication.tests.factories import (
    PermissionFactory,
    RoleFactory,
    RolePermissionFactory,
    UserFactory,
    UserRoleFactory,
)
from markets.tests.test_result_verification_queue_api import (
    ResultVerificationQueueFixtureMixin,
)


class MarketAdminDetailPermissionTests(ResultVerificationQueueFixtureMixin, APITestCase):
    """A "verify_results"-only actor (e.g. a Result Verification Admin) must
    be able to read a market's detail via the admin GET endpoint — it's a
    prerequisite step in publishing a provisional result (see
    resultVerificationService.ts::verifyResult), even though they don't hold
    manage_market/approve_market."""

    def authenticate(self, user):
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def detail_url(self, market):
        return reverse("markets:admin-market-detail", kwargs={"market_id": market.id})

    def test_verify_results_only_actor_can_read_market_detail(self):
        verify_permission = PermissionFactory(
            name="verify_results", resource="market", action="verify"
        )
        result_role = RoleFactory(name="Detail API Result Verifier")
        RolePermissionFactory(role=result_role, permission=verify_permission)
        result_actor = UserFactory()
        UserRoleFactory(user=result_actor, role=result_role)

        market = self.create_market(opens_at=self.now, closes_at=self.now + timedelta(hours=1))

        self.authenticate(result_actor)
        response = self.client.get(self.detail_url(market))

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_actor_with_no_relevant_permission_is_forbidden(self):
        market = self.create_market(opens_at=self.now, closes_at=self.now + timedelta(hours=1))
        bystander = UserFactory()

        self.authenticate(bystander)
        response = self.client.get(self.detail_url(market))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_write_access_still_requires_manage_market(self):
        verify_permission = PermissionFactory(
            name="verify_results", resource="market", action="verify"
        )
        result_role = RoleFactory(name="Detail API Result Verifier Write Check")
        RolePermissionFactory(role=result_role, permission=verify_permission)
        result_actor = UserFactory()
        UserRoleFactory(user=result_actor, role=result_role)

        market = self.create_market(opens_at=self.now, closes_at=self.now + timedelta(hours=1))

        self.authenticate(result_actor)
        response = self.client.patch(
            self.detail_url(market), {"question": "Changed?"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
