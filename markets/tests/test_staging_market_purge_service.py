from datetime import timedelta
from decimal import Decimal

from django.db.models import Q
from django.test import TestCase
from django.utils import timezone

from authentication.tests.factories import (
    PermissionFactory,
    RoleFactory,
    RolePermissionFactory,
    UserFactory,
    UserRoleFactory,
)
from markets.models import (
    Market,
    MarketCategory,
    MarketCollateralPool,
    MarketLiquidityProvider,
    MarketOrder,
    MarketOutcome,
    MarketPosition,
    MarketScope,
    MarketSettlement,
    MarketStatusTransition,
)
from markets.services.catalog_service import (
    MarketCatalogService,
)
from markets.services.lifecycle_service import (
    MarketLifecycleService,
)
from markets.services.liquidity_service import (
    MarketLiquidityService,
)
from markets.services.opening_pricing_service import (
    MarketOpeningPricingService,
)
from markets.services.staging_market_purge_service import (
    CONFIRMATION_PHRASE,
    PurgeReport,
    StagingMarketPurgeError,
    _delete_market_graph,
    _unwind_market_if_required,
    apply_staging_market_purge,
    build_purge_preflight,
)
from markets.services.staging_market_purge_snapshot import (
    KEEPER_IDS,
    PURGE_IDS,
    SNAPSHOT_DIGEST,
)
from markets.tests.wallet_test_support import (
    fund_market_wallet,
)
from sports.models import Sport
from wallets.models import (
    DepositIntent,
    LedgerEntry,
    PaymentProvider,
    PesapalDeposit,
    Wallet,
    WalletTransaction,
    WithdrawalRequest,
)


class StagingMarketPurgeSnapshotTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

        self.actor = UserFactory(
            is_superuser=True,
            is_staff=True,
        )

        self.sport = Sport.objects.create(
            name="Purge Snapshot Football",
            code="PURGE_SNAPSHOT_FOOTBALL",
        )

        self.category = MarketCategory.objects.create(
            name="Purge Snapshot Match Result",
        )

        self.payment_user = UserFactory(
            is_verified=True,
        )

        self.wallet = Wallet.objects.create(
            user=self.payment_user,
            currency="UGX",
            available_balance=Decimal("100000.0000"),
            reserved_balance=Decimal("0.0000"),
        )

        self.provider = PaymentProvider.objects.create(
            code="PURGE_TEST_PESAPAL",
            name="Purge Test Pesapal",
        )

        self.transaction = WalletTransaction.objects.create(
            wallet=self.wallet,
            reference=("PURGE-PAYMENT-TRANSACTION"),
            transaction_type=(WalletTransaction.TransactionType.DEPOSIT),
            amount=Decimal("25000.0000"),
            currency="UGX",
            status=(WalletTransaction.Status.PENDING),
            provider=self.provider,
        )

        self.deposit_intent = DepositIntent.objects.create(
            user=self.payment_user,
            provider=self.provider,
            amount=Decimal("25000.0000"),
            currency="UGX",
            transaction=self.transaction,
            expires_at=(self.now + timedelta(hours=1)),
        )

        self.pesapal = PesapalDeposit.objects.create(
            intent=self.deposit_intent,
            environment=(PesapalDeposit.Environment.SANDBOX),
            merchant_reference=("PURGE-TEST-MERCHANT"),
        )

        self.withdrawal = WithdrawalRequest.objects.create(
            wallet=self.wallet,
            amount=Decimal("5000.0000"),
            destination={
                "method": "MOBILE_MONEY",
                "network": "MTN",
                "mobile_money_number": "0777000000",
                "account_name": "Purge Test Fan",
            },
        )

    def _create_snapshot_market(
        self,
        *,
        market_id,
        question,
        visible,
    ):
        return Market.objects.create(
            id=market_id,
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.CUSTOM,
            custom_subject=(f"Snapshot market {market_id}"),
            question=question,
            status=Market.Status.DRAFT,
            is_catalog_visible=visible,
        )

    def seed_snapshot(self):
        for index, market_id in enumerate(
            KEEPER_IDS,
            start=1,
        ):
            self._create_snapshot_market(
                market_id=market_id,
                question=(f"Keeper market {index}?"),
                visible=True,
            )

        for index, market_id in enumerate(
            PURGE_IDS,
            start=1,
        ):
            self._create_snapshot_market(
                market_id=market_id,
                question=(f"Legacy purge market {index}?"),
                visible=False,
            )

    def test_preflight_matches_exact_40_market_snapshot(
        self,
    ):
        self.seed_snapshot()

        result = build_purge_preflight()

        self.assertTrue(result["snapshot_matches_database"])
        self.assertEqual(
            result["database_market_count"],
            40,
        )
        self.assertEqual(
            result["keeper_count"],
            4,
        )
        self.assertEqual(
            result["purge_target_count"],
            36,
        )
        self.assertEqual(
            result["unexpected_market_ids"],
            [],
        )
        self.assertEqual(
            result["missing_snapshot_ids"],
            [],
        )
        self.assertEqual(
            result["unsettled_financial_market_ids"],
            [],
        )

    def test_apply_deletes_exact_36_and_preserves_payments(
        self,
    ):
        self.seed_snapshot()

        transaction_id = self.transaction.id
        intent_id = self.deposit_intent.id
        pesapal_id = self.pesapal.id
        withdrawal_id = self.withdrawal.id

        wallet_before = (
            self.wallet.available_balance,
            self.wallet.reserved_balance,
        )

        result = apply_staging_market_purge(
            actor=self.actor,
            confirmation=CONFIRMATION_PHRASE,
            snapshot_digest=SNAPSHOT_DIGEST,
        )

        self.assertEqual(
            result["deleted_market_count"],
            36,
        )
        self.assertEqual(
            result["remaining_market_count"],
            4,
        )
        self.assertTrue(result["payment_rows_unchanged"])

        self.assertEqual(
            set(
                str(value)
                for value in (
                    Market.objects.values_list(
                        "id",
                        flat=True,
                    )
                )
            ),
            set(KEEPER_IDS),
        )

        self.assertFalse(
            Market.objects.filter(
                id__in=PURGE_IDS,
            ).exists()
        )

        self.assertTrue(
            WalletTransaction.objects.filter(
                id=transaction_id,
            ).exists()
        )
        self.assertTrue(
            DepositIntent.objects.filter(
                id=intent_id,
            ).exists()
        )
        self.assertTrue(
            PesapalDeposit.objects.filter(
                id=pesapal_id,
            ).exists()
        )
        self.assertTrue(
            WithdrawalRequest.objects.filter(
                id=withdrawal_id,
            ).exists()
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            (
                self.wallet.available_balance,
                self.wallet.reserved_balance,
            ),
            wallet_before,
        )

    def test_wrong_confirmation_or_digest_never_mutates_snapshot(
        self,
    ):
        self.seed_snapshot()

        with self.assertRaises(StagingMarketPurgeError):
            apply_staging_market_purge(
                actor=self.actor,
                confirmation="WRONG",
                snapshot_digest=(SNAPSHOT_DIGEST),
            )

        self.assertEqual(
            Market.objects.count(),
            40,
        )

        with self.assertRaises(StagingMarketPurgeError):
            apply_staging_market_purge(
                actor=self.actor,
                confirmation=(CONFIRMATION_PHRASE),
                snapshot_digest="WRONG",
            )

        self.assertEqual(
            Market.objects.count(),
            40,
        )

    def test_new_market_causes_full_abort_instead_of_being_touched(
        self,
    ):
        self.seed_snapshot()

        extra = Market.objects.create(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.CUSTOM,
            custom_subject=("Market created after snapshot"),
            question=("Will this future market survive?"),
            status=Market.Status.DRAFT,
            is_catalog_visible=True,
        )

        with self.assertRaises(StagingMarketPurgeError):
            apply_staging_market_purge(
                actor=self.actor,
                confirmation=(CONFIRMATION_PHRASE),
                snapshot_digest=(SNAPSHOT_DIGEST),
            )

        self.assertEqual(
            Market.objects.count(),
            41,
        )

        self.assertTrue(
            Market.objects.filter(
                id=extra.id,
                is_catalog_visible=True,
            ).exists()
        )

        self.assertEqual(
            Market.objects.filter(
                id__in=PURGE_IDS,
            ).count(),
            36,
        )


class StagingMarketPurgeFinancialTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

        manage = PermissionFactory(
            name="manage_market",
            resource="market",
            action="manage",
        )
        approve = PermissionFactory(
            name="approve_market",
            resource="market",
            action="approve",
        )

        operations_role = RoleFactory(
            name="Purge Operations",
            display_name="Purge Operations",
        )
        approval_role = RoleFactory(
            name="Purge Approval",
            display_name="Purge Approval",
        )

        RolePermissionFactory(
            role=operations_role,
            permission=manage,
        )
        RolePermissionFactory(
            role=approval_role,
            permission=approve,
        )

        self.creator = UserFactory()
        self.actor = UserFactory()

        UserRoleFactory(
            user=self.creator,
            role=operations_role,
        )
        UserRoleFactory(
            user=self.actor,
            role=approval_role,
        )

        self.provider_user = UserFactory(
            is_verified=True,
        )

        self.provider_wallet = fund_market_wallet(self.provider_user)

        self.provider = MarketLiquidityProvider.objects.create(
            code=("PURGE_PLATFORM_TREASURY"),
            provider_type=(MarketLiquidityProvider.ProviderType.PLATFORM_TREASURY),
            user=self.provider_user,
            display_name=("Purge Platform Treasury"),
        )

        self.sport = Sport.objects.create(
            name="Purge Financial Football",
            code="PURGE_FINANCIAL_FOOTBALL",
        )

        self.category = MarketCategory.objects.create(
            name=("Purge Financial Match Result"),
        )

    def create_market(
        self,
        *,
        question,
    ):
        return MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.CUSTOM,
            custom_subject=("Synthetic staging purge test"),
            question=question,
            description=("Synthetic staging purge test."),
            rules="Official result applies.",
            resolution_source=("Official result"),
            resolution_criteria=("Use the final verified result."),
            status=Market.Status.DRAFT,
            opens_at=(self.now - timedelta(hours=1)),
            closes_at=(self.now + timedelta(hours=1)),
            created_by=self.creator,
            yes_label="Yes",
            no_label="No",
        )

    def open_with_liquidity(
        self,
        market,
    ):
        MarketOpeningPricingService.configure(
            market=market,
            actor=self.creator,
            face_value_ugx=Decimal("10000"),
            yes_probability=60,
        )

        MarketLiquidityService.configure(
            market=market,
            actor=self.creator,
            provider=self.provider,
            initial_liquidity_ugx=Decimal("500000"),
            opening_spread_bps=100,
        )

        MarketLifecycleService.submit(
            market_id=market.id,
            actor=self.creator,
            notes="Ready for purge test.",
        )

        MarketLifecycleService.approve(
            market_id=market.id,
            actor=self.actor,
            notes="Approved.",
        )

        return MarketLifecycleService.open(
            market_id=market.id,
            actor=self.actor,
            notes="Opened.",
        )

    def test_opening_liquidity_is_refunded_before_market_graph_is_deleted(
        self,
    ):
        market = self.open_with_liquidity(
            self.create_market(
                question=("Will the obsolete market win?"),
            )
        )

        self.provider_wallet.refresh_from_db()

        self.assertEqual(
            self.provider_wallet.available_balance,
            Decimal("500000.0000"),
        )

        self.assertEqual(
            MarketOrder.objects.filter(
                market=market,
                status=MarketOrder.Status.OPEN,
            ).count(),
            2,
        )

        self.assertEqual(
            MarketPosition.objects.filter(
                market=market,
            ).count(),
            2,
        )

        pool = MarketCollateralPool.objects.get(
            market=market,
        )

        self.assertEqual(
            pool.locked_collateral,
            Decimal("500000.0000"),
        )

        original_ledger_ids = {
            str(value)
            for value in (
                LedgerEntry.objects.filter(
                    market=market,
                ).values_list(
                    "id",
                    flat=True,
                )
            )
        }

        self.assertTrue(original_ledger_ids)

        report = PurgeReport()

        _unwind_market_if_required(
            market_id=market.id,
            actor=self.actor,
            report=report,
        )

        market.refresh_from_db()
        self.provider_wallet.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.VOIDED,
        )

        self.assertEqual(
            report.voided_market_ids,
            [str(market.id)],
        )
        self.assertEqual(
            report.refunded_market_ids,
            [str(market.id)],
        )

        self.assertEqual(
            self.provider_wallet.available_balance,
            Decimal("1000000.0000"),
        )
        self.assertEqual(
            self.provider_wallet.reserved_balance,
            Decimal("0.0000"),
        )

        self.assertFalse(
            MarketOrder.objects.filter(
                market=market,
                status__in=(
                    MarketOrder.Status.OPEN,
                    MarketOrder.Status.PARTIALLY_FILLED,
                ),
            ).exists()
        )

        self.assertFalse(
            MarketPosition.objects.filter(
                market=market,
            )
            .filter(Q(quantity__gt=0) | Q(reserved_quantity__gt=0) | Q(total_cost__gt=0))
            .exists()
        )

        pool.refresh_from_db()

        self.assertEqual(
            pool.locked_collateral,
            Decimal("0.0000"),
        )

        all_market_ledger_ids = {
            str(value)
            for value in (
                LedgerEntry.objects.filter(
                    market=market,
                ).values_list(
                    "id",
                    flat=True,
                )
            )
        }

        self.assertTrue(original_ledger_ids.issubset(all_market_ledger_ids))

        _delete_market_graph(
            Market,
            {market.id},
            visited={},
            report=report,
        )

        self.assertFalse(
            Market.objects.filter(
                id=market.id,
            ).exists()
        )

        remaining_ledger_ids = {
            str(value)
            for value in (
                LedgerEntry.objects.filter(
                    id__in=all_market_ledger_ids,
                ).values_list(
                    "id",
                    flat=True,
                )
            )
        }

        self.assertEqual(
            remaining_ledger_ids,
            all_market_ledger_ids,
        )

        self.assertFalse(
            LedgerEntry.objects.filter(
                id__in=all_market_ledger_ids,
            )
            .filter(Q(market__isnull=False) | Q(order__isnull=False) | Q(fill__isnull=False))
            .exists()
        )

        self.provider_wallet.refresh_from_db()

        self.assertEqual(
            self.provider_wallet.available_balance,
            Decimal("1000000.0000"),
        )

    def test_resolved_settlement_is_not_refunded_again_before_purge(
        self,
    ):
        market = self.create_market(
            question=("Will settled history be purged?"),
        )

        winner = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        Market.objects.filter(
            pk=market.pk,
        ).update(
            status=Market.Status.RESOLVED,
            winning_outcome=winner,
            resolved_by=self.actor,
            resolved_at=self.now,
            resolution_notes="Resolved.",
            resolution_evidence="Evidence.",
        )

        market.refresh_from_db()

        MarketStatusTransition.objects.create(
            market=market,
            action=(MarketStatusTransition.Action.RESOLVE),
            from_status=Market.Status.CLOSED,
            to_status=Market.Status.RESOLVED,
            actor=self.actor,
            actor_email=self.actor.email,
            notes="Resolved.",
        )

        MarketSettlement.objects.create(
            market=market,
            winning_outcome=winner,
            payout_per_unit=Decimal("1.0000"),
            settlement_currency="UGX",
            executed_by=self.actor,
        )

        report = PurgeReport()

        _unwind_market_if_required(
            market_id=market.id,
            actor=self.actor,
            report=report,
        )

        self.assertEqual(
            report.voided_market_ids,
            [],
        )
        self.assertEqual(
            report.refunded_market_ids,
            [],
        )

        self.assertTrue(
            MarketSettlement.objects.filter(
                market=market,
            ).exists()
        )

        _delete_market_graph(
            Market,
            {market.id},
            visited={},
            report=report,
        )

        self.assertFalse(
            Market.objects.filter(
                id=market.id,
            ).exists()
        )

        self.assertFalse(
            MarketSettlement.objects.filter(
                market_id=market.id,
            ).exists()
        )

        self.assertFalse(
            MarketStatusTransition.objects.filter(
                market_id=market.id,
            ).exists()
        )
