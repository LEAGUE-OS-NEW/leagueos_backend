import uuid
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO

from django.apps import apps as global_apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, skipUnlessDBFeature

WALLET_0001 = ("wallets", "0001_wallet_ledger_foundation")
WALLET_0002 = (
    "wallets",
    "0002_remove_ledgerentry_wallets_led_created_abc123_idx_and_more",
)
WALLET_LEAF = ("wallets", "0004_ledgerentry_ledger_amount_positive_and_more")
MARKETS_PRE_WALLET = ("markets", "0005_add_market_fill")


@skipUnlessDBFeature("can_rollback_ddl")
class WalletMigrationTests(TransactionTestCase):
    """PostgreSQL-only coverage for the overwritten-0001 repair path."""

    available_apps = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if connection.vendor != "postgresql":
            raise cls.skipTest("wallet migration repair tests require PostgreSQL")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([("wallets", None)])
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([MARKETS_PRE_WALLET])
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([WALLET_0001])
        self.old_apps = self.executor.loader.project_state([WALLET_0001]).apps

    def tearDown(self):
        # A refusal test intentionally leaves the legacy table in place. Empty
        # it so 0002 can safely restore the normal leaf state for Django.
        if "wallets_ledgerentry" in connection.introspection.table_names():
            with connection.cursor() as cursor:
                with suppress(Exception):
                    cursor.execute("DELETE FROM wallets_ledgerentry")
        MigrationExecutor(connection).migrate([WALLET_0002])
        MigrationExecutor(connection).migrate([WALLET_LEAF])
        super().tearDown()

    def _columns(self, table):
        with connection.cursor() as cursor:
            return {
                item.name for item in connection.introspection.get_table_description(cursor, table)
            }

    def _table_oid(self, table):
        with connection.cursor() as cursor:
            cursor.execute("SELECT %s::regclass::oid", [table])
            return cursor.fetchone()[0]

    def _wallet_constraint_names(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'wallets_wallet'::regclass ORDER BY conname"
            )
            return {row[0] for row in cursor.fetchall()}

    def _wallet_index_names(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT indexrelid::regclass::text FROM pg_index "
                "WHERE indrelid = 'wallets_wallet'::regclass"
            )
            return {row[0] for row in cursor.fetchall()}

    def _make_legacy_schema(self):
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE wallets_wallet DROP COLUMN status")
            for current, legacy in (
                ("unique_user_currency_wallet", "wallet_user_currency_unique"),
                ("available_balance_not_negative", "wallet_available_balance_non_negative"),
                ("reserved_balance_not_negative", "wallet_reserved_balance_non_negative"),
            ):
                cursor.execute(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'wallets_wallet'::regclass AND conname = %s",
                    [legacy],
                )
                if cursor.fetchone():
                    cursor.execute(f"ALTER TABLE wallets_wallet DROP CONSTRAINT {current}")
                else:
                    cursor.execute(
                        f"ALTER TABLE wallets_wallet RENAME CONSTRAINT {current} TO {legacy}"
                    )
            cursor.execute("DROP TABLE wallets_ledgerentry")
            cursor.execute("""
                CREATE TABLE wallets_ledgerentry (
                    id uuid PRIMARY KEY,
                    created_at timestamptz NOT NULL,
                    updated_at timestamptz NOT NULL,
                    amount numeric(20, 4) NOT NULL,
                    entry_type varchar(20) NOT NULL,
                    idempotency_reference uuid NOT NULL UNIQUE,
                    available_balance_before numeric(20, 4) NOT NULL,
                    available_balance_after numeric(20, 4) NOT NULL,
                    reserved_balance_before numeric(20, 4) NOT NULL,
                    reserved_balance_after numeric(20, 4) NOT NULL,
                    wallet_id uuid NOT NULL REFERENCES wallets_wallet(id),
                    market_id uuid NULL REFERENCES markets_market(id),
                    order_id uuid NULL REFERENCES markets_marketorder(id),
                    fill_id uuid NULL REFERENCES markets_marketfill(id),
                    CONSTRAINT ledger_entry_amount_positive CHECK (amount > 0),
                    CONSTRAINT ledger_available_before_non_negative
                        CHECK (available_balance_before >= 0),
                    CONSTRAINT ledger_available_after_non_negative
                        CHECK (available_balance_after >= 0),
                    CONSTRAINT ledger_reserved_before_non_negative
                        CHECK (reserved_balance_before >= 0),
                    CONSTRAINT ledger_reserved_after_non_negative
                        CHECK (reserved_balance_after >= 0)
                )
                """)
        for model_name in (
            "AuditLog",
            "Receipt",
            "WithdrawalRequest",
            "DepositIntent",
            "WalletTransaction",
            "PaymentProvider",
        ):
            model = self.old_apps.get_model("wallets", model_name)
            if model._meta.db_table in connection.introspection.table_names():
                with connection.cursor() as cursor:
                    cursor.execute(f'DROP TABLE "{model._meta.db_table}"')

    def _create_user_and_wallet(self):
        # Accounts isn't being tested at a historical boundary here. Its newer
        # physical columns remain present, so use its current model to satisfy
        # all non-null fields while keeping Wallet at the 0001 state.
        User = global_apps.get_model("accounts", "User")
        Wallet = self.old_apps.get_model("wallets", "Wallet")
        user = User.objects.create(
            username=f"migration-{uuid.uuid4()}",
            email=f"migration-{uuid.uuid4()}@example.test",
            first_name="Migration",
            last_name="Fixture",
        )
        wallet = Wallet.objects.create(
            user_id=user.id,
            currency="UGX",
            available_balance=Decimal("12.5000"),
            reserved_balance=Decimal("3.2500"),
        )
        return user, wallet

    def test_fresh_database_runs_repair_and_all_wallet_migrations(self):
        MigrationExecutor(connection).migrate([("wallets", None)])
        self.assertNotIn("wallets_wallet", connection.introspection.table_names())
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([WALLET_LEAF])
        expected_tables = {
            model._meta.db_table
            for model in self.executor.loader.project_state([WALLET_LEAF])
            .apps.get_app_config("wallets")
            .get_models()
        }
        self.assertTrue(expected_tables.issubset(set(connection.introspection.table_names())))
        self.assertIn("status", self._columns("wallets_wallet"))
        self.assertIn("transaction_id", self._columns("wallets_ledgerentry"))
        self.assertIn("wallet_id", self._columns("wallets_ledgerentry"))

    def test_legacy_schema_repairs_and_preserves_wallet(self):
        user, wallet = self._create_user_and_wallet()
        original = {
            "id": wallet.id,
            "user_id": user.id,
            "currency": wallet.currency,
            "available_balance": wallet.available_balance,
            "reserved_balance": wallet.reserved_balance,
            "created_at": wallet.created_at,
            "updated_at": wallet.updated_at,
        }
        self._make_legacy_schema()
        legacy_ledger_oid = self._table_oid("wallets_ledgerentry")

        self.executor = MigrationExecutor(connection)
        self.executor.migrate([WALLET_0002])
        self.assertIn("provider_reference", self._columns("wallets_wallettransaction"))
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([WALLET_LEAF])

        Wallet = self.executor.loader.project_state([WALLET_LEAF]).apps.get_model(
            "wallets", "Wallet"
        )
        repaired = Wallet.objects.get(pk=wallet.id)
        for field, value in original.items():
            self.assertEqual(getattr(repaired, field), value)
        self.assertEqual(repaired.status, "ACTIVE")
        self.assertNotEqual(self._table_oid("wallets_ledgerentry"), legacy_ledger_oid)
        expected_tables = {
            "wallets_paymentprovider",
            "wallets_wallettransaction",
            "wallets_depositintent",
            "wallets_withdrawalrequest",
            "wallets_receipt",
            "wallets_auditlog",
        }
        self.assertTrue(expected_tables.issubset(set(connection.introspection.table_names())))
        names = self._wallet_constraint_names()
        self.assertTrue(
            {
                "unique_user_currency_wallet",
                "available_balance_not_negative",
                "reserved_balance_not_negative",
            }.issubset(names)
        )
        self.assertTrue(
            {
                "wallet_user_currency_unique",
                "wallet_available_balance_non_negative",
                "wallet_reserved_balance_non_negative",
            }.isdisjoint(names)
        )
        indexes = self._wallet_index_names()
        self.assertIn("unique_user_currency_wallet", indexes)
        self.assertNotIn("wallet_user_currency_unique", indexes)

    def test_nonempty_incompatible_ledger_refuses_without_data_loss(self):
        _, wallet = self._create_user_and_wallet()
        self._make_legacy_schema()
        ledger_id = uuid.uuid4()
        now = datetime.now(UTC)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO wallets_ledgerentry (
                    id, created_at, updated_at, amount, entry_type, idempotency_reference,
                    available_balance_before, available_balance_after,
                    reserved_balance_before, reserved_balance_after, wallet_id
                ) VALUES (%s, %s, %s, 1, 'CREDIT', %s, 0, 1, 0, 0, %s)
                """,
                [ledger_id, now, now, uuid.uuid4(), wallet.id],
            )
        before_oid = self._table_oid("wallets_ledgerentry")

        audit_output = StringIO()
        with self.assertRaises(CommandError):
            call_command("audit_wallet_schema", stdout=audit_output)
        self.assertIn("REFUSE - incompatible ledger contains data", audit_output.getvalue())

        with self.assertRaisesRegex(RuntimeError, "approved ledger data-mapping migration"):
            MigrationExecutor(connection).migrate([WALLET_0002])

        self.assertEqual(self._table_oid("wallets_ledgerentry"), before_oid)
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM wallets_ledgerentry WHERE id = %s", [ledger_id])
            self.assertEqual(cursor.fetchone()[0], ledger_id)
        self.assertNotIn(WALLET_0002, MigrationExecutor(connection).loader.applied_migrations)

    def test_repair_logic_is_idempotent_on_correct_0001_schema(self):
        before = {
            table: self._table_oid(table)
            for table in connection.introspection.table_names()
            if table.startswith("wallets_")
        }
        MigrationExecutor(connection).migrate([WALLET_0002])
        after = {table: self._table_oid(table) for table in before}
        self.assertEqual(after, before)
        self.assertIn("provider_reference", self._columns("wallets_wallettransaction"))

    def test_both_equivalent_constraint_names_remove_only_legacy_duplicates(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE wallets_wallet ADD CONSTRAINT wallet_user_currency_unique "
                "UNIQUE (user_id, currency)"
            )
            cursor.execute(
                "ALTER TABLE wallets_wallet ADD CONSTRAINT "
                "wallet_available_balance_non_negative CHECK (available_balance >= 0)"
            )
            cursor.execute(
                "ALTER TABLE wallets_wallet ADD CONSTRAINT "
                "wallet_reserved_balance_non_negative CHECK (reserved_balance >= 0)"
            )
        MigrationExecutor(connection).migrate([WALLET_0002])
        names = self._wallet_constraint_names()
        self.assertTrue(
            {
                "unique_user_currency_wallet",
                "available_balance_not_negative",
                "reserved_balance_not_negative",
            }.issubset(names)
        )
        self.assertTrue(
            {
                "wallet_user_currency_unique",
                "wallet_available_balance_non_negative",
                "wallet_reserved_balance_non_negative",
            }.isdisjoint(names)
        )

    def test_incompatible_current_constraint_name_refuses_actionably(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE wallets_wallet DROP CONSTRAINT " "available_balance_not_negative"
            )
            cursor.execute(
                "ALTER TABLE wallets_wallet ADD CONSTRAINT "
                "available_balance_not_negative CHECK (available_balance >= -1)"
            )
        with self.assertRaisesRegex(RuntimeError, "incompatible definition"):
            MigrationExecutor(connection).migrate([WALLET_0002])
        self.assertNotIn(WALLET_0002, MigrationExecutor(connection).loader.applied_migrations)
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE wallets_wallet DROP CONSTRAINT " "available_balance_not_negative"
            )
            cursor.execute(
                "ALTER TABLE wallets_wallet ADD CONSTRAINT "
                "available_balance_not_negative CHECK (available_balance >= 0)"
            )

    def test_previously_applied_0002_has_consistent_published_graph(self):
        MigrationExecutor(connection).migrate([WALLET_0002])
        executor = MigrationExecutor(connection)
        executor.loader.check_consistent_history(connection)
        self.assertIn(WALLET_0002, executor.loader.applied_migrations)
        planned = {
            (migration.app_label, migration.name)
            for migration, _ in executor.migration_plan([WALLET_LEAF])
        }
        self.assertNotIn(WALLET_0002, planned)


class WalletSchemaAuditCommandTests(TransactionTestCase):
    def test_reports_current_schema_as_noop(self):
        if connection.vendor != "postgresql":
            self.skipTest("wallet schema audit integration test requires PostgreSQL")
        output = StringIO()
        call_command("audit_wallet_schema", stdout=output)
        report = output.getvalue()
        self.assertIn("Applied wallet migrations:", report)
        self.assertIn("Missing wallet tables: none", report)
        self.assertIn("Wallets 0002 repair assessment: NO-OP", report)
        self.assertIn("Wallet rows:", report)
        self.assertIn("Ledger rows:", report)
