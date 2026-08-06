# Wallet migration history repair

## Root cause and confirmed drift

Commit `eb443f8` published `wallets.0001_wallet_ledger_foundation` as a two-table
trading wallet/ledger migration. Its wallet had no `status`; its ledger used
`wallet`, `entry_type`, balance snapshots, idempotency, and optional market,
order, and fill references. Commit `8f8f5ae` later edited that same published
file in place, replacing its meaning with a broader payments schema and adding
six models. It also added 0002; `7c6dbbc` added 0003 and 0004.

Staging records 0001 as applied, but its two physical tables and original
constraint names match the `eb443f8` version. The six payment tables and wallet
`status` are absent. Its empty ledger has the original trading fields rather
than the debit/credit/transaction fields represented by current 0001. Current
0002 would therefore address absent tables, and 0003 would try to add columns
already present in the physical legacy ledger.

## Why the repair is inside published 0002

A separate migration inserted between published 0001 and published 0002 was
rejected. A database that had already applied 0002 would have an applied
migration whose newly introduced dependency was unapplied, producing
`InconsistentMigrationHistory`. The graph remains exactly:

```text
0001_wallet_ledger_foundation
  -> 0002_remove_ledgerentry_wallets_led_created_abc123_idx_and_more
  -> 0003_ledgerentry_available_balance_after_and_more
  -> 0004_ledgerentry_ledger_amount_positive_and_more
```

The compatibility repair is the first operation inside the existing 0002. This
is a deliberate edit to a published migration, required because the previously
published 0001 was overwritten. `SeparateDatabaseAndState` runs the physical
repair while leaving migration state unchanged; current 0001 already provides
that state. Every original 0002 operation follows in its original order.

On PostgreSQL the first operation:

- requires the wallet table and accepts the exact current-0001 columns or that
  shape without `status`;
- adds `status` with the normal `ACTIVE` default while preserving wallet rows;
- validates legacy and current wallet constraints by name and PostgreSQL
  definition;
- renames an equivalent legacy constraint to its current name, or removes only
  an equivalent redundant legacy constraint when both names exist;
- creates only missing payment tables from the historical apps registry in
  foreign-key dependency order;
- leaves an already-correct current-0001 ledger untouched;
- recreates an incompatible ledger only when it is empty and has no inbound
  foreign keys, using a plain drop without `CASCADE`;
- refuses incompatible constraint definitions, unknown existing-table shapes,
  and any incompatible nonempty ledger before destructive SQL.

Renaming `wallet_user_currency_unique` to `unique_user_currency_wallet` also
renames PostgreSQL's constraint-owned unique index. The checks become
`available_balance_not_negative` and `reserved_balance_not_negative`.
Equivalent legacy duplicates do not remain.

Fresh databases already match current 0001, so the repair no-ops before the
original 0002 operations. Confirmed legacy staging databases recorded at 0001
are repaired first. Environments where 0002 is already applied retain a
consistent graph, do not rerun it, and have no new pending predecessor.

There is intentionally no destructive reverse repair. Reversing 0002 cannot
reconstruct the overwritten original schema. A nonempty legacy ledger requires
a separately reviewed data-mapping migration; debit/credit mappings must not be
inferred from trading records. Take and verify a database backup before rollout.

## Read-only audit

Run before rollout:

```console
python manage.py audit_wallet_schema
```

It reports migration records, missing tables, column drift, wallet and ledger
row counts, and exactly one assessment: `NO-OP`, `SAFE REPAIR DURING WALLETS
0002`, `REFUSE - incompatible ledger contains data`, or `REFUSE - unknown
schema`. It never writes. A refusal returns a nonzero status.

## Local validation

Use an isolated local PostgreSQL database and an explicit local `DATABASE_URL`.
Never inherit a staging or production URL.

```console
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
pytest wallets/tests
pytest markets/tests
ruff check <modified Python files>
black --check <modified Python files>
git diff --check
```

## Staging rollout order

After a verified backup and approval, use the normal secret-injection mechanism
and run exactly:

```console
python manage.py audit_wallet_schema
python manage.py migrate wallets 0002_remove_ledgerentry_wallets_led_created_abc123_idx_and_more --plan
python manage.py migrate wallets 0002_remove_ledgerentry_wallets_led_created_abc123_idx_and_more
python manage.py audit_wallet_schema
python manage.py migrate --plan
python manage.py migrate
python manage.py audit_wallet_schema
```

Stop immediately if the first audit refuses, especially for a nonempty
incompatible ledger, or if the observed shape differs from the confirmed
fixture. Do not use `--fake` and do not edit `django_migrations`. Rollback means
restoring the pre-rollout backup or applying a separately reviewed forward
repair; reversing a migration record alone is not a schema rollback.
