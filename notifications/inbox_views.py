from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.generics import GenericAPIView, ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from notifications.models import Notification
from notifications.serializers import (
    NotificationIdsSerializer,
    NotificationSerializer,
    UnreadCountSerializer,
    UpdatedCountSerializer,
)
from system.pagination import PublicCatalogPagination


class InboxListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        q = Notification.objects.filter(
            recipient=self.request.user, archived_at__isnull=True
        ).select_related("category")
        p = self.request.query_params
        if p.get("category"):
            if (
                not q.model._meta.get_field("category")
                .related_model.objects.filter(code=p["category"], is_active=True)
                .exists()
            ):
                raise serializers.ValidationError({"category": "Invalid category."})
            q = q.filter(category__code=p["category"])
        if p.get("event_type"):
            q = q.filter(event_type=p["event_type"])
        if p.get("read"):
            if p["read"] not in ("true", "false"):
                raise serializers.ValidationError({"read": "Use true or false."})
            q = q.filter(read_at__isnull=p["read"] == "false")
        if p.get("from"):
            value = serializers.DateTimeField().run_validation(p["from"])
            q = q.filter(occurred_at__gte=value)
        if p.get("to"):
            value = serializers.DateTimeField().run_validation(p["to"])
            q = q.filter(occurred_at__lte=value)
        return q


class InboxDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer
    lookup_url_kwarg = "notification_id"

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user).select_related("category")


class UnreadCountView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UnreadCountSerializer

    @extend_schema(responses=UnreadCountSerializer, operation_id="notification_inbox_unread_count")
    def get(self, request):
        return Response(
            {
                "unread_count": Notification.objects.filter(
                    recipient=request.user, read_at__isnull=True, archived_at__isnull=True
                ).count()
            }
        )


class MarkReadView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    @extend_schema(
        request=None, responses=NotificationSerializer, operation_id="notification_inbox_mark_read"
    )
    def post(self, request, notification_id):
        note = get_object_or_404(Notification, id=notification_id, recipient=request.user)
        if note.read_at is None:
            note.read_at = timezone.now()
            note.save(update_fields=["read_at"])
        return Response(NotificationSerializer(note).data)


class MarkMultipleReadView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationIdsSerializer

    @extend_schema(
        request=NotificationIdsSerializer,
        responses=UpdatedCountSerializer,
        operation_id="notification_inbox_mark_multiple_read",
    )
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        count = Notification.objects.filter(
            recipient=request.user, id__in=serializer.validated_data["ids"], read_at__isnull=True
        ).update(read_at=timezone.now())
        return Response({"updated": count})


class MarkAllReadView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses=UpdatedCountSerializer,
        operation_id="notification_inbox_mark_all_read",
    )
    def post(self, request):
        count = Notification.objects.filter(
            recipient=request.user, read_at__isnull=True, archived_at__isnull=True
        ).update(read_at=timezone.now())
        return Response({"updated": count})


class ArchiveView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    @extend_schema(
        request=None, responses=NotificationSerializer, operation_id="notification_inbox_archive"
    )
    def post(self, request, notification_id):
        note = get_object_or_404(Notification, id=notification_id, recipient=request.user)
        if note.archived_at is None:
            note.archived_at = timezone.now()
            note.save(update_fields=["archived_at"])
        return Response(NotificationSerializer(note).data)
