import logging
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from accounts.models import User
from authentication.models import AccountSetupToken

logger = logging.getLogger(__name__)


class AccountSetupService:
    """Manages the invitation/setup token lifecycle for subordinate users.

    A new user account is created in ``PENDING_INVITATION`` state. A single-use,
    expiring setup token is generated and linked to that account. The invitee
    uses the token to set their own password, which activates the account.
    """

    @staticmethod
    def create_setup_token(
        user: User,
        expires_in_days: int = 7,
    ) -> AccountSetupToken:
        token = secrets.token_urlsafe(32)
        expires_at = timezone.now() + timedelta(days=expires_in_days)

        setup_token = AccountSetupToken.objects.create(
            user=user,
            token=token,
            token_expires_at=expires_at,
        )

        logger.info("Account setup token created for %s", user.email)
        return setup_token

    @staticmethod
    def get_effective_token(token: str) -> AccountSetupToken | None:
        return (
            AccountSetupToken.objects.select_related("user")
            .filter(
                token=token,
                used_at__isnull=True,
                token_expires_at__gt=timezone.now(),
                user__account_status=User.AccountStatus.PENDING_INVITATION,
            )
            .first()
        )

    @staticmethod
    def complete_setup(
        token: str,
        password: str,
        first_name: str,
        last_name: str,
    ) -> tuple[User | None, str | None]:
        setup_token = AccountSetupService.get_effective_token(token)
        if not setup_token:
            return None, "Invalid or expired setup token."

        user = setup_token.user

        with transaction.atomic():
            user.first_name = first_name
            user.last_name = last_name
            user.set_password(password)
            user.is_verified = True
            user.account_status = User.AccountStatus.ACTIVE
            user.save(
                update_fields=[
                    "first_name",
                    "last_name",
                    "password",
                    "is_verified",
                    "account_status",
                    "updated_at",
                ]
            )

            setup_token.used_at = timezone.now()
            setup_token.save(update_fields=["used_at", "updated_at"])

        from accounts.models import AuditLog

        AuditLog.objects.create(
            user=user,
            action="PASSWORD_SETUP_COMPLETED",
            metadata={"setup_token_id": str(setup_token.id)},
        )

        logger.info("Account setup completed for %s", user.email)
        return user, None

    @staticmethod
    def revoke_token(token: str) -> bool:
        setup_token = AccountSetupToken.objects.filter(token=token).first()
        if not setup_token:
            return False
        setup_token.used_at = timezone.now()
        setup_token.save(update_fields=["used_at", "updated_at"])
        return True

    @staticmethod
    def expire_old_tokens() -> int:
        expired = AccountSetupToken.objects.filter(
            used_at__isnull=True,
            token_expires_at__lt=timezone.now(),
        )
        count = expired.update(updated_at=timezone.now())
        if count:
            logger.info("Marked %d expired account setup tokens", count)
        return count
