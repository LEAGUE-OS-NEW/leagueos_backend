from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from authentication.tests.factories import (
    PermissionFactory,
    RoleFactory,
    RolePermissionFactory,
    UserFactory,
    UserRoleFactory,
)
from markets.models import (
    Market,
    MarketCategory,
    MarketFill,
    MarketOrder,
    MarketOrderExpiryAudit,
    MarketOutcome,
    MarketPosition,
    MarketScope,
)
from markets.services.catalog_service import MarketCatalogService
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.matching_service import MarketMatchingService
from markets.services.order_expiry_service import (
    MarketOrderExpiryService,
)
from markets.services.participation_service import (
    MarketParticipationService,
)
from markets.tests.eligibility_test_support import (
    make_market_eligible,
)
from markets.tests.wallet_test_support import (
    fund_market_wallet,
)
from sports.models import Competition, Sport, SportingEvent
from wallets.models import LedgerEntry


class MarketOrderExpiryServiceTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

        manage_permission = PermissionFactory(
            name="manage_market",
            resource="market",
            action="manage",
        )
        approve_permission = PermissionFactory(
            name="approve_market",
            resource="market",
            action="approve",
        )
        participate_permission = PermissionFactory(
            name="participate_market",
            resource="market",
            action="participate",
        )

        operations_role = RoleFactory(
            name="Expiry Operations",
            display_name="Expiry Operations",
        )
        approval_role = RoleFactory(
            name="Expiry Approval",
            display_name="Expiry Approval",
        )
        participant_role = RoleFactory(
            name="Expiry Participant",
            display_name="Expiry Participant",
        )

        RolePermissionFactory(
            role=operations_role,
            permission=manage_permission,
        )
        RolePermissionFactory(
            role=approval_role,
            permission=approve_permission,
        )
        RolePermissionFactory(
            role=participant_role,
            permission=participate_permission,
        )

        self.operations_user = UserFactory()
        self.approver_user = UserFactory()
        self.owner = UserFactory(is_verified=True)
        self.seller = UserFactory(is_verified=True)

        UserRoleFactory(
            user=self.operations_user,
            role=operations_role,
        )
        UserRoleFactory(
            user=self.approver_user,
            role=approval_role,
        )
        UserRoleFactory(
            user=self.owner,
            role=participant_role,
        )
        UserRoleFactory(
            user=self.seller,
            role=participant_role,
        )

        make_market_eligible(self.owner)
        make_market_eligible(self.seller)

        self.wallet = fund_market_wallet(self.owner)

        self.sport = Sport.objects.create(
            name="Expiry Football",
            code="EXPIRY_FOOTBALL",
        )
        self.category = MarketCategory.objects.create(
            name="Expiry Match Result",
        )
        self.competition = Competition.objects.create(
            sport=self.sport,
            name="Expiry Premier League",
            country_code="UG",
            is_verified=True,
        )
        self.event = SportingEvent.objects.create(
            sport=self.sport,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="Expiry United v Deadline City",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

        self.market = self.open_market(self.create_market())
        self.outcome = self.market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

    def create_market(self):
        return MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question="Will Expiry United win?",
            description="Order expiry test market.",
            rules="Use the official competition result.",
            resolution_source="Official competition result",
            resolution_criteria="Use the verified final score.",
            status=Market.Status.DRAFT,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=2),
            created_by=self.operations_user,
            yes_label="Yes",
            no_label="No",
        )

    def open_market(self, market):
        MarketLifecycleService.submit(
            market_id=market.id,
            actor=self.operations_user,
            notes="Ready for review.",
        )
        MarketLifecycleService.approve(
            market_id=market.id,
            actor=self.approver_user,
            notes="Approved.",
        )
        return MarketLifecycleService.open(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading opened.",
        )

    def create_buy_order(
        self,
        *,
        quantity=Decimal("10.0000"),
        limit_price=Decimal("0.55000"),
        time_in_force=None,
        expires_at=None,
    ):
        kwargs = {}

        if time_in_force is not None:
            kwargs["time_in_force"] = time_in_force

        if expires_at is not None:
            kwargs["expires_at"] = expires_at

        return MarketParticipationService.place_order(
            user=self.owner,
            market_id=self.market.id,
            outcome_id=self.outcome.id,
            side=MarketOrder.Side.BUY,
            quantity=quantity,
            limit_price=limit_price,
            **kwargs,
        )

    def create_sell_order(
        self,
        *,
        quantity=Decimal("10.0000"),
        limit_price=Decimal("0.55000"),
        time_in_force=None,
        expires_at=None,
    ):
        position, _ = MarketPosition.objects.get_or_create(
            user=self.seller,
            market=self.market,
            outcome=self.outcome,
            defaults={
                "quantity": Decimal("10.0000"),
                "reserved_quantity": Decimal("0.0000"),
                "average_entry_price": Decimal("0.40000"),
                "total_cost": Decimal("4.0000"),
                "realized_pnl": Decimal("0.0000"),
            },
        )

        kwargs = {}

        if time_in_force is not None:
            kwargs["time_in_force"] = time_in_force

        if expires_at is not None:
            kwargs["expires_at"] = expires_at

        order = MarketParticipationService.place_order(
            user=self.seller,
            market_id=self.market.id,
            outcome_id=self.outcome.id,
            side=MarketOrder.Side.SELL,
            quantity=quantity,
            limit_price=limit_price,
            **kwargs,
        )

        return order, position

    def expire(
        self,
        order,
        *,
        current_time,
    ):
        with patch(
            "markets.services.order_expiry_service.timezone.now",
            return_value=current_time,
        ):
            return MarketOrderExpiryService.expire_order(
                order_id=order.id,
                source=MarketOrderExpiryAudit.Source.SYSTEM,
                reason="The GTD deadline has elapsed.",
            )

    def test_order_defaults_to_gtc(self):
        order = self.create_buy_order()

        self.assertEqual(
            order.time_in_force,
            MarketOrder.TimeInForce.GTC,
        )
        self.assertIsNone(order.expires_at)
        self.assertIsNone(order.expired_at)

    def test_gtd_requires_expiry_before_market_close(self):
        with self.assertRaises(ValidationError) as context:
            self.create_buy_order(
                time_in_force=MarketOrder.TimeInForce.GTD,
            )

        self.assertIn(
            "expires_at",
            context.exception.message_dict,
        )

        with self.assertRaises(ValidationError) as context:
            self.create_buy_order(
                time_in_force=MarketOrder.TimeInForce.GTD,
                expires_at=(self.market.closes_at + timedelta(minutes=1)),
            )

        self.assertIn(
            "expires_at",
            context.exception.message_dict,
        )

    def test_non_gtd_orders_reject_expires_at(self):
        with self.assertRaises(ValidationError) as context:
            self.create_buy_order(
                time_in_force=MarketOrder.TimeInForce.GTC,
                expires_at=self.now + timedelta(minutes=30),
            )

        self.assertIn(
            "expires_at",
            context.exception.message_dict,
        )

    def test_future_gtd_order_cannot_expire_early(self):
        expires_at = self.now + timedelta(minutes=30)

        order = self.create_buy_order(
            time_in_force=MarketOrder.TimeInForce.GTD,
            expires_at=expires_at,
        )

        with self.assertRaises(ValidationError) as context:
            self.expire(
                order,
                current_time=expires_at - timedelta(seconds=1),
            )

        self.assertIn(
            "expires_at",
            context.exception.message_dict,
        )

        order.refresh_from_db()

        self.assertEqual(
            order.status,
            MarketOrder.Status.OPEN,
        )
        self.assertFalse(
            MarketOrderExpiryAudit.objects.filter(
                market_order=order,
            ).exists()
        )

    def test_expiring_buy_order_releases_reserved_wallet_amount(self):
        expires_at = self.now + timedelta(minutes=30)

        order = self.create_buy_order(
            time_in_force=MarketOrder.TimeInForce.GTD,
            expires_at=expires_at,
        )

        audit = self.expire(
            order,
            current_time=expires_at + timedelta(seconds=1),
        )

        order.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(
            order.status,
            MarketOrder.Status.EXPIRED,
        )
        self.assertEqual(
            order.expired_at,
            expires_at + timedelta(seconds=1),
        )
        self.assertEqual(
            self.wallet.available_balance,
            Decimal("1000000.0000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("0.0000"),
        )

        release_entry = LedgerEntry.objects.get(
            order=order,
            entry_type=LedgerEntry.EntryType.RELEASE,
        )

        self.assertEqual(
            release_entry.amount,
            Decimal("5.5000"),
        )
        self.assertEqual(
            audit.previous_status,
            MarketOrder.Status.OPEN,
        )
        self.assertEqual(
            audit.expired_quantity,
            Decimal("10.0000"),
        )
        self.assertEqual(
            audit.released_wallet_reservation_amount,
            Decimal("5.5000"),
        )
        self.assertEqual(
            audit.released_position_reservation_quantity,
            Decimal("0.0000"),
        )
        self.assertEqual(
            audit.wallet_release_ledger_entry,
            release_entry,
        )

    def test_partial_buy_expiry_releases_only_unfilled_remainder_once(
        self,
    ):
        expires_at = self.now + timedelta(minutes=30)

        order = self.create_buy_order(
            time_in_force=MarketOrder.TimeInForce.GTD,
            expires_at=expires_at,
        )
        order.status = MarketOrder.Status.PARTIALLY_FILLED
        order.filled_quantity = Decimal("4.0000")
        order.average_fill_price = Decimal("0.54000")
        order.save(
            update_fields=[
                "status",
                "filled_quantity",
                "average_fill_price",
                "updated_at",
            ]
        )

        first_audit = self.expire(
            order,
            current_time=expires_at + timedelta(seconds=1),
        )
        second_audit = self.expire(
            order,
            current_time=expires_at + timedelta(seconds=2),
        )

        self.assertEqual(
            first_audit.id,
            second_audit.id,
        )
        self.assertEqual(
            first_audit.expired_quantity,
            Decimal("6.0000"),
        )
        self.assertEqual(
            first_audit.released_wallet_reservation_amount,
            Decimal("3.3000"),
        )

        self.assertEqual(
            MarketOrderExpiryAudit.objects.filter(
                market_order=order,
            ).count(),
            1,
        )
        self.assertEqual(
            LedgerEntry.objects.filter(
                order=order,
                entry_type=LedgerEntry.EntryType.RELEASE,
            ).count(),
            1,
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.available_balance,
            Decimal("999997.8000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("2.2000"),
        )

    def test_expiring_sell_order_releases_reserved_position(self):
        expires_at = self.now + timedelta(minutes=30)

        order, position = self.create_sell_order(
            time_in_force=MarketOrder.TimeInForce.GTD,
            expires_at=expires_at,
        )

        audit = self.expire(
            order,
            current_time=expires_at + timedelta(seconds=1),
        )

        order.refresh_from_db()
        position.refresh_from_db()

        self.assertEqual(
            order.status,
            MarketOrder.Status.EXPIRED,
        )
        self.assertEqual(
            position.reserved_quantity,
            Decimal("0.0000"),
        )
        self.assertEqual(
            audit.released_position_reservation_quantity,
            Decimal("10.0000"),
        )
        self.assertEqual(
            audit.released_wallet_reservation_amount,
            Decimal("0.0000"),
        )

    def test_filled_order_cannot_be_expired(self):
        expires_at = self.now + timedelta(minutes=30)

        order = self.create_buy_order(
            time_in_force=MarketOrder.TimeInForce.GTD,
            expires_at=expires_at,
        )
        order.status = MarketOrder.Status.FILLED
        order.filled_quantity = order.quantity
        order.average_fill_price = order.limit_price
        order.save(
            update_fields=[
                "status",
                "filled_quantity",
                "average_fill_price",
                "updated_at",
            ]
        )

        with self.assertRaises(ValidationError) as context:
            self.expire(
                order,
                current_time=expires_at + timedelta(seconds=1),
            )

        self.assertIn(
            "status",
            context.exception.message_dict,
        )

    def test_expired_orders_are_not_matched(self):
        expires_at = self.now + timedelta(minutes=30)

        buy_order = self.create_buy_order(
            limit_price=Decimal("0.60000"),
            time_in_force=MarketOrder.TimeInForce.GTD,
            expires_at=expires_at,
        )

        self.expire(
            buy_order,
            current_time=expires_at + timedelta(seconds=1),
        )

        sell_order, _ = self.create_sell_order(
            limit_price=Decimal("0.50000"),
        )

        fills = MarketMatchingService.match_order(
            sell_order.id,
        )

        buy_order.refresh_from_db()
        sell_order.refresh_from_db()

        self.assertEqual(
            buy_order.status,
            MarketOrder.Status.EXPIRED,
        )
        self.assertEqual(
            sell_order.status,
            MarketOrder.Status.OPEN,
        )
        self.assertEqual(fills, [])
        self.assertFalse(
            MarketFill.objects.filter(
                buy_order=buy_order,
            ).exists()
        )

    def test_expiry_audit_is_immutable(self):
        expires_at = self.now + timedelta(minutes=30)

        order = self.create_buy_order(
            time_in_force=MarketOrder.TimeInForce.GTD,
            expires_at=expires_at,
        )
        audit = self.expire(
            order,
            current_time=expires_at + timedelta(seconds=1),
        )

        audit.reason = "Changed reason."

        with self.assertRaises(ValidationError):
            audit.save()

        with self.assertRaises(ValidationError):
            audit.delete()
