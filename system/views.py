from django.core.cache import cache
from django.db import connections
from django.db.utils import OperationalError
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from system.serializers import HealthCheckSerializer


def _check_database() -> bool:
    try:
        connections["default"].ensure_connection()
        return True
    except OperationalError:
        return False


def _check_cache() -> bool:
    probe_key = "system:health-check:probe"
    try:
        cache.set(probe_key, "ok", timeout=5)
        return cache.get(probe_key) == "ok"
    except Exception:  # noqa: BLE001 - cache backend errors vary by provider
        return False


@extend_schema(
    request=None,
    responses=HealthCheckSerializer,
    summary="Backend health check",
    tags=["System"],
)
@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    dependencies = {
        "database": _check_database(),
        "cache": _check_cache(),
    }
    healthy = all(dependencies.values())

    return Response(
        {
            "status": "ok" if healthy else "degraded",
            "service": "leagueos-backend",
            "dependencies": dependencies,
        },
        status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )
