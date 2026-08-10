import logging

from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError

from accounts.models import AuditLog, User
from authentication.services.session_service import SessionService

logger = logging.getLogger(__name__)


class PasswordChangeService:
    """Service for handling user password changes."""

    @staticmethod
    def change_password(
        *, user: User, current_password: str, new_password: str, ip_address: str, user_agent: str
    ) -> None:
        """
        Change a user's password after verifying their current one.

        Args:
            user: The user changing their password.
            current_password: The user's current password.
            new_password: The desired new password.
            ip_address: The IP address of the request.
            user_agent: The user agent of the request.

        Raises:
            PermissionError: If the current password is incorrect.
            ValidationError: If the new password is the same as the old one.
        """
        if not user.check_password(current_password):
            logger.warning("Password change failed for %s: incorrect current password.", user.email)
            raise PermissionError("Incorrect current password.")

        if check_password(new_password, user.password):
            raise ValidationError("New password cannot be the same as the current password.")

        user.set_password(new_password)
        user.save(update_fields=["password", "updated_at"])

        # Invalidate all other sessions for security
        SessionService.invalidate_user_sessions(user)

        AuditLog.objects.create(
            user=user,
            action="PASSWORD_CHANGED",
            ip_address=ip_address,
            user_agent=user_agent,
        )

        logger.info("Password changed successfully for %s.", user.email)