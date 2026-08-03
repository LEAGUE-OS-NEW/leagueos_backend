from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone

from markets.models import (
    MarketFill,
    MarketOrder,
    MarketPosition,
    MarketResponsibleParticipation,
    MarketResponsibleParticipationEvent,
)
from markets.services.order_financials import calculate_buy_commitment

_CONTROLS_NOT_LOADED = object()


@dataclass(frozen=True)
class ResponsibleParticipationResult:
    allowed: bool
    buy_allowed: bool
    sell_allowed: bool
    evaluated_at: object
    proposed_notional: Decimal
    daily_buy_notional: Decimal
    weekly_buy_notional: Decimal
    open_buy_commitment: Decimal
    market_exposure: Decimal
    total_exposure: Decimal
    cumulative_realized_loss: Decimal
    limits: dict
    cooling_off_active: bool
    self_exclusion_active: bool
    administrative_block_active: bool
    reason_codes: tuple
    buy_reason_codes: tuple
    sell_reason_codes: tuple
    next_actions: tuple

    def utilization(self):
        return {
            "proposed_notional": self.proposed_notional,
            "daily_buy_notional": self.daily_buy_notional,
            "weekly_buy_notional": self.weekly_buy_notional,
            "open_buy_commitment": self.open_buy_commitment,
            "market_exposure": self.market_exposure,
            "total_exposure": self.total_exposure,
            "cumulative_realized_loss": self.cumulative_realized_loss,
        }


class MarketResponsibleParticipationService:
    MONEY_QUANTUM = Decimal("0.0001")
    ACTIVE_ORDER_STATUSES = (MarketOrder.Status.OPEN, MarketOrder.Status.PARTIALLY_FILLED)
    LIMIT_REASON_FIELDS = (
        ("max_order_notional", "MAX_ORDER_NOTIONAL_EXCEEDED"),
        ("daily_buy_notional_limit", "DAILY_BUY_NOTIONAL_LIMIT_EXCEEDED"),
        ("weekly_buy_notional_limit", "WEEKLY_BUY_NOTIONAL_LIMIT_EXCEEDED"),
        ("max_open_buy_commitment", "OPEN_BUY_COMMITMENT_LIMIT_EXCEEDED"),
        ("max_market_exposure", "MARKET_EXPOSURE_LIMIT_EXCEEDED"),
        ("max_total_exposure", "TOTAL_EXPOSURE_LIMIT_EXCEEDED"),
    )
    DURATIONS = {
        "ONE_HOUR": timedelta(hours=1),
        "ONE_DAY": timedelta(days=1),
        "SEVEN_DAYS": timedelta(days=7),
        "THIRTY_DAYS": timedelta(days=30),
    }
    EXCLUSION_DURATIONS = {**DURATIONS, "NINETY_DAYS": timedelta(days=90)}

    @classmethod
    def _money(cls, value):
        return Decimal(value or 0).quantize(cls.MONEY_QUANTUM, rounding=ROUND_HALF_UP)

    @classmethod
    def _reservation(cls, quantity, price):
        return calculate_buy_commitment(quantity=quantity, limit_price=price)

    @classmethod
    def _limits(cls, controls):
        setting_names = {
            "max_order_notional": "MARKET_RESPONSIBLE_DEFAULT_MAX_ORDER_NOTIONAL",
            "daily_buy_notional_limit": "MARKET_RESPONSIBLE_DEFAULT_DAILY_BUY_NOTIONAL",
            "weekly_buy_notional_limit": "MARKET_RESPONSIBLE_DEFAULT_WEEKLY_BUY_NOTIONAL",
            "max_open_buy_commitment": "MARKET_RESPONSIBLE_DEFAULT_MAX_OPEN_BUY_COMMITMENT",
            "max_market_exposure": "MARKET_RESPONSIBLE_DEFAULT_MAX_MARKET_EXPOSURE",
            "max_total_exposure": "MARKET_RESPONSIBLE_DEFAULT_MAX_TOTAL_EXPOSURE",
            "max_cumulative_realized_loss": (
                "MARKET_RESPONSIBLE_DEFAULT_MAX_CUMULATIVE_REALIZED_LOSS"
            ),
        }
        limits = {}
        for field, setting_name in setting_names.items():
            value = getattr(controls, field) if controls else None
            configured = getattr(settings, setting_name, None)
            limits[field] = value if value is not None else configured
        return limits

    @classmethod
    def status(cls, *, participant, as_of=None, controls=_CONTROLS_NOT_LOADED):
        return cls.evaluate_order(
            participant=participant,
            market=None,
            outcome=None,
            side=None,
            quantity=0,
            limit_price=0,
            as_of=as_of,
            controls=controls,
        )

    @classmethod
    def evaluate_order(
        cls,
        *,
        participant,
        market,
        outcome,
        side,
        quantity,
        limit_price,
        as_of=None,
        controls=_CONTROLS_NOT_LOADED,
    ):
        evaluated_at = as_of or timezone.now()
        if controls is _CONTROLS_NOT_LOADED:
            controls = MarketResponsibleParticipation.objects.filter(
                participant=participant
            ).first()
        limits = cls._limits(controls)
        proposed_notional = cls._reservation(quantity, limit_price) if side else cls._money(0)
        proposed_buy = proposed_notional if side == MarketOrder.Side.BUY else cls._money(0)
        local_now = timezone.localtime(evaluated_at)
        day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=day_start.weekday())
        fills = MarketFill.objects.filter(buy_order__user=participant, created_at__lte=evaluated_at)
        fill_notional = ExpressionWrapper(
            F("quantity") * F("price"), output_field=DecimalField(max_digits=24, decimal_places=9)
        )
        daily = cls._money(
            fills.filter(created_at__gte=day_start).aggregate(v=Sum(fill_notional))["v"]
        )
        weekly = cls._money(
            fills.filter(created_at__gte=week_start).aggregate(v=Sum(fill_notional))["v"]
        )
        commitments = list(
            MarketOrder.objects.filter(
                user=participant, side=MarketOrder.Side.BUY, status__in=cls.ACTIVE_ORDER_STATUSES
            ).values("market_id", "quantity", "filled_quantity", "limit_price")
        )
        open_total = cls._money(
            sum(
                (
                    cls._reservation(row["quantity"] - row["filled_quantity"], row["limit_price"])
                    for row in commitments
                ),
                Decimal(0),
            )
        )
        market_open = cls._money(
            sum(
                (
                    cls._reservation(row["quantity"] - row["filled_quantity"], row["limit_price"])
                    for row in commitments
                    if market and row["market_id"] == market.id
                ),
                Decimal(0),
            )
        )
        all_positions = MarketPosition.objects.filter(user=participant)
        positions = all_positions.filter(quantity__gt=0)
        total_cost = cls._money(positions.aggregate(v=Sum("total_cost"))["v"])
        market_cost = (
            cls._money(positions.filter(market=market).aggregate(v=Sum("total_cost"))["v"])
            if market
            else cls._money(0)
        )
        negative_pnl = all_positions.filter(realized_pnl__lt=0).aggregate(
            value=Sum("realized_pnl")
        )["value"]
        loss = cls._money(-negative_pnl if negative_pnl is not None else 0)
        open_with_proposed = open_total + proposed_buy
        market_exposure = market_cost + market_open + proposed_buy
        total_exposure = total_cost + open_total + proposed_buy
        cooling = bool(
            controls and controls.cooling_off_until and controls.cooling_off_until > evaluated_at
        )
        exclusion = bool(
            controls
            and (
                controls.self_excluded_indefinitely
                or (controls.self_exclusion_until and controls.self_exclusion_until > evaluated_at)
            )
        )
        admin = bool(
            controls
            and controls.administrative_block_until
            and controls.administrative_block_until > evaluated_at
        )
        universal_reasons = []
        if cooling:
            universal_reasons.append("COOLING_OFF_ACTIVE")
        if exclusion:
            universal_reasons.append("SELF_EXCLUSION_ACTIVE")
        if admin:
            universal_reasons.append("ADMINISTRATIVE_BLOCK_ACTIVE")
        values = (
            proposed_notional,
            daily + proposed_buy,
            weekly + proposed_buy,
            open_with_proposed,
            market_exposure,
            total_exposure,
        )
        order_reasons = []
        capacity_reasons = []
        for index, ((field, code), value) in enumerate(
            zip(cls.LIMIT_REASON_FIELDS, values, strict=True)
        ):
            if limits[field] is not None and value > limits[field]:
                if index == 0:
                    order_reasons.append(code)
                elif side == MarketOrder.Side.BUY:
                    capacity_reasons.append(code)
        loss_limit = limits["max_cumulative_realized_loss"]
        loss_reasons = []
        if loss_limit is not None and loss > loss_limit:
            loss_reasons.append("CUMULATIVE_REALIZED_LOSS_LIMIT_REACHED")
        if side is None:
            status_values = (
                daily,
                weekly,
                open_total,
                market_cost + market_open,
                total_cost + open_total,
            )
            for (field, code), value in zip(
                cls.LIMIT_REASON_FIELDS[1:], status_values, strict=True
            ):
                if limits[field] is not None and value >= limits[field]:
                    capacity_reasons.append(code)
            if limits["max_order_notional"] == 0:
                order_reasons.append("MAX_ORDER_NOTIONAL_EXCEEDED")
        sell_reasons = tuple(universal_reasons + order_reasons + loss_reasons)
        buy_reasons = tuple(universal_reasons + order_reasons + capacity_reasons + loss_reasons)
        reasons = sell_reasons if side == MarketOrder.Side.SELL else buy_reasons
        actions = []
        if any(code.endswith("EXCEEDED") for code in reasons):
            actions.append("REDUCE_ORDER_SIZE")
        if cooling:
            actions.append("WAIT_FOR_COOLING_OFF")
        if exclusion or admin:
            actions.append("CONTACT_SUPPORT")
        if any("LIMIT" in code for code in reasons) and "REVIEW_LIMITS" not in actions:
            actions.append("REVIEW_LIMITS")
        return ResponsibleParticipationResult(
            (not buy_reasons or not sell_reasons) if side is None else not reasons,
            not buy_reasons,
            not sell_reasons,
            evaluated_at,
            proposed_notional,
            daily,
            weekly,
            open_with_proposed,
            market_exposure,
            total_exposure,
            loss,
            limits,
            cooling,
            exclusion,
            admin,
            tuple(reasons),
            buy_reasons,
            sell_reasons,
            tuple(actions),
        )

    @classmethod
    def _snapshot(cls, controls):
        data = {
            field: (
                format(getattr(controls, field), ".4f")
                if getattr(controls, field) is not None
                else None
            )
            for field in MarketResponsibleParticipation.MONEY_FIELDS
        }
        for field in (
            "cooling_off_until",
            "self_exclusion_until",
            "self_excluded_indefinitely",
            "administrative_block_until",
        ):
            value = getattr(controls, field)
            data[field] = value.isoformat() if hasattr(value, "isoformat") else value
        data["administrative_block_reason"] = controls.administrative_block_reason
        return data

    @classmethod
    def _locked_controls(cls, participant):
        try:
            return MarketResponsibleParticipation.objects.select_for_update().get(
                participant=participant
            )
        except MarketResponsibleParticipation.DoesNotExist:
            try:
                with transaction.atomic():
                    return MarketResponsibleParticipation.objects.create(participant=participant)
            except IntegrityError:
                return MarketResponsibleParticipation.objects.select_for_update().get(
                    participant=participant
                )

    @classmethod
    @transaction.atomic
    def update_participant_limits(cls, *, participant, changes):
        if not changes:
            raise ValueError("PARTICIPANT_LIMIT_UPDATE_REQUIRED")
        participant = get_user_model().objects.select_for_update().get(pk=participant.pk)
        controls = cls._locked_controls(participant)
        before = cls._snapshot(controls)
        for field, value in changes.items():
            old = getattr(controls, field)
            if value is None or (old is not None and value > old):
                raise ValueError("PARTICIPANT_LIMIT_RELAXATION_NOT_ALLOWED")
            setattr(controls, field, value)
        after = cls._snapshot(controls)
        if before == after:
            return controls
        controls.full_clean()
        controls.save()
        event = "LIMITS_SET" if any(before[k] is None for k in changes) else "LIMITS_TIGHTENED"
        MarketResponsibleParticipationEvent.objects.create(
            participant=participant,
            actor=participant,
            event_type=event,
            previous_state=before,
            new_state=after,
        )
        return controls

    @classmethod
    @transaction.atomic
    def start_cooling_off(cls, *, participant, duration, as_of=None):
        participant = get_user_model().objects.select_for_update().get(pk=participant.pk)
        controls = cls._locked_controls(participant)
        before = cls._snapshot(controls)
        until = (as_of or timezone.now()) + cls.DURATIONS[duration]
        if controls.cooling_off_until and until <= controls.cooling_off_until:
            raise ValueError("COOLING_OFF_MAY_NOT_BE_SHORTENED")
        controls.cooling_off_until = until
        controls.save()
        MarketResponsibleParticipationEvent.objects.create(
            participant=participant,
            actor=participant,
            event_type=(
                "COOLING_OFF_EXTENDED" if before["cooling_off_until"] else "COOLING_OFF_STARTED"
            ),
            previous_state=before,
            new_state=cls._snapshot(controls),
        )
        return controls

    @classmethod
    @transaction.atomic
    def start_self_exclusion(cls, *, participant, duration, as_of=None):
        participant = get_user_model().objects.select_for_update().get(pk=participant.pk)
        controls = cls._locked_controls(participant)
        before = cls._snapshot(controls)
        if controls.self_excluded_indefinitely:
            raise ValueError("SELF_EXCLUSION_MAY_NOT_BE_SHORTENED")
        if duration == "INDEFINITE":
            controls.self_excluded_indefinitely = True
            controls.self_exclusion_until = None
        else:
            until = (as_of or timezone.now()) + cls.EXCLUSION_DURATIONS[duration]
            if controls.self_exclusion_until and until <= controls.self_exclusion_until:
                raise ValueError("SELF_EXCLUSION_MAY_NOT_BE_SHORTENED")
            controls.self_exclusion_until = until
        event = (
            "SELF_EXCLUSION_EXTENDED"
            if before["self_exclusion_until"]
            else "SELF_EXCLUSION_STARTED"
        )
        controls.save()
        MarketResponsibleParticipationEvent.objects.create(
            participant=participant,
            actor=participant,
            event_type=event,
            previous_state=before,
            new_state=cls._snapshot(controls),
        )
        return controls

    @classmethod
    @transaction.atomic
    def update_admin(cls, *, participant, actor, changes, reason):
        if not reason.strip():
            raise ValueError("ADMIN_REASON_REQUIRED")
        participant = get_user_model().objects.select_for_update().get(pk=participant.pk)
        controls = cls._locked_controls(participant)
        before = cls._snapshot(controls)
        now = timezone.now()
        requested_block_until = changes.get(
            "administrative_block_until", controls.administrative_block_until
        )
        if (
            "administrative_block_until" in changes
            and requested_block_until is not None
            and requested_block_until <= now
        ):
            raise ValueError("ADMIN_BLOCK_UNTIL_MUST_BE_FUTURE")
        for field, value in changes.items():
            old = getattr(controls, field)
            if (
                field in ("cooling_off_until", "self_exclusion_until")
                and old
                and (value is None or value < old)
            ):
                raise ValueError("PARTICIPANT_EXCLUSION_MAY_NOT_BE_SHORTENED")
            if (
                field == "self_excluded_indefinitely"
                and controls.self_excluded_indefinitely
                and not value
            ):
                raise ValueError("INDEFINITE_SELF_EXCLUSION_MAY_NOT_BE_REMOVED")
            if (
                field == "administrative_block_until"
                and old
                and old > now
                and (value is None or value < old)
            ):
                raise ValueError("ADMIN_BLOCK_MAY_NOT_BE_SHORTENED")
            setattr(controls, field, value)
        after = cls._snapshot(controls)
        if before == after:
            return controls
        block_until = controls.administrative_block_until
        if block_until and block_until > now:
            if not controls.administrative_block_reason.strip():
                raise ValueError("ADMIN_BLOCK_REASON_REQUIRED")
        controls.reviewed_by = actor
        controls.reviewed_at = now
        controls.full_clean()
        controls.save()
        changed_fields = {field for field in changes if before.get(field) != after.get(field)}
        categories = set()
        if changed_fields & set(MarketResponsibleParticipation.MONEY_FIELDS):
            categories.add("limits")
        if changed_fields & {"administrative_block_until", "administrative_block_reason"}:
            categories.add("admin_block")
        if "cooling_off_until" in changed_fields:
            categories.add("cooling")
        if changed_fields & {"self_exclusion_until", "self_excluded_indefinitely"}:
            categories.add("self_exclusion")
        if len(categories) != 1:
            event = "ADMIN_CONTROLS_UPDATED"
        elif "limits" in categories:
            event = "ADMIN_LIMITS_UPDATED"
        elif "cooling" in categories:
            event = "COOLING_OFF_EXTENDED"
        elif "self_exclusion" in categories:
            event = "SELF_EXCLUSION_EXTENDED"
        elif "administrative_block_until" not in changed_fields:
            event = "ADMIN_CONTROLS_UPDATED"
        elif before["administrative_block_until"]:
            event = "ADMIN_BLOCK_EXTENDED"
        else:
            event = "ADMIN_BLOCK_STARTED"
        MarketResponsibleParticipationEvent.objects.create(
            participant=participant,
            actor=actor,
            event_type=event,
            previous_state=before,
            new_state=after,
            reason=reason.strip(),
        )
        return controls
