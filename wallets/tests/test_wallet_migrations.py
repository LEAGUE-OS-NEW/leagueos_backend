import uuid
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from importlib import import_module
from io import StringIO
from pathlib import Path

from django.apps import apps as global_apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.utils import ProgrammingError
from django.test import TransactionTestCase, skipUnlessDBFeature

WALLET_0001 = ("wallets", "0001_wallet_ledger_foundation")
WALLET_0002 = (
    "wallets",
    "0002_remove_ledgerentry_wallets_led_created_abc123_idx_and_more",
)
WALLET_LEAF = (
    "wallets",
    "0008_withdrawal_failure_reason_and_processing_audit",
)
MARKETS_WITH_LEDGER_REFERENCES = (
    "markets",
    "0021_remove_marketfeeschedule_mkt_fee_scope_version_uniq_and_more",
)


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
        self.executor.migrate([MARKETS_WITH_LEDGER_REFERENCES])
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

    def _ledger_index_names(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT indexrelid::regclass::text FROM pg_index "
                "WHERE indrelid = 'wallets_ledgerentry'::regclass"
            )
            return {row[0] for row in cursor.fetchall()}

    def _inbound_ledger_fks(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT c.conrelid::regclass::text, c.conname,
                       pg_get_constraintdef(c.oid, true), c.convalidated
                FROM pg_constraint c
                WHERE c.contype = 'f'
                  AND c.confrelid = 'wallets_ledgerentry'::regclass
                  AND c.conrelid <> c.confrelid
                ORDER BY 1, 2
                """)
            return cursor.fetchall()

    def _assert_inbound_fk_refuses(self, message="inbound ledger foreign key"):
        output = StringIO()
        with self.assertRaises(CommandError):
            call_command("audit_wallet_schema", stdout=output)
        self.assertIn("REFUSE - unknown schema", output.getvalue())
        with self.assertRaisesRegex(RuntimeError, message):
            MigrationExecutor(connection).migrate([WALLET_0002])
        self.assertNotIn(WALLET_0002, MigrationExecutor(connection).loader.applied_migrations)

    def _make_legacy_schema(self):
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE wallets_wallet DROP COLUMN status")
            cursor.execute(
                "ALTER TABLE wallets_wallet "
                "ALTER COLUMN available_balance TYPE numeric(20, 4), "
                "ALTER COLUMN reserved_balance TYPE numeric(20, 4)"
            )
            cursor.execute("""
                SELECT indexrelid::regclass::text
                FROM pg_index i
                JOIN pg_attribute a
                  ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = 'wallets_wallet'::regclass
                  AND a.attname = 'created_at'
                """)
            for (index_name,) in cursor.fetchall():
                cursor.execute(f'DROP INDEX "{index_name}"')
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
            cursor.execute("""
                SELECT indexrelid::regclass::text
                FROM pg_index
                WHERE indrelid = 'wallets_ledgerentry'::regclass
                  AND NOT indisprimary
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_constraint WHERE conindid = indexrelid
                  )
                """)
            for (index_name,) in cursor.fetchall():
                cursor.execute(f'DROP INDEX "{index_name}"')
            cursor.execute(
                "ALTER TABLE wallets_ledgerentry "
                "DROP COLUMN debit_account, DROP COLUMN credit_account, "
                "DROP COLUMN currency, DROP COLUMN transaction_id, "
                "ALTER COLUMN amount TYPE numeric(20, 4), "
                "ADD COLUMN entry_type varchar(20) NOT NULL, "
                "ADD COLUMN idempotency_reference uuid NOT NULL, "
                "ADD COLUMN available_balance_before numeric(20, 4) NOT NULL, "
                "ADD COLUMN available_balance_after numeric(20, 4) NOT NULL, "
                "ADD COLUMN reserved_balance_before numeric(20, 4) NOT NULL, "
                "ADD COLUMN reserved_balance_after numeric(20, 4) NOT NULL, "
                "ADD COLUMN wallet_id uuid NOT NULL, ADD COLUMN market_id uuid NULL, "
                "ADD COLUMN order_id uuid NULL, ADD COLUMN fill_id uuid NULL"
            )
            for sql in self._legacy_ledger_constraints_and_indexes():
                cursor.execute(sql)
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

    @staticmethod
    def _legacy_ledger_constraints_and_indexes():
        return (
            "ALTER TABLE wallets_ledgerentry ADD CONSTRAINT "
            "wallets_ledgerentry_idempotency_reference_key UNIQUE (idempotency_reference)",
            "ALTER TABLE wallets_ledgerentry ADD CONSTRAINT "
            "wallets_ledgerentry_wallet_id_686913ed_fk_wallets_wallet_id "
            "FOREIGN KEY (wallet_id) REFERENCES wallets_wallet(id) DEFERRABLE INITIALLY DEFERRED",
            "ALTER TABLE wallets_ledgerentry ADD CONSTRAINT "
            "wallets_ledgerentry_market_id_02fb812f_fk_markets_market_id "
            "FOREIGN KEY (market_id) REFERENCES markets_market(id) DEFERRABLE INITIALLY DEFERRED",
            "ALTER TABLE wallets_ledgerentry ADD CONSTRAINT "
            "wallets_ledgerentry_order_id_0d8b0e8a_fk_markets_marketorder_id "
            "FOREIGN KEY (order_id) REFERENCES markets_marketorder(id) "
            "DEFERRABLE INITIALLY DEFERRED",
            "ALTER TABLE wallets_ledgerentry ADD CONSTRAINT "
            "wallets_ledgerentry_fill_id_8bbbb97a_fk_markets_marketfill_id "
            "FOREIGN KEY (fill_id) REFERENCES markets_marketfill(id) DEFERRABLE INITIALLY DEFERRED",
            "ALTER TABLE wallets_ledgerentry ADD CONSTRAINT ledger_entry_amount_positive "
            "CHECK (amount > 0)",
            "ALTER TABLE wallets_ledgerentry ADD CONSTRAINT ledger_available_before_non_negative "
            "CHECK (available_balance_before >= 0)",
            "ALTER TABLE wallets_ledgerentry ADD CONSTRAINT ledger_available_after_non_negative "
            "CHECK (available_balance_after >= 0)",
            "ALTER TABLE wallets_ledgerentry ADD CONSTRAINT ledger_reserved_before_non_negative "
            "CHECK (reserved_balance_before >= 0)",
            "ALTER TABLE wallets_ledgerentry ADD CONSTRAINT ledger_reserved_after_non_negative "
            "CHECK (reserved_balance_after >= 0)",
            "CREATE INDEX wallets_led_wallet__d6cac1_idx ON wallets_ledgerentry "
            "(wallet_id, created_at)",
            "CREATE INDEX wallets_led_entry_t_4511e8_idx ON wallets_ledgerentry "
            "(entry_type, created_at)",
            "CREATE INDEX wallets_led_market__55d08b_idx ON wallets_ledgerentry "
            "(market_id, created_at)",
            "CREATE INDEX wallets_led_order_i_b751ee_idx ON wallets_ledgerentry "
            "(order_id, created_at)",
            "CREATE INDEX wallets_ledgerentry_entry_type_089eaf54 ON wallets_ledgerentry "
            "(entry_type)",
            "CREATE INDEX wallets_ledgerentry_entry_type_089eaf54_like ON wallets_ledgerentry "
            "(entry_type varchar_pattern_ops)",
            "CREATE INDEX wallets_ledgerentry_wallet_id_686913ed "
            "ON wallets_ledgerentry (wallet_id)",
            "CREATE INDEX wallets_ledgerentry_market_id_02fb812f "
            "ON wallets_ledgerentry (market_id)",
            "CREATE INDEX wallets_ledgerentry_order_id_0d8b0e8a ON wallets_ledgerentry (order_id)",
            "CREATE INDEX wallets_ledgerentry_fill_id_8bbbb97a ON wallets_ledgerentry (fill_id)",
        )

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
        inbound_before = self._inbound_ledger_fks()
        self.assertEqual(len(inbound_before), 6)
        self.assertTrue(all(item[3] for item in inbound_before))
        self.assertNotIn("wallets_led_created_abc123_idx", self._ledger_index_names())
        with self.assertRaises(ProgrammingError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DROP INDEX wallets_led_created_abc123_idx")

        audit_output = StringIO()
        call_command("audit_wallet_schema", stdout=audit_output)
        self.assertIn(
            "Wallets 0002 repair assessment: SAFE REPAIR DURING WALLETS 0002",
            audit_output.getvalue(),
        )

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
        self.assertEqual(self._table_oid("wallets_ledgerentry"), legacy_ledger_oid)
        self.assertEqual(self._inbound_ledger_fks(), inbound_before)
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
        applied = MigrationExecutor(connection).loader.applied_migrations
        self.assertTrue(
            {
                WALLET_0001,
                WALLET_0002,
                ("wallets", "0003_ledgerentry_available_balance_after_and_more"),
                WALLET_LEAF,
            }.issubset(applied)
        )
        final_audit = StringIO()
        repair = import_module(
            "wallets.migrations." "0002_remove_ledgerentry_wallets_led_created_abc123_idx_and_more"
        )
        self.assertIsNone(repair._current_schema_problem(connection))
        call_command("audit_wallet_schema", stdout=final_audit)
        self.assertIn("Wallets 0002 repair assessment: NO-OP", final_audit.getvalue())
        final_apps = self.executor.loader.project_state([WALLET_LEAF]).apps
        for model_name in ("Wallet", "LedgerEntry"):
            model = final_apps.get_model("wallets", model_name)
            self.assertEqual(
                self._columns(model._meta.db_table),
                {field.column for field in model._meta.local_fields},
            )
        with connection.cursor() as cursor:
            ledger_constraints = connection.introspection.get_constraints(
                cursor, "wallets_ledgerentry"
            )
        self.assertTrue(
            {
                constraint.name
                for constraint in final_apps.get_model("wallets", "LedgerEntry")._meta.constraints
            }.issubset(ledger_constraints)
        )

    def test_structural_constraints_exclude_only_postgresql_not_null_rows(self):
        repair = import_module(
            "wallets.migrations." "0002_remove_ledgerentry_wallets_led_created_abc123_idx_and_more"
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT conname, contype FROM pg_constraint "
                "WHERE conrelid = 'wallets_ledgerentry'::regclass"
            )
            raw = dict(cursor.fetchall())
        structural = repair._ledger_constraints(connection, "wallets_ledgerentry")
        self.assertEqual(set(structural), {name for name, kind in raw.items() if kind != "n"})
        self.assertNotIn("n", {details[0] for details in structural.values()})
        self.assertFalse(repair._column_definitions(connection, "wallets_ledgerentry")["id"][3])

    def test_unexpected_non_not_null_constraint_refuses(self):
        self._make_legacy_schema()
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE wallets_ledgerentry ADD CONSTRAINT unexpected_structural_check "
                "CHECK (amount < 1000000000)"
            )
        try:
            with self.assertRaisesRegex(RuntimeError, "unknown, missing, or unvalidated"):
                MigrationExecutor(connection).migrate([WALLET_0002])
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE wallets_ledgerentry DROP CONSTRAINT unexpected_structural_check"
                )

    def test_repair_source_prohibits_ledger_drop_and_cascade(self):
        module = import_module(
            "wallets.migrations." "0002_remove_ledgerentry_wallets_led_created_abc123_idx_and_more"
        )
        source = Path(module.__file__).read_text(encoding="utf-8").upper()
        self.assertNotIn('"DROP TABLE', source)
        self.assertNotIn('"CASCADE', source)
        self.assertNotIn("MIGRATIONRECORDER", source)
        self.assertNotIn("--FAKE", source)

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

    def test_unapproved_inbound_foreign_key_refuses(self):
        self._make_legacy_schema()
        before_oid = self._table_oid("wallets_ledgerentry")
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE wallet_repair_unknown (ledger_id uuid)")
            cursor.execute(
                "ALTER TABLE wallet_repair_unknown ADD CONSTRAINT unknown_ledger_fk "
                "FOREIGN KEY (ledger_id) REFERENCES wallets_ledgerentry(id) "
                "DEFERRABLE INITIALLY DEFERRED"
            )
        try:
            with self.assertRaisesRegex(RuntimeError, "unapproved or missing inbound"):
                MigrationExecutor(connection).migrate([WALLET_0002])
            self.assertEqual(self._table_oid("wallets_ledgerentry"), before_oid)
            self.assertNotIn(WALLET_0002, MigrationExecutor(connection).loader.applied_migrations)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP TABLE wallet_repair_unknown")

    def test_unvalidated_inbound_foreign_key_refuses(self):
        self._make_legacy_schema()
        table, name, definition, _ = self._inbound_ledger_fks()[0]
        with connection.cursor() as cursor:
            cursor.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{name}"')
            cursor.execute(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" {definition} NOT VALID')
        try:
            output = StringIO()
            with self.assertRaises(CommandError):
                call_command("audit_wallet_schema", stdout=output)
            self.assertIn("REFUSE - unknown schema", output.getvalue())
            with self.assertRaisesRegex(RuntimeError, "malformed or unvalidated"):
                MigrationExecutor(connection).migrate([WALLET_0002])
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f'ALTER TABLE "{table}" VALIDATE CONSTRAINT "{name}"')

    def test_renamed_approved_inbound_foreign_key_refuses(self):
        self._make_legacy_schema()
        table, name, _, _ = self._inbound_ledger_fks()[0]
        renamed = "renamed_approved_inbound_ledger_fk"
        with connection.cursor() as cursor:
            cursor.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{name}" TO "{renamed}"')
        try:
            self._assert_inbound_fk_refuses("unapproved or missing inbound")
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{renamed}" TO "{name}"')

    def _replace_inbound_fk_and_assert_refusal(self, action):
        self._make_legacy_schema()
        table, name, definition, _ = self._inbound_ledger_fks()[0]
        replacement = definition.replace(
            " DEFERRABLE INITIALLY DEFERRED", f" {action} DEFERRABLE INITIALLY DEFERRED"
        )
        with connection.cursor() as cursor:
            cursor.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{name}"')
            cursor.execute(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" {replacement}')
        try:
            self._assert_inbound_fk_refuses("malformed or unvalidated")
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{name}"')
                cursor.execute(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" {definition}')

    def test_inbound_foreign_key_on_delete_cascade_refuses(self):
        self._replace_inbound_fk_and_assert_refusal("ON DELETE CASCADE")

    def test_inbound_foreign_key_on_update_cascade_refuses(self):
        self._replace_inbound_fk_and_assert_refusal("ON UPDATE CASCADE")

    def test_unknown_legacy_column_definition_refuses(self):
        self._make_legacy_schema()
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE wallets_ledgerentry ALTER COLUMN entry_type TYPE varchar(21)"
            )
        try:
            with self.assertRaisesRegex(RuntimeError, "unknown ledger columns"):
                MigrationExecutor(connection).migrate([WALLET_0002])
            self.assertNotIn(WALLET_0002, MigrationExecutor(connection).loader.applied_migrations)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE wallets_ledgerentry ALTER COLUMN entry_type TYPE varchar(20)"
                )

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
        repair = import_module(
            "wallets.migrations." "0002_remove_ledgerentry_wallets_led_created_abc123_idx_and_more"
        )
        self.assertIsNone(repair._current_schema_problem(connection))
        call_command("audit_wallet_schema", stdout=output)
        report = output.getvalue()
        self.assertIn("Applied wallet migrations:", report)
        self.assertIn("Missing wallet tables: none", report)
        self.assertIn("Wallets 0002 repair assessment: NO-OP", report)
        self.assertIn("Wallet rows:", report)
        self.assertIn("Ledger rows:", report)
