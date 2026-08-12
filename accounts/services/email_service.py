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
