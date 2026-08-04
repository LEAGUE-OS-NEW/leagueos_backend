from django.contrib.auth import get_user_model
from django.db.models import Q


class PermissionRecipientService:
    """Resolve active users through permissions, never through role names."""

    @staticmethod
    def resolve(permission_names):
        names = tuple(dict.fromkeys(permission_names))
        if not names:
            return get_user_model().objects.none()
        return (
            get_user_model()
            .objects.filter(is_active=True)
            .filter(
                Q(is_superuser=True)
                | Q(user_roles__role__role_permissions__permission__name__in=names)
            )
            .distinct()
            .order_by("id")
        )
