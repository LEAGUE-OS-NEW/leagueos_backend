import logging

from django.utils import timezone

from authentication.models import LoginHistory

logger = logging.getLogger(__name__)


class LoginHistoryService:
    @staticmethod
    def record_login(user, ip_address=None, user_agent=None, successful=True, failure_reason=""):
        LoginHistory.objects.create(
            user=user,
            ip_address=ip_address,
            user_agent=user_agent or "",
            successful=successful,
            failure_reason=failure_reason,
        )

    @staticmethod
    def record_logout(user):
        LoginHistory.objects.filter(user=user, logout_time__isnull=True).update(
            logout_time=timezone.now()
        )
