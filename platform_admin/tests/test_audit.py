import uuid


from accounts.models import AuditLog
from accounts.services.audit_service import AuditService

from .factories import UserFactory


class TestAuditService:
    def test_record_creates_audit_log(self, db):
        actor = UserFactory()

        log = AuditService.record(
            actor,
            "ROLE_ASSIGNED",
            resource_type="role",
            resource_id=uuid.uuid4(),
            metadata={"role": "Finance Admin"},
        )

        assert log.action == "ROLE_ASSIGNED"
        assert log.user == actor
        assert log.resource_type == "role"
        assert log.metadata["role"] == "Finance Admin"

    def test_record_without_actor(self, db):
        log = AuditService.record(
            None,
            "PLATFORM_CONFIGURATION_CHANGED",
            resource_type="configuration",
        )

        assert log.user is None
        assert log.action == "PLATFORM_CONFIGURATION_CHANGED"

    def test_record_with_request_extracts_metadata(self, db):
        actor = UserFactory()

        class FakeRequest:
            META = {
                "REMOTE_ADDR": "127.0.0.1",
                "HTTP_USER_AGENT": "test-agent",
                "HTTP_X_REQUEST_ID": "req-123",
            }

        log = AuditService.record(
            actor,
            "ADMIN_INVITED",
            resource_type="invitation",
            request=FakeRequest(),
        )

        assert log.ip_address == "127.0.0.1"
        assert log.user_agent == "test-agent"
        assert log.request_id == "req-123"

    def test_record_with_previous_and_new_state(self, db):
        actor = UserFactory()

        log = AuditService.record(
            actor,
            "MARKET_UPDATED",
            resource_type="market",
            previous_state={"status": "DRAFT"},
            new_state={"status": "PENDING_APPROVAL"},
        )

        assert log.metadata["previous_state"] == {"status": "DRAFT"}
        assert log.metadata["new_state"] == {"status": "PENDING_APPROVAL"}

    def test_record_with_invalid_resource_id(self, db):
        actor = UserFactory()

        log = AuditService.record(
            actor,
            "ROLE_ASSIGNED",
            resource_type="role",
            resource_id="not-a-uuid",
        )

        assert log.resource_id is None

    def test_audit_log_has_all_admin_actions(self, db):
        expected_actions = [
            "ADMIN_INVITED",
            "ADMIN_INVITATION_ACCEPTED",
            "ADMIN_DISABLED",
            "ADMIN_ENABLED",
            "ROLE_ASSIGNED",
            "ROLE_REVOKED",
            "PERMISSION_GRANTED",
            "PERMISSION_REVOKED",
            "MARKET_CREATED",
            "MARKET_UPDATED",
            "MARKET_REVIEWED",
            "MARKET_APPROVED",
            "MARKET_REJECTED",
            "MARKET_PUBLISHED",
            "MARKET_SUSPENDED",
            "MARKET_RESUMED",
            "MARKET_CLOSED",
            "MARKET_ARCHIVED",
            "RESULT_VERIFIED",
            "RESULT_REVERIFIED",
            "COMPLIANCE_ACTION",
            "FINANCIAL_RECONCILIATION",
            "PLATFORM_CONFIGURATION_CHANGED",
        ]

        available_actions = {choice[0] for choice in AuditLog.ACTION_CHOICES}

        for action in expected_actions:
            assert action in available_actions, f"Missing audit action: {action}"
