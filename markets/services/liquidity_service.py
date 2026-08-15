from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID, uuid5

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from markets.models import (
    Market,
    MarketCollateralEntry,
    MarketCollateralPool,
    MarketCompleteSetIssuance,
    MarketLiquidityConfiguration,
    MarketLiquidityProvider,
    MarketOrder,
    MarketOutcome,
    MarketPosition,
)
from markets.services.fee_service import MarketFeeService
from wallets.services.wallet_service import WalletService


class MarketLiquidityService:
    CURRENCY = "UGX"
    OPENING_NAMESPACE = UUID("09e02fdd-f68e-48de-9aa4-5f07df4b99ba")

    @classmethod
    @transaction.atomic
    def configure(
        cls,
        *,
        market,
        actor,
        initial_liquidity_ugx=0,
        source=MarketLiquidityConfiguration.Source.PLATFORM_TREASURY,
        opening_spread_bps=0,
        provider=None,
    ):
        market = Market.objects.select_for_update().get(pk=market.pk)
        if market.status not in {Market.Status.DRAFT, Market.Status.REJECTED}:
            raise ValidationError(
                {"status": "Liquidity can only be configured for draft/rejected markets."}
            )
        values = {
            "source": source,
            "initial_liquidity_ugx": Decimal(str(initial_liquidity_ugx)),
            "opening_spread_bps": opening_spread_bps,
            "provider": provider,
            "configured_by": actor,
            "configured_at": timezone.now(),
            "status": MarketLiquidityConfiguration.Status.CONFIGURED,
        }
        config, _ = MarketLiquidityConfiguration.objects.update_or_create(
            market=market, defaults=values
        )
        config.full_clean()
        config.save()
        return config

    @classmethod
    @transaction.atomic
    def activate_opening_liquidity(cls, *, market, actor=None):
        market = Market.objects.select_for_update().get(pk=market.pk)
        config = (
            MarketLiquidityConfiguration.objects.select_for_update().filter(market=market).first()
        )
        if config is None or config.initial_liquidity_ugx == 0:
            return None
        reference = uuid5(cls.OPENING_NAMESPACE, str(market.id))
        existing = MarketCompleteSetIssuance.objects.filter(idempotency_reference=reference).first()
        if existing:
            return existing
        outcomes = {o.side: o for o in market.outcomes.select_for_update().all()}
        yes, no = outcomes.get(MarketOutcome.Side.YES), outcomes.get(MarketOutcome.Side.NO)
        if not yes or not no or yes.opening_price is None or no.opening_price is None:
            raise ValidationError({"outcomes": "YES and NO opening prices are required."})
        if yes.opening_price + no.opening_price != Decimal("1.00000"):
            raise ValidationError({"outcomes": "Opening prices must sum exactly to 1.00000."})
        provider = (
            config.provider
            or MarketLiquidityProvider.objects.select_for_update()
            .filter(
                provider_type=MarketLiquidityProvider.ProviderType.PLATFORM_TREASURY, is_active=True
            )
            .order_by("created_at")
            .first()
        )
        if not provider or not provider.is_active:
            raise ValidationError(
                {"liquidity_provider": "An active platform treasury provider is required."}
            )
        quantity = config.initial_liquidity_ugx.quantize(Decimal("0.0001"))
        WalletService.debit_available(
            user=provider.user,
            currency=cls.CURRENCY,
            amount=quantity,
            idempotency_reference=uuid5(reference, "treasury-debit"),
            market=market,
        )
        pool, _ = MarketCollateralPool.objects.select_for_update().get_or_create(market=market)
        pool.locked_collateral += quantity
        pool.full_clean()
        pool.save(update_fields=["locked_collateral", "updated_at"])
        issuance = MarketCompleteSetIssuance(
            market=market,
            issuance_type=MarketCompleteSetIssuance.IssuanceType.PLATFORM_OPENING,
            quantity=quantity,
            collateral_amount=quantity,
            yes_execution_price=yes.opening_price,
            no_execution_price=no.opening_price,
            provider=provider,
            idempotency_reference=reference,
        )
        issuance.full_clean()
        issuance.save(force_insert=True)
        MarketCollateralEntry.objects.create(
            pool=pool,
            market=market,
            entry_type=MarketCollateralEntry.EntryType.TREASURY_LOCK,
            amount=quantity,
            idempotency_reference=uuid5(reference, "collateral-lock"),
            actor=actor,
            provider=provider,
            issuance=issuance,
        )
        half_spread = Decimal(config.opening_spread_bps) / Decimal("20000")
        for outcome, price in (
            (yes, yes.opening_price + half_spread),
            (no, no.opening_price + half_spread),
        ):
            price = price.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
            if price <= 0 or price >= 1:
                raise ValidationError(
                    {"opening_spread_bps": "Opening spread produces an invalid ask price."}
                )
            cost = (quantity * outcome.opening_price).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
            position = MarketPosition(
                user=provider.user,
                market=market,
                outcome=outcome,
                quantity=quantity,
                reserved_quantity=quantity,
                average_entry_price=outcome.opening_price,
                total_cost=cost,
            )
            position.full_clean()
            position.save(force_insert=True)
            schedule, rates = MarketFeeService.rates(market=market)
            order = MarketOrder(
                user=provider.user,
                market=market,
                outcome=outcome,
                side=MarketOrder.Side.SELL,
                quantity=quantity,
                limit_price=price,
                status=MarketOrder.Status.OPEN,
                time_in_force=MarketOrder.TimeInForce.GTC,
                fee_schedule=schedule,
                maximum_fee_bps=max(rates["maker"], rates["taker"]),
            )
            order.full_clean()
            order.save(force_insert=True)
        config.provider = provider
        config.status = MarketLiquidityConfiguration.Status.ACTIVE
        config.activated_at = timezone.now()
        config.save(update_fields=["provider", "status", "activated_at", "updated_at"])
        return issuance

    @classmethod
    def lock_complementary_collateral(cls, *, market, issuance, amount, actor=None):
        pool, _ = MarketCollateralPool.objects.select_for_update().get_or_create(market=market)
        pool.locked_collateral += amount
        pool.save(update_fields=["locked_collateral", "updated_at"])
        return MarketCollateralEntry.objects.create(
            pool=pool,
            market=market,
            entry_type=MarketCollateralEntry.EntryType.COMPLEMENTARY_BUY_LOCK,
            amount=amount,
            idempotency_reference=uuid5(issuance.id, "collateral-lock"),
            actor=actor,
            issuance=issuance,
        )
