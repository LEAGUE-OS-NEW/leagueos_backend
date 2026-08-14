from uuid import UUID

import pytest
from django.core.exceptions import ValidationError

from accounts.models import AuditLog, User


@pytest.mark.django_db
def test_user_uses_uuid_primary_key():
    user = User.objects.create_user(
        username="testfan",
        email="testfan@example.com",
        password="StrongTestPassword123!",
    )

    assert isinstance(user.id, UUID)
    assert user.email == "testfan@example.com"


@pytest.mark.django_db
def test_audit_log_is_immutable():
    entry = AuditLog.objects.create(action="USER_REGISTERED")

    entry.action = "ACCOUNT_ACTIVATED"
    with pytest.raises(ValidationError):
        entry.save()

    with pytest.raises(ValidationError):
        entry.delete()

    assert AuditLog.objects.get(pk=entry.pk).action == "USER_REGISTERED"
