"""Views for the Fan Onboarding & Personalization module."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from onboarding.permissions import IsOnboardingOwner
from onboarding.serializers import (
    ClubCatalogueSerializer,
    ClubSelectionResponseSerializer,
    ClubSelectionSerializer,
    CompetitionCatalogueSerializer,
    CompetitionSelectionResponseSerializer,
    CompetitionSelectionSerializer,
    CountryCatalogueSerializer,
    CountrySelectionResponseSerializer,
    CountrySelectionSerializer,
    DashboardConfigurationSerializer,
    DashboardEnvelopeResponseSerializer,
    OnboardingSerializer,
    OnboardingStatusResponseSerializer,
    SkipStepResponseSerializer,
    SkipStepSerializer,
    SportCatalogueSerializer,
    SportSelectionResponseSerializer,
    SportSelectionSerializer,
)
from onboarding.services.catalogue_service import CatalogueService
from onboarding.services.dashboard_configuration_service import (
    DashboardConfigurationService,
)
from onboarding.services.onboarding_service import OnboardingService
from onboarding.services.preference_service import PreferenceService


def get_client_ip(request: Request) -> str | None:
    """Extract the client IP address from the request."""
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0]
    return request.META.get("REMOTE_ADDR")


# =============================================================================
# Preference Catalogues
# =============================================================================


class CountryCatalogueView(generics.ListAPIView):
    """List all active countries for the preference catalogue."""

    serializer_class = CountryCatalogueSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CatalogueService.get_countries()

    def list(self, request: Request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {"success": True, "message": "Countries fetched.", "data": serializer.data},
            status=status.HTTP_200_OK,
        )


class SportCatalogueView(generics.ListAPIView):
    """List all active sports for the preference catalogue."""

    serializer_class = SportCatalogueSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CatalogueService.get_sports()

    def list(self, request: Request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {"success": True, "message": "Sports fetched.", "data": serializer.data},
            status=status.HTTP_200_OK,
        )


class CompetitionCatalogueView(generics.ListAPIView):
    """List active competitions, optionally filtered by sport."""

    serializer_class = CompetitionCatalogueSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        sport_id = self.request.query_params.get("sport")
        return CatalogueService.get_competitions(sport_id=sport_id)

    def list(self, request: Request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {"success": True, "message": "Competitions fetched.", "data": serializer.data},
            status=status.HTTP_200_OK,
        )


class ClubCatalogueView(generics.ListAPIView):
    """List active clubs, optionally filtered by competition."""

    serializer_class = ClubCatalogueSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        competition_id = self.request.query_params.get("competition")
        return CatalogueService.get_clubs(competition_id=competition_id)

    def list(self, request: Request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {"success": True, "message": "Clubs fetched.", "data": serializer.data},
            status=status.HTTP_200_OK,
        )


# =============================================================================
# Onboarding
# =============================================================================


class OnboardingStatusView(APIView):
    """Return the current onboarding status and saved preferences."""

    serializer_class = OnboardingSerializer
    permission_classes = [IsAuthenticated, IsOnboardingOwner]

    @extend_schema(
        summary="Get onboarding status",
        responses=OnboardingStatusResponseSerializer,
    )
    def get(self, request: Request) -> Response:
        onboarding = OnboardingService.get_onboarding_status(request.user)
        serializer = OnboardingSerializer(
            onboarding,
            context={
                "request": request,
                "preferred_country": PreferenceService.get_preferred_country(request.user),
                "favourite_sports": PreferenceService.get_user_sports(request.user),
                "favourite_competitions": PreferenceService.get_user_competitions(request.user),
                "favourite_clubs": PreferenceService.get_user_clubs(request.user),
            },
        )
        return Response(
            {"success": True, "message": "Onboarding status fetched.", "data": serializer.data},
            status=status.HTTP_200_OK,
        )


class CountrySelectionView(APIView):
    """Select the user's preferred country during onboarding."""

    serializer_class = CountrySelectionSerializer
    permission_classes = [IsAuthenticated, IsOnboardingOwner]

    @extend_schema(
        summary="Select preferred country",
        request=CountrySelectionSerializer,
        responses=CountrySelectionResponseSerializer,
    )
    def post(self, request: Request) -> Response:
        serializer = CountrySelectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        country = serializer.context["country"]

        PreferenceService.select_country(request.user, country, ip_address=get_client_ip(request))
        onboarding = OnboardingService.get_or_create_onboarding(
            request.user, ip_address=get_client_ip(request)
        )
        OnboardingService.advance_step(onboarding, onboarding.Step.COUNTRY)

        return Response(
            {
                "success": True,
                "message": "Country selected successfully.",
                "data": {
                    "country": CountryCatalogueSerializer(country).data,
                    "current_step": onboarding.current_step,
                    "completed": onboarding.completed,
                },
            },
            status=status.HTTP_200_OK,
        )


class SportSelectionView(APIView):
    """Select the user's favourite sports during onboarding."""

    serializer_class = SportSelectionSerializer
    permission_classes = [IsAuthenticated, IsOnboardingOwner]

    @extend_schema(
        summary="Select favourite sports",
        request=SportSelectionSerializer,
        responses=SportSelectionResponseSerializer,
    )
    def post(self, request: Request) -> Response:
        serializer = SportSelectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sports = serializer.context["sports"]

        PreferenceService.select_sports(request.user, sports, ip_address=get_client_ip(request))
        onboarding = OnboardingService.get_or_create_onboarding(
            request.user, ip_address=get_client_ip(request)
        )
        OnboardingService.advance_step(onboarding, onboarding.Step.SPORTS)

        return Response(
            {
                "success": True,
                "message": "Favourite sports selected successfully.",
                "data": {
                    "sports": SportCatalogueSerializer(sports, many=True).data,
                    "current_step": onboarding.current_step,
                    "completed": onboarding.completed,
                },
            },
            status=status.HTTP_200_OK,
        )


class CompetitionSelectionView(APIView):
    """Select the user's favourite competitions during onboarding."""

    serializer_class = CompetitionSelectionSerializer
    permission_classes = [IsAuthenticated, IsOnboardingOwner]

    @extend_schema(
        summary="Select favourite competitions",
        request=CompetitionSelectionSerializer,
        responses=CompetitionSelectionResponseSerializer,
    )
    def post(self, request: Request) -> Response:
        serializer = CompetitionSelectionSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        competitions = serializer.context["competitions"]

        PreferenceService.select_competitions(
            request.user, competitions, ip_address=get_client_ip(request)
        )
        onboarding = OnboardingService.get_or_create_onboarding(
            request.user, ip_address=get_client_ip(request)
        )
        OnboardingService.advance_step(onboarding, onboarding.Step.COMPETITIONS)

        return Response(
            {
                "success": True,
                "message": "Favourite competitions selected successfully.",
                "data": {
                    "competitions": CompetitionCatalogueSerializer(competitions, many=True).data,
                    "current_step": onboarding.current_step,
                    "completed": onboarding.completed,
                },
            },
            status=status.HTTP_200_OK,
        )


class ClubSelectionView(APIView):
    """Select the user's favourite clubs during onboarding."""

    serializer_class = ClubSelectionSerializer
    permission_classes = [IsAuthenticated, IsOnboardingOwner]

    @extend_schema(
        summary="Select favourite clubs",
        request=ClubSelectionSerializer,
        responses=ClubSelectionResponseSerializer,
    )
    def post(self, request: Request) -> Response:
        serializer = ClubSelectionSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        clubs = serializer.context["clubs"]

        PreferenceService.select_clubs(request.user, clubs, ip_address=get_client_ip(request))
        onboarding = OnboardingService.get_or_create_onboarding(
            request.user, ip_address=get_client_ip(request)
        )
        OnboardingService.advance_step(onboarding, onboarding.Step.CLUBS)

        return Response(
            {
                "success": True,
                "message": "Favourite clubs selected successfully.",
                "data": {
                    "clubs": ClubCatalogueSerializer(clubs, many=True).data,
                    "current_step": onboarding.current_step,
                    "completed": onboarding.completed,
                },
            },
            status=status.HTTP_200_OK,
        )


class SkipStepView(APIView):
    """Skip an onboarding step."""

    serializer_class = SkipStepSerializer
    permission_classes = [IsAuthenticated, IsOnboardingOwner]

    @extend_schema(
        summary="Skip onboarding step",
        request=SkipStepSerializer,
        responses=SkipStepResponseSerializer,
    )
    def post(self, request: Request) -> Response:
        serializer = SkipStepSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        step = serializer.validated_data["step"]

        onboarding = OnboardingService.skip_step(
            request.user, step, ip_address=get_client_ip(request)
        )

        return Response(
            {
                "success": True,
                "message": f"Step '{step}' skipped.",
                "data": {
                    "current_step": onboarding.current_step,
                    "completed": onboarding.completed,
                    "skipped_steps": onboarding.skipped_steps,
                },
            },
            status=status.HTTP_200_OK,
        )


class CompleteOnboardingView(APIView):
    """Complete the onboarding flow and return the dashboard configuration."""

    serializer_class = DashboardConfigurationSerializer
    permission_classes = [IsAuthenticated, IsOnboardingOwner]

    @extend_schema(
        summary="Complete onboarding",
        responses=DashboardEnvelopeResponseSerializer,
    )
    def post(self, request: Request) -> Response:
        onboarding = OnboardingService.complete_onboarding(
            request.user, ip_address=get_client_ip(request)
        )
        configuration = DashboardConfigurationService.generate_dashboard_configuration(
            request.user, ip_address=get_client_ip(request)
        )
        serializer = DashboardConfigurationSerializer(configuration)

        return Response(
            {
                "success": True,
                "message": "Onboarding completed successfully.",
                "data": {
                    "configuration": serializer.data,
                    "current_step": onboarding.current_step,
                    "completed": onboarding.completed,
                },
            },
            status=status.HTTP_200_OK,
        )


class DashboardConfigurationView(APIView):
    """Return the personalized dashboard configuration."""

    serializer_class = DashboardConfigurationSerializer
    permission_classes = [IsAuthenticated, IsOnboardingOwner]

    @extend_schema(
        summary="Get dashboard configuration",
        responses=DashboardEnvelopeResponseSerializer,
    )
    def get(self, request: Request) -> Response:
        configuration = DashboardConfigurationService.generate_dashboard_configuration(
            request.user, ip_address=get_client_ip(request)
        )
        serializer = DashboardConfigurationSerializer(configuration)
        onboarding = OnboardingService.get_onboarding_status(request.user)

        return Response(
            {
                "success": True,
                "message": "Dashboard configuration generated.",
                "data": {
                    "configuration": serializer.data,
                    "current_step": onboarding.current_step,
                    "completed": onboarding.completed,
                },
            },
            status=status.HTTP_200_OK,
        )
