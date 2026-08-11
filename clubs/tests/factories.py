import factory
from django.contrib.auth import get_user_model

from clubs.models import ClubWorkspace, WorkspaceMembership
from profiles.models import Club

User = get_user_model()


class ClubFactory(factory.django.DjangoModelFactory):
    """Factory for creating Club instances."""

    class Meta:
        model = Club

    name = factory.Sequence(lambda n: f"Club {n}")
    slug = factory.Sequence(lambda n: f"club-{n}")
    is_active = True


class ClubWorkspaceFactory(factory.django.DjangoModelFactory):
    """Factory for creating ClubWorkspace instances."""

    class Meta:
        model = ClubWorkspace

    user = factory.SubFactory("authentication.tests.factories.UserFactory")
    club = factory.SubFactory(ClubFactory)
    role = ClubWorkspace.WorkspaceRole.ADMIN
    permissions = factory.List([])
    is_active = True


class WorkspaceMembershipFactory(factory.django.DjangoModelFactory):
    """Factory for creating WorkspaceMembership instances."""

    class Meta:
        model = WorkspaceMembership

    user = factory.SubFactory("authentication.tests.factories.UserFactory")
    workspace = factory.SubFactory(ClubWorkspaceFactory)
    role = ClubWorkspace.WorkspaceRole.STAFF
    added_by = None
    is_active = True
