"""Bridges StaffInvitation (club scoping) with AccountSetupToken (brand-new
account password setup) so a Super Admin can invite the first Club Admin
for a club end to end.

StaffInvitation.accept requires the invitee to already be authenticated,
which a brand-new invitee never is. AccountSetupService already builds a
pending user + single-use setup token for exactly this "no account yet"
case, but was never wired to anything. This service composes the two:
create the StaffInvitation for club-scoping/audit, and — for a genuinely
new email — also create the pending user + setup token and email that
instead of StaffInvitation's own (dead-end) accept-link email.

Also handles resending: inviting the same (club, email) again while the
first invite is still pending must not try to insert a second row (that
collides with StaffInvitation's own uniqueness) and must actually issue
a fresh, working link rather than silently doing nothing.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from accounts.models import User
from accounts.services.email_service import EmailService
from accounts.services.username_service import UsernameService
from authentication.models import AccountSetupToken
from authentication.services.account_setup_service import AccountSetupService
from clubs.models import ClubWorkspace, StaffInvitation
from clubs.services.staff_service import StaffService

logger = logging.getLogger(__name__)


class ClubAdminInvitationService:
    @staticmethod
    @transaction.atomic
    def invite(*, club, login_email: str, notify_email: str, invited_by: User) -> StaffInvitation:
        login_email = login_email.strip().lower()
        notify_email = notify_email.strip().lower()

        invitation = (
            StaffInvitation.objects.filter(
                club=club,
                email=login_email,
                status=StaffInvitation.Status.PENDING,
            )
            .order_by("-created_at")
            .first()
        )
        if invitation is None:
            invitation = StaffService.invite_staff(
                club=club,
                email=login_email,
                role=ClubWorkspace.WorkspaceRole.ADMIN,
                invited_by=invited_by,
                send_email=False,
            )

        user = User.objects.filter(email=login_email).first()
        if user is None:
            # username has no bearing on login (USERNAME_FIELD is email) but
            # is still unique/required at the DB level, so it needs a real
            # value here rather than being left to default to "".
            user = User.objects.create(
                email=login_email,
                username=UsernameService.generate_unique_username(email=login_email),
                account_status=User.AccountStatus.PENDING_INVITATION,
                is_staff=True,
            )
            ClubAdminInvitationService._issue_and_send_setup_link(
                user=user, club=club, notify_email=notify_email
            )
        elif user.account_status == User.AccountStatus.PENDING_INVITATION:
            # Resend — the earlier token (if any) is still sitting in an
            # older email; revoke it so only the freshly-sent link works,
            # then issue and send a new one.
            AccountSetupToken.objects.filter(user=user, used_at__isnull=True).update(
                used_at=timezone.now()
            )
            ClubAdminInvitationService._issue_and_send_setup_link(
                user=user, club=club, notify_email=notify_email
            )
        else:
            # Already has an active account — StaffInvitation is recorded,
            # but they need to log in and accept it themselves
            # (StaffInvitationAcceptView); that UI path isn't wired on the
            # frontend yet.
            logger.info(
                "Club admin invite for existing active user %s on club %s — "
                "StaffInvitation created, no setup email sent.",
                login_email,
                club.id,
            )

        return invitation

    @staticmethod
    def _issue_and_send_setup_link(*, user: User, club, notify_email: str) -> None:
        setup_token = AccountSetupService.create_setup_token(user)
        try:
            EmailService.send_club_admin_setup_email(
                user=user,
                setup_token=setup_token.token,
                club_name=club.name,
                deliver_to=notify_email,
            )
        except Exception:
            logger.exception("Failed to send club admin setup email to %s", notify_email)
