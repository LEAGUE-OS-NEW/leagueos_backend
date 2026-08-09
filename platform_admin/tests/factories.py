import factory
from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import AuditLog
from authentication.models import (
    AdminInvitation,
    Permission,
    Role,
    RolePermission,
    UserRole,
    UserSession,
)

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"admin{n}@example.com")
    username = factory.Sequence(lambda n: f"admin{n}")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    is_verified = True
    is_active = True
    failed_attempts = 0
    locked_until = None

    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        pwd = extracted or "StrongPass123!"
        obj.set_password(pwd)
        if create:
            obj.save()


class RoleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Role

    name = factory.Sequence(lambda n: f"role_{n}")
    display_name = factory.Faker("job")
    description = factory.Faker("text")
    dashboard_url = factory.Faker("url")
    is_system = False


class PermissionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Permission

    name = factory.Sequence(lambda n: f"perm_{n}")
    resource = factory.Faker("word")
    action = factory.Faker("word")
    description = factory.Faker("text")


class RolePermissionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RolePermission

    role = factory.SubFactory(RoleFactory)
    permission = factory.SubFactory(PermissionFactory)


class UserRoleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UserRole

    user = factory.SubFactory(UserFactory)
    role = factory.SubFactory(RoleFactory)
    assigned_by = None
    assigned_at = factory.LazyFunction(timezone.now)


class AdminInvitationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AdminInvitation

    email = factory.Sequence(lambda n: f"invite{n}@example.com")
    token = factory.Faker("uuid4")
    token_expires_at = factory.LazyFunction(lambda: timezone.now() + timezone.timedelta(days=7))
    invited_by = factory.SubFactory(UserFactory)
    status = AdminInvitation.Status.PENDING


class UserSessionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UserSession

    user = factory.SubFactory(UserFactory)
    refresh_token_jti = factory.Faker("uuid4")
    ip_address = factory.Faker("ipv4")
    user_agent = factory.Faker("user_agent")
    device = factory.Faker("word")
    browser = factory.Faker("word")
    operating_system = factory.Faker("word")
    is_active = True


class AuditLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AuditLog

    user = factory.SubFactory(UserFactory)
    action = "ROLE_ASSIGNED"
    resource_type = "role"
    metadata = {}
