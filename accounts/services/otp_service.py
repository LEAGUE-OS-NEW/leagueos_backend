import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from accounts.models import OTPVerification


class OTPService:
    @staticmethod
    def generate_secure_otp() -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    @staticmethod
    def hash_otp(otp: str) -> str:
        return make_password(otp)

    @staticmethod
    def create_otp_record(user, purpose: str, channel: str = "EMAIL") -> OTPVerification:
        if purpose == "REGISTER":
            channel = settings.REGISTRATION_OTP_CHANNEL
        with transaction.atomic():
            OTPVerification.objects.select_for_update().filter(
                user=user, purpose=purpose, is_used=False
            ).update(is_used=True)
            otp_code = OTPService.generate_secure_otp()
            otp = OTPVerification.objects.create(
                user=user,
                otp_hash=OTPService.hash_otp(otp_code),
                purpose=purpose,
                expires_at=timezone.now() + timedelta(minutes=settings.OTP_EXPIRY_MINUTES),
                channel=channel,
            )

        return otp, otp_code

    @staticmethod
    def verify_otp(user, otp_code: str, purpose: str) -> OTPVerification:
        otp = (
            OTPVerification.objects.select_for_update()
            .filter(
                user=user,
                purpose=purpose,
                is_used=False,
            )
            .order_by("-created_at")
            .first()
        )

        if not otp:
            raise ValueError("Invalid verification code.")

        if otp.is_expired():
            otp.is_used = True
            otp.save(update_fields=["is_used"])
            raise ValueError("Invalid verification code.")

        if otp.attempts >= settings.OTP_MAX_VERIFICATION_ATTEMPTS:
            raise ValueError("Invalid verification code.")

        if not check_password(otp_code, otp.otp_hash):
            otp.attempts += 1
            otp.save(update_fields=["attempts"])
            raise ValueError("Invalid verification code.")

        otp.mark_used()
        return otp
