"""Tests for profile avatar API endpoints."""

from __future__ import annotations

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from profiles.models import Profile


def _create_image_bytes(
    width: int = 400,
    height: int = 400,
    format_name: str = "JPEG",
) -> bytes:
    img = Image.new("RGB", (width, height), color="white")
    buf = io.BytesIO()
    img.save(buf, format=format_name)
    return buf.getvalue()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def fan_user(db):
    return User.objects.create_user(
        username="fanuser",
        email="fan@example.com",
        password="Pass123!Password",
    )


@pytest.fixture
def other_user(db):
    return User.objects.create_user(
        username="otheruser",
        email="other@example.com",
        password="Pass123!Password",
    )


AVATAR_URL = "/api/v1/profile/avatar/"


@pytest.mark.django_db
class TestAvatarUpload:
    def test_upload_jpeg_avatar_success(self, api_client, fan_user):
        api_client.force_authenticate(user=fan_user)

        img_bytes = _create_image_bytes(format_name="JPEG")
        avatar_file = SimpleUploadedFile("avatar.jpg", img_bytes, content_type="image/jpeg")

        response = api_client.post(AVATAR_URL, {"avatar": avatar_file}, format="multipart")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["success"] is True
        assert "avatar_url" in response.data["data"]
        assert response.data["data"]["avatar_url"].endswith(".jpg")

        profile = Profile.objects.get(user=fan_user)
        assert profile.avatar.name.endswith(".jpg")
        assert profile.avatar_updated_at is not None

    def test_upload_png_avatar_success(self, api_client, fan_user):
        api_client.force_authenticate(user=fan_user)

        img_bytes = _create_image_bytes(format_name="PNG")
        avatar_file = SimpleUploadedFile("avatar.png", img_bytes, content_type="image/png")

        response = api_client.post(AVATAR_URL, {"avatar": avatar_file}, format="multipart")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["success"] is True
        assert response.data["data"]["avatar_url"].endswith(".png")

        profile = Profile.objects.get(user=fan_user)
        assert profile.avatar.name.endswith(".png")

    def test_upload_webp_avatar_success(self, api_client, fan_user):
        api_client.force_authenticate(user=fan_user)

        img_bytes = _create_image_bytes(format_name="WEBP")
        avatar_file = SimpleUploadedFile("avatar.webp", img_bytes, content_type="image/webp")

        response = api_client.post(AVATAR_URL, {"avatar": avatar_file}, format="multipart")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["success"] is True
        assert response.data["data"]["avatar_url"].endswith(".webp")

        profile = Profile.objects.get(user=fan_user)
        assert profile.avatar.name.endswith(".webp")

    def test_replace_existing_avatar(self, api_client, fan_user):
        api_client.force_authenticate(user=fan_user)

        img_bytes = _create_image_bytes(format_name="JPEG")
        old_avatar = SimpleUploadedFile("old.jpg", img_bytes, content_type="image/jpeg")
        api_client.post(AVATAR_URL, {"avatar": old_avatar}, format="multipart")

        profile = Profile.objects.get(user=fan_user)
        old_name = profile.avatar.name
        assert old_name != ""

        new_avatar_bytes = _create_image_bytes(format_name="PNG")
        new_avatar = SimpleUploadedFile("new.png", new_avatar_bytes, content_type="image/png")
        response = api_client.post(AVATAR_URL, {"avatar": new_avatar}, format="multipart")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["success"] is True
        profile.refresh_from_db()
        assert profile.avatar.name != old_name
        assert profile.avatar.name.endswith(".png")

    def test_unauthenticated_upload_rejected(self, api_client):
        img_bytes = _create_image_bytes(format_name="JPEG")
        avatar_file = SimpleUploadedFile("avatar.jpg", img_bytes, content_type="image/jpeg")

        response = api_client.post(AVATAR_URL, {"avatar": avatar_file}, format="multipart")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_missing_avatar_file_rejected(self, api_client, fan_user):
        api_client.force_authenticate(user=fan_user)

        response = api_client.post(AVATAR_URL, {}, format="multipart")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "avatar" in response.data["errors"]

    def test_unsupported_format_rejected(self, api_client, fan_user):
        api_client.force_authenticate(user=fan_user)

        fake_bytes = b"%PDF-1.4 fake pdf content here"
        bad_file = SimpleUploadedFile("avatar.pdf", fake_bytes, content_type="application/pdf")

        response = api_client.post(AVATAR_URL, {"avatar": bad_file}, format="multipart")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "avatar" in response.data["errors"]

    def test_oversized_file_rejected(self, api_client, fan_user):
        api_client.force_authenticate(user=fan_user)

        oversized = b"x" * (6 * 1024 * 1024)
        big_file = SimpleUploadedFile("avatar.jpg", oversized, content_type="image/jpeg")

        response = api_client.post(AVATAR_URL, {"avatar": big_file}, format="multipart")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "avatar" in response.data["errors"]

    def test_corrupt_image_rejected(self, api_client, fan_user):
        api_client.force_authenticate(user=fan_user)

        corrupt = b"this is not a valid image file content"
        bad_file = SimpleUploadedFile("avatar.jpg", corrupt, content_type="image/jpeg")

        response = api_client.post(AVATAR_URL, {"avatar": bad_file}, format="multipart")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "avatar" in response.data["errors"]

    def test_avatar_response_does_not_leak_other_user_data(self, api_client, fan_user, other_user):
        api_client.force_authenticate(user=fan_user)

        img_bytes = _create_image_bytes(format_name="JPEG")
        avatar_file = SimpleUploadedFile("fan_avatar.jpg", img_bytes, content_type="image/jpeg")

        response = api_client.post(AVATAR_URL, {"avatar": avatar_file}, format="multipart")

        assert response.status_code == status.HTTP_200_OK
        assert "avatar_url" in response.data["data"]

        response_data = response.data["data"]
        assert "fan_avatar.jpg" not in str(response_data.get("avatar_url", ""))
        assert "otheruser" not in str(response_data)


@pytest.mark.django_db
class TestAvatarDelete:
    def test_delete_avatar_success(self, api_client, fan_user):
        api_client.force_authenticate(user=fan_user)

        img_bytes = _create_image_bytes(format_name="JPEG")
        avatar_file = SimpleUploadedFile("avatar.jpg", img_bytes, content_type="image/jpeg")
        api_client.post(AVATAR_URL, {"avatar": avatar_file}, format="multipart")

        profile = Profile.objects.get(user=fan_user)
        assert profile.avatar.name != ""

        response = api_client.delete(AVATAR_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["success"] is True
        profile.refresh_from_db()
        assert profile.avatar.name == ""

    def test_unauthenticated_delete_rejected(self, api_client):
        response = api_client.delete(AVATAR_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestAvatarInfo:
    def test_get_avatar_info_no_avatar(self, api_client, fan_user):
        api_client.force_authenticate(user=fan_user)

        response = api_client.get(AVATAR_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["has_avatar"] is False
        assert response.data["avatar_url"] is not None

    def test_get_avatar_info_with_avatar(self, api_client, fan_user):
        api_client.force_authenticate(user=fan_user)

        img_bytes = _create_image_bytes(format_name="JPEG")
        avatar_file = SimpleUploadedFile("avatar.jpg", img_bytes, content_type="image/jpeg")
        api_client.post(AVATAR_URL, {"avatar": avatar_file}, format="multipart")

        response = api_client.get(AVATAR_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["has_avatar"] is True
        assert response.data["avatar_url"].endswith(".jpg")
        assert response.data["avatar_updated_at"] is not None
