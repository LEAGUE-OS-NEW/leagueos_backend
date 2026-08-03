from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from django.utils import timezone

from authentication.tests.factories import UserFactory
from markets.models import (
    Market,
    MarketCategory,
    MarketRecentView,
    MarketScope,
    MarketWatchlistEntry,
)
from markets.services.catalog_service import MarketCatalogService
from markets.services.recent_view_service import (
    MarketRecentViewService,
)
from markets.services.watchlist_service import (
    MarketWatchlistService,
)
from sports.models import Sport


class MarketDiscoveryConcurrencyFixtureMixin:
    def setUp(self):
        super().setUp()

        now = timezone.now()
        self.user = UserFactory()
        self.sport = Sport.objects.create(
            name="Concurrency Football",
            code="DISCOVERY_CONCURRENCY_FOOTBALL",
        )
        self.category = MarketCategory.objects.create(
            name="Concurrency Markets",
        )
        self.market = MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.CUSTOM,
            custom_subject="Concurrency",
            question="Will the concurrency test market resolve YES?",
            status=Market.Status.OPEN,
            opens_at=now,
            closes_at=now + timedelta(days=1),
        )

    def run_workers(self, worker, *, count=2):
        barrier = Barrier(count)

        def synchronized_worker():
            close_old_connections()

            try:
                barrier.wait(timeout=10)
                return worker()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=count) as executor:
            futures = [executor.submit(synchronized_worker) for _ in range(count)]
            return [future.result(timeout=30) for future in futures]


class MarketDiscoveryPostgreSQLConcurrencyTests(
    MarketDiscoveryConcurrencyFixtureMixin,
    TransactionTestCase,
):
    reset_sequences = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        if connection.vendor != "postgresql":
            raise cls.skipTest("Market discovery concurrency guarantees require PostgreSQL.")

    def participant(self):
        return get_user_model().objects.get(pk=self.user.pk)

    def test_concurrent_first_recent_views_create_one_row_and_count_two(
        self,
    ):
        def record():
            row, created = MarketRecentViewService.record(
                participant=self.participant(),
                market_id=self.market.id,
            )
            return row.id, created

        results = self.run_workers(record)

        self.assertEqual(len(results), 2)
        self.assertEqual(
            {row_id for row_id, _created in results},
            {
                MarketRecentView.objects.get(
                    participant=self.user,
                    market=self.market,
                ).id
            },
        )
        self.assertEqual(
            sorted(created for _row_id, created in results),
            [False, True],
        )

        row = MarketRecentView.objects.get(
            participant=self.user,
            market=self.market,
        )

        self.assertEqual(MarketRecentView.objects.count(), 1)
        self.assertEqual(row.view_count, 2)
        self.assertLessEqual(
            row.first_viewed_at,
            row.last_viewed_at,
        )

    def test_concurrent_existing_recent_view_increments_are_not_lost(
        self,
    ):
        original, created = MarketRecentViewService.record(
            participant=self.user,
            market_id=self.market.id,
        )
        self.assertTrue(created)
        original_first_viewed_at = original.first_viewed_at

        def record():
            row, repeated_created = MarketRecentViewService.record(
                participant=self.participant(),
                market_id=self.market.id,
            )
            return row.id, repeated_created

        results = self.run_workers(record)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(repeated_created is False for _row_id, repeated_created in results))

        row = MarketRecentView.objects.get(
            participant=self.user,
            market=self.market,
        )

        self.assertEqual(MarketRecentView.objects.count(), 1)
        self.assertEqual(row.view_count, 3)
        self.assertEqual(
            row.first_viewed_at,
            original_first_viewed_at,
        )
        self.assertGreaterEqual(
            row.last_viewed_at,
            row.first_viewed_at,
        )

    def test_concurrent_watchlist_follow_creates_one_entry(self):
        def follow():
            row, created = MarketWatchlistService.follow(
                participant=self.participant(),
                market_id=self.market.id,
            )
            return row.id, created

        results = self.run_workers(follow)

        self.assertEqual(len(results), 2)
        self.assertEqual(
            sorted(created for _row_id, created in results),
            [False, True],
        )

        row = MarketWatchlistEntry.objects.get(
            participant=self.user,
            market=self.market,
        )

        self.assertEqual(MarketWatchlistEntry.objects.count(), 1)
        self.assertEqual(
            {row_id for row_id, _created in results},
            {row.id},
        )
