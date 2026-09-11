"""
Tests for the admin competition create endpoint (POST /admin/sports/competitions/).

Regression coverage for the slug UniqueTogetherValidator 400 bug:
the UniqueTogetherValidator auto-generated from the unique_competition_identity
constraint (sport + country_code + slug) was requiring slug to be present in
the request payload even though the field was marked required=False.  The fix
adds default="" to the slug extra_kwargs so the validator receives an empty
string and the model's save() auto-generates the real slug from name.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from authentication.models import Permission, Role, RolePermission, UserRole
from sports.models import Competition, Sport

User = get_user_model()

COMP_CREATE_URL = reverse("sports:admin-competition-create")


def _make_admin_user(email="admin@test.com"):
    """Create a user and grant them admin.clubs.manage permission."""
    user = User.objects.create_user(email=email, username=email, password="testpass123")
    perm, _ = Permission.objects.get_or_create(
        code="admin.clubs.manage",
        defaults={"name": "admin.clubs.manage", "resource": "admin", "action": "clubs.manage"},
    )
    role = Role.objects.create(name=f"clubs-manager-{email}", display_name="Clubs Manager")
    RolePermission.objects.create(role=role, permission=perm)
    UserRole.objects.create(user=user, role=role)
    return user


class CompetitionAdminCreateTests(APITestCase):
    """Endpoint: POST /api/v1/admin/sports/competitions/"""

    def setUp(self):
        self.admin = _make_admin_user()
        self.client.force_authenticate(user=self.admin)
        self.sport = Sport.objects.create(name="Football", code="FOOTBALL_COMP_TEST")

    # ------------------------------------------------------------------
    # Core fix: creating without a slug must succeed and auto-generate it
    # ------------------------------------------------------------------

    def test_create_competition_without_slug_returns_201(self):
        """Exact frontend payload (no slug) must succeed after the fix."""
        payload = {
            "sport": str(self.sport.id),
            "name": "Uganda Premier League",
            "country_code": "UG",
            "is_active": True,
        }
        response = self.client.post(COMP_CREATE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_slug_auto_generated_from_name_when_omitted(self):
        """When slug is omitted the model save() derives it from name."""
        payload = {
            "sport": str(self.sport.id),
            "name": "Auto Slug Competition",
            "country_code": "UG",
        }
        response = self.client.post(COMP_CREATE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        comp = Competition.objects.get(id=response.data["id"])
        self.assertEqual(comp.slug, "auto-slug-competition")

    def test_explicit_slug_is_preserved(self):
        """If the caller supplies a slug, it must be used as-is."""
        payload = {
            "sport": str(self.sport.id),
            "name": "Named League",
            "slug": "my-custom-slug",
            "country_code": "UG",
        }
        response = self.client.post(COMP_CREATE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        comp = Competition.objects.get(id=response.data["id"])
        self.assertEqual(comp.slug, "my-custom-slug")

    # ------------------------------------------------------------------
    # Uniqueness protection remains intact
    # ------------------------------------------------------------------

    def test_duplicate_name_in_same_sport_and_country_is_rejected(self):
        """
        Two competitions with the same sport + country_code + slugified-name
        violate unique_competition_identity and must return 400.
        """
        payload = {
            "sport": str(self.sport.id),
            "name": "Duplicate League",
            "country_code": "UG",
        }
        r1 = self.client.post(COMP_CREATE_URL, payload, format="json")
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED, r1.data)

        r2 = self.client.post(COMP_CREATE_URL, payload, format="json")
        self.assertEqual(r2.status_code, status.HTTP_400_BAD_REQUEST, r2.data)

    def test_same_name_different_country_is_allowed(self):
        """Different country_code → different identity, so it must succeed."""
        base = {
            "sport": str(self.sport.id),
            "name": "Regional League",
        }
        r1 = self.client.post(COMP_CREATE_URL, {**base, "country_code": "UG"}, format="json")
        r2 = self.client.post(COMP_CREATE_URL, {**base, "country_code": "KE"}, format="json")
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED, r1.data)
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED, r2.data)

    # ------------------------------------------------------------------
    # Permission gate
    # ------------------------------------------------------------------

    def test_unauthenticated_request_is_rejected(self):
        self.client.force_authenticate(user=None)
        payload = {
            "sport": str(self.sport.id),
            "name": "Unauthorized League",
            "country_code": "UG",
        }
        response = self.client.post(COMP_CREATE_URL, payload, format="json")
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

    def test_user_without_permission_is_rejected(self):
        unprivileged = User.objects.create_user(
            email="unprivileged@test.com",
            username="unprivileged@test.com",
            password="testpass123",
        )
        self.client.force_authenticate(user=unprivileged)
        payload = {
            "sport": str(self.sport.id),
            "name": "No-Permission League",
            "country_code": "UG",
        }
        response = self.client.post(COMP_CREATE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)
