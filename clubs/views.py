"""Views for club management."""

from __future__ import annotations

from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from discovery.models import News
from discovery.serializers import NewsModerationSerializer, NewsSubmissionSerializer
from discovery.services.news_moderation_service import news_moderation_service
from profiles.services.club_logo_service import club_logo_service
from profiles.services.image_validation_service import ValidationError as ImageValidationError
from clubs.models import (
    ClubAuditLog,
    ClubMedia,
    ClubNews,
    ClubProfileVersion,
    ClubWorkspace,
    MembershipPlan,
    MerchandiseProduct,
    ProductCategory,
    StaffInvitation,
    StoreOrder,
    TicketProduct,
)
from clubs.permissions import IsClubAdmin, IsClubStaff
from clubs.services.club_admin_invitation_service import ClubAdminInvitationService
from clubs.services.staff_service import StaffService
from clubs.serializers.club_serializers import (
    ClubAdminInviteSerializer,
    ClubAuditLogSerializer,
    ClubLogoResponseSerializer,
    ClubLogoUploadSerializer,
    ClubMediaSerializer,
    ClubNewsSerializer,
    ClubProfileVersionSerializer,
    ClubWorkspaceSerializer,
    MembershipPlanSerializer,
    MerchandiseProductSerializer,
    ProductCategorySerializer,
    StaffInvitationAcceptSerializer,
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

    @action(detail=True, methods=["post"], permission_classes=[IsClubStaff])
    def publish(self, request, club_pk=None, pk=None):
        profile = self.get_object()
        from clubs.services.club_profile_service import ClubProfileService

        published = ClubProfileService.publish_profile(profile, request.user)
        serializer = self.get_serializer(published)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], permission_classes=[IsClubStaff])
    def schedule(self, request, club_pk=None, pk=None):
        profile = self.get_object()
        scheduled_at = request.data.get("scheduled_at")
        if not scheduled_at:
            return Response(
                {"scheduled_at": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            scheduled_dt = timezone.datetime.fromisoformat(scheduled_at)
            if scheduled_dt <= timezone.now():
                return Response(
                    {"scheduled_at": "Scheduled time must be in the future."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except (ValueError, TypeError):
            return Response(
                {"scheduled_at": "Invalid datetime format."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from clubs.services.club_profile_service import ClubProfileService

        scheduled = ClubProfileService.schedule_profile(profile, scheduled_dt, request.user)
        serializer = self.get_serializer(scheduled)
        return Response(serializer.data, status=status.HTTP_200_OK)


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

    @action(detail=True, methods=["post"], permission_classes=[IsClubStaff])
    def publish(self, request, club_pk=None, pk=None):
        media = self.get_object()
        from clubs.services.media_service import MediaService

        published = MediaService.publish_media(media, request.user)
        serializer = self.get_serializer(published)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], permission_classes=[IsClubStaff])
    def schedule(self, request, club_pk=None, pk=None):
        media = self.get_object()
        scheduled_at = request.data.get("scheduled_at")
        if not scheduled_at:
            return Response(
                {"scheduled_at": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            scheduled_dt = timezone.datetime.fromisoformat(scheduled_at)
            if scheduled_dt <= timezone.now():
                return Response(
                    {"scheduled_at": "Scheduled time must be in the future."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except (ValueError, TypeError):
            return Response(
                {"scheduled_at": "Invalid datetime format."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from clubs.services.media_service import MediaService

        scheduled = MediaService.schedule_media(media, scheduled_dt, request.user)
        serializer = self.get_serializer(scheduled)
        return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(operation_id="api_v1_club_news_list"),
    retrieve=extend_schema(operation_id="api_v1_club_news_retrieve"),
)
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

    @action(detail=True, methods=["post"], permission_classes=[IsClubStaff])
    def publish(self, request, club_pk=None, pk=None):
        news = self.get_object()
        from clubs.services.news_service import NewsService

        published = NewsService.publish_news(news, request.user)
        serializer = self.get_serializer(published)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], permission_classes=[IsClubStaff])
    def schedule(self, request, club_pk=None, pk=None):
        news = self.get_object()
        scheduled_at = request.data.get("scheduled_at")
        if not scheduled_at:
            return Response(
                {"scheduled_at": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            scheduled_dt = timezone.datetime.fromisoformat(scheduled_at)
            if scheduled_dt <= timezone.now():
                return Response(
                    {"scheduled_at": "Scheduled time must be in the future."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except (ValueError, TypeError):
            return Response(
                {"scheduled_at": "Invalid datetime format."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from clubs.services.news_service import NewsService

        scheduled = NewsService.schedule_news(news, scheduled_dt, request.user)
        serializer = self.get_serializer(scheduled)
        return Response(serializer.data, status=status.HTTP_200_OK)


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


class ProductCategoryViewSet(viewsets.ModelViewSet):
    serializer_class = ProductCategorySerializer
    permission_classes = [IsClubStaff]

    def get_queryset(self):
        return ProductCategory.objects.filter(club_id=self.kwargs.get("club_pk")).order_by(
            "display_order", "name"
        )

    def perform_create(self, serializer):
        club_id = self.kwargs.get("club_pk")
        club = Club.objects.get(id=club_id)
        serializer.save(club=club)


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


class NewsSubmissionView(generics.ListCreateAPIView):
    """Club-side submission into the real discovery.News moderation pipeline
    (distinct from ClubNewsViewSet's orphaned ClubNews model above — this is
    what Sports Data & Statistics Admin / Super Admin actually review)."""

    permission_classes = [IsClubStaff]

    def get_queryset(self):
        return (
            News.objects.filter(club_id=self.kwargs.get("club_pk"))
            .select_related("category", "sport", "competition")
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        return (
            NewsModerationSerializer if self.request.method == "GET" else NewsSubmissionSerializer
        )

    def create(self, request, *args, **kwargs):
        serializer = NewsSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        club = Club.objects.get(id=self.kwargs["club_pk"])
        news = news_moderation_service.submit_for_review(
            club=club,
            created_by=request.user,
            **serializer.validated_data,
        )

        from clubs.services.audit_service import club_audit_service

        club_audit_service.record(
            "NEWS_SUBMITTED",
            club,
            request.user,
            entity_type="news",
            entity_id=news.id,
            request=request,
            metadata={"title": news.title},
        )

        return Response(NewsModerationSerializer(news).data, status=status.HTTP_201_CREATED)


class ClubLogoView(APIView):
    """Upload, replace, or delete a club's logo. IsClubAdmin already covers
    both cases this needs: the club's own Club Admin (via workspace check),
    and a Super Admin / admin.clubs.manage holder for any club — including
    right after creating one, before any workspace exists."""

    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsClubAdmin]
    serializer_class = ClubLogoUploadSerializer

    def _get_ip_address(self, request) -> str | None:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")

    @extend_schema(
        summary="Upload or replace a club's logo",
        request=ClubLogoUploadSerializer,
        responses={200: ClubLogoResponseSerializer, 400: None, 403: None, 404: None},
        tags=["Clubs"],
    )
    def post(self, request, club_pk=None):
        club = Club.objects.filter(id=club_pk).first()
        if not club:
            return Response({"detail": "Club not found."}, status=status.HTTP_404_NOT_FOUND)

        if "logo" not in request.data:
            return Response(
                {
                    "success": False,
                    "message": "No logo file provided.",
                    "errors": {"logo": ["This field is required."]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        uploaded_file = request.data["logo"]

        try:
            result = club_logo_service.upload_or_replace_logo(
                club=club,
                file_data=uploaded_file.read(),
                content_type=uploaded_file.content_type,
                filename=uploaded_file.name,
                actor=request.user,
                ip_address=self._get_ip_address(request),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )
        except ImageValidationError as exc:
            return Response(
                {
                    "success": False,
                    "message": "Image validation failed.",
                    "errors": {"logo": [str(exc)]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"success": True, **result}, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Delete a club's logo",
        responses={200: None, 403: None, 404: None},
        tags=["Clubs"],
    )
    def delete(self, request, club_pk=None):
        club = Club.objects.filter(id=club_pk).first()
        if not club:
            return Response({"detail": "Club not found."}, status=status.HTTP_404_NOT_FOUND)

        club_logo_service.delete_logo(
            club=club,
            actor=request.user,
            ip_address=self._get_ip_address(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        return Response({"success": True}, status=status.HTTP_200_OK)


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


class ClubAdminInviteView(APIView):
    """Invites the first (or another) Club Admin for a club end to end —
    creates the StaffInvitation and, for a brand-new email, also a pending
    account + setup-link email (see ClubAdminInvitationService). Separate
    from StaffInvitationViewSet.create, which only records a generic staff
    invitation and assumes the invitee can already log in to accept it."""

    permission_classes = [IsClubAdmin]

    @extend_schema(
        request=ClubAdminInviteSerializer,
        responses={201: StaffInvitationSerializer},
        tags=["Clubs"],
    )
    def post(self, request, club_pk=None):
        club = Club.objects.get(id=club_pk)
        serializer = ClubAdminInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        invitation = ClubAdminInvitationService.invite(
            club=club,
            login_email=serializer.validated_data["login_email"],
            notify_email=serializer.validated_data["notify_email"],
            invited_by=request.user,
        )
        return Response(
            StaffInvitationSerializer(invitation).data,
            status=status.HTTP_201_CREATED,
        )


class StaffInvitationAcceptView(APIView):
    """Accepts a StaffInvitation by token, granting the requesting user a
    ClubWorkspace (and, for ADMIN invitations, the platform Club Admin
    role — see StaffService.accept_invitation)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=StaffInvitationAcceptSerializer,
        responses={200: ClubWorkspaceSerializer},
        tags=["Clubs"],
    )
    def post(self, request):
        token = request.data.get("token")
        if not token:
            return Response({"detail": "token is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            workspace = StaffService.accept_invitation(token=token, user=request.user)
        except ValueError as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ClubWorkspaceSerializer(workspace).data, status=status.HTTP_200_OK)


# =============================================================================
# Match Data Upload (Club Admin CSV import)
# =============================================================================


class ClubFixtureListView(APIView):
    """Return fixtures that involve the requesting Club Admin's club.

    Used to populate the fixture-picker dropdown before uploading a CSV.

    GET /api/v1/<club_pk>/match-data/fixtures/
    """

    permission_classes = [IsClubAdmin]

    @extend_schema(
        tags=["Club Match Data"],
        summary="List fixtures available for match data upload",
        responses={200: {"type": "array", "items": {"type": "object"}}},
    )
    def get(self, request, club_pk=None):
        club = _get_club_or_404(club_pk)

        from discovery.models import ClubProfile
        from sports.models import EventParticipant, Participant, SportingEvent

        # Collect all participant IDs (ATHLETE + TEAM) linked to this club
        athlete_ids = set(
            Participant.objects.filter(
                player_profile__club=club
            ).values_list("id", flat=True)
        )

        # Events where any of the club's athletes participate directly
        fixture_ids_via_athletes = set(
            EventParticipant.objects.filter(
                participant_id__in=athlete_ids
            ).values_list("event_id", flat=True)
        )

        # Events in the club's league (ClubProfile.league)
        club_profile = ClubProfile.objects.filter(club=club).first()
        league_id = club_profile.league_id if club_profile else None
        fixture_ids_via_league: set = set()
        if league_id:
            fixture_ids_via_league = set(
                SportingEvent.objects.filter(
                    competition_id=league_id
                ).values_list("id", flat=True)
            )

        all_fixture_ids = fixture_ids_via_athletes | fixture_ids_via_league

        fixtures = (
            SportingEvent.objects.filter(
                id__in=all_fixture_ids,
            )
            .select_related("competition")
            .prefetch_related("event_participants__participant")
            .order_by("-starts_at")
        )

        data = []
        for f in fixtures:
            participants = list(f.event_participants.select_related("participant").all())
            home_team = next(
                (ep.participant.name for ep in participants if ep.role == "HOME"), None
            )
            away_team = next(
                (ep.participant.name for ep in participants if ep.role == "AWAY"), None
            )
            data.append(
                {
                    "id": str(f.id),
                    "name": f.name,
                    "starts_at": f.starts_at,
                    "status": f.status,
                    "competition": f.competition.name if f.competition else None,
                    "home_team": home_team,
                    "away_team": away_team,
                }
            )

        return Response(data, status=status.HTTP_200_OK)


class ClubMatchDataUploadView(APIView):
    """Accept a CSV file and import match player statistics for a fixture.

    The entire file is validated before any row is written.  On success,
    ``SportsFeedService.complete_ingestion()`` is called inside the same
    ``transaction.atomic()`` block, which schedules
    ``score_affected_gameweeks.delay()`` via ``transaction.on_commit()``.
    The Club Admin never needs to click Recalculate.

    POST /api/v1/<club_pk>/match-data/upload/
    Content-Type: multipart/form-data
    Body: file=<csv>
    """

    permission_classes = [IsClubAdmin]

    @extend_schema(
        tags=["Club Match Data"],
        summary="Upload match player statistics CSV",
        request={"multipart/form-data": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}}},
        responses={
            202: {"description": "Import accepted; fantasy scoring scheduled."},
            400: {"description": "Validation failure with row-level errors."},
        },
    )
    def post(self, request, club_pk=None):
        from clubs.serializers.match_data_serializers import MatchDataUploadSerializer
        from clubs.services.match_data_service import import_csv_for_club

        club = _get_club_or_404(club_pk)

        serializer = MatchDataUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        result = import_csv_for_club(
            file_obj=serializer.validated_data["file"],
            club=club,
            uploaded_by=request.user,
        )

        if not result.success:
            payload = {
                "success": False,
                "message": result.message,
                "records_received": result.records_received,
                "row_errors": result.row_errors,
            }
            return Response(payload, status=status.HTTP_400_BAD_REQUEST)

        payload = {
            "success": True,
            "message": result.message,
            "records_received": result.records_received,
            "records_processed": result.records_processed,
            "ingestion_id": result.ingestion_id,
            "fixture_ids": result.fixture_ids,
        }
        return Response(payload, status=status.HTTP_202_ACCEPTED)


class ClubMatchDataTemplateView(APIView):
    """Return a downloadable CSV template for the Club Admin.

    GET /api/v1/<club_pk>/match-data/template/

    Optionally pass ?sport=<sport_slug_or_name> to get sport-specific
    example stat_type values.
    """

    permission_classes = [IsClubAdmin]

    @extend_schema(
        tags=["Club Match Data"],
        summary="Download CSV template for match data upload",
        responses={200: {"description": "CSV file download."}},
    )
    def get(self, request, club_pk=None):
        from django.http import HttpResponse

        from clubs.services.match_data_service import generate_csv_template
        from sports.models import Sport

        _get_club_or_404(club_pk)  # permission check: club must exist

        sport_param = request.query_params.get("sport", "")
        sport = None
        if sport_param:
            sport = (
                Sport.objects.filter(slug__iexact=sport_param).first()
                or Sport.objects.filter(name__iexact=sport_param).first()
            )

        csv_content = generate_csv_template(sport=sport)
        response = HttpResponse(csv_content, content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="match_data_template.csv"'
        return response


# ---------------------------------------------------------------------------
# Internal helper used by the three views above
# ---------------------------------------------------------------------------


def _get_club_or_404(club_pk):
    """Return the Club instance or raise Http404."""
    from django.http import Http404

    try:
        return Club.objects.get(id=club_pk)
    except Club.DoesNotExist:
        raise Http404(f"Club {club_pk} not found.")
