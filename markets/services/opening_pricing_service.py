from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from authentication.services.permission_service import PermissionService
from markets.models import Market, MarketOutcome


class MarketOpeningPricingService:
    EDITABLE_STATUSES = {
        Market.Status.DRAFT,
        Market.Status.PENDING_APPROVAL,
        Market.Status.APPROVED,
    }
    LOCAL_HISTORICAL_BACKFILL_STATUSES = EDITABLE_STATUSES | {Market.Status.OPEN}

    @staticmethod
    def _validated_values(*, face_value_ugx, yes_probability):
        try:
            probability = Decimal(str(yes_probability))
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError({"yes_probability": "Enter a valid probability."}) from None
        if probability <= 0 or probability >= 100:
            raise ValidationError(
                {"yes_probability": "Probability must be greater than 0 and less than 100."}
            )
        try:
            face_value = int(face_value_ugx)
            supplied_face_value = Decimal(str(face_value_ugx))
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError(
                {"face_value_ugx": "Enter a positive whole UGX amount."}
            ) from None
        if face_value <= 0 or supplied_face_value != face_value:
            raise ValidationError({"face_value_ugx": "Enter a positive whole UGX amount."})

        yes_price = (probability / Decimal("100")).quantize(Decimal("0.00001"))
        no_price = Decimal("1.00000") - yes_price
        if yes_price + no_price != Decimal("1.00000"):
            raise ValidationError({"outcomes": "YES and NO prices must total exactly 1.00000."})
        return face_value, yes_price, no_price

    @staticmethod
    def _update_locked_market(*, market, face_value, yes_price, no_price):
        outcomes = {item.side: item for item in market.outcomes.select_for_update()}
        if set(outcomes) != {MarketOutcome.Side.YES, MarketOutcome.Side.NO}:
            raise ValidationError({"outcomes": "A binary YES/NO outcome pair is required."})

        market.face_value_ugx = face_value
        market.save(update_fields=["face_value_ugx", "updated_at"])
        outcomes[MarketOutcome.Side.YES].opening_price = yes_price
        outcomes[MarketOutcome.Side.NO].opening_price = no_price
        MarketOutcome.objects.bulk_update(outcomes.values(), ["opening_price", "updated_at"])
        return market

    @classmethod
    @transaction.atomic
    def configure(cls, *, market: Market, actor, face_value_ugx, yes_probability) -> Market:
        if not PermissionService.has_permission(actor, "manage_market"):
            raise ValidationError({"actor": "The manage_market permission is required."})

        locked_market = Market.objects.select_for_update().get(pk=market.pk)
        if locked_market.status not in cls.EDITABLE_STATUSES:
            raise ValidationError({"status": "Opening pricing is immutable once trading opens."})

        face_value, yes_price, no_price = cls._validated_values(
            face_value_ugx=face_value_ugx, yes_probability=yes_probability
        )
        return cls._update_locked_market(
            market=locked_market,
            face_value=face_value,
            yes_price=yes_price,
            no_price=no_price,
        )

    @classmethod
    @transaction.atomic
    def configure_local_untraded_historical_market(
        cls, *, market: Market, actor, face_value_ugx, yes_probability
    ) -> Market:
        """Local-only repair for explicit historical/demo markets with no trading history."""
        if not settings.DEBUG:
            raise ValidationError(
                {"debug": "Historical market pricing backfill requires DEBUG=True."}
            )
        if not PermissionService.has_permission(actor, "manage_market"):
            raise ValidationError({"actor": "The manage_market permission is required."})

        locked_market = Market.objects.select_for_update().get(pk=market.pk)
        if locked_market.status not in cls.LOCAL_HISTORICAL_BACKFILL_STATUSES:
            raise ValidationError({"status": "Market status is not eligible for local backfill."})
        if (
            locked_market.orders.exists()
            or locked_market.fills.exists()
            or locked_market.positions.exists()
            or hasattr(locked_market, "settlement")
        ):
            raise ValidationError(
                {
                    "market": (
                        "Historical backfill requires zero orders, fills, positions, "
                        "and no settlement."
                    )
                }
            )

        face_value, yes_price, no_price = cls._validated_values(
            face_value_ugx=face_value_ugx, yes_probability=yes_probability
        )
        return cls._update_locked_market(
            market=locked_market,
            face_value=face_value,
            yes_price=yes_price,
            no_price=no_price,
        )
