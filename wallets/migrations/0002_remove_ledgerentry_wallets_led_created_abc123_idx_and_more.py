"""Published wallets 0002, with an in-place overwritten-0001 compatibility repair.

The database-only first operation is deliberate. The previously published 0001
was overwritten, while this 0002 was also published and may already be recorded
as applied. Inserting a new predecessor would make those histories inconsistent.
"""

import django.db.models.deletion
from django.db import migrations, models

EXPECTED_MODELS = (
    "PaymentProvider",
    "WalletTransaction",
    "DepositIntent",
    "WithdrawalRequest",
    "Receipt",
    "AuditLog",
)

CONSTRAINT_EQUIVALENTS = (
    ("wallet_user_currency_unique", "unique_user_currency_wallet", "u", ("user_id", "currency")),
    (
        "wallet_available_balance_non_negative",
        "available_balance_not_negative",
        "c",
        ("available_balance",),
    ),
    (
        "wallet_reserved_balance_non_negative",
        "reserved_balance_not_negative",
        "c",
        ("reserved_balance",),
    ),
)


def _tables(connection):
    return set(connection.introspection.table_names())


def _columns(connection, table):
    with connection.cursor() as cursor:
        return {
            column.name for column in connection.introspection.get_table_description(cursor, table)
        }


def _model_columns(model):
    return {field.column for field in model._meta.local_fields}


def _row_count(schema_editor, table):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {schema_editor.quote_name(table)}")
        return cursor.fetchone()[0]


def _inbound_foreign_keys(connection, table):
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
            [table],
        )
        return cursor.fetchall()


def _wallet_constraints(connection, table):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.conname, c.contype,
                   ARRAY(
                       SELECT a.attname
                       FROM unnest(c.conkey) WITH ORDINALITY AS key(attnum, ord)
                       JOIN pg_attribute a
                         ON a.attrelid = c.conrelid AND a.attnum = key.attnum
                       ORDER BY key.ord
                   ),
                   pg_get_constraintdef(c.oid, true)
            FROM pg_constraint c
            WHERE c.conrelid = %s::regclass
            """,
            [table],
        )
        return {
            name: (kind, tuple(columns), definition) for name, kind, columns, definition in cursor
        }


def _normalized_definition(definition):
    return "".join(definition.lower().replace('"', "").split())


def _validate_constraint(name, details, expected_kind, expected_columns):
    kind, columns, definition = details
    if kind != expected_kind or columns != expected_columns:
        raise RuntimeError(
            f"wallets_wallet constraint {name!r} has incompatible definition "
            f"{definition!r}; expected type {expected_kind!r} on columns "
            f"{list(expected_columns)!r}. Manual review is required."
        )
    if expected_kind == "c":
        column = expected_columns[0]
        normalized = _normalized_definition(definition)
        approved = {
            f"check(({column}>=0))",
            f"check(({column}>=(0)::numeric))",
            f"check({column}>=0::numeric)",
        }
        if normalized not in approved:
            raise RuntimeError(
                f"wallets_wallet constraint {name!r} has incompatible definition "
                f"{definition!r}; expected {column} >= 0. Manual review is required."
            )


def _normalize_wallet_constraints(connection, schema_editor, table):
    constraints = _wallet_constraints(connection, table)
    quoted_table = schema_editor.quote_name(table)
    for legacy, current, kind, columns in CONSTRAINT_EQUIVALENTS:
        legacy_details = constraints.get(legacy)
        current_details = constraints.get(current)
        if legacy_details:
            _validate_constraint(legacy, legacy_details, kind, columns)
        if current_details:
            _validate_constraint(current, current_details, kind, columns)
        if legacy_details and current_details:
            if _normalized_definition(legacy_details[2]) != _normalized_definition(
                current_details[2]
            ):
                raise RuntimeError(
                    f"wallets_wallet constraints {legacy!r} and {current!r} are not "
                    "equivalent; no constraint was removed. Manual review is required."
                )
            schema_editor.execute(
                f"ALTER TABLE {quoted_table} DROP CONSTRAINT " f"{schema_editor.quote_name(legacy)}"
            )
        elif legacy_details:
            schema_editor.execute(
                f"ALTER TABLE {quoted_table} RENAME CONSTRAINT "
                f"{schema_editor.quote_name(legacy)} TO {schema_editor.quote_name(current)}"
            )


def _ensure_wallet(apps, schema_editor):
    connection = schema_editor.connection
    Wallet = apps.get_model("wallets", "Wallet")
    table = Wallet._meta.db_table
    if table not in _tables(connection):
        raise RuntimeError(
            "wallets_wallet is missing although wallets.0001 is recorded as applied; "
            "restore or investigate it before running wallets 0002."
        )
    columns = _columns(connection, table)
    expected = _model_columns(Wallet)
    legacy_expected = expected - {"status"}
    if columns not in (expected, legacy_expected):
        raise RuntimeError(
            f"{table} has an unknown structure (missing={sorted(expected - columns)}, "
            f"extra={sorted(columns - expected)}); no automatic repair was attempted."
        )
    if "status" not in columns:
        schema_editor.add_field(Wallet, Wallet._meta.get_field("status"))
    _normalize_wallet_constraints(connection, schema_editor, table)
    constraints = _wallet_constraints(connection, table)
    for constraint in Wallet._meta.constraints:
        if constraint.name not in constraints:
            schema_editor.add_constraint(Wallet, constraint)


def _ensure_model_table(apps, schema_editor, model_name):
    model = apps.get_model("wallets", model_name)
    table = model._meta.db_table
    connection = schema_editor.connection
    if table not in _tables(connection):
        schema_editor.create_model(model)
        return
    actual = _columns(connection, table)
    expected = _model_columns(model)
    if actual != expected:
        raise RuntimeError(
            f"{table} already exists with an incompatible structure "
            f"(missing={sorted(expected - actual)}, extra={sorted(actual - expected)}); "
            "manual review is required."
        )


def _ensure_ledger(apps, schema_editor):
    LedgerEntry = apps.get_model("wallets", "LedgerEntry")
    table = LedgerEntry._meta.db_table
    connection = schema_editor.connection
    if table not in _tables(connection):
        schema_editor.create_model(LedgerEntry)
        return
    actual = _columns(connection, table)
    expected = _model_columns(LedgerEntry)
    if actual == expected:
        return
    count = _row_count(schema_editor, table)
    if count:
        raise RuntimeError(
            f"{table} is incompatible with wallets.0001 and contains {count} row(s). "
            "No destructive action was taken; an approved ledger data-mapping migration "
            "is required."
        )
    inbound = _inbound_foreign_keys(connection, table)
    if inbound:
        details = ", ".join(f"{source}.{name}" for source, name in inbound)
        raise RuntimeError(
            f"{table} is empty but has inbound foreign keys ({details}); manual review "
            "is required before recreation."
        )
    schema_editor.execute(f"DROP TABLE {schema_editor.quote_name(table)}")
    schema_editor.create_model(LedgerEntry)


def repair_legacy_schema(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    _ensure_wallet(apps, schema_editor)
    _ensure_model_table(apps, schema_editor, "PaymentProvider")
    _ensure_model_table(apps, schema_editor, "WalletTransaction")
    _ensure_ledger(apps, schema_editor)
    for model_name in EXPECTED_MODELS[2:]:
        _ensure_model_table(apps, schema_editor, model_name)
    # create_model() defers indexes and foreign keys until the schema editor
    # exits. The original 0002 operations run before that exit and immediately
    # rename two WalletTransaction indexes, so materialize repair-created
    # deferred SQL now.
    deferred_sql = list(schema_editor.deferred_sql)
    schema_editor.deferred_sql.clear()
    for statement in deferred_sql:
        schema_editor.execute(statement)


class Migration(migrations.Migration):

    dependencies = [
        ("wallets", "0001_wallet_ledger_foundation"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(repair_legacy_schema, migrations.RunPython.noop)
            ],
            state_operations=[],
        ),
        migrations.RemoveIndex(
            model_name="ledgerentry",
            name="wallets_led_created_abc123_idx",
        ),
        migrations.RemoveIndex(
            model_name="wallet",
            name="wallets_wal_user_id_5f9113_idx",
        ),
        migrations.RenameIndex(
            model_name="wallettransaction",
            new_name="wallets_wal_wallet__6d3ee8_idx",
            old_name="wallets_txn_wallet__abc123_idx",
        ),
        migrations.RenameIndex(
            model_name="wallettransaction",
            new_name="wallets_wal_transac_d6c260_idx",
            old_name="wallets_txn_type_abc123_idx",
        ),
        migrations.AddField(
            model_name="wallettransaction",
            name="provider_reference",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="depositintent",
            name="transaction",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="deposit_intent",
                to="wallets.wallettransaction",
            ),
        ),
        migrations.AlterField(
            model_name="ledgerentry",
            name="transaction",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="ledger_entries",
                to="wallets.wallettransaction",
            ),
        ),
        migrations.AlterField(
            model_name="paymentprovider",
            name="config",
            field=models.JSONField(
                blank=True, default=dict, help_text="Provider-specific configuration"
            ),
        ),
        migrations.AlterField(
            model_name="withdrawalrequest",
            name="destination",
            field=models.JSONField(
                help_text="Provider-specific destination details, e.g., bank account"
            ),
        ),
        migrations.AlterField(
            model_name="withdrawalrequest",
            name="transaction",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="withdrawal_request",
                to="wallets.wallettransaction",
            ),
        ),
    ]
