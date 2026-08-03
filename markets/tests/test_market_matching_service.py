from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

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
    MarketOutcome,
    MarketPosition,
    MarketScope,
)
from markets.services.catalog_service import MarketCatalogService
from markets.services.fill_service import MarketFillService
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.matching_service import MarketMatchingService
from markets.services.participation_service import MarketParticipationService
from markets.tests.eligibility_test_support import make_market_eligible
from markets.tests.wallet_test_support import fund_market_wallet
from sports.models import Competition, Sport, SportingEvent
from wallets.models import LedgerEntry, Wallet


class MarketMatchingServiceTests(APITestCase):
    def setUp(self):
        self.now = timezone.now()
        permissions = {}
        for name, action in (
            ("manage_market", "manage"),
            ("approve_market", "approve"),
            ("participate_market", "participate"),
        ):
            permissions[name] = PermissionFactory(name=name, resource="market", action=action)

        self.operations_role = RoleFactory(name="Operations", display_name="Operations")
        self.approval_role = RoleFactory(name="Approval", display_name="Approval")
        self.participant_role = RoleFactory(name="Participant", display_name="Participant")
        RolePermissionFactory(role=self.operations_role, permission=permissions["manage_market"])
        RolePermissionFactory(role=self.approval_role, permission=permissions["approve_market"])
        RolePermissionFactory(
            role=self.participant_role, permission=permissions["participate_market"]
        )

        self.operator = UserFactory()
        self.approver = UserFactory()
        UserRoleFactory(user=self.operator, role=self.operations_role)
        UserRoleFactory(user=self.approver, role=self.approval_role)
        self.users = [self.create_trader() for _ in range(6)]

        self.sport = Sport.objects.create(name="Football", code="FOOTBALL")
        self.category = MarketCategory.objects.create(name="Match Result")
        self.competition = Competition.objects.create(
            sport=self.sport,
            name="Uganda Premier League",
            country_code="UG",
            is_verified=True,
        )
        self.event = SportingEvent.objects.create(
            sport=self.sport,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="KCCA FC vs Vipers SC",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )
        self.market = self.create_open_market("Will KCCA FC win?")
        self.outcome = self.market.outcomes.get(side=MarketOutcome.Side.YES)

    def create_trader(self):
        user = UserFactory(is_verified=True)
        UserRoleFactory(user=user, role=self.participant_role)
        fund_market_wallet(user)
        return user

    def create_open_market(self, question):
        market = MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question=question,
            description="Prediction market.",
            rules="Official result.",
            resolution_source="Official result",
            resolution_criteria="Verified score.",
            status=Market.Status.DRAFT,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=1),
            created_by=self.operator,
            yes_label="Yes",
            no_label="No",
        )
        market = MarketLifecycleService.submit(
            market_id=market.id, actor=self.operator, notes="Ready."
        )
        market = MarketLifecycleService.approve(
            market_id=market.id, actor=self.approver, notes="Approved."
        )
        return MarketLifecycleService.open(
            market_id=market.id, actor=self.approver, notes="Opened."
        )

    def create_position(self, user, quantity="20.0000", market=None, outcome=None):
        return MarketPosition.objects.create(
            user=user,
            market=market or self.market,
            outcome=outcome or self.outcome,
            quantity=Decimal(quantity),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal(quantity) * Decimal("0.40000"),
        )

    def place(
        self,
        user,
        side,
        quantity="10.0000",
        price="0.55000",
        market=None,
        outcome=None,
    ):
        make_market_eligible(user)
        return MarketParticipationService.place_order(
            user=user,
            market_id=(market or self.market).id,
            outcome_id=(outcome or self.outcome).id,
            side=side,
            quantity=Decimal(quantity),
            limit_price=Decimal(price),
        )

    def resting_sell(self, user, quantity="10.0000", price="0.55000"):
        self.create_position(user, quantity=quantity)
        return self.place(user, MarketOrder.Side.SELL, quantity, price)

    def test_incoming_buy_uses_lowest_price_then_maker_price(self):
        expensive = self.resting_sell(self.users[1], "3.0000", "0.58000")
        cheapest = self.resting_sell(self.users[0], "3.0000", "0.54000")

        taker = self.place(self.users[2], MarketOrder.Side.BUY, "3.0000", "0.60000")

        fill = MarketFill.objects.get(taker_order=taker)
        self.assertEqual(fill.maker_order, cheapest)
        self.assertEqual(fill.price, Decimal("0.54000"))
        self.assertEqual(fill.buy_order, taker)
        self.assertEqual(fill.sell_order, cheapest)
        expensive.refresh_from_db()
        self.assertEqual(expensive.status, MarketOrder.Status.OPEN)

    def test_incoming_sell_uses_highest_buy_and_maker_price(self):
        low = self.place(self.users[0], MarketOrder.Side.BUY, "3.0000", "0.58000")
        high = self.place(self.users[1], MarketOrder.Side.BUY, "3.0000", "0.62000")
        self.create_position(self.users[2], "3.0000")

        taker = self.place(self.users[2], MarketOrder.Side.SELL, "3.0000", "0.55000")

        fill = MarketFill.objects.get(taker_order=taker)
        self.assertEqual(fill.maker_order, high)
        self.assertEqual(fill.price, Decimal("0.62000"))
        self.assertEqual(fill.buy_order, high)
        self.assertEqual(fill.sell_order, taker)
        low.refresh_from_db()
        self.assertEqual(low.status, MarketOrder.Status.OPEN)

    def test_same_price_uses_oldest_then_uuid_tie_breaker(self):
        first = self.resting_sell(self.users[0], "1.0000", "0.55000")
        second = self.resting_sell(self.users[1], "1.0000", "0.55000")
        shared_time = self.now - timedelta(minutes=1)
        MarketOrder.objects.filter(id__in=[first.id, second.id]).update(created_at=shared_time)
        expected = min((first, second), key=lambda order: order.id)

        taker = self.place(self.users[2], MarketOrder.Side.BUY, "1.0000", "0.55000")

        self.assertEqual(MarketFill.objects.get(taker_order=taker).maker_order, expected)

    def test_older_same_price_maker_wins(self):
        first = self.resting_sell(self.users[0], "1.0000", "0.55000")
        second = self.resting_sell(self.users[1], "1.0000", "0.55000")
        MarketOrder.objects.filter(id=first.id).update(created_at=self.now - timedelta(minutes=2))

        taker = self.place(self.users[2], MarketOrder.Side.BUY, "1.0000", "0.55000")

        self.assertEqual(MarketFill.objects.get(taker_order=taker).maker_order, first)
        second.refresh_from_db()
        self.assertEqual(second.status, MarketOrder.Status.OPEN)

    def test_smaller_maker_partially_fills_taker_and_accounting(self):
        maker = self.resting_sell(self.users[0], "4.0000", "0.54000")
        buyer_wallet = Wallet.objects.get(user=self.users[1], currency="UGX")
        seller_wallet = Wallet.objects.get(user=self.users[0], currency="UGX")

        taker = self.place(self.users[1], MarketOrder.Side.BUY, "10.0000", "0.60000")

        taker.refresh_from_db()
        maker.refresh_from_db()
        buyer_wallet.refresh_from_db()
        seller_wallet.refresh_from_db()
        seller_position = MarketPosition.objects.get(user=self.users[0], outcome=self.outcome)
        self.assertEqual(taker.status, MarketOrder.Status.PARTIALLY_FILLED)
        self.assertEqual(taker.filled_quantity, Decimal("4.0000"))
        self.assertEqual(maker.status, MarketOrder.Status.FILLED)
        self.assertEqual(buyer_wallet.available_balance, Decimal("999994.2400"))
        self.assertEqual(buyer_wallet.reserved_balance, Decimal("3.6000"))
        self.assertEqual(seller_wallet.available_balance, Decimal("1000002.1600"))
        self.assertEqual(seller_position.quantity, Decimal("0.0000"))
        self.assertEqual(seller_position.reserved_quantity, Decimal("0.0000"))

    def test_larger_taker_fills_multiple_makers_without_overfill(self):
        first = self.resting_sell(self.users[0], "3.0000", "0.53000")
        second = self.resting_sell(self.users[1], "4.0000", "0.54000")

        taker = self.place(self.users[2], MarketOrder.Side.BUY, "6.0000", "0.60000")

        fills = list(MarketFill.objects.filter(taker_order=taker).order_by("created_at", "id"))
        self.assertEqual([fill.maker_order_id for fill in fills], [first.id, second.id])
        self.assertEqual([fill.quantity for fill in fills], [Decimal("3.0000"), Decimal("3.0000")])
        taker.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(taker.status, MarketOrder.Status.FILLED)
        self.assertEqual(taker.filled_quantity, taker.quantity)
        self.assertEqual(second.status, MarketOrder.Status.PARTIALLY_FILLED)
        self.assertEqual(second.filled_quantity, Decimal("3.0000"))

    def test_non_crossing_order_stays_open_with_full_reservation(self):
        self.resting_sell(self.users[0], "3.0000", "0.61000")

        taker = self.place(self.users[1], MarketOrder.Side.BUY, "3.0000", "0.60000")

        wallet = Wallet.objects.get(user=self.users[1], currency="UGX")
        self.assertEqual(taker.status, MarketOrder.Status.OPEN)
        self.assertEqual(wallet.reserved_balance, Decimal("1.8000"))
        self.assertFalse(MarketFill.objects.exists())

    def test_unmatched_sell_keeps_full_position_reservation(self):
        position = self.create_position(self.users[0], "3.0000")
        order = self.place(self.users[0], MarketOrder.Side.SELL, "3.0000", "0.70000")
        position.refresh_from_db()
        self.assertEqual(order.status, MarketOrder.Status.OPEN)
        self.assertEqual(position.reserved_quantity, Decimal("3.0000"))

    def test_different_market_outcome_and_self_orders_are_ignored(self):
        other_market = self.create_open_market("Will Vipers score?")
        other_outcome = other_market.outcomes.get(side=MarketOutcome.Side.YES)
        self.create_position(self.users[0], "2.0000", other_market, other_outcome)
        self.place(
            self.users[0], MarketOrder.Side.SELL, "2.0000", "0.50000", other_market, other_outcome
        )
        no_outcome = self.market.outcomes.get(side=MarketOutcome.Side.NO)
        self.create_position(self.users[1], "2.0000", self.market, no_outcome)
        self.place(
            self.users[1], MarketOrder.Side.SELL, "2.0000", "0.50000", self.market, no_outcome
        )
        self.create_position(self.users[2], "2.0000")
        self.place(self.users[2], MarketOrder.Side.SELL, "2.0000", "0.50000")

        taker = self.place(self.users[2], MarketOrder.Side.BUY, "2.0000", "0.60000")

        self.assertEqual(taker.status, MarketOrder.Status.OPEN)
        self.assertFalse(MarketFill.objects.exists())

    def test_terminal_and_zero_remaining_legacy_orders_are_ignored(self):
        for index, order_status in enumerate(
            (MarketOrder.Status.CANCELLED, MarketOrder.Status.REJECTED, MarketOrder.Status.FILLED)
        ):
            user = self.users[index]
            self.create_position(user, "1.0000")
            MarketOrder.objects.create(
                user=user,
                market=self.market,
                outcome=self.outcome,
                side=MarketOrder.Side.SELL,
                quantity=Decimal("1.0000"),
                limit_price=Decimal("0.50000"),
                filled_quantity=(
                    Decimal("1.0000") if order_status == MarketOrder.Status.FILLED else Decimal("0")
                ),
                average_fill_price=(
                    Decimal("0.50000") if order_status == MarketOrder.Status.FILLED else None
                ),
                status=order_status,
            )
        taker = self.place(self.users[4], MarketOrder.Side.BUY, "1.0000", "0.60000")
        self.assertEqual(taker.status, MarketOrder.Status.OPEN)
        self.assertFalse(MarketFill.objects.exists())

    def test_match_order_replay_is_idempotent(self):
        self.resting_sell(self.users[0], "2.0000", "0.55000")
        taker = self.place(self.users[1], MarketOrder.Side.BUY, "2.0000", "0.60000")
        before_entries = LedgerEntry.objects.count()

        replay = MarketMatchingService.match_order(taker.id)

        self.assertEqual(replay, [])
        self.assertEqual(MarketFill.objects.count(), 1)
        self.assertEqual(LedgerEntry.objects.count(), before_entries)

    def test_execution_reference_is_stable_after_rollback(self):
        maker = self.resting_sell(self.users[0], "2.0000", "0.55000")
        with patch.object(MarketMatchingService, "match_order", return_value=[]):
            taker = self.place(self.users[1], MarketOrder.Side.BUY, "2.0000", "0.60000")
        references = []
        original = MarketFillService.execute_fill

        def fail_once(**kwargs):
            references.append(kwargs["execution_reference"])
            raise RuntimeError("rollback")

        with self.assertRaises(RuntimeError):
            with patch.object(MarketFillService, "execute_fill", side_effect=fail_once):
                MarketMatchingService.match_order(taker.id)
        with patch.object(MarketFillService, "execute_fill", wraps=original) as execute:
            MarketMatchingService.match_order(taker.id)
            references.append(execute.call_args.kwargs["execution_reference"])
        self.assertEqual(references[0], references[1])
        self.assertIsInstance(references[0], UUID)
        self.assertEqual(MarketFill.objects.get().maker_order_id, maker.id)

    def test_second_fill_failure_rolls_back_entire_match(self):
        makers = [
            self.resting_sell(
                self.users[0],
                "2.0000",
                "0.53000",
            ),
            self.resting_sell(
                self.users[1],
                "2.0000",
                "0.54000",
            ),
        ]
        seller_positions = [
            MarketPosition.objects.get(
                user=self.users[0],
                market=self.market,
                outcome=self.outcome,
            ),
            MarketPosition.objects.get(
                user=self.users[1],
                market=self.market,
                outcome=self.outcome,
            ),
        ]
        seller_wallets = [
            Wallet.objects.get(
                user=self.users[0],
                currency="UGX",
            ),
            Wallet.objects.get(
                user=self.users[1],
                currency="UGX",
            ),
        ]

        with patch.object(
            MarketMatchingService,
            "match_order",
            return_value=[],
        ):
            taker = self.place(
                self.users[2],
                MarketOrder.Side.BUY,
                "4.0000",
                "0.60000",
            )

        buyer_wallet = Wallet.objects.get(
            user=self.users[2],
            currency="UGX",
        )
        ledger_count_before = LedgerEntry.objects.count()
        buyer_balances_before = (
            buyer_wallet.available_balance,
            buyer_wallet.reserved_balance,
        )
        seller_balances_before = [
            (
                wallet.available_balance,
                wallet.reserved_balance,
            )
            for wallet in seller_wallets
        ]
        seller_positions_before = [
            (
                position.quantity,
                position.reserved_quantity,
                position.total_cost,
                position.realized_pnl,
            )
            for position in seller_positions
        ]

        original = MarketFillService.execute_fill
        calls = 0

        def fail_second(**kwargs):
            nonlocal calls
            calls += 1

            if calls == 2:
                raise RuntimeError("second fill failed")

            return original(**kwargs)

        with self.assertRaises(RuntimeError):
            with patch.object(
                MarketFillService,
                "execute_fill",
                side_effect=fail_second,
            ):
                MarketMatchingService.match_order(taker.id)

        self.assertFalse(MarketFill.objects.exists())

        taker.refresh_from_db()
        buyer_wallet.refresh_from_db()

        self.assertEqual(
            taker.filled_quantity,
            Decimal("0.0000"),
        )
        self.assertEqual(
            (
                buyer_wallet.available_balance,
                buyer_wallet.reserved_balance,
            ),
            buyer_balances_before,
        )

        for index, maker in enumerate(makers):
            maker.refresh_from_db()
            seller_positions[index].refresh_from_db()
            seller_wallets[index].refresh_from_db()

            self.assertEqual(
                maker.filled_quantity,
                Decimal("0.0000"),
            )
            self.assertEqual(
                (
                    seller_wallets[index].available_balance,
                    seller_wallets[index].reserved_balance,
                ),
                seller_balances_before[index],
            )
            self.assertEqual(
                (
                    seller_positions[index].quantity,
                    seller_positions[index].reserved_quantity,
                    seller_positions[index].total_cost,
                    seller_positions[index].realized_pnl,
                ),
                seller_positions_before[index],
            )

        self.assertEqual(
            LedgerEntry.objects.count(),
            ledger_count_before,
        )
        self.assertFalse(
            LedgerEntry.objects.filter(
                fill__isnull=False,
            ).exists()
        )

    def test_place_order_matching_failure_rolls_back_order_and_reservation(self):
        self.resting_sell(self.users[0], "2.0000", "0.55000")
        before_orders = MarketOrder.objects.count()
        with patch.object(MarketMatchingService, "match_order", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):
                self.place(self.users[1], MarketOrder.Side.BUY, "2.0000", "0.60000")
        wallet = Wallet.objects.get(user=self.users[1], currency="UGX")
        self.assertEqual(MarketOrder.objects.count(), before_orders)
        self.assertEqual(wallet.available_balance, Decimal("1000000.0000"))
        self.assertEqual(wallet.reserved_balance, Decimal("0.0000"))

    def test_sell_place_order_matching_failure_rolls_back_reservation(
        self,
    ):
        self.place(
            self.users[0],
            MarketOrder.Side.BUY,
            "2.0000",
            "0.62000",
        )
        position = self.create_position(
            self.users[1],
            "2.0000",
        )
        seller_wallet = Wallet.objects.get(
            user=self.users[1],
            currency="UGX",
        )

        order_count_before = MarketOrder.objects.count()
        ledger_count_before = LedgerEntry.objects.count()
        seller_balances_before = (
            seller_wallet.available_balance,
            seller_wallet.reserved_balance,
        )

        with patch.object(
            MarketMatchingService,
            "match_order",
            side_effect=RuntimeError("matching failed"),
        ):
            with self.assertRaises(RuntimeError):
                self.place(
                    self.users[1],
                    MarketOrder.Side.SELL,
                    "2.0000",
                    "0.55000",
                )

        position.refresh_from_db()
        seller_wallet.refresh_from_db()

        self.assertEqual(
            MarketOrder.objects.count(),
            order_count_before,
        )
        self.assertFalse(
            MarketOrder.objects.filter(
                user=self.users[1],
                side=MarketOrder.Side.SELL,
            ).exists()
        )
        self.assertEqual(
            position.quantity,
            Decimal("2.0000"),
        )
        self.assertEqual(
            position.reserved_quantity,
            Decimal("0.0000"),
        )
        self.assertEqual(
            (
                seller_wallet.available_balance,
                seller_wallet.reserved_balance,
            ),
            seller_balances_before,
        )
        self.assertEqual(
            LedgerEntry.objects.count(),
            ledger_count_before,
        )

    def test_partially_matched_sell_retains_remaining_reservation(
        self,
    ):
        maker = self.place(
            self.users[0],
            MarketOrder.Side.BUY,
            "2.0000",
            "0.62000",
        )
        seller_position = self.create_position(
            self.users[1],
            "5.0000",
        )
        seller_wallet = Wallet.objects.get(
            user=self.users[1],
            currency="UGX",
        )

        taker = self.place(
            self.users[1],
            MarketOrder.Side.SELL,
            "5.0000",
            "0.55000",
        )

        maker.refresh_from_db()
        taker.refresh_from_db()
        seller_position.refresh_from_db()
        seller_wallet.refresh_from_db()

        self.assertEqual(
            maker.status,
            MarketOrder.Status.FILLED,
        )
        self.assertEqual(
            taker.status,
            MarketOrder.Status.PARTIALLY_FILLED,
        )
        self.assertEqual(
            taker.filled_quantity,
            Decimal("2.0000"),
        )
        self.assertEqual(
            seller_position.quantity,
            Decimal("3.0000"),
        )
        self.assertEqual(
            seller_position.reserved_quantity,
            Decimal("3.0000"),
        )
        self.assertEqual(
            seller_wallet.available_balance,
            Decimal("1000001.2400"),
        )
        self.assertEqual(
            MarketFill.objects.get(
                taker_order=taker,
            ).price,
            Decimal("0.62000"),
        )

    def test_match_order_returns_priority_ordered_fills(self):
        makers = [
            self.resting_sell(self.users[0], "1.0000", "0.53000"),
            self.resting_sell(self.users[1], "1.0000", "0.54000"),
        ]
        with patch.object(MarketMatchingService, "match_order", return_value=[]):
            taker = self.place(self.users[2], MarketOrder.Side.BUY, "2.0000", "0.60000")
        fills = MarketMatchingService.match_order(taker.id)
        self.assertEqual([fill.maker_order_id for fill in fills], [order.id for order in makers])

    def test_api_returns_final_status_and_fill_values(self):
        self.resting_sell(self.users[0], "2.0000", "0.54000")
        make_market_eligible(self.users[1])
        self.client.force_authenticate(user=self.users[1])
        response = self.client.post(
            reverse("markets:market-order-create", kwargs={"market_id": self.market.id}),
            {
                "outcome_id": str(self.outcome.id),
                "side": MarketOrder.Side.BUY,
                "quantity": "2.0000",
                "limit_price": "0.60000",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], MarketOrder.Status.FILLED)
        self.assertEqual(Decimal(response.data["filled_quantity"]), Decimal("2.0000"))
        self.assertEqual(Decimal(response.data["average_fill_price"]), Decimal("0.54000"))
