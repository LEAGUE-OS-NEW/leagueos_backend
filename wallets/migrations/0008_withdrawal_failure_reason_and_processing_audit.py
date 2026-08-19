from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "wallets",
            "0007_seed_pesapal_sandbox_provider",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="withdrawalrequest",
            name="failure_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="action",
            field=models.CharField(
                choices=[
                    (
                        "DEPOSIT_INTENT_CREATED",
                        "Deposit intent created",
                    ),
                    (
                        "DEPOSIT_COMPLETED",
                        "Deposit completed",
                    ),
                    (
                        "DEPOSIT_FAILED",
                        "Deposit failed",
                    ),
                    (
                        "WITHDRAWAL_REQUESTED",
                        "Withdrawal requested",
                    ),
                    (
                        "WITHDRAWAL_APPROVED",
                        "Withdrawal approved",
                    ),
                    (
                        "WITHDRAWAL_REJECTED",
                        "Withdrawal rejected",
                    ),
                    (
                        "WITHDRAWAL_PROCESSING",
                        "Withdrawal processing",
                    ),
                    (
                        "WITHDRAWAL_COMPLETED",
                        "Withdrawal completed",
                    ),
                    (
                        "WITHDRAWAL_FAILED",
                        "Withdrawal failed",
                    ),
                    (
                        "LEDGER_ENTRY_CREATED",
                        "Ledger entry created",
                    ),
                    (
                        "TRANSACTION_VIEWED",
                        "Transaction viewed",
                    ),
                    (
                        "RECEIPT_GENERATED",
                        "Receipt generated",
                    ),
                    (
                        "RECEIPT_DOWNLOADED",
                        "Receipt downloaded",
                    ),
                ],
                db_index=True,
                max_length=50,
            ),
        ),
    ]
