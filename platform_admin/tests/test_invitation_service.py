import pytest
from django.core.management import call_command
from django.utils import timezone

from authentication.models import AdminInvitation, Role, UserRole
from authentication.services.invitation_service import InvitationService

from .factories import UserFactory


@pytest.fixture
def seeded_roles(db):
    call_command("seed_roles", verbosity=0)


class TestCreateInvitation:
    def test_create_invitation(self, db, seeded_roles):
        inviter = UserFactory()
        role = Role.objects.get(name="Finance Admin")

        invitation = InvitationService.create_invitation(
            email="newadmin@example.com",
            roles=[role],
            invited_by=inviter,
            expires_in_days=7,
        )

        assert invitation.email == "newadmin@example.com"
        assert invitation.status == AdminInvitation.Status.PENDING
        assert invitation.token_expires_at > timezone.now()
        assert list(invitation.assigned_roles.all()) == [role]

    def test_duplicate_pending_invitation_rejected(self, db, seeded_roles):
        inviter = UserFactory()
        role = Role.objects.get(name="Finance Admin")

        InvitationService.create_invitation(
            email="dup@example.com",
            roles=[role],
            invited_by=inviter,
        )

        with pytest.raises(ValueError):
            InvitationService.create_invitation(
                email="dup@example.com",
                roles=[role],
                invited_by=inviter,
            )

    def test_email_is_normalized(self, db, seeded_roles):
        inviter = UserFactory()
        role = Role.objects.get(name="Finance Admin")

        invitation = InvitationService.create_invitation(
            email="  MixedCase@Example.COM  ",
            roles=[role],
            invited_by=inviter,
        )

        assert invitation.email == "mixedcase@example.com"


class TestAcceptInvitation:
    def test_accept_invitation_assigns_roles(self, db, seeded_roles):
        inviter = UserFactory()
        user = UserFactory()
        role = Role.objects.get(name="Finance Admin")

        invitation = InvitationService.create_invitation(
            email=user.email,
            roles=[role],
            invited_by=inviter,
        )

        accepted = InvitationService.accept_invitation(invitation.token, user)

        assert accepted is not None
        assert accepted.status == AdminInvitation.Status.ACCEPTED
        assert accepted.accepted_by == user
        assert UserRole.objects.filter(user=user, role=role, is_active=True).exists()

    def test_accept_expired_invitation_returns_none(self, db, seeded_roles):
        inviter = UserFactory()
        user = UserFactory()
        role = Role.objects.get(name="Finance Admin")

        invitation = InvitationService.create_invitation(
            email=user.email,
            roles=[role],
            invited_by=inviter,
        )
        invitation.token_expires_at = timezone.now() - timezone.timedelta(days=1)
        invitation.save(update_fields=["token_expires_at"])

        accepted = InvitationService.accept_invitation(invitation.token, user)

        assert accepted is None
        invitation.refresh_from_db()
        assert invitation.status == AdminInvitation.Status.EXPIRED

    def test_accept_invalid_token_returns_none(self, db):
        user = UserFactory()

        accepted = InvitationService.accept_invitation("invalid-token", user)

        assert accepted is None

    def test_accept_already_accepted_invitation_returns_none(self, db, seeded_roles):
        inviter = UserFactory()
        user = UserFactory()
        role = Role.objects.get(name="Finance Admin")

        invitation = InvitationService.create_invitation(
            email=user.email,
            roles=[role],
            invited_by=inviter,
        )
        InvitationService.accept_invitation(invitation.token, user)

        accepted = InvitationService.accept_invitation(invitation.token, user)

        assert accepted is None


class TestRevokeInvitation:
    def test_revoke_pending_invitation(self, db, seeded_roles):
        inviter = UserFactory()
        role = Role.objects.get(name="Finance Admin")

        invitation = InvitationService.create_invitation(
            email="revoke@example.com",
            roles=[role],
            invited_by=inviter,
        )

        InvitationService.revoke_invitation(invitation, inviter)

        invitation.refresh_from_db()
        assert invitation.status == AdminInvitation.Status.REVOKED
        assert invitation.revoked_by == inviter

    def test_revoke_non_pending_invitation_raises(self, db, seeded_roles):
        inviter = UserFactory()
        role = Role.objects.get(name="Finance Admin")

        invitation = InvitationService.create_invitation(
            email="revoke2@example.com",
            roles=[role],
            invited_by=inviter,
        )
        invitation.status = AdminInvitation.Status.ACCEPTED
        invitation.save(update_fields=["status"])

        with pytest.raises(ValueError):
            InvitationService.revoke_invitation(invitation, inviter)


class TestExpireOldInvitations:
    def test_expire_old_invitations(self, db, seeded_roles):
        inviter = UserFactory()
        role = Role.objects.get(name="Finance Admin")

        invitation = InvitationService.create_invitation(
            email="expire@example.com",
            roles=[role],
            invited_by=inviter,
        )
        invitation.token_expires_at = timezone.now() - timezone.timedelta(days=1)
        invitation.save(update_fields=["token_expires_at"])

        count = InvitationService.expire_old_invitations()

        assert count == 1
        invitation.refresh_from_db()
        assert invitation.status == AdminInvitation.Status.EXPIRED
