"""Views for club management."""

from __future__ import annotations

import uuid

from django.utils import timezone
from rest_framework import viewsets

from clubs.models import (
    ClubAuditLog,
    ClubMedia,
    ClubNews,
    ClubProfileVersion,
    ClubWorkspace,
    MembershipPlan,
    MerchandiseProduct,
    StaffInvitation,
    StoreOrder,
    TicketProduct,
)
from clubs.permissions import IsClubAdmin, IsClubStaff
from clubs.serializers.club_serializers import (
    ClubAuditLogSerializer,
    ClubMediaSerializer,
    ClubNewsSerializer,
    ClubProfileVersionSerializer,
    ClubWorkspaceSerializer,
    MembershipPlanSerializer,
    MerchandiseProductSerializer,
    StaffInvitationSerializer,
    StoreOrderSerializer,
    TicketProductSerializer,
)
from profiles.models import Club


class ClubWorkspaceViewSet(viewsets.ModelViewSet):
    serializer_class = ClubWorkspaceSerializer
    permission_classes = [IsClubAdmin]

    def get_queryset(self):
        return ClubWorkspace.objects.filter(club_id=self.kwargs.get("club_pk")).select_related(
            "user", "club"
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        club_id = self.kwargs.get("club_pk")
        if club_id:
            context["club"] = Club.objects.get(id=club_id)
        return context

    def perform_create(self, serializer):
        club_id = self.kwargs.get("club_pk")
        club = Club.objects.get(id=club_id)
        serializer.save(club=club)


class ClubProfileVersionViewSet(viewsets.ModelViewSet):
    serializer_class = ClubProfileVersionSerializer
    permission_classes = [IsClubStaff]

    def get_queryset(self):
        return ClubProfileVersion.objects.filter(club_id=self.kwargs.get("club_pk")).order_by(
            "-version"
        )

    def perform_create(self, serializer):
        club_id = self.kwargs.get("club_pk")
        club = Club.objects.get(id=club_id)
        next_version = (
            ClubProfileVersion.objects.filter(club=club)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
            or 0
        ) + 1
        serializer.save(club=club, version=next_version, created_by=self.request.user)


class ClubMediaViewSet(viewsets.ModelViewSet):
    serializer_class = ClubMediaSerializer
    permission_classes = [IsClubStaff]

    def get_queryset(self):
        return ClubMedia.objects.filter(club_id=self.kwargs.get("club_pk")).order_by(
            "display_order", "-created_at"
        )

    def perform_create(self, serializer):
        club_id = self.kwargs.get("club_pk")
        club = Club.objects.get(id=club_id)
        serializer.save(club=club, uploaded_by=self.request.user)


class ClubNewsViewSet(viewsets.ModelViewSet):
    serializer_class = ClubNewsSerializer
    permission_classes = [IsClubStaff]

    def get_queryset(self):
        return ClubNews.objects.filter(club_id=self.kwargs.get("club_pk")).order_by(
            "-published_at", "-created_at"
        )

    def perform_create(self, serializer):
        club_id = self.kwargs.get("club_pk")
        club = Club.objects.get(id=club_id)
        serializer.save(club=club, created_by=self.request.user)


class MembershipPlanViewSet(viewsets.ModelViewSet):
    serializer_class = MembershipPlanSerializer
    permission_classes = [IsClubStaff]

    def get_queryset(self):
        return MembershipPlan.objects.filter(club_id=self.kwargs.get("club_pk")).order_by(
            "-is_featured", "name"
        )

    def perform_create(self, serializer):
        club_id = self.kwargs.get("club_pk")
        club = Club.objects.get(id=club_id)
        serializer.save(club=club, created_by=self.request.user)


class TicketProductViewSet(viewsets.ModelViewSet):
    serializer_class = TicketProductSerializer
    permission_classes = [IsClubStaff]

    def get_queryset(self):
        return TicketProduct.objects.filter(club_id=self.kwargs.get("club_pk")).order_by(
            "-created_at"
        )

    def perform_create(self, serializer):
        club_id = self.kwargs.get("club_pk")
        club = Club.objects.get(id=club_id)
        serializer.save(club=club, created_by=self.request.user)


class MerchandiseProductViewSet(viewsets.ModelViewSet):
    serializer_class = MerchandiseProductSerializer
    permission_classes = [IsClubStaff]

    def get_queryset(self):
        return MerchandiseProduct.objects.filter(club_id=self.kwargs.get("club_pk")).order_by(
            "-is_featured", "name"
        )

    def perform_create(self, serializer):
        club_id = self.kwargs.get("club_pk")
        club = Club.objects.get(id=club_id)
        serializer.save(club=club, created_by=self.request.user)


class StoreOrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StoreOrderSerializer
    permission_classes = [IsClubStaff]

    def get_queryset(self):
        return StoreOrder.objects.filter(club_id=self.kwargs.get("club_pk")).order_by("-created_at")


class ClubAuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ClubAuditLogSerializer
    permission_classes = [IsClubAdmin]

    def get_queryset(self):
        return ClubAuditLog.objects.filter(club_id=self.kwargs.get("club_pk")).order_by(
            "-created_at"
        )


class StaffInvitationViewSet(viewsets.ModelViewSet):
    serializer_class = StaffInvitationSerializer
    permission_classes = [IsClubAdmin]

    def get_queryset(self):
        return StaffInvitation.objects.filter(club_id=self.kwargs.get("club_pk")).order_by(
            "-created_at"
        )

    def perform_create(self, serializer):
        club_id = self.kwargs.get("club_pk")
        club = Club.objects.get(id=club_id)
        serializer.save(
            club=club,
            invited_by=self.request.user,
            token=uuid.uuid4().hex,
            expires_at=timezone.now() + timezone.timedelta(days=7),
        )
