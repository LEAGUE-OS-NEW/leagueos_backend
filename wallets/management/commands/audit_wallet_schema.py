"""Read-only audit of wallet migration and physical schema drift."""

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder


class Command(BaseCommand):
    help = "Report wallet migration/schema drift without modifying the database."

    def handle(self, *args, **options):
        tables = set(connection.introspection.table_names())
        wallet_models = sorted(
            apps.get_app_config("wallets").get_models(), key=lambda model: model._meta.db_table
        )
        applied = sorted(
            name
            for app_label, name in MigrationRecorder(connection).applied_migrations()
            if app_label == "wallets"
        )
        self.stdout.write("Applied wallet migrations:")
        for name in applied:
            self.stdout.write(f"  {name}")

        missing_tables = [
            model._meta.db_table for model in wallet_models if model._meta.db_table not in tables
        ]
        self.stdout.write(
            "Missing wallet tables: " + (", ".join(missing_tables) if missing_tables else "none")
        )

        drift = {}
        for model in wallet_models:
            table = model._meta.db_table
            expected = {field.column for field in model._meta.local_fields}
            if table in tables:
                with connection.cursor() as cursor:
                    actual = {
                        column.name
                        for column in connection.introspection.get_table_description(cursor, table)
                    }
                missing = sorted(expected - actual)
                extra = sorted(actual - expected)
                drift[table] = (missing, extra)
                self.stdout.write(
                    f"{table}: missing columns={missing or 'none'}; extra columns={extra or 'none'}"
                )
            else:
                drift[table] = (sorted(expected), [])
                self.stdout.write(f"{table}: table missing")

        counts = {}
        for table in ("wallets_wallet", "wallets_ledgerentry"):
            if table in tables:
                with connection.cursor() as cursor:
                    cursor.execute(f"SELECT COUNT(*) FROM {connection.ops.quote_name(table)}")
                    counts[table] = cursor.fetchone()[0]
            else:
                counts[table] = None
        wallet_rows = counts["wallets_wallet"]
        ledger_rows = counts["wallets_ledgerentry"]
        self.stdout.write(
            f"Wallet rows: {wallet_rows if wallet_rows is not None else 'table missing'}"
        )
        self.stdout.write(
            f"Ledger rows: {ledger_rows if ledger_rows is not None else 'table missing'}"
        )

        decision, blocking = self._repair_decision(tables, drift, counts)
        self.stdout.write(f"Wallets 0002 repair assessment: {decision}")
        if blocking:
            raise CommandError("Blocking wallet schema drift detected.")

    def _repair_decision(self, tables, drift, counts):
        wallet_table = "wallets_wallet"
        ledger_table = "wallets_ledgerentry"
        if wallet_table not in tables:
            return "REFUSE - unknown schema", True

        wallet_missing, wallet_extra = drift[wallet_table]
        if wallet_extra or wallet_missing not in ([], ["status"]):
            return "REFUSE - unknown schema", True

        expected_0001_ledger = {
            "id",
            "created_at",
            "updated_at",
            "debit_account",
            "credit_account",
            "amount",
            "currency",
            "transaction_id",
        }
        current_ledger = apps.get_model("wallets", "LedgerEntry")
        expected_current = {field.column for field in current_ledger._meta.local_fields}
        repair_apps = (
            MigrationLoader(connection)
            .project_state([("wallets", "0001_wallet_ledger_foundation")])
            .apps
        )
        repair_columns = {
            model._meta.db_table: {field.column for field in model._meta.local_fields}
            for model in repair_apps.get_app_config("wallets").get_models()
        }
        current_columns = {
            model._meta.db_table: {field.column for field in model._meta.local_fields}
            for model in apps.get_app_config("wallets").get_models()
        }
        actual_ledger = set()
        if ledger_table in tables:
            with connection.cursor() as cursor:
                actual_ledger = {
                    column.name
                    for column in connection.introspection.get_table_description(
                        cursor, ledger_table
                    )
                }
        if ledger_table not in tables:
            actual_ledger = set()
        elif actual_ledger not in (expected_0001_ledger, expected_current):
            if counts[ledger_table]:
                return "REFUSE - incompatible ledger contains data", True
            if connection.vendor != "postgresql":
                return "REFUSE - unknown schema", True
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT conrelid::regclass::text, conname
                    FROM pg_constraint
                    WHERE contype = 'f'
                      AND confrelid = %s::regclass
                      AND conrelid <> confrelid
                    ORDER BY 1, 2
                    """,
                    [ledger_table],
                )
                inbound = cursor.fetchall()
            if inbound:
                return "REFUSE - unknown schema", True

        existing_unknown = []
        for table in drift:
            if table in tables and table not in (wallet_table, ledger_table):
                with connection.cursor() as cursor:
                    actual = {
                        column.name
                        for column in connection.introspection.get_table_description(cursor, table)
                    }
                if actual not in (current_columns[table], repair_columns[table]):
                    existing_unknown.append(table)
        if existing_unknown:
            return "REFUSE - unknown schema", True

        if (
            not missing_tables_from_drift(drift)
            and not wallet_missing
            and actual_ledger in (expected_0001_ledger, expected_current)
        ):
            return "NO-OP", False
        return "SAFE REPAIR DURING WALLETS 0002", False


def missing_tables_from_drift(drift):
    existing = set(connection.introspection.table_names())
    return [table for table in drift if table not in existing]
