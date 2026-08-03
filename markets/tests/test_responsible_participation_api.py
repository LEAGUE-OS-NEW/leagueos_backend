from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from markets.models import (
    MarketResponsibleParticipation,
    MarketResponsibleParticipationEvent,
)
from markets.responsible_participation_serializers import (
    AdminResponsibleStatusSerializer,
    ResponsibleStatusSerializer,
)
from markets.responsible_participation_views import (
    AdminResponsibleEventListView,
    AdminResponsibleParticipationView,
    ParticipantResponsibleEventListView,
    status_data,
)


class ResponsibleParticipationAPITests(TestCase):
    def setUp(self):
        self.participant = get_user_model().objects.create_user(
            username="responsible-api", email="responsible-api@example.com", password="password"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.participant)

    def test_status_keys_match_participant_serializer_and_split_buy_sell_semantics(self):
        MarketResponsibleParticipation.objects.create(
            participant=self.participant, daily_buy_notional_limit=Decimal("0")
        )
        response = self.client.get(reverse("markets:market-responsible-participation"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), set(ResponsibleStatusSerializer().fields))
        self.assertFalse(response.data["buy_allowed"])
        self.assertTrue(response.data["sell_allowed"])
        self.assertTrue(response.data["participation_allowed"])
        self.assertNotIn("administrative_block_reason", response.data)
        self.assertNotIn("reviewed_by", response.data)

    def test_admin_detail_keys_match_explicit_admin_serializer(self):
        data = status_data(self.participant, admin=True)
        self.assertEqual(set(data), set(AdminResponsibleStatusSerializer().fields))

    def test_empty_patch_is_rejected_without_creating_controls(self):
        response = self.client.patch(
            reverse("markets:market-responsible-participation"), {}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            MarketResponsibleParticipation.objects.filter(participant=self.participant).exists()
        )

    def test_null_participant_limit_is_rejected(self):
        response = self.client.patch(
            reverse("markets:market-responsible-participation"),
            {"max_order_notional": None},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(MarketResponsibleParticipation.objects.exists())

    def test_participant_can_set_and_lower_limit_through_api_but_not_raise_it(self):
        url = reverse("markets:market-responsible-participation")
        response = self.client.patch(url, {"max_order_notional": "10.0000"}, format="json")
        self.assertEqual(response.status_code, 200)
        response = self.client.patch(url, {"max_order_notional": "5.0000"}, format="json")
        self.assertEqual(response.status_code, 200)
        response = self.client.patch(url, {"max_order_notional": "6.0000"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "PARTICIPANT_LIMIT_RELAXATION_NOT_ALLOWED")

    def test_cooling_off_and_self_exclusion_endpoints_activate_controls(self):
        cooling = self.client.post(
            reverse("markets:market-responsible-participation-cooling-off"),
            {"duration": "ONE_HOUR"},
            format="json",
        )
        self.assertEqual(cooling.status_code, 200)
        self.assertTrue(cooling.data["cooling_off_active"])
        exclusion = self.client.post(
            reverse("markets:market-responsible-participation-self-exclusion"),
            {"duration": "ONE_DAY"},
            format="json",
        )
        self.assertEqual(exclusion.status_code, 200)
        self.assertTrue(exclusion.data["self_exclusion_active"])

    def test_participant_event_queryset_is_scoped_and_ordered(self):
        outsider = get_user_model().objects.create_user(username="event-outsider")
        own = MarketResponsibleParticipationEvent.objects.create(
            participant=self.participant,
            actor=self.participant,
            event_type=MarketResponsibleParticipationEvent.EventType.LIMITS_SET,
        )
        MarketResponsibleParticipationEvent.objects.create(
            participant=outsider,
            actor=outsider,
            event_type=MarketResponsibleParticipationEvent.EventType.LIMITS_SET,
        )
        view = ParticipantResponsibleEventListView()
        view.request = SimpleNamespace(user=self.participant)
        self.assertEqual(list(view.get_queryset()), [own])

    def test_admin_detail_patch_and_event_queryset_use_admin_contract(self):
        view = AdminResponsibleParticipationView()
        request = SimpleNamespace(user=self.participant, data={})
        response = view.get(request, self.participant.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), set(AdminResponsibleStatusSerializer().fields))
        request.data = {"max_order_notional": "4.0000", "reason": "manual review"}
        response = view.patch(request, self.participant.id)
        self.assertEqual(response.status_code, 200)
        event_view = AdminResponsibleEventListView()
        event_view.kwargs = {"user_id": self.participant.id}
        self.assertEqual(event_view.get_queryset().count(), 1)

    def test_admin_patch_validation_errors_are_stable(self):
        view = AdminResponsibleParticipationView()
        request = SimpleNamespace(
            user=self.participant,
            data={
                "administrative_block_until": timezone.now().isoformat(),
                "administrative_block_reason": "review",
                "reason": "manual review",
            },
        )
        with self.assertRaises(Exception) as raised:
            view.patch(request, self.participant.id)
        self.assertEqual(raised.exception.detail["code"], "ADMIN_BLOCK_UNTIL_MUST_BE_FUTURE")

    def test_schema_represents_both_order_forbidden_response_shapes(self):
        schema = self.client.get(reverse("api-schema"), {"format": "json"}).json()
        operation = schema["paths"]["/api/v1/markets/{market_id}/orders/"]["post"]
        forbidden = operation["responses"]["403"]["content"]["application/json"]["schema"]
        component = schema["components"]["schemas"][forbidden["$ref"].rsplit("/", 1)[-1]]
        refs = {item["$ref"].rsplit("/", 1)[-1] for item in component["oneOf"]}
        self.assertEqual(
            refs,
            {"IneligibleOrderResponse", "ResponsibleOrderBlockedResponse"},
        )
