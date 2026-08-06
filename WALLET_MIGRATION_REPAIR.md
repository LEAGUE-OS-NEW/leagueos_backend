# Wallet migration history repair

## Historical states and root cause

Commit `eb443f8` published `wallets.0001_wallet_ledger_foundation` with two
trading tables. `wallets_wallet` had `id`, timestamps, currency, available and
reserved balances, and `user_id`; it had no `status`. Its constraints were
`wallet_user_currency_unique`, `wallet_available_balance_non_negative`, and
`wallet_reserved_balance_non_negative`.

The original `wallets_ledgerentry` had `id`, timestamps, `entry_type`, a
`numeric(20,4)` amount, four `numeric(20,4)` balance snapshots, a unique
non-null idempotency UUID, and `wallet_id` plus nullable `market_id`, `order_id`,
and `fill_id`. It had the five named positive/non-negative checks and the four
published composite trading indexes. It did not have
`wallets_led_created_abc123_idx`.

Commit `8f8f5ae` overwrote the already-published 0001 in place. The overwritten
ledger has `debit_account`, `credit_account`, `numeric(16,4)` `amount`,
`currency`, and nullable `transaction_id`, plus a created-at index named
`wallets_led_created_abc123_idx`. It also introduced the six payments tables,
wallet `status`, current wallet constraint names, and two WalletTransaction
indexes. Its published 0002 removes the ledger created-at index and wallet
composite index, renames both WalletTransaction indexes, adds
`provider_reference`, and alters several fields (including making the ledger
transaction non-null). Commit `7c6dbbc` published 0003, which adds the trading
fields back with their current nullability/defaults and adds conditional
idempotency uniqueness; 0004 adds the current five ledger checks.

Staging records only 0001, but its physical tables are the original `eb443f8`
shape. Payment tables and wallet `status` are absent, and both wallet and ledger
rows are zero. The first repair compared that ledger only with the overwritten
0001 columns, classified it as unknown, and would otherwise have dropped and
recreated it. That is unsafe: six validated, deferrable, initially-deferred
Markets foreign keys reference `wallets_ledgerentry(id)`, so PostgreSQL refuses
the drop and the replacement would lose the table identity and relationships.

The earlier Render failure was:

```text
relation "wallets_txn_wallet__abc123_idx" does not exist
```

The same history also lacks `wallets_led_created_abc123_idx`, which the
published 0002 tries to remove.

## In-place normalization in published 0002

No migration name, dependency, graph edge, or recorder row changes. The repair
remains the first database-only operation inside published 0002 because adding
a new predecessor would make databases that already recorded 0002 inconsistent.

On PostgreSQL only, the repair verifies the complete original column types,
sizes, nullability and defaults; the exact original indexes and same-table
constraints; an `id` primary key; zero ledger rows; and exactly these validated,
deferrable, initially-deferred inbound references to `wallets_ledgerentry(id)`:

- `markets_marketcloseordercancellation.wallet_release_ledger_entry_id`
- `markets_marketfinancialadjustmentline.wallet_ledger_entry_id`
- `markets_marketorderexpiryaudit.wallet_release_ledger_entry_id`
- `markets_marketpositionsettlement.wallet_ledger_entry_id`
- `markets_marketpositionvoidrefund.wallet_credit_ledger_entry_id`
- `markets_marketvoidordercancellation.wallet_release_ledger_entry_id`

Newer PostgreSQL versions can also represent `NOT NULL` constraints in
`pg_constraint` with `contype = 'n'`, while older versions do not. Those rows
alone are excluded from structural constraint-name comparisons; column
nullability is still validated separately through `information_schema.columns`.

It then alters the existing ledger in place: narrows `amount` to
`numeric(16,4)`; adds debit account, credit account, currency, and transaction;
removes the original-only trading columns and their dependent same-table
objects; and creates the overwritten-0001 created-at indexes. Missing payment
tables are created first, including the two old WalletTransaction index names.
Deferred schema-editor SQL is flushed before the untouched published 0002
operations continue. Thus 0002 can remove/rename the expected old indexes, and
0003 and 0004 can reintroduce the trading fields and final constraints normally.

The table is never dropped, renamed, or replaced. Its OID and `id` primary-key
identity remain stable, so the six inbound constraint names and definitions are
preserved untouched. There is no `CASCADE`, fake migration, recorder edit, or
manual migration marking.

Wallet rows are preserved while `status` and normalized constraint names are
added. Fresh databases and exact overwritten-0001 databases remain no-ops;
missing payment tables are still created; already-applied 0002 histories retain
the published graph.

## Refusal conditions and audit

`python manage.py audit_wallet_schema` is read-only and shares the historical
classification code embedded in 0002. It reports `NO-OP` for the final schema,
`SAFE REPAIR DURING WALLETS 0002` only for the exact approved empty original
shape, and refuses all other shapes. Refusal includes a nonempty incompatible
ledger, unknown columns/types/nullability/defaults, unknown or missing indexes
or constraints, a primary key other than `id`, any unknown inbound relationship,
or any malformed/unvalidated/non-deferred inbound constraint.

A nonempty original ledger requires a separately reviewed data-mapping
migration. Do not infer mappings, weaken this guard, use `--fake`, edit
`django_migrations`, use `CASCADE`, or manually drop the ledger.

## Disposable PostgreSQL dry run and rollback

Use an isolated local database first, then a disposable Neon child branch only
after review. Never point local commands at staging or production. Capture a
verified backup/branch restore point, run the audit, inspect `migrate --plan`,
apply through wallets 0002, audit again, apply through 0004, and run the final
audit and integrity checks. Verify the ledger OID and all six inbound constraint
names/definitions before and after.

Stop on any refusal or unexpected SQL. Rollback means discard the disposable
child branch or restore the verified pre-run backup. Reversing recorder state is
not a schema rollback, and this repair intentionally has no destructive reverse
mapping.

```console
python manage.py audit_wallet_schema
python manage.py migrate wallets 0002_remove_ledgerentry_wallets_led_created_abc123_idx_and_more --plan
python manage.py migrate wallets 0002_remove_ledgerentry_wallets_led_created_abc123_idx_and_more
python manage.py audit_wallet_schema
python manage.py migrate wallets 0004_ledgerentry_ledger_amount_positive_and_more
python manage.py audit_wallet_schema
```
