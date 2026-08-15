from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import AuditLog
from authentication.tests.factories import (
    PermissionFactory,
    RoleFactory,
    RolePermissionFactory,
    UserFactory,
    UserRoleFactory,
)
from markets.models import (
    MarketComplianceReview,
    MarketParticipantCompliance,
)
from markets.services.compliance_service import MarketComplianceService
from markets.tests.eligibility_test_support import make_market_eligible
from wallets.models import Wallet


class MarketComplianceAPITests(APITestCase):
    def setUp(self):
        self.participant = UserFactory()
        self.admin = UserFactory()
        permission = PermissionFactory(
            name="manage_compliance", resource="compliance", action="manage"
        )
        role = RoleFactory(name="Compliance Admin")
        RolePermissionFactory(role=role, permission=permission)
        UserRoleFactory(user=self.admin, role=role)

    def test_participant_read_is_private_and_non_mutating(self):
        url = reverse("markets:market-participant-eligibility")
        self.assertEqual(self.client.get(url).status_code, 401)
        self.client.force_authenticate(self.participant)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["eligible"])
        self.assertNotIn("internal_review_notes", response.data)
        self.assertNotIn("reviewed_by", response.data)
        self.assertFalse(MarketParticipantCompliance.objects.exists())
        self.assertFalse(AuditLog.objects.exists())
        self.assertFalse(Wallet.objects.exists())

    def test_admin_permission_patch_validation_audit_and_noop(self):
        url = reverse(
            "markets:admin-participant-compliance-detail", kwargs={"user_id": self.participant.id}
        )
        self.client.force_authenticate(self.participant)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(
            self.client.patch(url, {"jurisdiction_override": "ALLOW"}, format="json").status_code,
            400,
        )
        response = self.client.patch(
            url,
            {
                "jurisdiction_override": "ALLOW",
                "jurisdiction_override_reason": "Approved residence evidence.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        compliance = MarketParticipantCompliance.objects.get(participant=self.participant)
        self.assertEqual(compliance.reviewed_by, self.admin)
        self.assertIsNotNone(compliance.reviewed_at)
        self.assertEqual(MarketComplianceReview.objects.count(), 1)
        self.client.patch(url, {"jurisdiction_override": "ALLOW"}, format="json")
        self.assertEqual(MarketComplianceReview.objects.count(), 1)
        self.assertEqual(
            MarketParticipantCompliance.objects.filter(participant=self.participant).count(), 1
        )
        self.assertEqual(
            set(response.data),
            {
                "participant_id",
                "eligible",
                "evaluated_at",
                "requirements",
                "reason_codes",
                "next_actions",
                "date_of_birth",
                "reviewed_at",
                "reviewed_by",
                "jurisdiction_override_reason",
                "internal_review_notes",
            },
        )

    def test_review_list_is_admin_only_and_paginated(self):
        make_market_eligible(self.participant)
        detail = reverse(
            "markets:admin-participant-compliance-detail", kwargs={"user_id": self.participant.id}
        )
        reviews = reverse(
            "markets:admin-participant-compliance-reviews", kwargs={"user_id": self.participant.id}
        )
        self.client.force_authenticate(self.admin)
        self.client.patch(detail, {"restriction_status": "PENDING"}, format="json")
        response = self.client.get(reviews)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"count", "next", "previous", "results"})
        self.client.force_authenticate(self.participant)
        self.assertEqual(self.client.get(reviews).status_code, 403)

    def test_create_collision_recovers_inside_savepoint(self):
        compliance = MarketParticipantCompliance.objects.create(participant=self.participant)
        locked_queryset = Mock()
        locked_queryset.get.side_effect = [
            MarketParticipantCompliance.DoesNotExist,
            compliance,
        ]
        with (
            patch.object(
                MarketParticipantCompliance.objects,
                "select_for_update",
                return_value=locked_queryset,
            ),
            patch.object(
                MarketParticipantCompliance.objects,
                "create",
                side_effect=IntegrityError("simulated unique collision"),
            ),
        ):
            result = MarketComplianceService.update(
                participant=self.participant,
                actor=self.admin,
                changes={"restriction_status": "CLEAR"},
            )
        self.assertEqual(result.pk, compliance.pk)
        self.assertEqual(MarketComplianceReview.objects.count(), 1)

    def test_review_records_are_immutable_and_routes_are_read_only(self):
        make_market_eligible(self.participant)
        reviews = reverse(
            "markets:admin-participant-compliance-reviews", kwargs={"user_id": self.participant.id}
        )
        self.client.force_authenticate(self.admin)
        first, second = MarketComplianceReview.objects.all()
        self.assertGreaterEqual(first.created_at, second.created_at)
        first.reason = "changed"
        with self.assertRaises(ValidationError):
            first.save()
        with self.assertRaises(ValidationError):
            first.delete()
        for method in (self.client.patch, self.client.put, self.client.delete):
            self.assertEqual(method(reviews, {}, format="json").status_code, 405)

    def test_eligibility_and_admin_endpoints_have_bounded_queries(self):
        eligibility = reverse("markets:market-participant-eligibility")
        self.client.force_authenticate(self.participant)
        with CaptureQueriesContext(connection) as queries:
            self.client.get(eligibility)
        self.assertLessEqual(len(queries), 4)
        make_market_eligible(self.participant)
        self.participant.refresh_from_db()
        with CaptureQueriesContext(connection) as queries:
            self.client.get(eligibility)
        self.assertLessEqual(len(queries), 4)

        self.client.force_authenticate(self.admin)
        detail = reverse(
            "markets:admin-participant-compliance-detail", kwargs={"user_id": self.participant.id}
        )
        with CaptureQueriesContext(connection) as queries:
            self.client.get(detail)
        self.assertLessEqual(len(queries), 6)

        reviews = reverse(
            "markets:admin-participant-compliance-reviews", kwargs={"user_id": self.participant.id}
        )
        for status in ("CLEAR", "RESTRICTED", "SUSPENDED"):
            self.client.patch(detail, {"restriction_status": status}, format="json")
        with CaptureQueriesContext(connection) as queries:
            self.client.get(reviews)
        self.assertLessEqual(len(queries), 7)

    def test_openapi_uses_admin_detail_schema(self):
        response = self.client.get(reverse("api-schema"), {"format": "json"})
        schema = response.json()
        path = "/api/v1/market-admin/participants/{user_id}/compliance/"
        for method in ("get", "patch"):
            reference = schema["paths"][path][method]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]["$ref"]
            self.assertTrue(reference.endswith("/AdminComplianceDetail"))
