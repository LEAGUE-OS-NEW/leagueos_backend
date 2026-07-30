from uuid import UUID

import pytest

from accounts.models import User


@pytest.mark.django_db
def test_user_uses_uuid_primary_key():
    user = User.objects.create_user(
        username="testfan",
        email="testfan@example.com",
        password="StrongTestPassword123!",
    )

    assert isinstance(user.id, UUID)
    assert user.email == "testfan@example.com"
