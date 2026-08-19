import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)


class EmailService:
    @staticmethod
    def send_verification_email(user, otp_code: str) -> None:
        subject = "Verify Your League OS Email Address"
        context = {
            "first_name": user.first_name or "Fan",
            "otp_code": otp_code,
            "expiry_minutes": settings.OTP_EXPIRY_MINUTES,
            "support_email": getattr(settings, "SUPPORT_EMAIL", "support@leagueos.com"),
            "website": getattr(settings, "WEBSITE_URL", "https://leagueos.com"),
            "current_year": timezone.now().year,
        }

        try:
            html_content = render_to_string("emails/verification_email.html", context)
        except Exception:
            html_content = None

        try:
            text_content = render_to_string("emails/verification_email.txt", context)
        except Exception:
            text_content = (
                f"Hello {context['first_name']},\n\n"
                f"Your League OS verification code is:\n\n{otp_code}\n\n"
                f"This code expires in {settings.OTP_EXPIRY_MINUTES} minutes.\n\n"
                "Do not share this code.\n"
            )

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )

        if html_content:
            email.attach_alternative(html_content, "text/html")

        email.send(fail_silently=False)
        logger.info("Verification email sent to %s", user.email)

    @staticmethod
    def send_password_reset_email(user, otp_code: str) -> None:
        subject = "League OS Password Reset"
        expires_in = getattr(settings, "PASSWORD_RESET_OTP_EXPIRY_MINUTES", 15) * 60
        context = {
            "first_name": user.first_name or "Fan",
            "otp_code": otp_code,
            "expires_in": expires_in,
            "current_year": timezone.now().year,
        }

        try:
            html_content = render_to_string("emails/password_reset_email.html", context)
        except Exception:
            html_content = None

        try:
            text_content = render_to_string("emails/password_reset_email.txt", context)
        except Exception:
            text_content = (
                f"Hello {context['first_name']},\n\n"
                f"We received a request to reset your League OS password.\n\n"
                f"Your verification code is:\n\n{otp_code}\n\n"
                f"This code expires in {expires_in // 60} minutes.\n\n"
                "If you did not request this reset, you can safely ignore this email.\n"
                "Do not share this code.\n"
            )

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )

        if html_content:
            email.attach_alternative(html_content, "text/html")

        email.send(fail_silently=False)
        logger.info("Password reset email sent to %s", user.email)

    @staticmethod
    def send_account_setup_email(
        user,
        setup_token: str,
    ) -> None:
        subject = "Set Up Your League OS Account"

        account_setup_url = getattr(
            settings,
            "ACCOUNT_SETUP_URL",
            "",
        ).strip()

        setup_url = None

        if account_setup_url:
            separator = "&" if "?" in account_setup_url else "?"
            setup_url = f"{account_setup_url}" f"{separator}" f"token={setup_token}"

        context = {
            "first_name": (user.first_name or "League OS User"),
            "setup_token": setup_token,
            "setup_url": setup_url,
            "expiry_days": 7,
            "support_email": getattr(
                settings,
                "SUPPORT_EMAIL",
                "support@leagueos.com",
            ),
            "website": getattr(
                settings,
                "WEBSITE_URL",
                "https://leagueos.com",
            ),
            "current_year": timezone.now().year,
        }

        if setup_url:
            text_content = (
                f"Hello {context['first_name']},\n\n"
                "Your League OS administrator account "
                "has been created.\n\n"
                "Complete your account setup using this link:\n"
                f"{setup_url}\n\n"
                "This invitation expires in 7 days.\n\n"
                "If you were not expecting this invitation, "
                "you can ignore this email.\n"
            )
        else:
            text_content = (
                f"Hello {context['first_name']},\n\n"
                "Your League OS administrator account "
                "has been created.\n\n"
                "Use the following account setup token:\n\n"
                f"{setup_token}\n\n"
                "This invitation expires in 7 days.\n\n"
                "If you were not expecting this invitation, "
                "you can ignore this email.\n"
            )

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )

        email.send(
            fail_silently=False,
        )

        logger.info(
            "Account setup email sent to %s",
            user.email,
        )

    @staticmethod
    def send_club_admin_setup_email(
        user,
        setup_token: str,
        club_name: str,
        deliver_to: str,
    ) -> None:
        """Same link-building logic as send_account_setup_email, but names
        the club/role and delivers to the invitee's personal address rather
        than the LeagueOS login identity (which has no working inbox yet)."""
        subject = f"You've been invited as Club Admin for {club_name}"

        account_setup_url = getattr(
            settings,
            "ACCOUNT_SETUP_URL",
            "",
        ).strip()

        setup_url = None

        if account_setup_url:
            separator = "&" if "?" in account_setup_url else "?"
            setup_url = f"{account_setup_url}" f"{separator}" f"token={setup_token}"

        first_name = user.first_name or "there"

        context = {
            "first_name": first_name,
            "club_name": club_name,
            "login_email": user.email,
            "setup_url": setup_url,
            "setup_token": setup_token,
            "expiry_days": 7,
            "support_email": getattr(settings, "SUPPORT_EMAIL", "support@leagueos.com"),
            "website": getattr(settings, "WEBSITE_URL", "https://leagueos.com"),
            "current_year": timezone.now().year,
        }

        try:
            html_content = render_to_string("emails/club_admin_setup_email.html", context)
        except Exception:
            html_content = None

        try:
            text_content = render_to_string("emails/club_admin_setup_email.txt", context)
        except Exception:
            text_content = (
                f"Hello {first_name},\n\n"
                f"You've been invited to manage {club_name} on League OS "
                f"as Club Admin, using the login {user.email}.\n\n"
                + (
                    f"Complete your account setup using this link:\n{setup_url}\n\n"
                    if setup_url
                    else f"Use the following account setup token:\n\n{setup_token}\n\n"
                )
                + "This invitation expires in 7 days.\n\n"
                "If you were not expecting this invitation, "
                "you can ignore this email.\n"
            )

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[deliver_to],
        )

        if html_content:
            email.attach_alternative(html_content, "text/html")

        email.send(
            fail_silently=False,
        )

        logger.info(
            "Club admin setup email for %s sent to %s",
            user.email,
            deliver_to,
        )

    @staticmethod
    def send_staff_invitation_email(invitation) -> None:
        """Emails the invite link for a clubs.StaffInvitation."""
        subject = f"You've Been Invited to {invitation.club.name} on League OS"

        staff_invite_url = getattr(settings, "STAFF_INVITE_URL", "").strip()
        accept_url = None
        if staff_invite_url:
            separator = "&" if "?" in staff_invite_url else "?"
            accept_url = f"{staff_invite_url}{separator}token={invitation.token}"

        context = {
            "club_name": invitation.club.name,
            "role_label": invitation.get_role_display(),
            "invited_by_name": invitation.invited_by.get_full_name() or invitation.invited_by.email,
            "token": invitation.token,
            "accept_url": accept_url,
            "expiry_days": max((invitation.expires_at - timezone.now()).days, 1),
            "support_email": getattr(settings, "SUPPORT_EMAIL", "support@leagueos.com"),
            "website": getattr(settings, "WEBSITE_URL", "https://leagueos.com"),
            "current_year": timezone.now().year,
        }

        try:
            html_content = render_to_string("emails/staff_invitation_email.html", context)
        except Exception:
            html_content = None

        try:
            text_content = render_to_string("emails/staff_invitation_email.txt", context)
        except Exception:
            text_content = (
                f"{context['invited_by_name']} has invited you to join {context['club_name']} "
                f"on League OS as a {context['role_label']}.\n\n"
                + (
                    f"Accept your invitation using this link:\n{accept_url}\n\n"
                    if accept_url
                    else f"Use the following invitation token to accept:\n\n{invitation.token}\n\n"
                )
                + f"This invitation expires in {context['expiry_days']} days.\n"
            )

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[invitation.email],
        )

        if html_content:
            email.attach_alternative(html_content, "text/html")

        email.send(fail_silently=False)
        logger.info(
            "Staff invitation email sent to %s for club %s",
            invitation.email,
            invitation.club.name,
        )

    @staticmethod
    def send_admin_invitation_email(invitation, deliver_to: str) -> None:
        """Emails the invite link for an authentication.AdminInvitation to an
        already-active user — deliver_to may differ from invitation.email
        (the login identity) since the two are no longer assumed to be the
        same inbox, same rationale as send_club_admin_setup_email."""
        subject = "You've Been Invited to League OS Administration"

        admin_invite_url = getattr(settings, "ADMIN_INVITE_URL", "").strip()
        accept_url = None
        if admin_invite_url:
            separator = "&" if "?" in admin_invite_url else "?"
            accept_url = f"{admin_invite_url}{separator}token={invitation.token}"

        role_names = list(invitation.assigned_roles.values_list("display_name", flat=True))
        context = {
            "role_names": ", ".join(role_names) if role_names else "Administrator",
            "invited_by_name": invitation.invited_by.get_full_name() or invitation.invited_by.email,
            "token": invitation.token,
            "accept_url": accept_url,
            "expiry_days": max((invitation.token_expires_at - timezone.now()).days, 1),
            "support_email": getattr(settings, "SUPPORT_EMAIL", "support@leagueos.com"),
            "website": getattr(settings, "WEBSITE_URL", "https://leagueos.com"),
            "current_year": timezone.now().year,
        }

        try:
            html_content = render_to_string("emails/admin_invitation_email.html", context)
        except Exception:
            html_content = None

        try:
            text_content = render_to_string("emails/admin_invitation_email.txt", context)
        except Exception:
            text_content = (
                f"{context['invited_by_name']} has invited you to League OS administration "
                f"as {context['role_names']}.\n\n"
                + (
                    f"Accept your invitation using this link:\n{accept_url}\n\n"
                    if accept_url
                    else f"Use the following invitation token to accept:\n\n{invitation.token}\n\n"
                )
                + f"This invitation expires in {context['expiry_days']} days.\n"
            )

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[deliver_to],
        )

        if html_content:
            email.attach_alternative(html_content, "text/html")

        email.send(fail_silently=False)
        logger.info("Admin invitation email for %s sent to %s", invitation.email, deliver_to)

    @staticmethod
    def send_admin_invitation_setup_email(
        user,
        setup_token: str,
        deliver_to: str,
        role_names: list[str],
    ) -> None:
        """Same link-building logic as send_club_admin_setup_email, for a
        brand-new platform-role admin identity (no club) that has no working
        inbox yet at its LeagueOS login address."""
        subject = "You've Been Invited to League OS Administration"

        account_setup_url = getattr(settings, "ACCOUNT_SETUP_URL", "").strip()
        setup_url = None
        if account_setup_url:
            separator = "&" if "?" in account_setup_url else "?"
            setup_url = f"{account_setup_url}{separator}token={setup_token}"

        first_name = user.first_name or "there"
        role_label = ", ".join(role_names) if role_names else "Administrator"

        context = {
            "first_name": first_name,
            "role_label": role_label,
            "login_email": user.email,
            "setup_url": setup_url,
            "setup_token": setup_token,
            "expiry_days": 7,
            "support_email": getattr(settings, "SUPPORT_EMAIL", "support@leagueos.com"),
            "website": getattr(settings, "WEBSITE_URL", "https://leagueos.com"),
            "current_year": timezone.now().year,
        }

        try:
            html_content = render_to_string("emails/admin_invitation_setup_email.html", context)
        except Exception:
            html_content = None

        try:
            text_content = render_to_string("emails/admin_invitation_setup_email.txt", context)
        except Exception:
            text_content = (
                f"Hello {first_name},\n\n"
                f"You've been invited to League OS administration as {role_label}, "
                f"using the login {user.email}.\n\n"
                + (
                    f"Complete your account setup using this link:\n{setup_url}\n\n"
                    if setup_url
                    else f"Use the following account setup token:\n\n{setup_token}\n\n"
                )
                + "This invitation expires in 7 days.\n\n"
                "If you were not expecting this invitation, "
                "you can ignore this email.\n"
            )

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[deliver_to],
        )

        if html_content:
            email.attach_alternative(html_content, "text/html")

        email.send(fail_silently=False)
        logger.info("Admin invitation setup email for %s sent to %s", user.email, deliver_to)
