"""Pesapal-backed wallet deposit orchestration."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid5

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from wallets.models import (
    DepositIntent,
    PesapalDeposit,
    WalletTransaction,
)
from wallets.services.pesapal_client import (
    PesapalClient,
)
from wallets.services.wallet_service import (
    WalletService,
)


class PesapalDepositService:
    """Coordinates Pesapal with the authoritative League OS wallet."""

    PROVIDER_CODE = "PESAPAL_SANDBOX"
    SUPPORTED_CURRENCY = "UGX"

    @classmethod
    def start_deposit(
        cls,
        *,
        user,
        amount,
        currency,
        idempotency_key,
        client: PesapalClient | None = None,
    ) -> PesapalDeposit:
        if not idempotency_key:
            raise ValidationError({"idempotency_key": "An idempotency key is required."})

        try:
            UUID(str(idempotency_key))
        except (
            TypeError,
            ValueError,
            AttributeError,
        ) as error:
            raise ValidationError({"idempotency_key": "A valid UUID is required."}) from error

        currency = str(currency or "").strip().upper()

        if currency != cls.SUPPORTED_CURRENCY:
            raise ValidationError(
                {"currency": "Pesapal wallet top-ups " "currently support UGX only."}
            )

        pesapal_client = client if client is not None else PesapalClient()

        config = pesapal_client.config

        if not config.is_sandbox or config.environment != "SANDBOX":
            raise ValidationError(
                {"provider": "This integration branch " "only permits Pesapal Sandbox."}
            )

        missing_config = []

        if not config.ipn_id:
            missing_config.append("PESAPAL_IPN_ID")

        if not config.callback_url:
            missing_config.append("PESAPAL_CALLBACK_URL")

        if missing_config:
            raise ValidationError(
                {
                    "provider": "Missing Pesapal Sandbox "
                    "configuration: " + ", ".join(missing_config)
                }
            )

        intent = WalletService.create_deposit_intent(
            user=user,
            provider_code=cls.PROVIDER_CODE,
            amount=amount,
            currency=currency,
            idempotency_key=idempotency_key,
        )

        merchant_reference = "LO-DEPOSIT-" + intent.id.hex

        with transaction.atomic():
            locked_intent = (
                DepositIntent.objects.select_for_update()
                .select_related("provider")
                .get(pk=intent.pk)
            )

            pesapal, created = PesapalDeposit.objects.get_or_create(
                intent=locked_intent,
                defaults={
                    "environment": PesapalDeposit.Environment.SANDBOX,
                    "merchant_reference": merchant_reference,
                },
            )

            if pesapal.order_tracking_id and pesapal.redirect_url:
                return pesapal

            if not created:
                raise ValidationError(
                    {
                        "idempotency_key": "This deposit request "
                        "already reached Pesapal "
                        "but does not yet have a "
                        "confirmed checkout URL. "
                        "Do not automatically "
                        "resubmit it."
                    }
                )

        payload = cls._build_order_payload(
            intent=intent,
            merchant_reference=merchant_reference,
            client=pesapal_client,
        )

        response = pesapal_client.submit_order(payload)

        returned_reference = str(response.get("merchant_reference") or "").strip()

        tracking_id = str(response.get("order_tracking_id") or "").strip()

        redirect_url = str(response.get("redirect_url") or "").strip()

        if returned_reference != merchant_reference:
            raise ValidationError(
                {"provider": "Pesapal returned a " "different merchant " "reference."}
            )

        if not tracking_id:
            raise ValidationError({"provider": "Pesapal did not return " "an order tracking ID."})

        if not redirect_url:
            raise ValidationError({"provider": "Pesapal did not return " "a checkout URL."})

        with transaction.atomic():
            pesapal = PesapalDeposit.objects.select_for_update().get(pk=pesapal.pk)

            if pesapal.order_tracking_id:
                if pesapal.order_tracking_id != tracking_id:
                    raise ValidationError({"provider": "Conflicting Pesapal " "tracking ID."})

                return pesapal

            pesapal.order_tracking_id = tracking_id
            pesapal.redirect_url = redirect_url
            pesapal.provider_status = "PENDING"
            pesapal.save(
                update_fields=[
                    "order_tracking_id",
                    "redirect_url",
                    "provider_status",
                    "updated_at",
                ]
            )

        return pesapal

    @classmethod
    def reconcile_notification(
        cls,
        *,
        order_tracking_id,
        merchant_reference,
        client: PesapalClient | None = None,
    ) -> dict:
        tracking_id = str(order_tracking_id or "").strip()

        merchant_reference = str(merchant_reference or "").strip()

        if not tracking_id:
            raise ValidationError({"OrderTrackingId": "OrderTrackingId is required."})

        if not merchant_reference:
            raise ValidationError(
                {"OrderMerchantReference": "OrderMerchantReference " "is required."}
            )

        try:
            pesapal = PesapalDeposit.objects.select_related(
                "intent",
                "intent__user",
                "intent__provider",
            ).get(merchant_reference=merchant_reference)
        except PesapalDeposit.DoesNotExist:
            raise ValidationError(
                {"merchant_reference": "Unknown Pesapal " "merchant reference."}
            ) from None

        if pesapal.order_tracking_id and pesapal.order_tracking_id != tracking_id:
            raise ValidationError(
                {"order_tracking_id": "Pesapal tracking ID " "does not match this " "deposit."}
            )

        pesapal_client = client if client is not None else PesapalClient()

        config = pesapal_client.config

        if not config.is_sandbox or config.environment != "SANDBOX":
            raise ValidationError({"provider": "Only Pesapal Sandbox " "is permitted."})

        provider_status = pesapal_client.get_transaction_status(
            order_tracking_id=tracking_id,
        )

        cls._validate_provider_status(
            pesapal=pesapal,
            provider_status=provider_status,
        )

        return cls._apply_provider_status(
            pesapal_id=pesapal.id,
            tracking_id=tracking_id,
            provider_status=provider_status,
        )

    @staticmethod
    def _build_order_payload(
        *,
        intent,
        merchant_reference,
        client,
    ) -> dict:
        user = intent.user
        config = client.config

        email = str(user.email or "").strip()

        phone = str(
            getattr(
                user,
                "phone_number",
                "",
            )
            or ""
        ).strip()

        if not email and not phone:
            raise ValidationError(
                {"billing_address": "An email address or " "phone number is required."}
            )

        return {
            "id": merchant_reference,
            "currency": intent.currency,
            "amount": float(intent.amount),
            "description": "League OS wallet top-up",
            "callback_url": config.callback_url,
            "redirect_mode": "TOP_WINDOW",
            "notification_id": config.ipn_id,
            "billing_address": {
                "email_address": email,
                "phone_number": phone,
                "first_name": str(user.first_name or "").strip(),
                "middle_name": "",
                "last_name": str(user.last_name or "").strip(),
            },
        }

    @classmethod
    def _validate_provider_status(
        cls,
        *,
        pesapal,
        provider_status,
    ) -> None:
        returned_reference = str(provider_status.get("merchant_reference") or "").strip()

        if returned_reference != pesapal.merchant_reference:
            raise ValidationError(
                {
                    "merchant_reference": "Pesapal status returned "
                    "a different merchant "
                    "reference."
                }
            )

        returned_currency = str(provider_status.get("currency") or "").strip().upper()

        if returned_currency != pesapal.intent.currency:
            raise ValidationError(
                {"currency": "Pesapal payment currency " "does not match the " "deposit intent."}
            )

        try:
            returned_amount = Decimal(str(provider_status.get("amount")))
        except (
            InvalidOperation,
            TypeError,
            ValueError,
        ) as error:
            raise ValidationError(
                {"amount": "Pesapal returned an " "invalid payment amount."}
            ) from error

        if returned_amount != pesapal.intent.amount:
            raise ValidationError(
                {"amount": "Pesapal payment amount " "does not match the " "deposit intent."}
            )

    @classmethod
    @transaction.atomic
    def _apply_provider_status(
        cls,
        *,
        pesapal_id,
        tracking_id,
        provider_status,
    ) -> dict:
        pesapal = (
            PesapalDeposit.objects.select_for_update()
            .select_related(
                "intent",
                "intent__user",
                "intent__provider",
            )
            .get(pk=pesapal_id)
        )

        intent = (
            DepositIntent.objects.select_for_update(of=("self",))
            .select_related(
                "user",
                "provider",
                "transaction",
            )
            .get(pk=pesapal.intent_id)
        )

        if pesapal.order_tracking_id and pesapal.order_tracking_id != tracking_id:
            raise ValidationError({"order_tracking_id": "Conflicting Pesapal " "tracking ID."})

        status_code = cls._status_code(provider_status)

        status_description = str(provider_status.get("payment_status_description") or "").strip()

        pesapal.order_tracking_id = tracking_id
        pesapal.provider_status = status_description.upper() or str(status_code)
        pesapal.confirmation_code = str(provider_status.get("confirmation_code") or "").strip()
        pesapal.payment_method = str(provider_status.get("payment_method") or "").strip()
        pesapal.payment_account = str(provider_status.get("payment_account") or "").strip()
        pesapal.status_description = str(provider_status.get("description") or "").strip()
        pesapal.last_checked_at = timezone.now()

        pesapal.save(
            update_fields=[
                "order_tracking_id",
                "provider_status",
                "confirmation_code",
                "payment_method",
                "payment_account",
                "status_description",
                "last_checked_at",
                "updated_at",
            ]
        )

        if status_code == 1:
            credited = cls._complete_deposit(
                intent=intent,
                pesapal=pesapal,
            )

            return {
                "deposit": pesapal,
                "credited": credited,
                "requires_manual_reconciliation": False,
            }

        if status_code in {
            0,
            2,
        }:
            if intent.status != DepositIntent.Status.COMPLETED:
                intent.status = DepositIntent.Status.FAILED
                intent.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )

            return {
                "deposit": pesapal,
                "credited": False,
                "requires_manual_reconciliation": False,
            }

        if status_code == 3:
            if intent.status == DepositIntent.Status.COMPLETED:
                return {
                    "deposit": pesapal,
                    "credited": False,
                    "requires_manual_reconciliation": True,
                }

            intent.status = DepositIntent.Status.FAILED
            intent.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            return {
                "deposit": pesapal,
                "credited": False,
                "requires_manual_reconciliation": False,
            }

        return {
            "deposit": pesapal,
            "credited": False,
            "requires_manual_reconciliation": False,
        }

    @classmethod
    def _complete_deposit(
        cls,
        *,
        intent,
        pesapal,
    ) -> bool:
        if intent.status == DepositIntent.Status.COMPLETED:
            if intent.transaction_id is None:
                raise ValidationError(
                    {"transaction": "Completed deposit " "is missing its wallet " "transaction."}
                )

            return False

        wallet = WalletService.get_or_create_wallet(
            intent.user,
            intent.currency,
        )

        transaction_reference = "PESAPAL-" + pesapal.merchant_reference

        wallet_transaction = WalletTransaction.objects.create(
            wallet=wallet,
            reference=transaction_reference,
            transaction_type=WalletTransaction.TransactionType.DEPOSIT,
            amount=intent.amount,
            currency=intent.currency,
            status=WalletTransaction.Status.PENDING,
            provider=intent.provider,
            provider_reference=pesapal.order_tracking_id,
            description="Pesapal wallet deposit",
        )

        ledger_reference = uuid5(
            intent.id,
            "pesapal-deposit-credit",
        )

        WalletService.credit(
            user=intent.user,
            currency=intent.currency,
            amount=intent.amount,
            idempotency_reference=ledger_reference,
            transaction=wallet_transaction,
        )

        wallet_transaction.status = WalletTransaction.Status.COMPLETED
        wallet_transaction.completed_at = timezone.now()
        wallet_transaction.save(
            update_fields=[
                "status",
                "completed_at",
                "updated_at",
            ]
        )

        intent.status = DepositIntent.Status.COMPLETED
        intent.transaction = wallet_transaction
        intent.save(
            update_fields=[
                "status",
                "transaction",
                "updated_at",
            ]
        )

        return True

    @staticmethod
    def _status_code(
        provider_status,
    ) -> int | None:
        raw = provider_status.get("status_code")

        try:
            return int(raw)
        except (
            TypeError,
            ValueError,
        ):
            return None


def pesapal_deposit_read_data(
    pesapal: PesapalDeposit,
) -> dict:
    """Return the public-safe deposit status contract."""

    intent = pesapal.intent

    return {
        "id": intent.id,
        "amount": intent.amount,
        "currency": intent.currency,
        "status": intent.status,
        "created_at": intent.created_at,
        "expires_at": intent.expires_at,
        "provider_code": intent.provider.code,
        "payment_url": pesapal.redirect_url,
        "order_tracking_id": pesapal.order_tracking_id,
        "provider_status": pesapal.provider_status,
    }
