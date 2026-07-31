import logging

from django.contrib.auth.hashers import check_password

from accounts.models import AuditLog, OTPVerification, User
from accounts.services.email_service import EmailService
from accounts.services.otp_service import OTPService
from authentication.services.session_service import SessionService

logger = logging.getLogger(__name__)

GENERIC_SUCCESS_MESSAGE = (
    "If an account exists for that email, password reset instructions have been sent."
)


def log_audit(user, action, ip_address=None, user_agent="", metadata=None):
    AuditLog.objects.create(
        user=user,
        action=action,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata=metadata or {},
    )


class PasswordResetService:
    @staticmethod
    def request_password_reset(email: str, ip_address=None, user_agent="") -> dict:
        normalized_email = email.lower().strip()
        user = User.objects.filter(email=normalized_email).first()

        if user and user.is_active:
            log_audit(
                user,
                "PASSWORD_RESET_REQUESTED",
                ip_address=ip_address,
                user_agent=user_agent,
            )

            otp_obj, otp_code = OTPService.create_otp_record(
                user, purpose="PASSWORD_RESET", channel="EMAIL"
            )

            EmailService.send_password_reset_email(user, otp_code)

            log_audit(
                user,
                "PASSWORD_RESET_EMAIL_SENT",
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"otp_id": str(otp_obj.id)},
            )

            logger.info("Password reset OTP sent to %s", user.email)

        return {
            "success": True,
            "message": GENERIC_SUCCESS_MESSAGE,
        }

    @staticmethod
    def verify_reset_token(email: str, otp_code: str, ip_address=None, user_agent="") -> dict:
        normalized_email = email.lower().strip()
        user = User.objects.filter(email=normalized_email).first()

        if not user or not user.is_active:
            return {
                "success": False,
                "message": "Invalid or expired OTP.",
            }

        try:
            otp = OTPService.verify_otp(user, otp_code, purpose="PASSWORD_RESET")
            log_audit(
                user,
                "PASSWORD_RESET_VERIFIED",
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"otp_id": str(otp.id)},
            )
            return {
                "success": True,
                "message": "OTP verified successfully.",
            }
        except ValueError as e:
            error_msg = str(e)
            if "expired" in error_msg:
                log_audit(
                    user,
                    "PASSWORD_RESET_EXPIRED",
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            elif "attempts" in error_msg:
                log_audit(
                    user,
                    "PASSWORD_RESET_FAILED",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    metadata={"reason": "max_attempts_exceeded"},
                )
            else:
                log_audit(
                    user,
                    "PASSWORD_RESET_FAILED",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    metadata={"reason": error_msg},
                )
            return {
                "success": False,
                "message": "Invalid or expired OTP.",
            }

    @staticmethod
    def confirm_password_reset(
        email: str, otp_code: str, new_password: str, ip_address=None, user_agent=""
    ) -> dict:
        normalized_email = email.lower().strip()
        user = User.objects.filter(email=normalized_email).first()

        if not user or not user.is_active:
            return {
                "success": False,
                "message": "Invalid or expired OTP.",
            }

        try:
            otp = OTPService.verify_otp(user, otp_code, purpose="PASSWORD_RESET")
        except ValueError as e:
            error_msg = str(e)
            if "expired" in error_msg:
                log_audit(
                    user,
                    "PASSWORD_RESET_EXPIRED",
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            elif "attempts" in error_msg:
                log_audit(
                    user,
                    "PASSWORD_RESET_FAILED",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    metadata={"reason": "max_attempts_exceeded"},
                )
            else:
                log_audit(
                    user,
                    "PASSWORD_RESET_FAILED",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    metadata={"reason": error_msg},
                )
            return {
                "success": False,
                "message": "Invalid or expired OTP.",
            }

        if check_password(new_password, user.password):
            log_audit(
                user,
                "PASSWORD_RESET_FAILED",
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"reason": "password_reuse"},
            )
            return {
                "success": False,
                "message": "New password cannot be the same as the current password.",
            }

        user.set_password(new_password)
        user.save(update_fields=["password"])

        OTPVerification.objects.filter(
            user=user,
            purpose="PASSWORD_RESET",
            is_used=False,
        ).update(is_used=True)

        SessionService.terminate_user_sessions(user)
        log_audit(
            user,
            "ALL_SESSIONS_TERMINATED",
            ip_address=ip_address,
            user_agent=user_agent,
        )

        log_audit(
            user,
            "PASSWORD_RESET_SUCCESS",
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"otp_id": str(otp.id)},
        )

        logger.info("Password reset successful for %s", user.email)

        return {
            "success": True,
            "message": "Password reset successfully. Please log in again.",
        }
