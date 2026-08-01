"""Permissions for the profiles app.

Implements object-level permissions ensuring authenticated users
can only view and update their own profile.
"""

from __future__ import annotations

from rest_framework import permissions


class IsProfileOwner(permissions.BasePermission):
    """Object-level permission: users can only access their own profile.

    Requires the user to be authenticated. For profile objects,
    checks that the requesting user owns the profile.
    """

    def has_permission(self, request, view) -> bool:
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj) -> bool:
        # obj may be a Profile or a User
        if hasattr(obj, "user"):
            return obj.user == request.user
        if hasattr(obj, "profile"):
            return obj.profile == request.user
        return obj == request.user


class IsProfileOwnerOrReadOnly(permissions.BasePermission):
    """Permission allowing owners full access; others read-only.

    Primarily used for lookup endpoints that don't need object-level
    checks, while still requiring authentication.
    """

    def has_permission(self, request, view) -> bool:
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj) -> bool:
        # SAFE methods (GET, HEAD, OPTIONS) are allowed
        if request.method in permissions.SAFE_METHODS:
            return True
        # Write methods: only the owner
        if hasattr(obj, "user"):
            return obj.user == request.user
        return False
