import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
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
        OTPVerification.objects.filter(
            user=user,
            purpose=purpose,
            is_used=False,
        ).update(is_used=True)

        otp_code = OTPService.generate_secure_otp()
        otp_hash = OTPService.hash_otp(otp_code)
        expires_at = timezone.now() + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)

        otp = OTPVerification.objects.create(
            user=user,
            otp_hash=otp_hash,
            purpose=purpose,
            expires_at=expires_at,
            channel=channel,
        )

        return otp, otp_code

    @staticmethod
    def verify_otp(user, otp_code: str, purpose: str) -> OTPVerification:
        otp = (
            OTPVerification.objects.filter(
                user=user,
                purpose=purpose,
                is_used=False,
            )
            .order_by("-created_at")
            .first()
        )

        if not otp:
            raise ValueError("No active OTP found.")

        if otp.is_expired():
            raise ValueError("OTP has expired.")

        if otp.attempts >= settings.OTP_MAX_VERIFICATION_ATTEMPTS:
            raise ValueError("Maximum verification attempts exceeded.")

        if not check_password(otp_code, otp.otp_hash):
            otp.attempts += 1
            otp.save(update_fields=["attempts"])
            raise ValueError("Invalid OTP.")

        otp.mark_used()
        return otp
