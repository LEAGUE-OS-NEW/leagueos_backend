from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from markets.models import (
    MarketOrder,
    MarketResponsibleParticipation,
    MarketResponsibleParticipationEvent,
)
from markets.services.order_financials import calculate_buy_commitment
from markets.services.responsible_participation_service import (
    MarketResponsibleParticipationService,
)


class ResponsibleParticipationModelTests(TestCase):
    def setUp(self):
        self.participant = get_user_model().objects.create_user(
            username="responsible-participant",
            email="responsible@example.com",
            password="test-password",
        )
        self.client = APIClient()

    def test_missing_row_means_no_optional_limits_and_read_does_not_create_it(self):
        status = MarketResponsibleParticipationService.status(participant=self.participant)

        self.assertIsNone(status.limits["max_order_notional"])
        self.assertFalse(
            MarketResponsibleParticipation.objects.filter(participant=self.participant).exists()
        )

    def test_negative_money_limit_is_rejected(self):
        controls = MarketResponsibleParticipation(
            participant=self.participant,
            max_order_notional=Decimal("-0.0001"),
        )

        with self.assertRaises(ValidationError):
            controls.full_clean()

    def test_zero_limit_is_valid_and_blocks_positive_order_notional(self):
        controls = MarketResponsibleParticipation(
            participant=self.participant,
            max_order_notional=Decimal("0.0000"),
        )
        controls.full_clean()

    def test_event_history_is_immutable(self):
        event = MarketResponsibleParticipationEvent.objects.create(
            participant=self.participant,
            actor=self.participant,
            event_type=MarketResponsibleParticipationEvent.EventType.LIMITS_SET,
        )
        event.reason = "changed"
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()
        with self.assertRaises(ValidationError):
            MarketResponsibleParticipationEvent.objects.filter(pk=event.pk).update(reason="changed")

    def test_status_api_is_non_mutating_and_hides_internal_fields(self):
        self.client.force_authenticate(self.participant)
        response = self.client.get(reverse("markets:market-responsible-participation"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("administrative_block_reason", response.data)
        self.assertNotIn("reviewed_by", response.data)
        self.assertFalse(
            MarketResponsibleParticipation.objects.filter(participant=self.participant).exists()
        )

    def test_participant_can_set_and_tighten_but_not_relax_limit(self):
        MarketResponsibleParticipationService.update_participant_limits(
            participant=self.participant,
            changes={"max_order_notional": Decimal("10.0000")},
        )
        controls = MarketResponsibleParticipationService.update_participant_limits(
            participant=self.participant,
            changes={"max_order_notional": Decimal("5.0000")},
        )
        self.assertEqual(controls.max_order_notional, Decimal("5.0000"))
        with self.assertRaisesMessage(ValueError, "PARTICIPANT_LIMIT_RELAXATION_NOT_ALLOWED"):
            MarketResponsibleParticipationService.update_participant_limits(
                participant=self.participant,
                changes={"max_order_notional": Decimal("6.0000")},
            )

    def evaluate(self, *, side, controls, quantity=Decimal("1"), price=Decimal("1")):
        return MarketResponsibleParticipationService.evaluate_order(
            participant=self.participant,
            market=None,
            outcome=None,
            side=side,
            quantity=quantity,
            limit_price=price,
            controls=controls,
            as_of=timezone.now(),
        )

    def test_sell_is_allowed_when_each_buy_only_capacity_is_reached(self):
        fields = (
            "daily_buy_notional_limit",
            "weekly_buy_notional_limit",
            "max_open_buy_commitment",
            "max_market_exposure",
            "max_total_exposure",
        )
        for field in fields:
            with self.subTest(field=field):
                controls = MarketResponsibleParticipation(
                    participant=self.participant,
                    max_order_notional=Decimal("2"),
                    **{field: Decimal("0")},
                )
                sell = self.evaluate(side=MarketOrder.Side.SELL, controls=controls)
                buy = self.evaluate(side=MarketOrder.Side.BUY, controls=controls)
                self.assertTrue(sell.allowed)
                self.assertFalse(buy.allowed)

    def test_sell_still_obeys_per_order_and_universal_controls(self):
        controls = MarketResponsibleParticipation(
            participant=self.participant,
            max_order_notional=Decimal("0.5"),
            cooling_off_until=timezone.now() + timezone.timedelta(hours=1),
        )
        result = self.evaluate(side=MarketOrder.Side.SELL, controls=controls)
        self.assertFalse(result.allowed)
        self.assertIn("MAX_ORDER_NOTIONAL_EXCEEDED", result.reason_codes)
        self.assertIn("COOLING_OFF_ACTIVE", result.reason_codes)

    def test_zero_cumulative_loss_limit_allows_zero_loss(self):
        controls = MarketResponsibleParticipation(
            participant=self.participant,
            max_cumulative_realized_loss=Decimal("0"),
        )
        self.assertTrue(self.evaluate(side=MarketOrder.Side.BUY, controls=controls).allowed)
        self.assertTrue(self.evaluate(side=MarketOrder.Side.SELL, controls=controls).allowed)

    def test_status_distinguishes_buy_and_sell_capacity(self):
        controls = MarketResponsibleParticipation.objects.create(
            participant=self.participant,
            daily_buy_notional_limit=Decimal("0"),
        )
        result = MarketResponsibleParticipationService.status(
            participant=self.participant, controls=controls
        )
        self.assertFalse(result.buy_allowed)
        self.assertTrue(result.sell_allowed)
        self.assertTrue(result.allowed)

    def test_empty_participant_update_does_not_create_row_or_event(self):
        with self.assertRaisesMessage(ValueError, "PARTICIPANT_LIMIT_UPDATE_REQUIRED"):
            MarketResponsibleParticipationService.update_participant_limits(
                participant=self.participant, changes={}
            )
        self.assertFalse(MarketResponsibleParticipation.objects.exists())
        self.assertFalse(MarketResponsibleParticipationEvent.objects.exists())

    def test_no_op_limit_update_creates_no_event(self):
        MarketResponsibleParticipationService.update_participant_limits(
            participant=self.participant, changes={"max_order_notional": Decimal("1")}
        )
        MarketResponsibleParticipationService.update_participant_limits(
            participant=self.participant, changes={"max_order_notional": Decimal("1")}
        )
        self.assertEqual(MarketResponsibleParticipationEvent.objects.count(), 1)

    def test_all_cooling_off_durations_activate_immediately_and_emit_one_event(self):
        expected = {"ONE_HOUR": 1, "ONE_DAY": 24, "SEVEN_DAYS": 168, "THIRTY_DAYS": 720}
        for duration, hours in expected.items():
            with self.subTest(duration=duration):
                MarketResponsibleParticipation.objects.filter(participant=self.participant).delete()
                before = MarketResponsibleParticipationEvent.objects.count()
                as_of = timezone.now()
                controls = MarketResponsibleParticipationService.start_cooling_off(
                    participant=self.participant, duration=duration, as_of=as_of
                )
                self.assertEqual(
                    controls.cooling_off_until, as_of + timezone.timedelta(hours=hours)
                )
                self.assertEqual(MarketResponsibleParticipationEvent.objects.count(), before + 1)

    def test_self_exclusion_duration_matrix_and_indefinite_transition(self):
        as_of = timezone.now()
        controls = MarketResponsibleParticipationService.start_self_exclusion(
            participant=self.participant, duration="ONE_DAY", as_of=as_of
        )
        self.assertEqual(controls.self_exclusion_until, as_of + timezone.timedelta(days=1))
        controls = MarketResponsibleParticipationService.start_self_exclusion(
            participant=self.participant, duration="INDEFINITE", as_of=as_of
        )
        self.assertTrue(controls.self_excluded_indefinitely)
        self.assertIsNone(controls.self_exclusion_until)
        self.assertEqual(
            MarketResponsibleParticipationEvent.objects.latest("created_at").event_type,
            MarketResponsibleParticipationEvent.EventType.SELF_EXCLUSION_EXTENDED,
        )

    def test_admin_event_classification_and_no_op(self):
        future = timezone.now() + timezone.timedelta(days=1)
        cases = (
            (
                {"max_order_notional": Decimal("10")},
                MarketResponsibleParticipationEvent.EventType.ADMIN_LIMITS_UPDATED,
            ),
            (
                {"cooling_off_until": future},
                MarketResponsibleParticipationEvent.EventType.COOLING_OFF_EXTENDED,
            ),
            (
                {"self_exclusion_until": future},
                MarketResponsibleParticipationEvent.EventType.SELF_EXCLUSION_EXTENDED,
            ),
        )
        for changes, expected in cases:
            MarketResponsibleParticipationService.update_admin(
                participant=self.participant,
                actor=self.participant,
                changes=changes,
                reason="reviewed",
            )
            self.assertEqual(
                MarketResponsibleParticipationEvent.objects.latest("created_at").event_type,
                expected,
            )
        count = MarketResponsibleParticipationEvent.objects.count()
        MarketResponsibleParticipationService.update_admin(
            participant=self.participant,
            actor=self.participant,
            changes={"max_order_notional": Decimal("10")},
            reason="reviewed",
        )
        self.assertEqual(MarketResponsibleParticipationEvent.objects.count(), count)

    def test_admin_block_requires_future_deadline_and_internal_reason(self):
        now = timezone.now()
        with self.assertRaisesMessage(ValueError, "ADMIN_BLOCK_UNTIL_MUST_BE_FUTURE"):
            MarketResponsibleParticipationService.update_admin(
                participant=self.participant,
                actor=self.participant,
                changes={
                    "administrative_block_until": now,
                    "administrative_block_reason": "risk review",
                },
                reason="reviewed",
            )
        with self.assertRaisesMessage(ValueError, "ADMIN_BLOCK_REASON_REQUIRED"):
            MarketResponsibleParticipationService.update_admin(
                participant=self.participant,
                actor=self.participant,
                changes={"administrative_block_until": now + timezone.timedelta(days=1)},
                reason="reviewed",
            )

    def test_admin_block_start_extension_reason_change_and_mixed_updates_are_audited(self):
        first = timezone.now() + timezone.timedelta(days=1)
        MarketResponsibleParticipationService.update_admin(
            participant=self.participant,
            actor=self.participant,
            changes={
                "administrative_block_until": first,
                "administrative_block_reason": "first reason",
            },
            reason="start",
        )
        self.assertEqual(
            MarketResponsibleParticipationEvent.objects.latest("created_at").event_type,
            MarketResponsibleParticipationEvent.EventType.ADMIN_BLOCK_STARTED,
        )
        MarketResponsibleParticipationService.update_admin(
            participant=self.participant,
            actor=self.participant,
            changes={"administrative_block_until": first + timezone.timedelta(days=1)},
            reason="extend",
        )
        self.assertEqual(
            MarketResponsibleParticipationEvent.objects.latest("created_at").event_type,
            MarketResponsibleParticipationEvent.EventType.ADMIN_BLOCK_EXTENDED,
        )
        MarketResponsibleParticipationService.update_admin(
            participant=self.participant,
            actor=self.participant,
            changes={"administrative_block_reason": "updated reason"},
            reason="reason corrected",
        )
        self.assertEqual(
            MarketResponsibleParticipationEvent.objects.latest("created_at").event_type,
            MarketResponsibleParticipationEvent.EventType.ADMIN_CONTROLS_UPDATED,
        )
        MarketResponsibleParticipationService.update_admin(
            participant=self.participant,
            actor=self.participant,
            changes={
                "max_order_notional": Decimal("5"),
                "cooling_off_until": first,
            },
            reason="mixed",
        )
        self.assertEqual(
            MarketResponsibleParticipationEvent.objects.latest("created_at").event_type,
            MarketResponsibleParticipationEvent.EventType.ADMIN_CONTROLS_UPDATED,
        )

    @override_settings(MARKET_RESPONSIBLE_DEFAULT_MAX_ORDER_NOTIONAL=Decimal("1.2500"))
    def test_decimal_default_is_used_without_float_conversion(self):
        result = MarketResponsibleParticipationService.status(participant=self.participant)
        self.assertEqual(result.limits["max_order_notional"], Decimal("1.2500"))


class OrderFinancialTests(TestCase):
    def test_commitment_uses_quantity_price_and_ceiling_to_four_decimals(self):
        self.assertEqual(
            calculate_buy_commitment(quantity=Decimal("3"), limit_price=Decimal("0.33333")),
            Decimal("1.0000"),
        )
        self.assertEqual(
            calculate_buy_commitment(quantity=Decimal("1"), limit_price=Decimal("0.00001")),
            Decimal("0.0001"),
        )
