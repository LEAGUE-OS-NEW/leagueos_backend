"""Storage service for handling file uploads across multiple backends.

Supports Local Storage (development), Amazon S3, MinIO, and Cloudflare R2
via environment configuration. All operations are backend-agnostic.
"""

from __future__ import annotations

import logging
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)


class StorageService:
    """Abstract storage service supporting multiple backends.

    All file operations (save, delete, exists, url) are routed through
    Django's configured default_storage backend, which is selected
    via the STORAGE_BACKEND environment variable.
    """

    # Maximum upload size in bytes (default: 5 MB)
    MAX_UPLOAD_SIZE: int = getattr(settings, "AVATAR_MAX_UPLOAD_SIZE", 5 * 1024 * 1024)

    @staticmethod
    def get_storage_backend() -> str:
        """Return the currently configured storage backend name."""
        return getattr(settings, "STORAGE_BACKEND", "local")

    @staticmethod
    def is_cloud_storage() -> bool:
        """Check if cloud storage (S3/MinIO/R2) is configured."""
        backend = StorageService.get_storage_backend()
        return backend in ("s3", "minio", "r2")

    @staticmethod
    def generate_filename(original_name: str) -> str:
        """Generate a unique UUID-based filename, preserving the original extension.

        Args:
            original_name: The original uploaded filename.

        Returns:
            A UUID-based filename with the same extension.
        """
        ext = ""
        if "." in original_name:
            ext = original_name.rsplit(".", 1)[-1].lower()
        return f"{uuid.uuid4()}.{ext}"

    @staticmethod
    def save_file(
        file_data: bytes,
        filename: str,
        folder: str = "avatars",
    ) -> str:
        """Save binary file data to the configured storage backend.

        Args:
            file_data: Raw bytes of the file.
            filename: The filename to use (typically UUID-based).
            folder: Target folder within storage.

        Returns:
            The relative path where the file was saved.
        """
        filepath = f"{folder}/{filename}"

        # Use ContentFile to wrap the binary data
        content_file = ContentFile(file_data)
        saved_path = default_storage.save(filepath, content_file)

        logger.info(
            "File saved to %s (backend: %s, size: %d bytes)",
            saved_path,
            StorageService.get_storage_backend(),
            file_data.__sizeof__(),
        )

        return saved_path

    @staticmethod
    def delete_file(filepath: str) -> bool:
        """Delete a file from storage.

        Args:
            filepath: The relative path of the file to delete.

        Returns:
            True if the file was deleted, False if it didn't exist.
        """
        if not filepath:
            return False

        if default_storage.exists(filepath):
            default_storage.delete(filepath)
            logger.info("File deleted from %s", filepath)
            return True

        return False

    @staticmethod
    def file_exists(filepath: str) -> bool:
        """Check if a file exists in storage."""
        return default_storage.exists(filepath)

    @staticmethod
    def get_file_url(filepath: str) -> str:
        """Return the public URL for a file in storage.

        For cloud storage, returns the S3/custom-domain URL.
        For local storage, returns the MEDIA_URL-prefixed path.
        """
        return default_storage.url(filepath)

    @staticmethod
    def get_public_url(filepath: str) -> str:
        """Build a publicly accessible URL for a stored file.

        For S3-compatible backends, uses the configured custom domain
        or constructs an S3 URL. For local storage, uses MEDIA_URL.
        """
        backend = StorageService.get_storage_backend()

        if backend == "local":
            media_url = getattr(settings, "MEDIA_URL", "/media/")
            return f"{media_url.rstrip('/')}/{filepath}"

        custom_domain = getattr(settings, "AWS_S3_CUSTOM_DOMAIN", "")
        if custom_domain:
            return f"https://{custom_domain}/{filepath}"

        bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "")
        region = getattr(settings, "AWS_S3_REGION_NAME", "")
        endpoint = getattr(settings, "AWS_S3_ENDPOINT_URL", "")

        if endpoint:
            base = endpoint.rstrip("/")
            if region:
                return f"{base}/{bucket}/{filepath}"
            return f"{base}/{bucket}/{filepath}"

        if bucket and region:
            return f"https://{bucket}.s3.{region}.amazonaws.com/{filepath}"

        return default_storage.url(filepath)

    @staticmethod
    def save_avatar(
        file_data: bytes,
        original_name: str,
        user_id: uuid.UUID,
    ) -> str:
        """Save an avatar image with a UUID-based filename.

        Args:
            file_data: Raw bytes of the image file.
            original_name: The original filename (used for extension).
            user_id: The user's UUID for directory organization.

        Returns:
            The relative storage path of the saved avatar.
        """
        filename = StorageService.generate_filename(original_name)
        folder = f"avatars/{user_id}"
        return StorageService.save_file(file_data, filename, folder=folder)
