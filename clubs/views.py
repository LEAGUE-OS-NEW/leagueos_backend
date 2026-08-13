"""Views for club management."""

from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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
from clubs.services.staff_service import StaffService
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
        # Goes through StaffService.invite_staff rather than a plain
        # serializer.save() so the audit log entry and invitation email
        # (see StaffService.invite_staff) both actually happen.
        invitation = StaffService.invite_staff(
            club=club,
            email=serializer.validated_data["email"],
            role=serializer.validated_data["role"],
            invited_by=self.request.user,
            permissions=serializer.validated_data.get("permissions"),
        )
        serializer.instance = invitation


class StaffInvitationAcceptView(APIView):
    """Accepts a StaffInvitation by token, granting the requesting user a
    ClubWorkspace (and, for ADMIN invitations, the platform Club Admin
    role — see StaffService.accept_invitation)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get("token")
        if not token:
            return Response({"detail": "token is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            workspace = StaffService.accept_invitation(token=token, user=request.user)
        except ValueError as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ClubWorkspaceSerializer(workspace).data, status=status.HTTP_200_OK)
