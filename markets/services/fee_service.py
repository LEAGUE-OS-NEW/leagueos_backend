from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid5

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from authentication.services.permission_service import PermissionService
from markets.models import MarketFeeLedgerEntry, MarketFeeSchedule


class MarketFeeService:
    MONEY_QUANTUM = Decimal("0.0001")
    BPS_DIVISOR = Decimal("10000")
    CURRENCY = "UGX"

    @classmethod
    def calculate_fee(cls, amount, rate_bps):
        return (Decimal(amount) * Decimal(rate_bps) / cls.BPS_DIVISOR).quantize(
            cls.MONEY_QUANTUM, rounding=ROUND_HALF_UP
        )

    @classmethod
    def effective_schedule(cls, *, market, at=None):
        at = at or timezone.now()
        base = MarketFeeSchedule.objects.filter(
            status=MarketFeeSchedule.Status.ACTIVE,
            effective_at__lte=at,
        )
        specific = base.filter(market=market).order_by("-effective_at", "-version", "-id").first()
        if specific is not None:
            return specific
        return base.filter(market__isnull=True).order_by("-effective_at", "-version", "-id").first()

    @classmethod
    def rates(cls, *, market, at=None):
        schedule = cls.effective_schedule(market=market, at=at)
        if schedule is None:
            return None, {"maker": 0, "taker": 0, "settlement": 0, "refund": 0}
        return schedule, {
            "maker": schedule.maker_fee_bps,
            "taker": schedule.taker_fee_bps,
            "settlement": schedule.settlement_fee_bps,
            "refund": schedule.refund_fee_bps,
        }

    @classmethod
    def preview(cls, *, market, quantity, limit_price):
        notional = (Decimal(quantity) * Decimal(limit_price)).quantize(cls.MONEY_QUANTUM)
        schedule, rates = cls.rates(market=market)
        maker_fee = cls.calculate_fee(notional, rates["maker"])
        taker_fee = cls.calculate_fee(notional, rates["taker"])
        return {
            "estimated_order_notional": notional,
            "estimated_maximum_buyer_reservation": notional + max(maker_fee, taker_fee),
            "estimated_maker_fee": maker_fee,
            "estimated_taker_fee": taker_fee,
            "schedule_id": schedule.id if schedule else None,
            "schedule_version": schedule.version if schedule else 0,
            "currency": cls.CURRENCY,
            "role_statement": "Final maker/taker role is determined during execution.",
        }

    @classmethod
    @transaction.atomic
    def create_draft(cls, *, actor, market=None, effective_at=None, **rates):
        cls._permission(actor, "manage_market")
        scope = MarketFeeSchedule.objects.select_for_update().filter(market=market)
        version = (scope.order_by("-version").values_list("version", flat=True).first() or 0) + 1
        schedule = MarketFeeSchedule(
            market=market,
            version=version,
            effective_at=effective_at or timezone.now(),
            created_by=actor,
            **rates,
        )
        schedule.save()
        return schedule

    @classmethod
    @transaction.atomic
    def activate(cls, *, schedule_id, actor):
        cls._permission(actor, "approve_market")
        schedule = MarketFeeSchedule.objects.select_for_update().get(id=schedule_id)
        if schedule.status != MarketFeeSchedule.Status.DRAFT:
            raise ValidationError({"status": "Only draft schedules can be activated."})
        if schedule.created_by_id == actor.id:
            raise ValidationError({"actor": "The creator cannot activate their own schedule."})
        conflict = MarketFeeSchedule.objects.filter(
            market=schedule.market,
            status=MarketFeeSchedule.Status.ACTIVE,
        ).exists()
        if conflict:
            raise ValidationError({"status": "Retire the active schedule before activation."})
        schedule.status = MarketFeeSchedule.Status.ACTIVE
        schedule.activated_by = actor
        schedule.activated_at = timezone.now()
        schedule.full_clean()
        MarketFeeSchedule._base_manager.filter(pk=schedule.pk).update(
            status=schedule.status,
            activated_by=actor,
            activated_at=schedule.activated_at,
            updated_at=timezone.now(),
        )
        return MarketFeeSchedule.objects.get(pk=schedule.pk)

    @classmethod
    @transaction.atomic
    def retire(cls, *, schedule_id, actor):
        cls._permission(actor, "approve_market")
        schedule = MarketFeeSchedule.objects.select_for_update().get(id=schedule_id)
        if schedule.status != MarketFeeSchedule.Status.ACTIVE:
            raise ValidationError({"status": "Only active schedules can be retired."})
        if schedule.created_by_id == actor.id:
            raise ValidationError({"actor": "The creator cannot retire their own schedule."})
        MarketFeeSchedule._base_manager.filter(pk=schedule.pk).update(
            status=MarketFeeSchedule.Status.RETIRED,
            retired_by=actor,
            retired_at=timezone.now(),
            updated_at=timezone.now(),
        )
        return MarketFeeSchedule.objects.get(pk=schedule.pk)

    @classmethod
    def record_fee(
        cls,
        *,
        parent_id,
        market,
        participant,
        fee_type,
        rate_bps,
        gross,
        order=None,
        fill=None,
        schedule=None,
    ):
        fee = cls.calculate_fee(gross, rate_bps)
        reference = uuid5(parent_id, f"fee:{fee_type}:{participant.id}")
        entry = MarketFeeLedgerEntry.objects.filter(idempotency_reference=reference).first()
        if entry:
            expected = {
                "schedule_id": getattr(schedule, "id", None),
                "schedule_version": schedule.version if schedule else 0,
                "market_id": market.id,
                "participant_id": participant.id,
                "fill_id": getattr(fill, "id", None),
                "order_id": getattr(order, "id", None),
                "fee_type": fee_type,
                "rate_bps": rate_bps,
                "gross_amount": Decimal(gross),
                "fee_amount": fee,
                "net_amount": Decimal(gross) - fee,
                "currency": cls.CURRENCY,
            }
            if any(getattr(entry, field) != value for field, value in expected.items()):
                raise ValidationError(
                    {"idempotency_reference": "Fee replay does not match the original entry."}
                )
            return entry
        entry = MarketFeeLedgerEntry(
            idempotency_reference=reference,
            schedule=schedule,
            schedule_version=schedule.version if schedule else 0,
            market=market,
            participant=participant,
            fill=fill,
            order=order,
            fee_type=fee_type,
            rate_bps=rate_bps,
            gross_amount=gross,
            fee_amount=fee,
            net_amount=Decimal(gross) - fee,
            currency=cls.CURRENCY,
        )
        entry.save(force_insert=True)
        return entry

    @staticmethod
    def _permission(actor, name):
        if not PermissionService.has_permission(actor, name):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(f"You do not have the {name} permission.")


def maximum_order_fee(*, market, notional):
    _schedule, rates = MarketFeeService.rates(market=market)
    return MarketFeeService.calculate_fee(notional, max(rates["maker"], rates["taker"]))
