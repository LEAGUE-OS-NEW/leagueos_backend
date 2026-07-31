from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken


class TokenService:
    @staticmethod
    def generate_tokens(user) -> tuple[str, str]:
        refresh = RefreshToken.for_user(user)

        return str(refresh.access_token), str(refresh)

    @staticmethod
    def blacklist_refresh_token(refresh_token: str) -> str:
        token = RefreshToken(refresh_token)
        jti = str(token["jti"])

        token.blacklist()

        return jti

    @staticmethod
    def blacklist_user_refresh_tokens(user) -> int:
        blacklisted_count = 0

        outstanding_tokens = OutstandingToken.objects.filter(
            user=user,
        )

        for outstanding_token in outstanding_tokens:
            _, created = BlacklistedToken.objects.get_or_create(
                token=outstanding_token,
            )

            if created:
                blacklisted_count += 1

        return blacklisted_count
