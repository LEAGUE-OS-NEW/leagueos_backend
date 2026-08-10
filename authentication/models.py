import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Role(models.Model):
    """Database-backed role.

    ``scope`` indicates whether the role is a platform role or a club-scoped
    role. ``category`` groups related roles (e.g. ``platform_admin``,
    ``club_staff``) for delegation purposes.
    """

    class Scope(models.TextChoices):
        PLATFORM = "PLATFORM", "Platform"
        CLUB = "CLUB", "Club"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    dashboard_url = models.CharField(max_length=500, blank=True)
    is_system = models.BooleanField(default=False)
    scope = models.CharField(
        max_length=20,
        choices=Scope.choices,
        default=Scope.PLATFORM,
        db_index=True,
    )
    category = models.CharField(max_length=100, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["scope", "is_system"]),
        ]

    def __str__(self) -> str:
        return self.display_name


class Permission(models.Model):
    """Granular, database-backed permission.

    ``scope`` indicates whether the permission is platform-scoped or
    club-scoped. ``delegatable`` controls whether an administrator may grant
    this permission to another user.
    """

    class Scope(models.TextChoices):
        PLATFORM = "PLATFORM", "Platform"
        CLUB = "CLUB", "Club"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=100, unique=True)  # code is the primary unique identifier
    name = models.CharField(max_length=255)  # name is human-readable, not unique
    resource = models.CharField(max_length=100)
    action = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True, db_index=True)
    scope = models.CharField(
        max_length=20,
        choices=Scope.choices,
        default=Scope.PLATFORM,
        db_index=True,
    )
    active = models.BooleanField(default=True, db_index=True)
    delegatable = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["resource", "action"]
        indexes = [
            models.Index(fields=["resource", "action"]),
            models.Index(fields=["scope", "active", "delegatable"]),
        ]

    def __str__(self) -> str:
        return f"{self.resource}:{self.action}"


class RolePermission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.ForeignKey(
        "authentication.Role",
        on_delete=models.CASCADE,
        related_name="role_permissions",
    )
    permission = models.ForeignKey(
        "authentication.Permission",
        on_delete=models.CASCADE,
        related_name="role_permissions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["role", "permission"]
        ordering = ["role__name", "permission__resource"]

    def __str__(self) -> str:
        return f"{self.role} - {self.permission}"


class UserRole(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_roles",
    )
    role = models.ForeignKey(
        "authentication.Role",
        on_delete=models.CASCADE,
        related_name="user_roles",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_user_roles",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_user_roles",
    )

    class Meta:
        unique_together = ["user", "role"]
        ordering = ["user__email", "role__name"]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["role", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} - {self.role}"

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and timezone.now() >= self.expires_at

    @property
    def is_effective(self) -> bool:
        return self.is_active and not self.is_expired


class AdminInvitation(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        EXPIRED = "EXPIRED", "Expired"
        REVOKED = "REVOKED", "Revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    token = models.CharField(max_length=255, unique=True, db_index=True)
    token_expires_at = models.DateTimeField()
    assigned_roles = models.ManyToManyField(
        "authentication.Role",
        related_name="admin_invitations",
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sent_admin_invitations",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_admin_invitations",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_admin_invitations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email", "status"]),
            models.Index(fields=["token", "status"]),
        ]

    def __str__(self) -> str:
        return f"Admin invitation for {self.email}"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.token_expires_at

    @property
    def is_effective(self) -> bool:
        return self.status == self.Status.PENDING and not self.is_expired


class UserSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_sessions",
    )
    refresh_token_jti = models.CharField(max_length=255, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    device = models.CharField(max_length=100, blank=True)
    browser = models.CharField(max_length=100, blank=True)
    operating_system = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    login_time = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    logout_time = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-login_time"]

    def __str__(self) -> str:
        return f"Session for {self.user}"


class LoginHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="login_history",
        null=True,
        blank=True,
    )
    login_time = models.DateTimeField(auto_now_add=True)
    logout_time = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    successful = models.BooleanField(default=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-login_time"]

    def __str__(self) -> str:
        return f"Login history for {self.user}"


class AccountSetupToken(models.Model):
    """Single-use, expiring setup token used to bootstrap a new account.

    Created when an administrator invites a subordinate user. The invitee
    uses the token to set their own password and activate their account.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="setup_tokens",
    )
    token = models.CharField(max_length=255, unique=True, db_index=True)
    token_expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Setup token for {self.user}"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.token_expires_at

    @property
    def is_effective(self) -> bool:
        return self.used_at is None and not self.is_expired


class UserPermission(models.Model):
    """Directly granted, user-scoped permission.

    Complements role-based permissions (``RolePermission``) so that an
    administrator can grant a specific permission to a specific user without
    assigning a whole role.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_permission_assignments",
    )
    permission = models.ForeignKey(
        "authentication.Permission",
        on_delete=models.CASCADE,
        related_name="user_permissions",
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_user_permissions",
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_user_permissions",
    )

    class Meta:
        unique_together = ["user", "permission"]
        ordering = ["user__email", "permission__name"]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["permission", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} - {self.permission}"

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and timezone.now() >= self.expires_at

    @property
    def is_effective(self) -> bool:
        return self.is_active and not self.is_expired
