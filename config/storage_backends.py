from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.files.storage import FileSystemStorage, storages
from django.core.exceptions import ImproperlyConfigured
from storages.backends.s3 import S3Storage


def rewrite_presigned_url(url: str, external_base_url: str) -> str:
    """
    Rewrite an internally generated S3 URL to the externally reachable
    League OS storage proxy while preserving the object path and signature.
    """
    external_base_url = (external_base_url or "").strip().rstrip("/")

    if not external_base_url:
        return url

    internal_parts = urlsplit(url)
    external_parts = urlsplit(external_base_url)

    if external_parts.scheme not in {"http", "https"}:
        raise ImproperlyConfigured("S3_PRIVATE_EXTERNAL_BASE_URL must use http or https.")

    if not external_parts.netloc:
        raise ImproperlyConfigured("S3_PRIVATE_EXTERNAL_BASE_URL must include a hostname.")

    if external_parts.query or external_parts.fragment:
        raise ImproperlyConfigured(
            "S3_PRIVATE_EXTERNAL_BASE_URL cannot contain a query or fragment."
        )

    prefix = external_parts.path.rstrip("/")
    internal_path = internal_parts.path

    if not internal_path.startswith("/"):
        internal_path = f"/{internal_path}"

    return urlunsplit(
        (
            external_parts.scheme,
            external_parts.netloc,
            f"{prefix}{internal_path}",
            internal_parts.query,
            internal_parts.fragment,
        )
    )


class PublicMediaStorage(S3Storage):
    """Public League OS assets such as avatars and club media."""


class PrivateMediaStorage(S3Storage):
    """Credential-protected League OS media such as KYC attachments."""

    def url(
        self,
        name,
        parameters=None,
        expire=None,
        http_method=None,
    ):
        internal_url = super().url(
            name,
            parameters=parameters,
            expire=expire,
            http_method=http_method,
        )

        return rewrite_presigned_url(
            internal_url,
            getattr(
                settings,
                "S3_PRIVATE_EXTERNAL_BASE_URL",
                "",
            ),
        )


class LocalPrivateMediaStorage(FileSystemStorage):
    """Private filesystem storage used outside S3 deployments."""


def get_private_storage():
    """
    Return the configured private storage alias.

    Using a callable keeps deployment configuration out of migrations.
    """
    return storages["private"]
