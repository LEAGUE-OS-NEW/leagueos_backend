from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from markets.models import MarketResponsibleParticipation, MarketResponsibleParticipationEvent
from markets.permissions import HasManageCompliancePermission
from markets.responsible_participation_serializers import (
    AdminResponsibleStatusSerializer,
    AdminResponsibleUpdateSerializer,
    DurationSerializer,
    ParticipantLimitsUpdateSerializer,
    ParticipantResponsibleEventSerializer,
    ResponsibleEventSerializer,
    ResponsibleStatusSerializer,
    SelfExclusionSerializer,
)
from markets.services.responsible_participation_service import MarketResponsibleParticipationService
from system.pagination import PublicCatalogPagination


def status_data(participant, *, admin=False):
    controls = MarketResponsibleParticipation.objects.filter(participant=participant).first()
    result = MarketResponsibleParticipationService.status(
        participant=participant, controls=controls
    )
    data = {
        "limits": result.limits,
        "utilization": result.utilization(),
        "cooling_off_until": controls.cooling_off_until if controls else None,
        "cooling_off_active": result.cooling_off_active,
        "self_exclusion_until": controls.self_exclusion_until if controls else None,
        "self_exclusion_active": result.self_exclusion_active,
        "self_excluded_indefinitely": controls.self_excluded_indefinitely if controls else False,
        "administrative_block_active": result.administrative_block_active,
        "buy_allowed": result.buy_allowed,
        "sell_allowed": result.sell_allowed,
        "participation_allowed": result.buy_allowed or result.sell_allowed,
        "buy_reason_codes": result.buy_reason_codes,
        "sell_reason_codes": result.sell_reason_codes,
        "next_actions": result.next_actions,
        "evaluated_at": result.evaluated_at,
    }
    if admin:
        data.update(
            {
                "participant_id": participant.id,
                "administrative_block_until": (
                    controls.administrative_block_until if controls else None
                ),
                "administrative_block_reason": (
                    controls.administrative_block_reason if controls else ""
                ),
                "reviewed_by": controls.reviewed_by_id if controls else None,
                "reviewed_at": controls.reviewed_at if controls else None,
            }
        )
    return data


def service_error(error):
    raise ValidationError({"code": str(error)}) from error


class ResponsibleParticipationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=ResponsibleStatusSerializer, tags=["Market Responsible Participation"])
    def get(self, request):
        return Response(status_data(request.user))

    @extend_schema(
        request=ParticipantLimitsUpdateSerializer,
        responses=ResponsibleStatusSerializer,
        tags=["Market Responsible Participation"],
    )
    def patch(self, request):
        serializer = ParticipantLimitsUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            MarketResponsibleParticipationService.update_participant_limits(
                participant=request.user, changes=serializer.validated_data
            )
        except ValueError as error:
            service_error(error)
        return Response(status_data(request.user))


class CoolingOffView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=DurationSerializer,
        responses=ResponsibleStatusSerializer,
        tags=["Market Responsible Participation"],
    )
    def post(self, request):
        serializer = DurationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            MarketResponsibleParticipationService.start_cooling_off(
                participant=request.user, duration=serializer.validated_data["duration"]
            )
        except ValueError as error:
            service_error(error)
        return Response(status_data(request.user), status=status.HTTP_200_OK)


class SelfExclusionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=SelfExclusionSerializer,
        responses=ResponsibleStatusSerializer,
        tags=["Market Responsible Participation"],
    )
    def post(self, request):
        serializer = SelfExclusionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            MarketResponsibleParticipationService.start_self_exclusion(
                participant=request.user, duration=serializer.validated_data["duration"]
            )
        except ValueError as error:
            service_error(error)
        return Response(status_data(request.user))


class ParticipantResponsibleEventListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ParticipantResponsibleEventSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        return MarketResponsibleParticipationEvent.objects.filter(
            participant=self.request.user
        ).order_by("-created_at", "-id")


class AdminResponsibleParticipationView(APIView):
    permission_classes = [IsAuthenticated, HasManageCompliancePermission]

    def participant(self, user_id):
        return get_object_or_404(get_user_model(), id=user_id)

    @extend_schema(
        responses=AdminResponsibleStatusSerializer,
        tags=["Market Responsible Participation Admin"],
    )
    def get(self, request, user_id):
        return Response(status_data(self.participant(user_id), admin=True))

    @extend_schema(
        request=AdminResponsibleUpdateSerializer,
        responses=AdminResponsibleStatusSerializer,
        tags=["Market Responsible Participation Admin"],
    )
    def patch(self, request, user_id):
        serializer = AdminResponsibleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        reason = values.pop("reason")
        try:
            MarketResponsibleParticipationService.update_admin(
                participant=self.participant(user_id),
                actor=request.user,
                changes=values,
                reason=reason,
            )
        except ValueError as error:
            service_error(error)
        return Response(status_data(self.participant(user_id), admin=True))


class AdminResponsibleEventListView(ListAPIView):
    permission_classes = [IsAuthenticated, HasManageCompliancePermission]
    serializer_class = ResponsibleEventSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        return (
            MarketResponsibleParticipationEvent.objects.filter(
                participant_id=self.kwargs["user_id"]
            )
            .select_related("participant", "actor")
            .order_by("-created_at", "-id")
        )
