# Initial and complete migration for the wallets module

import django.db.models.deletion
import uuid
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("markets", "0005_add_market_fill"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PaymentProvider",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("code", models.CharField(db_index=True, max_length=100, unique=True)),
                ("name", models.CharField(max_length=200)),
                (
                    "provider_type",
                    models.CharField(
                        choices=[
                            ("GENERIC", "Generic"),
                            ("MOCK", "Mock Provider"),
                        ],
                        default="GENERIC",
                        max_length=50,
                    ),
                ),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("config", models.JSONField(blank=True, default=dict)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="Wallet",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "currency",
                    models.CharField(db_index=True, max_length=3),
                ),
                (
                    "available_balance",
                    models.DecimalField(decimal_places=4, default=Decimal("0.0000"), max_digits=16),
                ),
                (
                    "reserved_balance",
                    models.DecimalField(decimal_places=4, default=Decimal("0.0000"), max_digits=16),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("ACTIVE", "Active"),
                            ("SUSPENDED", "Suspended"),
                            ("CLOSED", "Closed"),
                        ],
                        db_index=True,
                        default="ACTIVE",
                        max_length=20,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="wallets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["currency"],
            },
        ),
        migrations.CreateModel(
            name="WalletTransaction",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "reference",
                    models.CharField(
                        db_index=True, default=uuid.uuid4, max_length=255, unique=True
                    ),
                ),
                (
                    "transaction_type",
                    models.CharField(
                        choices=[
                            ("DEPOSIT", "Deposit"),
                            ("WITHDRAWAL", "Withdrawal"),
                            ("ADJUSTMENT", "Adjustment"),
                        ],
                        db_index=True,
                        max_length=20,
                    ),
                ),
                ("amount", models.DecimalField(decimal_places=4, max_digits=16)),
                ("currency", models.CharField(max_length=3)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("COMPLETED", "Completed"),
                            ("FAILED", "Failed"),
                            ("CANCELLED", "Cancelled"),
                        ],
                        db_index=True,
                        default="PENDING",
                        max_length=20,
                    ),
                ),
                ("description", models.TextField(blank=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "provider",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="transactions",
                        to="wallets.paymentprovider",
                    ),
                ),
                (
                    "wallet",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="transactions",
                        to="wallets.wallet",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="LedgerEntry",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "debit_account",
                    models.CharField(
                        choices=[
                            ("USER_WALLET", "User Wallet"),
                            ("PROVIDER_PAYABLE", "Provider Payable"),
                            ("REVENUE", "Revenue"),
                        ],
                        max_length=50,
                    ),
                ),
                (
                    "credit_account",
                    models.CharField(
                        choices=[
                            ("USER_WALLET", "User Wallet"),
                            ("PROVIDER_PAYABLE", "Provider Payable"),
                            ("REVENUE", "Revenue"),
                        ],
                        max_length=50,
                    ),
                ),
                ("amount", models.DecimalField(decimal_places=4, max_digits=16)),
                ("currency", models.CharField(max_length=3)),
                (
                    "transaction",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ledger_entries",
                        to="wallets.wallettransaction",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "verbose_name_plural": "Ledger entries",
            },
        ),
        migrations.CreateModel(
            name="DepositIntent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("amount", models.DecimalField(decimal_places=4, max_digits=16)),
                ("currency", models.CharField(max_length=3)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("COMPLETED", "Completed"),
                            ("FAILED", "Failed"),
                            ("EXPIRED", "Expired"),
                        ],
                        db_index=True,
                        default="PENDING",
                        max_length=20,
                    ),
                ),
                ("idempotency_key", models.UUIDField(default=uuid.uuid4, unique=True)),
                ("expires_at", models.DateTimeField()),
                (
                    "provider",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="deposit_intents",
                        to="wallets.paymentprovider",
                    ),
                ),
                (
                    "transaction",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="deposit_intent",
                        to="wallets.wallettransaction",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="deposit_intents",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="WithdrawalRequest",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("amount", models.DecimalField(decimal_places=4, max_digits=16)),
                (
                    "destination",
                    models.JSONField(help_text="Provider-specific destination details"),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING_APPROVAL", "Pending Approval"),
                            ("APPROVED", "Approved"),
                            ("REJECTED", "Rejected"),
                            ("PROCESSING", "Processing"),
                            ("COMPLETED", "Completed"),
                            ("FAILED", "Failed"),
                        ],
                        db_index=True,
                        default="PENDING_APPROVAL",
                        max_length=20,
                    ),
                ),
                (
                    "risk_status",
                    models.CharField(
                        choices=[
                            ("NOT_CHECKED", "Not Checked"),
                            ("PASSED", "Passed"),
                            ("FLAGGED", "Flagged for Review"),
                            ("FAILED", "Failed"),
                        ],
                        db_index=True,
                        default="NOT_CHECKED",
                        max_length=20,
                    ),
                ),
                ("rejection_reason", models.TextField(blank=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approved_withdrawals",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "transaction",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="withdrawal_request",
                        to="wallets.wallettransaction",
                    ),
                ),
                (
                    "wallet",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="withdrawal_requests",
                        to="wallets.wallet",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="Receipt",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("receipt_number", models.CharField(db_index=True, max_length=255, unique=True)),
                ("file_url", models.URLField(blank=True, max_length=1024)),
                ("generated_at", models.DateTimeField(auto_now_add=True)),
                (
                    "transaction",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="receipt",
                        to="wallets.wallettransaction",
                    ),
                ),
            ],
            options={
                "ordering": ["-generated_at"],
            },
        ),
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("DEPOSIT_INTENT_CREATED", "Deposit intent created"),
                            ("DEPOSIT_COMPLETED", "Deposit completed"),
                            ("DEPOSIT_FAILED", "Deposit failed"),
                            ("WITHDRAWAL_REQUESTED", "Withdrawal requested"),
                            ("WITHDRAWAL_APPROVED", "Withdrawal approved"),
                            ("WITHDRAWAL_REJECTED", "Withdrawal rejected"),
                            ("WITHDRAWAL_COMPLETED", "Withdrawal completed"),
                            ("WITHDRAWAL_FAILED", "Withdrawal failed"),
                            ("LEDGER_ENTRY_CREATED", "Ledger entry created"),
                            ("TRANSACTION_VIEWED", "Transaction viewed"),
                            ("RECEIPT_GENERATED", "Receipt generated"),
                            ("RECEIPT_DOWNLOADED", "Receipt downloaded"),
                        ],
                        db_index=True,
                        max_length=50,
                    ),
                ),
                ("related_object_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="wallet_audit_logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        # Wallet indexes and constraints
        migrations.AddIndex(
            model_name="wallet",
            index=models.Index(fields=["user", "currency"], name="wallets_wal_user_id_5f9113_idx"),
        ),
        migrations.AddConstraint(
            model_name="wallet",
            constraint=models.UniqueConstraint(
                fields=("user", "currency"), name="unique_user_currency_wallet"
            ),
        ),
        migrations.AddConstraint(
            model_name="wallet",
            constraint=models.CheckConstraint(
                condition=models.Q(("available_balance__gte", 0)),
                name="available_balance_not_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="wallet",
            constraint=models.CheckConstraint(
                condition=models.Q(("reserved_balance__gte", 0)),
                name="reserved_balance_not_negative",
            ),
        ),
        # WalletTransaction indexes
        migrations.AddIndex(
            model_name="wallettransaction",
            index=models.Index(
                fields=["wallet", "status", "-created_at"],
                name="wallets_txn_wallet__abc123_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="wallettransaction",
            index=models.Index(
                fields=["transaction_type", "status"],
                name="wallets_txn_type_abc123_idx",
            ),
        ),
        # LedgerEntry index
        migrations.AddIndex(
            model_name="ledgerentry",
            index=models.Index(fields=["-created_at"], name="wallets_led_created_abc123_idx"),
        ),
        # AuditLog indexes
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(
                fields=["user", "action", "-created_at"],
                name="wallets_aud_user_id_21e81c_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(
                fields=["action", "-created_at"],
                name="wallets_aud_action_9b54dc_idx",
            ),
        ),
    ]
