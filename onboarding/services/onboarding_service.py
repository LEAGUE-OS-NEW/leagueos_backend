"""Onboarding service for the Fan Onboarding module.

Manages the onboarding lifecycle: start, resume, skip steps,
and complete onboarding.
"""

from __future__ import annotations

from django.utils import timezone

from accounts.models import AuditLog, User
from onboarding.models import OnboardingAnalyticsEvent, UserOnboarding


class OnboardingService:
    """Service for managing the onboarding lifecycle."""

    STEP_ORDER = [
        UserOnboarding.Step.COUNTRY,
        UserOnboarding.Step.SPORTS,
        UserOnboarding.Step.COMPETITIONS,
        UserOnboarding.Step.CLUBS,
    ]

    @staticmethod
    def get_or_create_onboarding(user: User, ip_address: str | None = None) -> UserOnboarding:
        """Return the user's onboarding record, creating it if necessary.

        Records ONBOARDING_STARTED audit log and analytics event
        on first creation.
        """
        onboarding, created = UserOnboarding.objects.get_or_create(user=user)
        if created:
            AuditLog.objects.create(
                user=user,
                action="ONBOARDING_STARTED",
                ip_address=ip_address,
                metadata={"current_step": onboarding.current_step},
            )
            OnboardingAnalyticsEvent.objects.create(
                user=user,
                event_type=OnboardingAnalyticsEvent.EventType.STARTED,
                metadata={"current_step": onboarding.current_step},
            )
        return onboarding

    @staticmethod
    def get_onboarding_status(user: User) -> UserOnboarding:
        """Return the user's onboarding status (creates if missing)."""
        return OnboardingService.get_or_create_onboarding(user)

    @staticmethod
    def advance_step(onboarding: UserOnboarding) -> None:
        """Advance the onboarding to the next step."""
        if onboarding.completed:
            return
        try:
            current_index = OnboardingService.STEP_ORDER.index(onboarding.current_step)
        except ValueError:
            return
        if current_index < len(OnboardingService.STEP_ORDER) - 1:
            onboarding.current_step = OnboardingService.STEP_ORDER[current_index + 1]
        else:
            onboarding.current_step = UserOnboarding.Step.COMPLETED
        onboarding.save(update_fields=["current_step", "updated_at"])

    @staticmethod
    def skip_step(user: User, step: str, ip_address: str | None = None) -> UserOnboarding:
        """Skip the given onboarding step.

        Records STEP_SKIPPED audit log and analytics event,
        then advances to the next step.
        """
        onboarding = OnboardingService.get_or_create_onboarding(user, ip_address)

        if step not in OnboardingService.STEP_ORDER:
            raise ValueError(f"Invalid step: {step}")

        if step not in onboarding.skipped_steps:
            onboarding.skipped_steps = [*onboarding.skipped_steps, step]
            onboarding.save(update_fields=["skipped_steps", "updated_at"])

        AuditLog.objects.create(
            user=user,
            action="STEP_SKIPPED",
            ip_address=ip_address,
            metadata={"step": step},
        )
        OnboardingAnalyticsEvent.objects.create(
            user=user,
            event_type=OnboardingAnalyticsEvent.EventType.STEP_SKIPPED,
            metadata={"step": step},
        )

        OnboardingService.advance_step(onboarding)
        return onboarding

    @staticmethod
    def complete_onboarding(user: User, ip_address: str | None = None) -> UserOnboarding:
        """Mark the user's onboarding as completed.

        Records ONBOARDING_COMPLETED audit log and analytics event.
        """
        onboarding = OnboardingService.get_or_create_onboarding(user, ip_address)
        if not onboarding.completed:
            onboarding.completed = True
            onboarding.completed_at = timezone.now()
            onboarding.current_step = UserOnboarding.Step.COMPLETED
            onboarding.save(
                update_fields=["completed", "completed_at", "current_step", "updated_at"]
            )

            AuditLog.objects.create(
                user=user,
                action="ONBOARDING_COMPLETED",
                ip_address=ip_address,
                metadata={
                    "completion_percentage": onboarding.completion_percentage,
                    "skipped_steps": onboarding.skipped_steps,
                },
            )
            OnboardingAnalyticsEvent.objects.create(
                user=user,
                event_type=OnboardingAnalyticsEvent.EventType.COMPLETED,
                metadata={
                    "completion_percentage": onboarding.completion_percentage,
                    "skipped_steps": onboarding.skipped_steps,
                },
            )
        return onboarding

    @staticmethod
    def resume_onboarding(user: User, ip_address: str | None = None) -> UserOnboarding:
        """Resume onboarding for a user who has already completed it.

        Resets the completed flag so the user can update preferences
        from the Profile flow. Records ONBOARDING_RESUMED audit log.
        """
        onboarding = OnboardingService.get_or_create_onboarding(user, ip_address)
        if onboarding.completed:
            onboarding.completed = False
            onboarding.completed_at = None
            onboarding.current_step = UserOnboarding.Step.COUNTRY
            onboarding.save(
                update_fields=["completed", "completed_at", "current_step", "updated_at"]
            )

            AuditLog.objects.create(
                user=user,
                action="ONBOARDING_RESUMED",
                ip_address=ip_address,
                metadata={"current_step": onboarding.current_step},
            )
            OnboardingAnalyticsEvent.objects.create(
                user=user,
                event_type=OnboardingAnalyticsEvent.EventType.RESUMED,
                metadata={"current_step": onboarding.current_step},
            )
        return onboarding
