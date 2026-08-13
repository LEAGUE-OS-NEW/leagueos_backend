"""API views for the profiles app.

All views are thin — business logic is delegated to services.
Includes profile management, lookup endpoints, club listings,
and avatar upload/delete/retrieve endpoints.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from authentication.services.permission_service import PermissionService
from profiles.models import Club, Country, Gender, Language, Profile, Timezone
from profiles.permissions import IsProfileOwner
from profiles.serializers import (
    AvatarSerializer,
    ClubCreateSerializer,
    ClubSerializer,
    CountrySerializer,
    GenderSerializer,
    LanguageSerializer,
    ProfileSerializer,
    ProfileUpdateSerializer,
    TimezoneSerializer,
)
from profiles.services.avatar_service import AvatarService
from profiles.services.image_validation_service import ValidationError as ImageValidationError
from profiles.services.profile_service import ProfileService

# =============================================================================
# Profile Views
# =============================================================================


class ProfileView(APIView):
    """View for retrieving and updating the authenticated user's profile.

    GET  /api/v1/profile/ — Retrieve profile
    PATCH  /api/v1/profile/ — Update profile
    """

    permission_classes = [IsAuthenticated, IsProfileOwner]

    def get_object(self) -> Profile:
        """Get or create the profile for the requesting user."""
        return ProfileService.get_or_create_profile(self.request.user)

    @extend_schema(
        summary="Get profile",
        description="Retrieve the authenticated user's profile information.",
        responses={200: ProfileSerializer},
    )
    def get(self, request: Request) -> Response:
        """Retrieve the authenticated user's profile."""
        profile = self.get_object()

        # Record audit log for profile view
        ProfileService.record_profile_view(
            user=request.user,
            ip_address=self._get_ip_address(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

        serializer = ProfileSerializer(profile, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Update profile",
        description=(
            "Update the authenticated user's profile. "
            "Allowed fields: first_name, last_name, display_name, "
            "date_of_birth, gender, country, city, biography, "
            "favourite_club, preferred_language, timezone, "
            "communication_preferences, notification_preferences."
        ),
        request=ProfileUpdateSerializer,
        responses={200: ProfileSerializer},
    )
    def patch(self, request: Request) -> Response:
        """Update the authenticated user's profile with validated data."""
        profile = self.get_object()

        serializer = ProfileUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(
                {"success": False, "message": "Validation failed", "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Pass validated data to the service
        ProfileService.update_profile(
            user=request.user,
            data=serializer.validated_data,
            ip_address=self._get_ip_address(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

        # Return the updated profile
        profile.refresh_from_db()
        user_profile = ProfileService.get_profile(request.user)
        result_serializer = ProfileSerializer(user_profile, context={"request": request})

        return Response(result_serializer.data, status=status.HTTP_200_OK)

    def _get_ip_address(self, request: Request) -> str | None:
        """Extract the client IP address from the request."""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")


# =============================================================================
# Lookup Views
# =============================================================================


class CountryListView(generics.ListAPIView):
    """List all active countries for profile lookup."""

    serializer_class = CountrySerializer
    queryset = Country.objects.filter(is_active=True)
    permission_classes = [IsAuthenticated]


class LanguageListView(generics.ListAPIView):
    """List all active languages for profile lookup."""

    serializer_class = LanguageSerializer
    queryset = Language.objects.filter(is_active=True)
    permission_classes = [IsAuthenticated]


class TimezoneListView(generics.ListAPIView):
    """List all active timezones for profile lookup."""

    serializer_class = TimezoneSerializer
    queryset = Timezone.objects.filter(is_active=True)
    permission_classes = [IsAuthenticated]


class GenderListView(generics.ListAPIView):
    """List all active genders for profile lookup."""

    serializer_class = GenderSerializer
    queryset = Gender.objects.filter(is_active=True)
    permission_classes = [IsAuthenticated]


class ClubListView(generics.ListCreateAPIView):
    """List all active clubs for favourite club selection.

    POST is restricted to Super Admin / holders of admin.clubs.manage
    (see StaffService for how a Club Admin is then invited onto it).
    """

    queryset = Club.objects.filter(is_active=True)
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ClubCreateSerializer
        return ClubSerializer

    def perform_create(self, serializer):
        if not PermissionService.has_permission(self.request.user, "admin.clubs.manage"):
            raise PermissionDenied("You do not have permission to create clubs.")
        serializer.save()


# =============================================================================
# Avatar Views
# =============================================================================


class AvatarView(APIView):
    """View for managing the authenticated user's avatar.

    POST   /api/v1/profile/avatar/ — Upload or replace avatar
    DELETE /api/v1/profile/avatar/ — Delete avatar
    GET    /api/v1/profile/avatar/ — Retrieve avatar metadata and URL
    """

    permission_classes = [IsAuthenticated, IsProfileOwner]

    def get_object(self) -> Profile:
        """Get or create the profile for the requesting user."""
        return ProfileService.get_or_create_profile(self.request.user)

    def _get_ip_address(self, request: Request) -> str | None:
        """Extract the client IP address from the request."""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")

    @extend_schema(
        summary="Upload or replace avatar",
        description=(
            "Upload or replace the authenticated user's profile picture. "
            "Accepts multipart/form-data with an 'avatar' image file. "
            "Supported formats: JPG, PNG, WebP. Max size: 5MB."
        ),
        request=AvatarSerializer,
        responses={
            200: OpenApiResponse(
                description="Avatar uploaded/replaced successfully",
                response=None,
            ),
            400: OpenApiResponse(description="Invalid image or validation error"),
        },
    )
    def post(self, request: Request) -> Response:
        """Upload or replace the user's profile avatar."""
        self.get_object()

        if "avatar" not in request.data:
            return Response(
                {
                    "success": False,
                    "message": "No avatar file provided.",
                    "errors": {"avatar": ["This field is required."]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        uploaded_file = request.data["avatar"]
        file_data = uploaded_file.read()
        content_type = uploaded_file.content_type
        filename = uploaded_file.name

        try:
            result = AvatarService.upload_or_replace_avatar(
                user=request.user,
                file_data=file_data,
                content_type=content_type,
                filename=filename,
                ip_address=self._get_ip_address(request),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )
        except ImageValidationError as exc:
            AvatarService.record_upload_failure(
                user=request.user,
                reason=str(exc),
                ip_address=self._get_ip_address(request),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )
            return Response(
                {
                    "success": False,
                    "message": "Image validation failed.",
                    "errors": {"avatar": [str(exc)]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            AvatarService.record_upload_failure(
                user=request.user,
                reason=str(exc),
                ip_address=self._get_ip_address(request),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )
            return Response(
                {
                    "success": False,
                    "message": "Upload failed.",
                    "errors": {"avatar": [str(exc)]},
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(result, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Delete avatar",
        description=(
            "Delete the authenticated user's profile picture. "
            "After deletion, the platform default avatar will be served."
        ),
        responses={
            200: OpenApiResponse(
                description="Avatar deleted successfully",
                response=None,
            ),
        },
    )
    def delete(self, request: Request) -> Response:
        """Delete the user's avatar and revert to default."""
        result = AvatarService.delete_avatar(
            user=request.user,
            ip_address=self._get_ip_address(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

        return Response(result, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Get avatar info",
        description=(
            "Retrieve the authenticated user's avatar metadata and URL. "
            "Returns the avatar URL (or default avatar URL if none set)."
        ),
        responses={200: AvatarSerializer},
    )
    def get(self, request: Request) -> Response:
        """Retrieve avatar metadata and URL for the user."""
        info = AvatarService.get_avatar_info(request.user)
        return Response(info, status=status.HTTP_200_OK)
