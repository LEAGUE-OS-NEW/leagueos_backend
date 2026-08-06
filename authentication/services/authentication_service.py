import logging
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from accounts.models import User
from authentication.models import LoginHistory
from authentication.services.login_history_service import LoginHistoryService

logger = logging.getLogger(__name__)


class AuthenticationService:
    @staticmethod
    def find_user(identifier: str) -> User | None:
        return User.objects.filter(
            Q(email__iexact=identifier) | Q(username__iexact=identifier)
        ).first()

    @staticmethod
    def authenticate(
        identifier: str, password: str, ip_address=None, user_agent=None
    ) -> User | None:
        user = AuthenticationService.find_user(identifier)
        if not user:
            LoginHistoryService.record_login(
                user=None,
                ip_address=ip_address,
                user_agent=user_agent,
                successful=False,
                failure_reason="Invalid credentials",
            )
            return None

        if not user.check_password(password):
            AuthenticationService.record_failed_attempt(user, ip_address, user_agent)
            return None

        if not user.is_active:
            return None

        if not user.is_verified:
            return None

        AuthenticationService.reset_failed_attempts(user)
        return user

    @staticmethod
    def record_login_attempt(
        user, successful: bool, ip_address=None, user_agent=None, failure_reason=""
    ):
        LoginHistory.objects.create(
            user=user,
            ip_address=ip_address,
            user_agent=user_agent or "",
            successful=successful,
            failure_reason=failure_reason,
        )

    @staticmethod
    def record_failed_attempt(user, ip_address, user_agent=""):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        user.last_failed_attempt = timezone.now()
        if user.failed_attempts >= getattr(settings, "LOGIN_MAX_FAILED_ATTEMPTS", 5):
            lock_minutes = getattr(settings, "LOGIN_LOCK_MINUTES", 15)
            user.locked_until = timezone.now() + timedelta(minutes=lock_minutes)
        user.save(update_fields=["failed_attempts", "last_failed_attempt", "locked_until"])
        AuthenticationService.record_login_attempt(
            user,
            successful=False,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason="Invalid credentials",
        )

    @staticmethod
    def reset_failed_attempts(user):
        user.failed_attempts = 0
        user.last_failed_attempt = None
        user.locked_until = None
        user.save(update_fields=["failed_attempts", "last_failed_attempt", "locked_until"])

    @staticmethod
    def is_account_locked(user) -> bool:
        if not user.locked_until:
            return False
        if user.locked_until < timezone.now():
            AuthenticationService.reset_failed_attempts(user)
            return False
        return True
