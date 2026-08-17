"""Tests for the club logo upload/replace/delete endpoint."""

from __future__ import annotations

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework.test import APIClient

from accounts.models import User
from clubs.models import ClubWorkspace
from profiles.models import Club

pytestmark = pytest.mark.django_db


def _create_image_bytes(width: int = 400, height: int = 400, format_name: str = "JPEG") -> bytes:
    img = Image.new("RGB", (width, height), color="blue")
    buf = io.BytesIO()
    img.save(buf, format=format_name)
    return buf.getvalue()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def club_admin_user():
    return User.objects.create_user(
        username="clubadmin",
        email="clubadmin@example.com",
        password="testpass123",
        first_name="Club",
        last_name="Admin",
    )


@pytest.fixture
def other_user():
    return User.objects.create_user(
        username="otheradmin",
        email="other@example.com",
        password="testpass123",
        first_name="Other",
        last_name="User",
    )


@pytest.fixture
def super_admin_user():
    return User.objects.create_user(
        username="superadmin",
        email="superadmin@example.com",
        password="testpass123",
        is_superuser=True,
    )


@pytest.fixture
def club():
    return Club.objects.create(name="Test Club", slug="test-club")


@pytest.fixture
def club_workspace(club_admin_user, club):
    return ClubWorkspace.objects.create(
        user=club_admin_user,
        club=club,
        role=ClubWorkspace.WorkspaceRole.ADMIN,
        is_active=True,
    )


def logo_url(club_id):
    return reverse("clubs:club-logo", kwargs={"club_pk": club_id})


class TestClubLogoUpload:
    def test_club_admin_can_upload_own_club_logo(
        self, api_client, club_admin_user, club, club_workspace
    ):
        api_client.force_authenticate(user=club_admin_user)
        logo_file = SimpleUploadedFile("logo.jpg", _create_image_bytes(), content_type="image/jpeg")

        resp = api_client.post(logo_url(club.id), {"logo": logo_file}, format="multipart")

        assert resp.status_code == 200
        assert resp.data["success"] is True
        assert resp.data["logo_url"]

        club.refresh_from_db()
        assert club.logo.name

    def test_super_admin_can_upload_any_club_logo(self, api_client, super_admin_user, club):
        api_client.force_authenticate(user=super_admin_user)
        logo_file = SimpleUploadedFile("logo.jpg", _create_image_bytes(), content_type="image/jpeg")

        resp = api_client.post(logo_url(club.id), {"logo": logo_file}, format="multipart")

        assert resp.status_code == 200
        club.refresh_from_db()
        assert club.logo.name

    def test_non_admin_forbidden(self, api_client, other_user, club):
        # No workspace for this club at all.
        api_client.force_authenticate(user=other_user)
        logo_file = SimpleUploadedFile("logo.jpg", _create_image_bytes(), content_type="image/jpeg")

        resp = api_client.post(logo_url(club.id), {"logo": logo_file}, format="multipart")

        assert resp.status_code == 403
        club.refresh_from_db()
        assert not club.logo

    def test_invalid_file_rejected(self, api_client, club_admin_user, club, club_workspace):
        api_client.force_authenticate(user=club_admin_user)
        bogus_file = SimpleUploadedFile("logo.txt", b"not an image", content_type="text/plain")

        resp = api_client.post(logo_url(club.id), {"logo": bogus_file}, format="multipart")

        assert resp.status_code == 400

    def test_replace_deletes_old_file(self, api_client, club_admin_user, club, club_workspace):
        api_client.force_authenticate(user=club_admin_user)
        first = SimpleUploadedFile("logo1.jpg", _create_image_bytes(), content_type="image/jpeg")
        api_client.post(logo_url(club.id), {"logo": first}, format="multipart")
        club.refresh_from_db()
        old_path = club.logo.name

        second = SimpleUploadedFile("logo2.jpg", _create_image_bytes(), content_type="image/jpeg")
        resp = api_client.post(logo_url(club.id), {"logo": second}, format="multipart")

        assert resp.status_code == 200
        club.refresh_from_db()
        assert club.logo.name != old_path


class TestClubLogoDelete:
    def test_club_admin_can_delete_own_club_logo(
        self, api_client, club_admin_user, club, club_workspace
    ):
        api_client.force_authenticate(user=club_admin_user)
        logo_file = SimpleUploadedFile("logo.jpg", _create_image_bytes(), content_type="image/jpeg")
        api_client.post(logo_url(club.id), {"logo": logo_file}, format="multipart")

        resp = api_client.delete(logo_url(club.id))

        assert resp.status_code == 200
        club.refresh_from_db()
        assert not club.logo

    def test_non_admin_cannot_delete(
        self, api_client, other_user, club_admin_user, club, club_workspace
    ):
        logo_file = SimpleUploadedFile("logo.jpg", _create_image_bytes(), content_type="image/jpeg")
        api_client.force_authenticate(user=club_admin_user)
        api_client.post(logo_url(club.id), {"logo": logo_file}, format="multipart")

        api_client.force_authenticate(user=other_user)
        resp = api_client.delete(logo_url(club.id))

        assert resp.status_code == 403
        club.refresh_from_db()
        assert club.logo
