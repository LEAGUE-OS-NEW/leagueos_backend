import logging

from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from authentication.models import UserSession

logger = logging.getLogger(__name__)


class SessionService:
    @staticmethod
    def create_session(user, refresh_token: str, ip_address=None, user_agent=None):
        jti = RefreshToken(refresh_token).get("jti")
        device, browser, operating_system = SessionService.parse_user_agent(user_agent)

        return UserSession.objects.create(
            user=user,
            refresh_token_jti=jti,
            ip_address=ip_address,
            user_agent=user_agent or "",
            device=device,
            browser=browser,
            operating_system=operating_system,
        )

    @staticmethod
    def parse_user_agent(user_agent: str):
        device = ""
        browser = ""
        operating_system = ""
        if user_agent:
            try:
                from ua_parser import user_agent_parser

                parsed = user_agent_parser.Parse(user_agent)
                device = parsed.get("device", {}).get("family", "")
                browser = parsed.get("user_agent", {}).get("family", "")
                operating_system = parsed.get("os", {}).get("family", "")
            except Exception:
                pass
        return device, browser, operating_system

    @staticmethod
    def terminate_session(session):
        if session.is_active:
            session.is_active = False
            session.logout_time = timezone.now()
            session.save(update_fields=["is_active", "logout_time"])

    @staticmethod
    def terminate_user_sessions(user):
        UserSession.objects.filter(user=user, is_active=True).update(
            is_active=False, logout_time=timezone.now()
        )

    @staticmethod
    def get_active_sessions(user):
        return UserSession.objects.filter(user=user, is_active=True)
