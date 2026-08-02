import json
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from authentication.tests.factories import UserFactory
from wallets.models import LedgerEntry, Wallet
from wallets.services.wallet_service import WalletService


class WalletAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = UserFactory()
        self.other_user = UserFactory()

    def authenticate(self, user=None):
        self.client.force_authenticate(user=user or self.user)

    @staticmethod
    def list_url():
        return reverse("wallets:wallet-list")

    @staticmethod
    def detail_url(currency="UGX"):
        return reverse("wallets:wallet-detail", kwargs={"currency": currency})

    @staticmethod
    def ledger_url(currency="UGX"):
        return reverse("wallets:wallet-ledger-list", kwargs={"currency": currency})

    def credit(self, user=None, amount="100.0000", **related):
        return WalletService.credit(
            user=user or self.user,
            currency="UGX",
            amount=Decimal(amount),
            idempotency_reference=uuid4(),
            **related,
        )

    def test_all_endpoints_require_authentication(self):
        for url in (self.list_url(), self.detail_url(), self.ledger_url()):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_wallet_list_is_scoped_sorted_paginated_and_formats_balances(self):
        Wallet.objects.create(
            user=self.user,
            currency="USD",
            available_balance=Decimal("1.2"),
            reserved_balance=Decimal("0.3"),
        )
        Wallet.objects.create(
            user=self.user,
            currency="UGX",
            available_balance=Decimal("10"),
            reserved_balance=Decimal("2.5"),
        )
        Wallet.objects.create(user=self.other_user, currency="EUR")
        self.authenticate()

        response = self.client.get(self.list_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(set(response.data), {"count", "next", "previous", "results"})
        self.assertEqual(response.data["count"], 2)
        self.assertEqual([item["currency"] for item in response.data["results"]], ["UGX", "USD"])
        self.assertEqual(response.data["results"][0]["available_balance"], "10.0000")
        self.assertEqual(response.data["results"][0]["reserved_balance"], "2.5000")
        self.assertEqual(response.data["results"][0]["total_balance"], "12.5000")

    def test_empty_wallet_list_does_not_create_wallet(self):
        self.authenticate()
        response = self.client.get(self.list_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"], [])
        self.assertFalse(Wallet.objects.filter(user=self.user).exists())

    def test_wallet_detail_accepts_lowercase_and_hides_identity(self):
        wallet = Wallet.objects.create(
            user=self.user,
            currency="UGX",
            available_balance=Decimal("7.1"),
            reserved_balance=Decimal("2.9"),
        )
        self.authenticate()
        response = self.client.get(self.detail_url("ugx"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            set(response.data),
            {
                "id",
                "currency",
                "available_balance",
                "reserved_balance",
                "total_balance",
                "created_at",
                "updated_at",
            },
        )
        self.assertEqual(response.data["id"], str(wallet.id))
        self.assertEqual(response.data["total_balance"], "10.0000")
        self.assert_privacy(response)

    def test_missing_or_other_users_wallet_returns_404(self):
        Wallet.objects.create(user=self.other_user, currency="UGX")
        self.authenticate()
        self.assertEqual(self.client.get(self.detail_url()).status_code, 404)
        self.assertEqual(self.client.get(self.ledger_url()).status_code, 404)

    def test_malformed_currency_returns_field_specific_400(self):
        self.authenticate()
        for currency in ("UG", "UG12", "1GX"):
            with self.subTest(currency=currency):
                response = self.client.get(self.detail_url(currency))
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn("currency", response.data)

    def test_ledger_contract_scope_ordering_and_privacy(self):
        first = self.credit(amount="10")
        second = WalletService.reserve(
            user=self.user,
            currency="UGX",
            amount=Decimal("2"),
            idempotency_reference=uuid4(),
        )
        other = self.credit(user=self.other_user, amount="99")
        self.authenticate()
        response = self.client.get(self.ledger_url())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            [row["id"] for row in response.data["results"]], [str(second.id), str(first.id)]
        )
        self.assertNotIn(str(other.id), json.dumps(response.data))
        self.assertEqual(
            set(response.data["results"][0]),
            {
                "id",
                "entry_type",
                "amount",
                "available_balance_before",
                "available_balance_after",
                "reserved_balance_before",
                "reserved_balance_after",
                "idempotency_reference",
                "market_id",
                "order_id",
                "fill_id",
                "created_at",
            },
        )
        self.assertEqual(response.data["results"][0]["amount"], "2.0000")
        self.assert_privacy(response)

    def test_ledger_deterministic_id_tie_breaking(self):
        first = self.credit(amount="10")
        second = WalletService.reserve(
            user=self.user,
            currency="UGX",
            amount=Decimal("2"),
            idempotency_reference=uuid4(),
        )
        stamp = timezone.now() - timedelta(days=1)
        LedgerEntry.objects.filter(id__in=[first.id, second.id]).update(created_at=stamp)
        self.authenticate()
        response = self.client.get(self.ledger_url())
        expected = sorted([str(first.id), str(second.id)], reverse=True)
        self.assertEqual([row["id"] for row in response.data["results"]], expected)

    def test_entry_type_filters_and_all_entry_types_serialize(self):
        self.credit(amount="20")
        WalletService.reserve(
            user=self.user, currency="UGX", amount=Decimal("8"), idempotency_reference=uuid4()
        )
        WalletService.release(
            user=self.user, currency="UGX", amount=Decimal("3"), idempotency_reference=uuid4()
        )
        WalletService.debit_available(
            user=self.user, currency="UGX", amount=Decimal("2"), idempotency_reference=uuid4()
        )
        self.authenticate()
        all_types = {
            row["entry_type"] for row in self.client.get(self.ledger_url()).data["results"]
        }
        self.assertEqual(all_types, {"CREDIT", "DEBIT", "RESERVE", "RELEASE"})
        for entry_type in all_types:
            response = self.client.get(self.ledger_url(), {"entry_type": entry_type})
            self.assertTrue(response.data["results"])
            self.assertTrue(
                all(row["entry_type"] == entry_type for row in response.data["results"])
            )

    def test_uuid_filters_work_individually_and_combined(self):
        entry = self.credit()
        filter_values = {"market_id": uuid4(), "order_id": uuid4(), "fill_id": uuid4()}
        self.authenticate()
        for field, value in filter_values.items():
            with self.subTest(field=field):
                response = self.client.get(self.ledger_url(), {field: value})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["results"], [])
        response = self.client.get(self.ledger_url(), filter_values)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["results"], [])
        self.assertTrue(LedgerEntry.objects.filter(pk=entry.pk).exists())

    def test_created_datetime_filters_are_inclusive_and_combinable(self):
        entry = self.credit()
        created = entry.created_at
        self.authenticate()
        params = {
            "created_from": (created - timedelta(seconds=1)).isoformat(),
            "created_to": (created + timedelta(seconds=1)).isoformat(),
            "entry_type": "CREDIT",
        }
        response = self.client.get(self.ledger_url(), params)
        self.assertEqual([row["id"] for row in response.data["results"]], [str(entry.id)])
        self.assertEqual(
            self.client.get(self.ledger_url(), {"created_from": created.isoformat()}).data["count"],
            1,
        )
        self.assertEqual(
            self.client.get(self.ledger_url(), {"created_to": created.isoformat()}).data["count"], 1
        )

    def test_invalid_filters_return_field_specific_400(self):
        self.credit()
        self.authenticate()
        cases = [
            ({"entry_type": "TRANSFER"}, "entry_type"),
            ({"market_id": "bad"}, "market_id"),
            ({"order_id": "bad"}, "order_id"),
            ({"fill_id": "bad"}, "fill_id"),
            ({"created_from": "yesterday"}, "created_from"),
            ({"created_to": "tomorrow"}, "created_to"),
            (
                {"created_from": "2026-02-02T00:00:00Z", "created_to": "2026-01-01T00:00:00Z"},
                "created_from",
            ),
        ]
        for params, field in cases:
            with self.subTest(params=params):
                response = self.client.get(self.ledger_url(), params)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn(field, response.data)

    def test_shared_pagination_page_size_is_respected(self):
        for _ in range(3):
            self.credit(amount="1")
        self.authenticate()
        response = self.client.get(self.ledger_url(), {"page_size": 2})
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertIsNotNone(response.data["next"])

    def test_gets_are_read_only_and_accounting_matches_service_state(self):
        self.credit(amount="100")
        WalletService.reserve(
            user=self.user, currency="UGX", amount=Decimal("40"), idempotency_reference=uuid4()
        )
        WalletService.consume_reserved(
            user=self.user, currency="UGX", amount=Decimal("25"), idempotency_reference=uuid4()
        )
        WalletService.release(
            user=self.user, currency="UGX", amount=Decimal("5"), idempotency_reference=uuid4()
        )
        wallet_before = Wallet.objects.get(user=self.user, currency="UGX")
        values_before = (
            wallet_before.available_balance,
            wallet_before.reserved_balance,
            wallet_before.updated_at,
        )
        counts_before = (Wallet.objects.count(), LedgerEntry.objects.count())
        snapshots = list(
            LedgerEntry.objects.values_list(
                "id", "available_balance_after", "reserved_balance_after"
            )
        )
        self.authenticate()
        detail = self.client.get(self.detail_url())
        ledger = self.client.get(self.ledger_url())
        self.assertEqual(detail.data["available_balance"], "65.0000")
        self.assertEqual(detail.data["reserved_balance"], "10.0000")
        self.assertEqual(detail.data["total_balance"], "75.0000")
        latest = ledger.data["results"][0]
        self.assertEqual(latest["available_balance_after"], "65.0000")
        self.assertEqual(latest["reserved_balance_after"], "10.0000")
        wallet_before.refresh_from_db()
        self.assertEqual(
            (
                wallet_before.available_balance,
                wallet_before.reserved_balance,
                wallet_before.updated_at,
            ),
            values_before,
        )
        self.assertEqual((Wallet.objects.count(), LedgerEntry.objects.count()), counts_before)
        self.assertEqual(
            list(
                LedgerEntry.objects.values_list(
                    "id", "available_balance_after", "reserved_balance_after"
                )
            ),
            snapshots,
        )

    def test_query_counts_are_bounded(self):
        self.credit()
        self.authenticate()
        with CaptureQueriesContext(connection) as list_queries:
            self.client.get(self.list_url())
        with CaptureQueriesContext(connection) as detail_queries:
            self.client.get(self.detail_url())
        with CaptureQueriesContext(connection) as ledger_queries:
            self.client.get(self.ledger_url())
        self.assertEqual(len(list_queries), 2)
        self.assertEqual(len(detail_queries), 1)
        self.assertEqual(len(ledger_queries), 3)

    def test_schema_contains_wallet_routes(self):
        response = self.client.get(reverse("api-schema"), {"format": "json"})
        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        self.assertIn("/api/v1/wallets/", paths)
        self.assertIn("/api/v1/wallets/{currency}/", paths)
        self.assertIn("/api/v1/wallets/{currency}/ledger/", paths)

    def assert_privacy(self, response):
        rendered = json.dumps(response.data).lower()
        for forbidden in (
            "password",
            "email",
            "phone",
            "username",
            "user_id",
            "buyer",
            "seller",
            "maker",
            "taker",
        ):
            self.assertNotIn(forbidden, rendered)
