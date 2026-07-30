from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import AuditLog, OTPVerification, User, VerificationAttempt


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = (
        "username",
        "email",
        "phone_number",
        "first_name",
        "last_name",
        "is_verified",
        "is_active",
        "is_staff",
    )

    search_fields = (
        "username",
        "email",
        "phone_number",
        "first_name",
        "last_name",
    )


@admin.register(OTPVerification)
class OTPVerificationAdmin(admin.ModelAdmin):
    list_display = ("user", "purpose", "channel", "is_used", "expires_at", "attempts", "created_at")
    list_filter = ("purpose", "channel", "is_used", "created_at")
    search_fields = ("user__email", "user__username", "purpose")


@admin.register(VerificationAttempt)
class VerificationAttemptAdmin(admin.ModelAdmin):
    list_display = ("user", "ip_address", "attempts", "last_attempt_at")
    list_filter = ("last_attempt_at",)
    search_fields = ("user__email", "user__username", "ip_address")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "user", "ip_address", "timestamp")
    list_filter = ("action", "timestamp")
    search_fields = ("user__email", "user__username", "ip_address", "action")
