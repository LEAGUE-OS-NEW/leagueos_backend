"""Published wallets 0002, with an in-place overwritten-0001 compatibility repair.

The database-only first operation is deliberate. The previously published 0001
was overwritten, while this 0002 was also published and may already be recorded
as applied. Inserting a new predecessor would make those histories inconsistent.
"""

import django.db.models.deletion
from django.db import migrations, models

LEGACY_LEDGER_COLUMNS = {
    "id": ("uuid", None, None, False),
    "created_at": ("timestamp with time zone", None, None, False),
    "updated_at": ("timestamp with time zone", None, None, False),
    "entry_type": ("character varying", 20, None, False),
    "amount": ("numeric", 20, 4, False),
    "available_balance_before": ("numeric", 20, 4, False),
    "available_balance_after": ("numeric", 20, 4, False),
    "reserved_balance_before": ("numeric", 20, 4, False),
    "reserved_balance_after": ("numeric", 20, 4, False),
    "idempotency_reference": ("uuid", None, None, False),
    "fill_id": ("uuid", None, None, True),
    "market_id": ("uuid", None, None, True),
    "order_id": ("uuid", None, None, True),
    "wallet_id": ("uuid", None, None, False),
}

LEGACY_LEDGER_INDEXES = {
    "wallets_led_entry_t_4511e8_idx",
    "wallets_led_market__55d08b_idx",
    "wallets_led_order_i_b751ee_idx",
    "wallets_led_wallet__d6cac1_idx",
    "wallets_ledgerentry_entry_type_089eaf54",
    "wallets_ledgerentry_entry_type_089eaf54_like",
    "wallets_ledgerentry_fill_id_8bbbb97a",
    "wallets_ledgerentry_idempotency_reference_key",
    "wallets_ledgerentry_market_id_02fb812f",
    "wallets_ledgerentry_order_id_0d8b0e8a",
    "wallets_ledgerentry_pkey",
    "wallets_ledgerentry_wallet_id_686913ed",
}

LEGACY_LEDGER_CHECKS = {
    "ledger_entry_amount_positive": "amount",
    "ledger_available_before_non_negative": "available_balance_before",
    "ledger_available_after_non_negative": "available_balance_after",
    "ledger_reserved_before_non_negative": "reserved_balance_before",
    "ledger_reserved_after_non_negative": "reserved_balance_after",
}

APPROVED_INBOUND_LEDGER_FKS = {
    (
        "markets_marketcloseordercancellation",
        "markets_marketcloseo_wallet_release_ledge_d2fa071e_fk_wallets_l",
    ): "wallet_release_ledger_entry_id",
    (
        "markets_marketfinancialadjustmentline",
        "markets_marketfinanc_wallet_ledger_entry__760faac1_fk_wallets_l",
    ): "wallet_ledger_entry_id",
    (
        "markets_marketorderexpiryaudit",
        "markets_marketordere_wallet_release_ledge_5ac8a784_fk_wallets_l",
    ): "wallet_release_ledger_entry_id",
    (
        "markets_marketpositionsettlement",
        "markets_marketpositi_wallet_ledger_entry__8c887452_fk_wallets_l",
    ): "wallet_ledger_entry_id",
    (
        "markets_marketpositionvoidrefund",
        "markets_marketpositi_wallet_credit_ledger_1d1028d7_fk_wallets_l",
    ): "wallet_credit_ledger_entry_id",
    (
        "markets_marketvoidordercancellation",
        "markets_marketvoidor_wallet_release_ledge_c4b99902_fk_wallets_l",
    ): "wallet_release_ledger_entry_id",
}

LEGACY_WALLET_COLUMNS = {
    "id": ("uuid", None, None, False),
    "created_at": ("timestamp with time zone", None, None, False),
    "updated_at": ("timestamp with time zone", None, None, False),
    "currency": ("character varying", 3, None, False),
    "available_balance": ("numeric", 20, 4, False),
    "reserved_balance": ("numeric", 20, 4, False),
    "user_id": ("uuid", None, None, False),
}

LEGACY_WALLET_INDEXES = {
    "wallets_wal_user_id_5f9113_idx",
    "wallets_wallet_currency_02c3a75b",
    "wallets_wallet_currency_02c3a75b_like",
    "wallets_wallet_user_id_6cb307a0",
    "wallets_wallet_pkey",
    "wallet_user_currency_unique",
}

CURRENT_WALLET_COLUMNS = {
    **LEGACY_WALLET_COLUMNS,
    "available_balance": ("numeric", 16, 4, False),
    "reserved_balance": ("numeric", 16, 4, False),
    "status": ("character varying", 20, None, False),
}

CURRENT_LEDGER_COLUMNS = {
    "id": ("uuid", None, None, False),
    "created_at": ("timestamp with time zone", None, None, False),
    "updated_at": ("timestamp with time zone", None, None, False),
    "wallet_id": ("uuid", None, None, True),
    "transaction_id": ("uuid", None, None, True),
    "entry_type": ("character varying", 20, None, False),
    "debit_account": ("character varying", 50, None, False),
    "credit_account": ("character varying", 50, None, False),
    "amount": ("numeric", 16, 4, False),
    "currency": ("character varying", 3, None, False),
    "available_balance_before": ("numeric", 16, 4, False),
    "available_balance_after": ("numeric", 16, 4, False),
    "reserved_balance_before": ("numeric", 16, 4, False),
    "reserved_balance_after": ("numeric", 16, 4, False),
    "idempotency_reference": ("uuid", None, None, True),
    "market_id": ("uuid", None, None, True),
    "order_id": ("uuid", None, None, True),
    "fill_id": ("uuid", None, None, True),
}

CURRENT_WALLET_INDEXES = {
    "wallets_wallet_pkey",
    "unique_user_currency_wallet",
    "wallets_wallet_created_at_44118365",
    "wallets_wallet_currency_02c3a75b",
    "wallets_wallet_currency_02c3a75b_like",
    "wallets_wallet_status_096cb08a",
    "wallets_wallet_status_096cb08a_like",
    "wallets_wallet_user_id_6cb307a0",
}

CURRENT_LEDGER_INDEXES = {
    "wallets_ledgerentry_pkey",
    "unique_idempotency_reference",
    "wallets_ledgerentry_created_at_a73d2d3a",
    "wallets_ledgerentry_entry_type_089eaf54",
    "wallets_ledgerentry_entry_type_089eaf54_like",
    "wallets_ledgerentry_fill_id_8bbbb97a",
    "wallets_ledgerentry_idempotency_reference_7f4c0015",
    "wallets_ledgerentry_market_id_02fb812f",
    "wallets_ledgerentry_order_id_0d8b0e8a",
    "wallets_ledgerentry_transaction_id_02ffb4c6",
    "wallets_ledgerentry_wallet_id_686913ed",
}

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


def _column_definitions(connection, table):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, data_type, character_maximum_length,
                   numeric_precision, numeric_scale, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = %s
            ORDER BY ordinal_position
            """,
            [table],
        )
        return {
            name: (
                data_type,
                length if data_type == "character varying" else precision,
                scale,
                nullable == "YES",
                default,
            )
            for name, data_type, length, precision, scale, nullable, default in cursor
        }


def _ledger_indexes(connection, table):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexrelid::regclass::text
            FROM pg_index
            WHERE indrelid = %s::regclass
            ORDER BY 1
            """,
            [table],
        )
        return {row[0] for row in cursor}


def _ledger_constraints(connection, table):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT conname, contype, pg_get_constraintdef(oid, true), convalidated
            FROM pg_constraint
            WHERE conrelid = %s::regclass
              -- PostgreSQL 18 can expose NOT NULL as contype = 'n', unlike
              -- older versions. Nullability is checked via information_schema.
              AND contype <> 'n'
            ORDER BY conname
            """,
            [table],
        )
        return {name: (kind, definition, validated) for name, kind, definition, validated in cursor}


def _inbound_foreign_keys(connection, table):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.conrelid::regclass::text, c.conname, source.attname,
                   c.confrelid::regclass::text, target.attname,
                   c.convalidated, c.condeferrable, c.condeferred,
                   c.confupdtype, c.confdeltype, c.confmatchtype,
                   pg_get_constraintdef(c.oid, true)
            FROM pg_constraint c
            JOIN pg_attribute source
              ON source.attrelid = c.conrelid AND source.attnum = c.conkey[1]
            JOIN pg_attribute target
              ON target.attrelid = c.confrelid AND target.attnum = c.confkey[1]
            WHERE c.contype = 'f'
              AND c.confrelid = %s::regclass
              AND c.conrelid <> c.confrelid
            ORDER BY 1, 2, 3
            """,
            [table],
        )
        return cursor.fetchall()


def _legacy_ledger_problem(connection, table="wallets_ledgerentry"):
    """Return None only for the exact, empty, approved Neon legacy shape."""
    definitions = _column_definitions(connection, table)
    comparable = {name: values[:4] for name, values in definitions.items()}
    if comparable != LEGACY_LEDGER_COLUMNS:
        return "unknown ledger columns or column definitions"
    if any(values[4] is not None for values in definitions.values()):
        return "legacy ledger columns have unexpected database defaults"
    if _ledger_indexes(connection, table) != LEGACY_LEDGER_INDEXES:
        return "unknown or missing legacy ledger indexes"

    constraints = _ledger_constraints(connection, table)
    expected_names = {
        "wallets_ledgerentry_pkey",
        "wallets_ledgerentry_idempotency_reference_key",
        "wallets_ledgerentry_wallet_id_686913ed_fk_wallets_wallet_id",
        "wallets_ledgerentry_market_id_02fb812f_fk_markets_market_id",
        "wallets_ledgerentry_order_id_0d8b0e8a_fk_markets_marketorder_id",
        "wallets_ledgerentry_fill_id_8bbbb97a_fk_markets_marketfill_id",
        *LEGACY_LEDGER_CHECKS,
    }
    if set(constraints) != expected_names or not all(item[2] for item in constraints.values()):
        return "unknown, missing, or unvalidated legacy ledger constraints"
    if (
        constraints["wallets_ledgerentry_pkey"][0] != "p"
        or _normalized_definition(constraints["wallets_ledgerentry_pkey"][1]) != "primarykey(id)"
    ):
        return "legacy ledger primary key is not id"
    unique = constraints["wallets_ledgerentry_idempotency_reference_key"]
    if unique[0] != "u" or _normalized_definition(unique[1]) != "unique(idempotency_reference)":
        return "legacy ledger idempotency constraint is malformed"
    outbound = {
        "wallets_ledgerentry_wallet_id_686913ed_fk_wallets_wallet_id": (
            "wallet_id",
            "wallets_wallet",
        ),
        "wallets_ledgerentry_market_id_02fb812f_fk_markets_market_id": (
            "market_id",
            "markets_market",
        ),
        "wallets_ledgerentry_order_id_0d8b0e8a_fk_markets_marketorder_id": (
            "order_id",
            "markets_marketorder",
        ),
        "wallets_ledgerentry_fill_id_8bbbb97a_fk_markets_marketfill_id": (
            "fill_id",
            "markets_marketfill",
        ),
    }
    for name, (column, target) in outbound.items():
        kind, definition, _ = constraints[name]
        normalized = _normalized_definition(definition)
        if kind != "f" or normalized != (
            f"foreignkey({column})references{target}(id)deferrableinitiallydeferred"
        ):
            return f"legacy ledger foreign key {name} is malformed"
    for name, column in LEGACY_LEDGER_CHECKS.items():
        normalized = _normalized_definition(constraints[name][1])
        operator = ">" if name == "ledger_entry_amount_positive" else ">="
        approved = {
            f"check(({column}{operator}0))",
            f"check(({column}{operator}(0)::numeric))",
            f"check({column}{operator}0::numeric)",
        }
        if constraints[name][0] != "c" or normalized not in approved:
            return f"legacy ledger constraint {name} is malformed"

    inbound = _inbound_foreign_keys(connection, table)
    if {(row[0], row[1]): row[2] for row in inbound} != APPROVED_INBOUND_LEDGER_FKS:
        return "unapproved or missing inbound ledger foreign keys"
    for row in inbound:
        (
            source_table,
            _,
            source_column,
            target_table,
            target_column,
            validated,
            deferrable,
            deferred,
            update_action,
            delete_action,
            match_type,
            definition,
        ) = row
        expected_definition = (
            f"foreignkey({source_column})referenceswallets_ledgerentry(id)"
            "deferrableinitiallydeferred"
        )
        if (
            source_table not in {key[0] for key in APPROVED_INBOUND_LEDGER_FKS}
            or target_table != table
            or target_column != "id"
            or not validated
            or not deferrable
            or not deferred
            or update_action != "a"
            or delete_action != "a"
            or match_type != "s"
            or _normalized_definition(definition) != expected_definition
        ):
            return "malformed or unvalidated inbound ledger foreign key"
    return None


def _legacy_wallet_problem(connection, table="wallets_wallet"):
    definitions = _column_definitions(connection, table)
    comparable = {name: values[:4] for name, values in definitions.items()}
    if comparable != LEGACY_WALLET_COLUMNS:
        return "unknown wallet columns or column definitions"
    if any(values[4] is not None for values in definitions.values()):
        return "legacy wallet columns have unexpected database defaults"
    if _ledger_indexes(connection, table) != LEGACY_WALLET_INDEXES:
        return "unknown or missing legacy wallet indexes"
    constraints = _wallet_constraints(connection, table)
    expected = {
        "wallets_wallet_pkey",
        "wallets_wallet_user_id_6cb307a0_fk_accounts_user_id",
        "wallet_user_currency_unique",
        "wallet_available_balance_non_negative",
        "wallet_reserved_balance_non_negative",
    }
    if set(constraints) != expected:
        return "unknown or missing legacy wallet constraints"
    try:
        _validate_constraint(
            "wallet_user_currency_unique",
            constraints["wallet_user_currency_unique"],
            "u",
            ("user_id", "currency"),
        )
        for name, column in (
            ("wallet_available_balance_non_negative", "available_balance"),
            ("wallet_reserved_balance_non_negative", "reserved_balance"),
        ):
            _validate_constraint(name, constraints[name], "c", (column,))
    except RuntimeError as exc:
        return str(exc)
    return None


def _current_schema_problem(connection):
    for table, expected_columns, expected_indexes in (
        ("wallets_wallet", CURRENT_WALLET_COLUMNS, CURRENT_WALLET_INDEXES),
        ("wallets_ledgerentry", CURRENT_LEDGER_COLUMNS, CURRENT_LEDGER_INDEXES),
    ):
        definitions = _column_definitions(connection, table)
        if {name: values[:4] for name, values in definitions.items()} != expected_columns:
            return f"{table} has unknown current column definitions"
        if any(values[4] is not None for values in definitions.values()):
            return f"{table} has unexpected database defaults"
        if _ledger_indexes(connection, table) != expected_indexes:
            return f"{table} has unknown or missing current indexes"

    wallet_constraints = _ledger_constraints(connection, "wallets_wallet")
    if set(wallet_constraints) != {
        "wallets_wallet_pkey",
        "wallets_wallet_user_id_6cb307a0_fk_accounts_user_id",
        "unique_user_currency_wallet",
        "available_balance_not_negative",
        "reserved_balance_not_negative",
    } or not all(details[2] for details in wallet_constraints.values()):
        return "wallets_wallet has unknown, missing, or unvalidated current constraints"
    ledger_constraints = _ledger_constraints(connection, "wallets_ledgerentry")
    if set(ledger_constraints) != {
        "wallets_ledgerentry_pkey",
        "wallets_ledgerentry_fill_id_8bbbb97a_fk_markets_marketfill_id",
        "wallets_ledgerentry_market_id_02fb812f_fk_markets_market_id",
        "wallets_ledgerentry_order_id_0d8b0e8a_fk_markets_marketorder_id",
        "wallets_ledgerentry_transaction_id_02ffb4c6_fk_wallets_w",
        "wallets_ledgerentry_wallet_id_686913ed_fk_wallets_wallet_id",
        "ledger_amount_positive",
        "ledger_available_before_non_negative",
        "ledger_available_after_non_negative",
        "ledger_reserved_before_non_negative",
        "ledger_reserved_after_non_negative",
    } or not all(details[2] for details in ledger_constraints.values()):
        return (
            "wallets_ledgerentry has unknown, missing, or unvalidated current constraints: "
            f"{sorted(ledger_constraints)}"
        )
    for name, column in (
        ("ledger_amount_positive", "amount"),
        ("ledger_available_before_non_negative", "available_balance_before"),
        ("ledger_available_after_non_negative", "available_balance_after"),
        ("ledger_reserved_before_non_negative", "reserved_balance_before"),
        ("ledger_reserved_after_non_negative", "reserved_balance_after"),
    ):
        normalized = _normalized_definition(ledger_constraints[name][1])
        operator = ">" if name == "ledger_amount_positive" else ">="
        if normalized not in {
            f"check(({column}{operator}0))",
            f"check(({column}{operator}(0)::numeric))",
            f"check({column}{operator}0::numeric)",
        }:
            return f"wallets_ledgerentry constraint {name} is malformed"
    return None


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
              -- See _ledger_constraints: NOT NULL is checked from columns.
              AND c.contype <> 'n'
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
        problem = _legacy_wallet_problem(connection, table)
        if problem:
            raise RuntimeError(
                f"{table} lacks status but is not the exact approved trading-wallet "
                f"0001 schema: {problem}. No schema change was attempted."
            )
        for field_name in ("available_balance", "reserved_balance"):
            old_field = models.DecimalField(decimal_places=4, max_digits=20, default=0)
            old_field.set_attributes_from_name(field_name)
            old_field.model = Wallet
            schema_editor.alter_field(
                Wallet, old_field, Wallet._meta.get_field(field_name), strict=True
            )
        old_created_at = models.DateTimeField(auto_now_add=True)
        old_created_at.set_attributes_from_name("created_at")
        old_created_at.model = Wallet
        schema_editor.alter_field(
            Wallet,
            old_created_at,
            Wallet._meta.get_field("created_at"),
            strict=True,
        )
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
    problem = _legacy_ledger_problem(connection, table)
    if problem:
        raise RuntimeError(
            f"{table} is empty but is not the exact approved trading-wallet 0001 "
            f"schema: {problem}. No schema change was attempted."
        )

    # Preserve the table, its primary key/OID, and all inbound Markets foreign
    # keys. PostgreSQL removes only constraints/indexes dependent on each
    # original-only column; no CASCADE is necessary or permitted.
    schema_editor.execute(
        f"ALTER TABLE {schema_editor.quote_name(table)} DROP CONSTRAINT "
        f"{schema_editor.quote_name('ledger_entry_amount_positive')}"
    )
    old_amount = models.DecimalField(decimal_places=4, max_digits=20)
    old_amount.set_attributes_from_name("amount")
    old_amount.model = LedgerEntry
    schema_editor.alter_field(
        LedgerEntry, old_amount, LedgerEntry._meta.get_field("amount"), strict=True
    )
    for field_name in ("debit_account", "credit_account", "currency", "transaction"):
        schema_editor.add_field(LedgerEntry, LedgerEntry._meta.get_field(field_name))
    quoted_table = schema_editor.quote_name(table)
    for column in (
        "entry_type",
        "available_balance_before",
        "available_balance_after",
        "reserved_balance_before",
        "reserved_balance_after",
        "idempotency_reference",
        "fill_id",
        "market_id",
        "order_id",
        "wallet_id",
    ):
        schema_editor.execute(
            f"ALTER TABLE {quoted_table} DROP COLUMN {schema_editor.quote_name(column)}"
        )
    old_created_at = models.DateTimeField(auto_now_add=True)
    old_created_at.set_attributes_from_name("created_at")
    old_created_at.model = LedgerEntry
    schema_editor.alter_field(
        LedgerEntry,
        old_created_at,
        LedgerEntry._meta.get_field("created_at"),
        strict=True,
    )
    for index in LedgerEntry._meta.indexes:
        schema_editor.add_index(LedgerEntry, index)


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
