from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from django.db import IntegrityError, connection
from django.db.models import Sum
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from authentication.tests.factories import UserFactory
from markets.models import (
    Market,
    MarketCategory,
    MarketEventGroup,
    MarketFill,
    MarketOrder,
    MarketPosition,
    MarketRecentView,
    MarketScope,
    MarketSettlement,
    MarketVoidRefund,
    MarketWatchlistEntry,
)
from markets.price_history_serializers import PriceHistoryQuerySerializer
from markets.services.catalog_service import MarketCatalogService
from markets.services.price_history_service import MarketPriceHistoryService
from markets.services.recent_view_service import MarketRecentViewService
from markets.services.watchlist_service import MarketWatchlistService
from sports.models import Sport, SportingEvent
from wallets.models import LedgerEntry, Wallet


class DiscoveryPricingFixtureMixin:
    def make_market(self, *, status=Market.Status.OPEN, question="A market"):
        return MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.CUSTOM,
            custom_subject="Discovery",
            question=question,
            status=status,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(days=1),
        )

    def setUp(self):
        self.now = timezone.now()
        self.user = UserFactory()
        self.other_user = UserFactory()
        self.sport = Sport.objects.create(name="Football", code="DISCOVERY_FOOTBALL")
        self.category = MarketCategory.objects.create(name="Discovery")
        self.market = self.make_market()
        self.hidden_market = self.make_market(status=Market.Status.DRAFT, question="Hidden")


class WatchlistRecentViewModelServiceTests(DiscoveryPricingFixtureMixin, TestCase):
    def test_watchlist_follow_is_idempotent_and_unique(self):
        first, created = MarketWatchlistService.follow(
            participant=self.user, market_id=self.market.id
        )
        second, repeated_created = MarketWatchlistService.follow(
            participant=self.user, market_id=self.market.id
        )
        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(first.id, second.id)
        self.assertEqual(MarketWatchlistEntry.objects.count(), 1)
        with self.assertRaises(IntegrityError):
            MarketWatchlistEntry.objects.create(participant=self.user, market=self.market)

    def test_recent_view_increments_and_preserves_first_timestamp(self):
        first, created = MarketRecentViewService.record(
            participant=self.user, market_id=self.market.id
        )
        original_first = first.first_viewed_at
        second, repeated_created = MarketRecentViewService.record(
            participant=self.user, market_id=self.market.id
        )
        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(second.first_viewed_at, original_first)
        self.assertEqual(second.view_count, 2)
        self.assertGreaterEqual(second.last_viewed_at, first.last_viewed_at)
        self.assertEqual(MarketRecentView.objects.count(), 1)

    def test_hidden_market_is_unavailable_to_preference_services(self):
        with self.assertRaises(Market.DoesNotExist):
            MarketWatchlistService.follow(participant=self.user, market_id=self.hidden_market.id)
        with self.assertRaises(Market.DoesNotExist):
            MarketRecentViewService.record(participant=self.user, market_id=self.hidden_market.id)


class WatchlistRecentDiscoveryAPITests(DiscoveryPricingFixtureMixin, APITestCase):
    def test_personal_endpoints_require_authentication(self):
        urls = [
            reverse("markets:market-watchlist"),
            reverse("markets:market-recently-viewed"),
            reverse("markets:market-discovery"),
        ]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 401)

    def test_watchlist_and_recent_view_put_are_idempotent(self):
        self.client.force_authenticate(self.user)
        watch_url = reverse("markets:market-watchlist-item", kwargs={"market_id": self.market.id})
        recent_url = reverse(
            "markets:market-recently-viewed-item",
            kwargs={"market_id": self.market.id},
        )
        self.assertEqual(self.client.put(watch_url).status_code, 201)
        self.assertEqual(self.client.put(watch_url).status_code, 200)
        self.assertEqual(self.client.put(recent_url).status_code, 201)
        self.assertEqual(self.client.put(recent_url).status_code, 200)
        self.assertEqual(MarketRecentView.objects.get().view_count, 2)

    def test_market_serializer_includes_watchlist_state(self):
        detail = reverse("markets:market-detail", kwargs={"market_id": self.market.id})
        self.assertIs(self.client.get(detail).data["is_watchlisted"], False)
        MarketWatchlistService.follow(participant=self.user, market_id=self.market.id)
        self.client.force_authenticate(self.user)
        self.assertIs(self.client.get(detail).data["is_watchlisted"], True)

    def test_discovery_is_non_mutating_and_has_exact_sections(self):
        self.client.force_authenticate(self.user)
        before = (MarketWatchlistEntry.objects.count(), MarketRecentView.objects.count())
        response = self.client.get(reverse("markets:market-discovery"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"watchlist", "recently_viewed", "related_markets"})
        self.assertEqual(
            before, (MarketWatchlistEntry.objects.count(), MarketRecentView.objects.count())
        )

    def test_lists_deletes_clear_and_unavailable_market_paths(self):
        self.client.force_authenticate(self.user)
        watch_url = reverse("markets:market-watchlist-item", kwargs={"market_id": self.market.id})
        recent_url = reverse(
            "markets:market-recently-viewed-item", kwargs={"market_id": self.market.id}
        )
        self.client.put(watch_url)
        self.client.put(recent_url)
        watch = self.client.get(reverse("markets:market-watchlist"))
        recent = self.client.get(reverse("markets:market-recently-viewed"))
        self.assertEqual(watch.data["count"], 1)
        self.assertEqual(recent.data["count"], 1)
        self.assertTrue(recent.data["results"][0]["is_watchlisted"])
        self.assertEqual(self.client.delete(watch_url).status_code, 204)
        self.assertEqual(self.client.delete(watch_url).status_code, 204)
        self.assertEqual(self.client.delete(recent_url).status_code, 204)
        self.client.put(recent_url)
        self.assertEqual(
            self.client.delete(reverse("markets:market-recently-viewed")).status_code, 204
        )
        self.assertFalse(MarketRecentView.objects.exists())
        hidden_watch = reverse(
            "markets:market-watchlist-item", kwargs={"market_id": self.hidden_market.id}
        )
        hidden_recent = reverse(
            "markets:market-recently-viewed-item", kwargs={"market_id": self.hidden_market.id}
        )
        self.assertEqual(self.client.put(hidden_watch).status_code, 404)
        self.assertEqual(self.client.put(hidden_recent).status_code, 404)

    def test_discovery_validates_limit_and_returns_populated_sections(self):
        self.client.force_authenticate(self.user)
        MarketWatchlistService.follow(participant=self.user, market_id=self.market.id)
        MarketRecentViewService.record(participant=self.user, market_id=self.market.id)
        url = reverse("markets:market-discovery")
        self.assertEqual(self.client.get(url, {"section_limit": 0}).status_code, 400)
        response = self.client.get(url, {"section_limit": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["watchlist"]), 1)
        self.assertEqual(len(response.data["recently_viewed"]), 1)

    def preference_snapshot(self):
        return {
            "watchlist": list(
                MarketWatchlistEntry.objects.order_by("id").values_list(
                    "id",
                    "participant_id",
                    "market_id",
                    "followed_at",
                    "created_at",
                    "updated_at",
                )
            ),
            "recent": list(
                MarketRecentView.objects.order_by("id").values_list(
                    "id",
                    "participant_id",
                    "market_id",
                    "first_viewed_at",
                    "last_viewed_at",
                    "view_count",
                    "created_at",
                    "updated_at",
                )
            ),
        }

    def test_read_endpoints_do_not_mutate_preference_rows(self):
        MarketWatchlistService.follow(
            participant=self.user,
            market_id=self.market.id,
        )
        MarketRecentViewService.record(
            participant=self.user,
            market_id=self.market.id,
        )
        self.client.force_authenticate(self.user)

        outcome = self.market.outcomes.first()
        history_url = reverse(
            "markets:market-outcome-price-history",
            kwargs={
                "market_id": self.market.id,
                "outcome_id": outcome.id,
            },
        )

        requests = [
            (reverse("markets:market-list"), {}),
            (
                reverse(
                    "markets:market-detail",
                    kwargs={"market_id": self.market.id},
                ),
                {},
            ),
            (reverse("markets:market-watchlist"), {}),
            (reverse("markets:market-recently-viewed"), {}),
            (reverse("markets:market-discovery"), {}),
            (history_url, {"interval": "RAW"}),
            (history_url, {"interval": "HOUR"}),
            (history_url, {"interval": "DAY"}),
        ]

        before = self.preference_snapshot()

        for url, params in requests:
            response = self.client.get(url, params)
            self.assertEqual(
                response.status_code,
                200,
                msg=f"Unexpected response for {url}: {response.data}",
            )

        self.assertEqual(
            self.preference_snapshot(),
            before,
        )

    def test_market_detail_get_does_not_create_recent_view(self):
        self.client.force_authenticate(self.user)

        before = self.preference_snapshot()

        response = self.client.get(
            reverse(
                "markets:market-detail",
                kwargs={"market_id": self.market.id},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.preference_snapshot(), before)
        self.assertFalse(MarketRecentView.objects.exists())

    def test_list_and_discovery_query_counts_do_not_grow_per_row(self):
        self.client.force_authenticate(self.user)

        def add_markets(start, stop):
            for index in range(start, stop):
                market = self.make_market(
                    question=f"Discovery query market {index}",
                )
                MarketWatchlistService.follow(
                    participant=self.user,
                    market_id=market.id,
                )
                MarketRecentViewService.record(
                    participant=self.user,
                    market_id=market.id,
                )

        def query_count(url, params=None):
            with CaptureQueriesContext(connection) as captured:
                response = self.client.get(url, params or {})
                self.assertEqual(
                    response.status_code,
                    200,
                    msg=f"Unexpected response for {url}: {response.data}",
                )
            return len(captured)

        add_markets(0, 5)

        urls = {
            "market_list": reverse("markets:market-list"),
            "watchlist": reverse("markets:market-watchlist"),
            "recent": reverse("markets:market-recently-viewed"),
            "discovery": reverse("markets:market-discovery"),
        }

        baseline = {name: query_count(url) for name, url in urls.items()}

        detail_count = query_count(
            reverse(
                "markets:market-detail",
                kwargs={"market_id": self.market.id},
            )
        )

        add_markets(5, 10)

        expanded = {name: query_count(url) for name, url in urls.items()}

        self.assertEqual(expanded, baseline)

        self.assertLessEqual(
            baseline["market_list"],
            12,
            baseline,
        )
        self.assertLessEqual(
            baseline["watchlist"],
            12,
            baseline,
        )
        self.assertLessEqual(
            baseline["recent"],
            12,
            baseline,
        )
        self.assertLessEqual(
            baseline["discovery"],
            20,
            baseline,
        )
        self.assertLessEqual(detail_count, 8)

    def test_price_history_no_fill_query_counts_are_fixed(self):
        outcome = self.market.outcomes.first()
        url = reverse(
            "markets:market-outcome-price-history",
            kwargs={
                "market_id": self.market.id,
                "outcome_id": outcome.id,
            },
        )

        counts = {}

        for interval in ("RAW", "HOUR", "DAY"):
            with CaptureQueriesContext(connection) as captured:
                response = self.client.get(
                    url,
                    {"interval": interval},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["points"], [])
            counts[interval] = len(captured)

        self.assertLessEqual(counts["RAW"], 4, counts)
        self.assertLessEqual(counts["HOUR"], 4, counts)
        self.assertLessEqual(counts["DAY"], 4, counts)

    def financial_snapshot(self):
        return {
            "wallets": list(
                Wallet.objects.order_by("id").values_list(
                    "id",
                    "user_id",
                    "currency",
                    "available_balance",
                    "reserved_balance",
                )
            ),
            "ledger_count": LedgerEntry.objects.count(),
            "ledger_amount": LedgerEntry.objects.aggregate(total=Sum("amount"))["total"],
            "order_count": MarketOrder.objects.count(),
            "order_quantity": MarketOrder.objects.aggregate(total=Sum("quantity"))["total"],
            "position_count": MarketPosition.objects.count(),
            "position_quantity": MarketPosition.objects.aggregate(total=Sum("quantity"))["total"],
            "fill_count": MarketFill.objects.count(),
            "fill_quantity": MarketFill.objects.aggregate(total=Sum("quantity"))["total"],
            "settlement_count": MarketSettlement.objects.count(),
            "void_refund_count": MarketVoidRefund.objects.count(),
        }

    def test_discovery_ranking_is_exact_and_participant_private(self):
        event = SportingEvent.objects.create(
            sport=self.sport,
            name="Discovery United v Ranking City",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

        group = MarketEventGroup.objects.create(
            title="Discovery Ranking Event",
            slug=f"discovery-ranking-{uuid4()}",
            event_type=MarketEventGroup.EventType.SPORTING_EVENT,
            sporting_event=event,
            category=self.category,
            scheduled_at=event.starts_at,
            status=MarketEventGroup.Status.PUBLISHED,
            created_by=self.user,
            published_by=self.user,
            published_at=self.now,
        )

        def event_market(
            *,
            question,
            event_group=None,
            status=Market.Status.OPEN,
            closes_in_hours=12,
        ):
            return MarketCatalogService.create_market(
                sport=self.sport,
                category=self.category,
                event_group=event_group,
                scope_type=MarketScope.EVENT,
                sporting_event=event,
                question=question,
                status=status,
                opens_at=self.now - timedelta(hours=1),
                closes_at=self.now + timedelta(hours=closes_in_hours),
            )

        source = event_market(
            question="Will Discovery United win?",
            event_group=group,
        )
        same_group = event_market(
            question="Will both teams score?",
            event_group=group,
            closes_in_hours=5,
        )
        same_event = event_market(
            question="Will there be over two goals?",
            closes_in_hours=4,
        )

        same_category = MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.CUSTOM,
            custom_subject="Category ranking",
            question="Will the category candidate resolve YES?",
            status=Market.Status.OPEN,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=3),
        )

        other_category = MarketCategory.objects.create(
            name="Discovery Other Category",
        )
        same_sport = MarketCatalogService.create_market(
            sport=self.sport,
            category=other_category,
            scope_type=MarketScope.CUSTOM,
            custom_subject="Sport ranking",
            question="Will the sport candidate resolve YES?",
            status=Market.Status.OPEN,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=2),
        )

        other_sport = Sport.objects.create(
            name="Discovery Basketball",
            code=f"DISCOVERY_BASKETBALL_{uuid4().hex[:8]}",
        )
        unrelated_category = MarketCategory.objects.create(
            name="Discovery Unrelated Category",
        )
        unrelated = MarketCatalogService.create_market(
            sport=other_sport,
            category=unrelated_category,
            scope_type=MarketScope.CUSTOM,
            custom_subject="Unrelated ranking",
            question="Will the unrelated candidate resolve YES?",
            status=Market.Status.OPEN,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=1),
        )

        hidden = event_market(
            question="Hidden ranking candidate",
            event_group=group,
            status=Market.Status.DRAFT,
            closes_in_hours=1,
        )
        closed = event_market(
            question="Closed ranking candidate",
            event_group=group,
            status=Market.Status.CLOSED,
            closes_in_hours=1,
        )

        # The shared fixture creates self.market with this same category and
        # sport. Hide it so this test has an explicit, isolated candidate set.
        Market.objects.filter(pk=self.market.pk).update(
            status=Market.Status.DRAFT,
        )
        self.market.refresh_from_db(fields=["status"])

        MarketWatchlistService.follow(
            participant=self.user,
            market_id=source.id,
        )
        MarketRecentViewService.record(
            participant=self.user,
            market_id=source.id,
        )

        self.client.force_authenticate(self.user)
        url = reverse("markets:market-discovery")

        response = self.client.get(
            url,
            {"section_limit": 10},
        )

        self.assertEqual(response.status_code, 200)

        related_ids = [str(item["id"]) for item in response.data["related_markets"]]

        self.assertEqual(
            related_ids[:5],
            [
                str(same_group.id),
                str(same_event.id),
                str(same_category.id),
                str(same_sport.id),
                str(unrelated.id),
            ],
        )

        excluded_ids = {
            str(source.id),
            str(hidden.id),
            str(closed.id),
            str(self.market.id),
        }

        self.assertTrue(excluded_ids.isdisjoint(related_ids))

        MarketWatchlistService.follow(
            participant=self.other_user,
            market_id=unrelated.id,
        )
        MarketRecentViewService.record(
            participant=self.other_user,
            market_id=same_sport.id,
        )

        repeated = self.client.get(
            url,
            {"section_limit": 10},
        )

        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(
            [str(item["id"]) for item in repeated.data["related_markets"]][:5],
            related_ids[:5],
        )

    def test_discovery_feature_operations_are_financially_neutral(self):
        self.client.force_authenticate(self.user)

        outcome = self.market.outcomes.first()
        history_url = reverse(
            "markets:market-outcome-price-history",
            kwargs={
                "market_id": self.market.id,
                "outcome_id": outcome.id,
            },
        )

        before = self.financial_snapshot()

        def assert_neutral(label, operation):
            result = operation()
            self.assertEqual(
                self.financial_snapshot(),
                before,
                msg=f"Financial state changed after {label}",
            )
            return result

        assert_neutral(
            "follow",
            lambda: MarketWatchlistService.follow(
                participant=self.user,
                market_id=self.market.id,
            ),
        )
        assert_neutral(
            "repeated follow",
            lambda: MarketWatchlistService.follow(
                participant=self.user,
                market_id=self.market.id,
            ),
        )
        assert_neutral(
            "unfollow",
            lambda: MarketWatchlistService.unfollow(
                participant=self.user,
                market_id=self.market.id,
            ),
        )
        assert_neutral(
            "record recent view",
            lambda: MarketRecentViewService.record(
                participant=self.user,
                market_id=self.market.id,
            ),
        )
        assert_neutral(
            "increment recent view",
            lambda: MarketRecentViewService.record(
                participant=self.user,
                market_id=self.market.id,
            ),
        )
        assert_neutral(
            "remove recent view",
            lambda: MarketRecentViewService.remove(
                participant=self.user,
                market_id=self.market.id,
            ),
        )
        assert_neutral(
            "record before clear",
            lambda: MarketRecentViewService.record(
                participant=self.user,
                market_id=self.market.id,
            ),
        )
        assert_neutral(
            "clear recent views",
            lambda: MarketRecentViewService.clear(
                participant=self.user,
            ),
        )

        get_requests = [
            (
                "market list",
                reverse("markets:market-list"),
                {},
            ),
            (
                "market detail",
                reverse(
                    "markets:market-detail",
                    kwargs={"market_id": self.market.id},
                ),
                {},
            ),
            (
                "watchlist",
                reverse("markets:market-watchlist"),
                {},
            ),
            (
                "recently viewed",
                reverse("markets:market-recently-viewed"),
                {},
            ),
            (
                "discovery",
                reverse("markets:market-discovery"),
                {},
            ),
            (
                "raw history",
                history_url,
                {"interval": "RAW"},
            ),
            (
                "hour history",
                history_url,
                {"interval": "HOUR"},
            ),
            (
                "day history",
                history_url,
                {"interval": "DAY"},
            ),
        ]

        for label, url, params in get_requests:
            response = assert_neutral(
                label,
                lambda url=url, params=params: self.client.get(
                    url,
                    params,
                ),
            )
            self.assertEqual(
                response.status_code,
                200,
                msg=f"Unexpected response for {label}: " f"{response.data}",
            )


class PriceHistoryAPITests(DiscoveryPricingFixtureMixin, APITestCase):
    def test_empty_raw_history_and_validation(self):
        outcome = self.market.outcomes.first()
        url = reverse(
            "markets:market-outcome-price-history",
            kwargs={"market_id": self.market.id, "outcome_id": outcome.id},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["interval"], "RAW")
        self.assertEqual(response.data["points"], [])
        self.assertEqual(self.client.get(url, {"interval": "WEEK"}).status_code, 400)
        self.assertEqual(self.client.get(url, {"limit": 0}).status_code, 400)
        self.assertEqual(
            self.client.get(
                url,
                {
                    "start": "2026-01-02T00:00:00Z",
                    "end": "2026-01-01T00:00:00Z",
                },
            ).status_code,
            400,
        )

    def test_price_history_does_not_record_a_recent_view(self):
        outcome = self.market.outcomes.first()
        url = reverse(
            "markets:market-outcome-price-history",
            kwargs={"market_id": self.market.id, "outcome_id": outcome.id},
        )
        self.client.get(url)
        self.assertFalse(MarketRecentView.objects.exists())

    def test_hidden_market_outcome_mismatch_and_timestamp_validation(self):
        outcome = self.market.outcomes.first()
        hidden_outcome = self.hidden_market.outcomes.first()
        hidden_url = reverse(
            "markets:market-outcome-price-history",
            kwargs={"market_id": self.hidden_market.id, "outcome_id": hidden_outcome.id},
        )
        mismatch_url = reverse(
            "markets:market-outcome-price-history",
            kwargs={"market_id": self.market.id, "outcome_id": hidden_outcome.id},
        )
        valid_url = reverse(
            "markets:market-outcome-price-history",
            kwargs={"market_id": self.market.id, "outcome_id": outcome.id},
        )
        self.assertEqual(self.client.get(hidden_url).status_code, 404)
        self.assertEqual(self.client.get(mismatch_url).status_code, 404)
        self.assertEqual(
            self.client.get(valid_url, {"start": "2026-01-01T00:00:00"}).status_code,
            400,
        )
        self.assertEqual(self.client.get(valid_url, {"limit": 1001}).status_code, 400)


class PriceHistoryServiceTests(TestCase):
    class FakeQuerySet:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, **kwargs):
            return self

        def only(self, *fields):
            return self

        def order_by(self, *fields):
            return self

        def __getitem__(self, item):
            return self.rows[item]

    def fill(self, *, when, price, quantity="1.0000", fill_id=None):
        return SimpleNamespace(
            id=fill_id or uuid4(),
            created_at=when,
            price=Decimal(price),
            quantity=Decimal(quantity),
        )

    def test_raw_and_ohlcv_are_derived_from_ordered_immutable_fills(self):
        # Fixed safely away from the Africa/Kampala midnight boundary so all
        # three fills belong to one DAY bucket.
        start = datetime(2026, 1, 15, 8, 5, tzinfo=UTC)
        rows = [
            self.fill(when=start, price="0.50000", quantity="2.0000"),
            self.fill(when=start + timedelta(minutes=10), price="0.70000", quantity="3.0000"),
            self.fill(when=start + timedelta(hours=1), price="0.40000", quantity="4.0000"),
        ]
        queryset = self.FakeQuerySet(rows)
        with patch(
            "markets.services.price_history_service.MarketFill.objects.filter",
            return_value=queryset,
        ):
            raw = MarketPriceHistoryService.history(
                market_id=uuid4(), outcome_id=uuid4(), interval="RAW", limit=200
            )
            hourly = MarketPriceHistoryService.history(
                market_id=uuid4(),
                outcome_id=uuid4(),
                interval="HOUR",
                start=start,
                end=start + timedelta(hours=2),
                limit=200,
            )
            daily = MarketPriceHistoryService.history(
                market_id=uuid4(),
                outcome_id=uuid4(),
                interval="DAY",
                start=start - timedelta(hours=1),
                end=start + timedelta(hours=2),
                limit=200,
            )
        self.assertEqual(raw[0]["price"], Decimal("0.5000"))
        self.assertEqual(hourly[0]["open"], Decimal("0.5000"))
        self.assertEqual(hourly[0]["high"], Decimal("0.7000"))
        self.assertEqual(hourly[0]["low"], Decimal("0.5000"))
        self.assertEqual(hourly[0]["close"], Decimal("0.7000"))
        self.assertEqual(hourly[0]["volume"], Decimal("5.0000"))
        self.assertEqual(hourly[0]["trade_count"], 2)
        self.assertEqual(len(hourly), 2)
        self.assertEqual(daily[0]["volume"], Decimal("9.0000"))


class PriceHistoryRangeContractTests(TestCase):
    class FakeQuerySet:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, **kwargs):
            return self

        def only(self, *fields):
            return self

        def order_by(self, *fields):
            return self

        def __iter__(self):
            return iter(self.rows)

        def __getitem__(self, item):
            return self.rows[item]

    def make_fill(self, *, fill_id, when, price, quantity):
        return SimpleNamespace(
            id=fill_id,
            created_at=when,
            price=Decimal(price),
            quantity=Decimal(quantity),
        )

    def test_aggregate_range_defaults_and_one_sided_ranges(self):
        fixed_now = datetime(2026, 1, 15, 8, 0, tzinfo=UTC)

        with patch(
            "markets.services.price_history_service.timezone.now",
            return_value=fixed_now,
        ):
            start, end = MarketPriceHistoryService.resolve_aggregate_range(interval="HOUR")

        self.assertEqual(end, fixed_now)
        self.assertEqual(start, fixed_now - timedelta(days=31))

        explicit_end = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
        start, end = MarketPriceHistoryService.resolve_aggregate_range(
            interval="HOUR",
            end=explicit_end,
        )
        self.assertEqual(end, explicit_end)
        self.assertEqual(start, explicit_end - timedelta(days=31))

        explicit_start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        start, end = MarketPriceHistoryService.resolve_aggregate_range(
            interval="DAY",
            start=explicit_start,
        )
        self.assertEqual(start, explicit_start)
        self.assertEqual(end, explicit_start + timedelta(days=730))

    def test_aggregate_range_rejects_invalid_and_excessive_ranges(self):
        start = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)

        with self.assertRaisesRegex(
            ValueError,
            "start must be before or equal to end",
        ):
            MarketPriceHistoryService.resolve_aggregate_range(
                interval="HOUR",
                start=start,
                end=start - timedelta(seconds=1),
            )

        with self.assertRaisesRegex(
            ValueError,
            "HOUR history cannot exceed 31 days",
        ):
            MarketPriceHistoryService.resolve_aggregate_range(
                interval="HOUR",
                start=start,
                end=start + timedelta(days=31, seconds=1),
            )

        with self.assertRaisesRegex(
            ValueError,
            "DAY history cannot exceed 730 days",
        ):
            MarketPriceHistoryService.resolve_aggregate_range(
                interval="DAY",
                start=start,
                end=start + timedelta(days=730, seconds=1),
            )

    def test_aggregate_limit_applies_after_complete_bucket_calculation(self):
        start = datetime(2026, 1, 15, 8, 0, tzinfo=UTC)
        rows = [
            self.make_fill(
                fill_id=UUID("00000000-0000-0000-0000-000000000001"),
                when=start + timedelta(minutes=1),
                price="0.40000",
                quantity="1.0000",
            ),
            self.make_fill(
                fill_id=UUID("00000000-0000-0000-0000-000000000002"),
                when=start + timedelta(minutes=10),
                price="0.80000",
                quantity="2.0000",
            ),
            self.make_fill(
                fill_id=UUID("00000000-0000-0000-0000-000000000003"),
                when=start + timedelta(minutes=50),
                price="0.60000",
                quantity="3.0000",
            ),
            self.make_fill(
                fill_id=UUID("00000000-0000-0000-0000-000000000004"),
                when=start + timedelta(hours=1, minutes=5),
                price="0.50000",
                quantity="4.0000",
            ),
        ]

        queryset = self.FakeQuerySet(rows)

        with patch(
            "markets.services.price_history_service.MarketFill.objects.filter",
            return_value=queryset,
        ):
            buckets = MarketPriceHistoryService.history(
                market_id=uuid4(),
                outcome_id=uuid4(),
                interval="HOUR",
                start=start,
                end=start + timedelta(hours=2),
                limit=1,
            )

        self.assertEqual(len(buckets), 1)
        self.assertEqual(buckets[0]["open"], Decimal("0.4000"))
        self.assertEqual(buckets[0]["high"], Decimal("0.8000"))
        self.assertEqual(buckets[0]["low"], Decimal("0.4000"))
        self.assertEqual(buckets[0]["close"], Decimal("0.6000"))
        self.assertEqual(buckets[0]["volume"], Decimal("6.0000"))
        self.assertEqual(buckets[0]["trade_count"], 3)

    def test_query_serializer_resolves_ranges_and_rejects_excessive_range(self):
        fixed_now = datetime(2026, 1, 15, 8, 0, tzinfo=UTC)

        with patch(
            "markets.services.price_history_service.timezone.now",
            return_value=fixed_now,
        ):
            serializer = PriceHistoryQuerySerializer(data={"interval": "HOUR"})
            self.assertTrue(serializer.is_valid(), serializer.errors)

        self.assertEqual(
            serializer.validated_data["start"],
            fixed_now - timedelta(days=31),
        )
        self.assertEqual(
            serializer.validated_data["end"],
            fixed_now,
        )

        invalid = PriceHistoryQuerySerializer(
            data={
                "interval": "HOUR",
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-02-02T00:00:00Z",
            }
        )
        self.assertFalse(invalid.is_valid())
        self.assertIn("code", invalid.errors)
        self.assertIn("detail", invalid.errors)


class PriceHistoryErrorContractAPITests(
    DiscoveryPricingFixtureMixin,
    APITestCase,
):
    def history_url(self):
        return reverse(
            "markets:market-outcome-price-history",
            kwargs={
                "market_id": self.market.id,
                "outcome_id": self.market.outcomes.first().id,
            },
        )

    def test_stable_price_history_error_codes(self):
        url = self.history_url()

        invalid_interval = self.client.get(
            url,
            {"interval": "WEEK"},
        )
        self.assertEqual(invalid_interval.status_code, 400)
        self.assertEqual(
            invalid_interval.data["code"],
            "market_price_history_invalid_interval",
        )

        invalid_limit = self.client.get(
            url,
            {"limit": 0},
        )
        self.assertEqual(invalid_limit.status_code, 400)
        self.assertEqual(
            invalid_limit.data["code"],
            "market_price_history_invalid_limit",
        )

        invalid_range = self.client.get(
            url,
            {
                "interval": "HOUR",
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-02-02T00:00:00Z",
            },
        )
        self.assertEqual(invalid_range.status_code, 400)
        self.assertEqual(
            invalid_range.data["code"],
            "market_price_history_invalid_range",
        )

        naive_timestamp = self.client.get(
            url,
            {
                "start": "2026-01-01T00:00:00",
            },
        )
        self.assertEqual(naive_timestamp.status_code, 400)
        self.assertEqual(
            naive_timestamp.data["code"],
            "market_price_history_invalid_range",
        )

    def test_aggregated_response_exposes_resolved_bounded_range(self):
        response = self.client.get(
            self.history_url(),
            {"interval": "HOUR"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["interval"], "HOUR")
        self.assertIsNotNone(response.data["start"])
        self.assertIsNotNone(response.data["end"])
        self.assertEqual(response.data["points"], [])
