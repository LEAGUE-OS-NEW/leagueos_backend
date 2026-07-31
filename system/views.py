from drf_spectacular.utils import extend_schema
from rest_framework.decorators import (
    api_view,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from system.serializers import HealthCheckSerializer


@extend_schema(
    request=None,
    responses=HealthCheckSerializer,
    summary="Backend health check",
    tags=["System"],
)
@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    return Response(
        {
            "status": "ok",
            "service": "leagueos-backend",
        }
    )
