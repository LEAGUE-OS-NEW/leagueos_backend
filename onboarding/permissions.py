"""Permissions for the Fan Onboarding & Personalization module.

Implements object-level permissions ensuring authenticated users
can only manage their own onboarding data.
"""

from __future__ import annotations

from rest_framework import permissions


class IsOnboardingOwner(permissions.BasePermission):
    """Object-level permission: users can only access their own onboarding data.

    Requires the user to be authenticated. For onboarding objects,
    checks that the requesting user owns the onboarding record.
    """

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj) -> bool:
        # obj may be a UserOnboarding or a preference model
        if hasattr(obj, "user"):
            return obj.user == request.user
        return obj == request.user
