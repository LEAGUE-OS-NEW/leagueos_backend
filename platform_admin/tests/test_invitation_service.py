import pytest
from django.core.management import call_command
from django.utils import timezone

from accounts.models import User
from authentication.models import AccountSetupToken, AdminInvitation, Role, UserRole
from authentication.services.invitation_service import InvitationService

from .factories import UserFactory


@pytest.fixture
def seeded_roles(db):
    call_command("seed_roles", verbosity=0)


class TestCreateInvitation:
    def test_create_invitation_for_new_login_creates_pending_user_and_setup_token(
        self, db, seeded_roles
    ):
        inviter = UserFactory()
        role = Role.objects.get(name="Finance Admin")

        invitation = InvitationService.create_invitation(
            login_email="newadmin@example.com",
            notify_email="notify-newadmin@example.com",
            roles=[role],
            invited_by=inviter,
            expires_in_days=7,
        )

        assert invitation.email == "newadmin@example.com"
        assert invitation.status == AdminInvitation.Status.PENDING
        assert invitation.token_expires_at > timezone.now()
        assert list(invitation.assigned_roles.all()) == [role]

        user = User.objects.get(email="newadmin@example.com")
        assert user.account_status == User.AccountStatus.PENDING_INVITATION
        assert AccountSetupToken.objects.filter(user=user, used_at__isnull=True).exists()

    def test_duplicate_invitation_to_active_user_rejected(self, db, seeded_roles):
        inviter = UserFactory()
        existing_active_user = UserFactory()
        role = Role.objects.get(name="Finance Admin")

        InvitationService.create_invitation(
            login_email=existing_active_user.email,
            notify_email="notify-dup@example.com",
            roles=[role],
            invited_by=inviter,
        )

        with pytest.raises(ValueError):
            InvitationService.create_invitation(
                login_email=existing_active_user.email,
                notify_email="notify-dup@example.com",
                roles=[role],
                invited_by=inviter,
            )

    def test_resend_to_still_pending_login_reuses_invitation_and_issues_fresh_token(
        self, db, seeded_roles
    ):
        inviter = UserFactory()
        role = Role.objects.get(name="Finance Admin")

        first = InvitationService.create_invitation(
            login_email="pending@example.com",
            notify_email="notify-pending@example.com",
            roles=[role],
            invited_by=inviter,
        )
        user = User.objects.get(email="pending@example.com")
        first_token = AccountSetupToken.objects.get(user=user, used_at__isnull=True)

        second = InvitationService.create_invitation(
            login_email="pending@example.com",
            notify_email="notify-pending@example.com",
            roles=[role],
            invited_by=inviter,
        )

        assert second.id == first.id

        first_token.refresh_from_db()
        assert first_token.used_at is not None
        assert AccountSetupToken.objects.filter(user=user, used_at__isnull=True).exists()

    def test_login_email_is_normalized(self, db, seeded_roles):
        inviter = UserFactory()
        role = Role.objects.get(name="Finance Admin")

        invitation = InvitationService.create_invitation(
            login_email="  MixedCase@Example.COM  ",
            notify_email="notify@example.com",
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
            login_email=user.email,
            notify_email="notify@example.com",
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
            login_email=user.email,
            notify_email="notify@example.com",
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
            login_email=user.email,
            notify_email="notify@example.com",
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
            login_email="revoke@example.com",
            notify_email="notify-revoke@example.com",
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
            login_email="revoke2@example.com",
            notify_email="notify-revoke2@example.com",
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
            login_email="expire@example.com",
            notify_email="notify-expire@example.com",
            roles=[role],
            invited_by=inviter,
        )
        invitation.token_expires_at = timezone.now() - timezone.timedelta(days=1)
        invitation.save(update_fields=["token_expires_at"])

        count = InvitationService.expire_old_invitations()

        assert count == 1
        invitation.refresh_from_db()
        assert invitation.status == AdminInvitation.Status.EXPIRED
