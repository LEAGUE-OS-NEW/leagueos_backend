from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.generics import GenericAPIView, ListAPIView, RetrieveAPIView
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from authentication.services.permission_service import PermissionService
from notifications.models import Notification
from notifications.serializers import NotificationSerializer, UnreadCountSerializer
from system.pagination import PublicCatalogPagination


class HasOperationalAlertPermission(BasePermission):
    def has_permission(self, request, view):
        return PermissionService.has_any_permission(
            request.user, ("manage_compliance", "manage_market", "approve_market")
        )


class AdminAlertMixin:
    permission_classes = [HasOperationalAlertPermission]

    def alerts(self):
        return Notification.objects.filter(
            recipient=self.request.user,
            category__code="MARKET_OPERATIONAL_ALERTS",
        ).select_related("category")


class AdminAlertListView(AdminAlertMixin, ListAPIView):
    serializer_class = NotificationSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        return self.alerts().filter(archived_at__isnull=True).order_by("-occurred_at", "-id")


class AdminAlertDetailView(AdminAlertMixin, RetrieveAPIView):
    serializer_class = NotificationSerializer
    lookup_url_kwarg = "alert_id"

    def get_queryset(self):
        return self.alerts()


class AdminAlertUnreadView(AdminAlertMixin, GenericAPIView):
    serializer_class = UnreadCountSerializer

    @extend_schema(operation_id="admin_alert_unread_count", responses=UnreadCountSerializer)
    def get(self, request):
        return Response(
            {
                "unread_count": self.alerts()
                .filter(read_at__isnull=True, archived_at__isnull=True)
                .count()
            }
        )


class AdminAlertReadView(AdminAlertMixin, GenericAPIView):
    serializer_class = NotificationSerializer

    @extend_schema(
        operation_id="admin_alert_mark_read", request=None, responses=NotificationSerializer
    )
    def post(self, request, alert_id):
        alert = get_object_or_404(self.alerts(), pk=alert_id)
        if alert.read_at is None:
            alert.read_at = timezone.now()
            alert.save(update_fields=["read_at"])
        return Response(NotificationSerializer(alert).data)


class AdminAlertArchiveView(AdminAlertMixin, GenericAPIView):
    serializer_class = NotificationSerializer

    @extend_schema(
        operation_id="admin_alert_archive", request=None, responses=NotificationSerializer
    )
    def post(self, request, alert_id):
        alert = get_object_or_404(self.alerts(), pk=alert_id)
        if alert.archived_at is None:
            alert.archived_at = timezone.now()
            alert.save(update_fields=["archived_at"])
        return Response(NotificationSerializer(alert).data)
