"""Service layer for profile management operations.

Handles all business logic for viewing and updating user profiles,
including audit logging for all profile-related actions.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from accounts.models import AuditLog
from profiles.models import Profile

logger = logging.getLogger(__name__)
User = get_user_model()


class ProfileService:
    """Service for profile CRUD and audit operations."""

    @staticmethod
    def get_or_create_profile(user: User) -> Profile:
        """Get existing profile for user, or create one if it does not exist."""
        profile, created = Profile.objects.get_or_create(user=user)
        if created:
            logger.info("Profile created for user %s", user)
        return profile

    @staticmethod
    def get_profile(user: User) -> Profile:
        """Retrieve the profile for a given user."""
        return ProfileService.get_or_create_profile(user)

    @staticmethod
    def record_audit_log(
        user: User | None,
        action: str,
        ip_address: str | None = None,
        user_agent: str = "",
        metadata_: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Create an audit log entry for profile actions."""
        return AuditLog.objects.create(
            user=user,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata_ or {},
        )

    @staticmethod
    def validate_date_of_birth(dob: date | None) -> date | None:
        """Validate that date of birth meets platform requirements.

        Raises:
            ValueError: If the date of birth is in the future or
                        the user is below the minimum age.
        """
        if dob is None:
            return None

        if dob > timezone.now().date():
            raise ValueError("Date of birth cannot be in the future.")

        min_age = getattr(settings, "PROFILE_MIN_AGE_YEARS", 13)
        today = timezone.now().date()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if age < min_age:
            raise ValueError(f"User must be at least {min_age} years old.")

        return dob

    @staticmethod
    def update_profile(
        user: User,
        data: dict[str, Any],
        ip_address: str | None = None,
        user_agent: str = "",
    ) -> Profile:
        """Update a user's profile with validated data.

        Handles updates to both User model fields (first_name, last_name)
        and Profile model fields. Records audit logs for profile updates
        and favourite club changes.

        Args:
            user: The authenticated user whose profile is being updated.
            data: Validated data dict containing profile fields.
                  ForeignKey fields (country, gender, etc.) are expected
                  as model instances.
            ip_address: IP address of the request.
            user_agent: User agent string of the request.

        Returns:
            The updated Profile instance with fresh data.
        """
        with transaction.atomic():
            profile = ProfileService.get_or_create_profile(user)
            old_club = profile.favourite_club

            # Fields that belong to User model rather than Profile
            user_fields = ("first_name", "last_name")

            # Track which fields are updated for audit
            updated_fields: list[str] = []

            # Update User-level fields
            for field_name in user_fields:
                if field_name in data:
                    value = data[field_name]
                    setattr(user, field_name, value)
                    updated_fields.append(field_name)

            user.save(update_fields=[*user_fields, "updated_at"])

            # Update Profile-level fields
            profile_fields = [
                "display_name",
                "date_of_birth",
                "gender",
                "country",
                "city",
                "preferred_language",
                "timezone",
                "biography",
                "favourite_club",
                "communication_preferences",
                "notification_preferences",
            ]

            for field_name in profile_fields:
                if field_name in data:
                    value = data[field_name]
                    setattr(profile, field_name, value)
                    updated_fields.append(field_name)

            profile.save()

            # Record PROFILE_UPDATED audit log
            ProfileService.record_audit_log(
                user=user,
                action="PROFILE_UPDATED",
                ip_address=ip_address,
                user_agent=user_agent,
                metadata_={"fields_updated": updated_fields},
            )

            # Record FAVOURITE_CLUB_UPDATED audit log if club changed
            new_club = profile.favourite_club
            club_changed = "favourite_club" in updated_fields and (
                (old_club is None and new_club is not None)
                or (old_club is not None and new_club is None)
                or (old_club is not None and new_club is not None and old_club != new_club)
            )
            if club_changed:
                ProfileService.record_audit_log(
                    user=user,
                    action="FAVOURITE_CLUB_UPDATED",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    metadata_={
                        "old_club": str(old_club) if old_club else None,
                        "new_club": str(new_club) if new_club else None,
                    },
                )

            # Refresh to get latest state from database
            profile.refresh_from_db()
            user.refresh_from_db()

            return profile

    @staticmethod
    def record_profile_view(
        user: User,
        ip_address: str | None = None,
        user_agent: str = "",
    ) -> None:
        """Record a profile view audit log entry."""
        ProfileService.record_audit_log(
            user=user,
            action="PROFILE_VIEWED",
            ip_address=ip_address,
            user_agent=user_agent,
        )
