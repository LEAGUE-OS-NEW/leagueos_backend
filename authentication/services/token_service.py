import logging

from rest_framework_simplejwt.tokens import RefreshToken

logger = logging.getLogger(__name__)


class TokenService:
    @staticmethod
    def generate_tokens(user) -> tuple[str, str]:
        refresh = RefreshToken.for_user(user)
        access = str(refresh.access_token)
        refresh_str = str(refresh)
        return access, refresh_str

    @staticmethod
    def blacklist_refresh_token(refresh_token: str) -> None:
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except Exception as exc:
            logger.error("Failed to blacklist refresh token: %s", exc)
