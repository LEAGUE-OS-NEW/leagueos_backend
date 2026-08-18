from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import SET_NULL

from authentication.services.permission_service import (
    PermissionService,
)

from markets.models import (
    Market,
    MarketCollateralPool,
    MarketOrder,
    MarketPosition,
    MarketSettlement,
)
from markets.services.resolution_service import (
    MarketResolutionService,
)
from markets.services.staging_market_purge_snapshot import (
    KEEPER_IDS,
    PURGE_IDS,
    SNAPSHOT_DIGEST,
    SNAPSHOT_VERSION,
    SOURCE_TOTAL_MARKETS,
)
from markets.services.void_refund_service import (
    MarketVoidRefundService,
)
from wallets.models import (
    DepositIntent,
    LedgerEntry,
    PesapalDeposit,
    Wallet,
    WalletTransaction,
    WithdrawalRequest,
)

CONFIRMATION_PHRASE = "PURGE_42_STAGING_MARKETS_KEEP_4"


class StagingMarketPurgeError(ValueError):
    pass


@dataclass
class PurgeReport:
    deleted_by_model: Counter = field(
        default_factory=Counter,
    )
    preserved_ledger_ids: set[str] = field(
        default_factory=set,
    )
    voided_market_ids: list[str] = field(
        default_factory=list,
    )
    refunded_market_ids: list[str] = field(
        default_factory=list,
    )


def _snapshot_sets():
    keepers = set(KEEPER_IDS)
    purge = set(PURGE_IDS)

    if len(keepers) != 4:
        raise StagingMarketPurgeError("Snapshot must contain exactly four keepers.")

    expected_purge_count = SOURCE_TOTAL_MARKETS - len(keepers)

    if len(purge) != expected_purge_count:
        raise StagingMarketPurgeError(
            "Snapshot purge target count does " "not match SOURCE_TOTAL_MARKETS."
        )

    if keepers & purge:
        raise StagingMarketPurgeError("Keeper and purge UUIDs overlap.")

    if len(keepers | purge) != SOURCE_TOTAL_MARKETS:
        raise StagingMarketPurgeError(
            "Snapshot market count does not " "match SOURCE_TOTAL_MARKETS."
        )

    return keepers, purge


def _wallet_balances(*, lock=False):
    queryset = Wallet.objects.order_by("id")

    if lock:
        queryset = queryset.select_for_update()

    return {
        str(row["id"]): (
            Decimal(row["available_balance"]),
            Decimal(row["reserved_balance"]),
        )
        for row in queryset.values(
            "id",
            "available_balance",
            "reserved_balance",
        )
    }


def _payment_counts():
    return {
        "wallet_transactions": WalletTransaction.objects.count(),
        "deposit_intents": DepositIntent.objects.count(),
        "pesapal_deposits": PesapalDeposit.objects.count(),
        "withdrawal_requests": WithdrawalRequest.objects.count(),
    }


def _ledger_ids():
    return {
        str(value)
        for value in LedgerEntry.objects.values_list(
            "id",
            flat=True,
        )
    }


def _affected_ledger_ids(purge_ids):
    return {
        str(value)
        for value in (
            LedgerEntry.objects.filter(
                Q(
                    market_id__in=purge_ids,
                )
                | Q(
                    order__market_id__in=purge_ids,
                )
                | Q(
                    fill__market_id__in=purge_ids,
                )
            )
            .distinct()
            .values_list(
                "id",
                flat=True,
            )
        )
    }


def _market_has_unsettled_financial_state(
    market_id,
):
    has_live_orders = MarketOrder.objects.filter(
        market_id=market_id,
        status__in=(
            MarketOrder.Status.OPEN,
            MarketOrder.Status.PARTIALLY_FILLED,
        ),
    ).exists()

    has_position_value = (
        MarketPosition.objects.filter(
            market_id=market_id,
        )
        .filter(Q(quantity__gt=0) | Q(reserved_quantity__gt=0) | Q(total_cost__gt=0))
        .exists()
    )

    has_locked_collateral = MarketCollateralPool.objects.filter(
        market_id=market_id,
        locked_collateral__gt=0,
    ).exists()

    return has_live_orders or has_position_value or has_locked_collateral


def _unwind_market_if_required(
    *,
    market_id,
    actor,
    report,
):
    market = Market.objects.select_for_update().get(id=market_id)

    has_unsettled_finance = _market_has_unsettled_financial_state(
        market.id,
    )

    has_settlement = MarketSettlement.objects.filter(
        market=market,
    ).exists()

    if has_settlement:
        if market.status != Market.Status.RESOLVED:
            raise StagingMarketPurgeError(
                "A purge target has a settlement but " "is not RESOLVED: " f"{market.id}"
            )

        return

    if not has_unsettled_finance:
        return

    if market.status == Market.Status.VOIDED:
        refunded = MarketVoidRefundService.refund_void_market(
            market_id=market.id,
            actor=actor,
        )

        report.refunded_market_ids.append(str(refunded.market_id))
        return

    if market.status not in MarketResolutionService.VOIDABLE_STATUSES:
        raise StagingMarketPurgeError(
            "Unsettled financial state cannot be "
            "safely unwound from status "
            f"{market.status}: {market.id}"
        )

    voided = MarketResolutionService.void(
        market_id=market.id,
        actor=actor,
        notes=("Staging-only cleanup of obsolete " "synthetic market data."),
        evidence=("Verified 2026-08-18 staging purge " "snapshot."),
    )

    report.voided_market_ids.append(str(voided.id))

    refunded = MarketVoidRefundService.refund_void_market(
        market_id=voided.id,
        actor=actor,
    )

    report.refunded_market_ids.append(str(refunded.market_id))


def _delete_market_graph(
    model,
    object_ids,
    *,
    visited,
    report,
):
    label = model._meta.label_lower

    already = visited.setdefault(
        label,
        set(),
    )

    pending_ids = {value for value in object_ids if str(value) not in already}

    if not pending_ids:
        return

    queryset = model._base_manager.filter(
        pk__in=pending_ids,
    )

    existing_ids = list(
        queryset.values_list(
            "pk",
            flat=True,
        )
    )

    if not existing_ids:
        return

    already.update(str(value) for value in existing_ids)

    # Market.winning_outcome protects MarketOutcome.
    # Break that forward reference before recursively
    # deleting the market-domain graph.
    if model is Market:
        Market.objects.filter(
            pk__in=existing_ids,
        ).update(
            winning_outcome=None,
        )

    for relation in model._meta.related_objects:
        related_model = relation.related_model
        relation_field = relation.field

        child_queryset = related_model._base_manager.filter(
            **{
                f"{relation_field.name}__in": existing_ids,
            }
        )

        child_ids = list(
            child_queryset.values_list(
                "pk",
                flat=True,
            )
        )

        if not child_ids:
            continue

        child_label = related_model._meta.label_lower

        if child_label == "wallets.ledgerentry":
            if relation_field.remote_field.on_delete is not SET_NULL:
                raise StagingMarketPurgeError(
                    "Ledger relation is not SET_NULL: "
                    f"{label}."
                    f"{relation.get_accessor_name()}"
                )

            report.preserved_ledger_ids.update(str(value) for value in child_ids)
            continue

        if related_model._meta.app_label != "markets":
            raise StagingMarketPurgeError(
                "Unexpected non-market dependency: " f"{label} -> {child_label}"
            )

        _delete_market_graph(
            related_model,
            child_ids,
            visited=visited,
            report=report,
        )

    before = model._base_manager.filter(
        pk__in=existing_ids,
    ).count()

    try:
        model._base_manager.filter(
            pk__in=existing_ids,
        ).delete()
    except Exception as exc:
        raise StagingMarketPurgeError(
            f"Could not purge {label}: " f"{type(exc).__name__}: {exc}"
        ) from exc

    remaining = model._base_manager.filter(
        pk__in=existing_ids,
    ).count()

    if remaining:
        raise StagingMarketPurgeError(f"{label} rows remain after purge.")

    report.deleted_by_model[label] += before


def build_purge_preflight(
    *,
    actor=None,
):
    keepers, purge = _snapshot_sets()

    market_ids = {
        str(value)
        for value in Market.objects.values_list(
            "id",
            flat=True,
        )
    }

    expected_ids = keepers | purge

    unsettled_ids = []

    for market_id in sorted(
        purge & market_ids,
    ):
        if _market_has_unsettled_financial_state(
            market_id,
        ):
            unsettled_ids.append(
                market_id,
            )

    settled_ids = [
        str(value)
        for value in (
            MarketSettlement.objects.filter(
                market_id__in=purge,
            ).values_list(
                "market_id",
                flat=True,
            )
        )
    ]

    settled_set = set(
        settled_ids,
    )

    unsettled_rows = list(
        Market.objects.filter(
            id__in=unsettled_ids,
        ).values(
            "id",
            "status",
            "created_by_id",
        )
    )

    void_required_ids = sorted(
        str(row["id"])
        for row in unsettled_rows
        if (str(row["id"]) not in settled_set and row["status"] != Market.Status.VOIDED)
    )

    actor_creator_conflict_ids = []

    if actor is not None:
        actor_creator_conflict_ids = sorted(
            str(row["id"])
            for row in unsettled_rows
            if (str(row["id"]) in void_required_ids and row["created_by_id"] == actor.id)
        )

    actor_has_resolution_permission = None
    actor_has_refund_permission = None

    if actor is not None:
        actor_has_resolution_permission = PermissionService.has_any_permission(
            actor,
            (MarketResolutionService.RESULT_VERIFICATION_PERMISSIONS),
        )

        actor_has_refund_permission = PermissionService.has_permission(
            actor,
            (MarketVoidRefundService.APPROVE_PERMISSION),
        )

    snapshot_matches = market_ids == expected_ids

    actor_ready = (
        actor is not None
        and actor_has_resolution_permission
        and actor_has_refund_permission
        and not actor_creator_conflict_ids
    )

    can_execute = (
        snapshot_matches
        and len(keepers & market_ids) == 4
        and len(purge & market_ids) == len(purge)
        and actor_ready
    )

    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "snapshot_digest": SNAPSHOT_DIGEST,
        "database_market_count": len(market_ids),
        "snapshot_matches_database": market_ids == expected_ids,
        "keeper_count": len(keepers & market_ids),
        "purge_target_count": len(purge & market_ids),
        "unexpected_market_ids": sorted(
            market_ids - expected_ids,
        ),
        "missing_snapshot_ids": sorted(
            expected_ids - market_ids,
        ),
        "unsettled_financial_market_ids": unsettled_ids,
        "settled_market_ids": sorted(settled_ids),
        "void_required_market_ids": void_required_ids,
        "actor_email": (str(actor.email or "") if actor is not None else ""),
        "actor_creator_conflict_ids": actor_creator_conflict_ids,
        "actor_has_resolution_permission": actor_has_resolution_permission,
        "actor_has_refund_permission": actor_has_refund_permission,
        "can_execute": can_execute,
        "affected_ledger_entry_count": len(
            _affected_ledger_ids(
                purge,
            )
        ),
        "payment_counts": _payment_counts(),
        "ledger_entry_count": LedgerEntry.objects.count(),
    }


@transaction.atomic
def apply_staging_market_purge(
    *,
    actor,
    confirmation,
    snapshot_digest,
):
    if confirmation != CONFIRMATION_PHRASE:
        raise StagingMarketPurgeError("Invalid purge confirmation phrase.")

    if snapshot_digest != SNAPSHOT_DIGEST:
        raise StagingMarketPurgeError("Snapshot digest does not match.")

    keepers, purge = _snapshot_sets()
    expected_ids = keepers | purge

    locked_ids = {
        str(value)
        for value in (
            Market.objects.select_for_update()
            .order_by("id")
            .values_list(
                "id",
                flat=True,
            )
        )
    }

    if locked_ids != expected_ids:
        raise StagingMarketPurgeError(
            "Staging market catalogue changed after " "the purge snapshot. Run a new audit."
        )

    balances_before = _wallet_balances(
        lock=True,
    )
    payments_before = _payment_counts()
    ledger_ids_before = _ledger_ids()

    report = PurgeReport()

    for market_id in sorted(purge):
        _unwind_market_if_required(
            market_id=market_id,
            actor=actor,
            report=report,
        )

    affected_ledger_ids = _affected_ledger_ids(
        purge,
    )

    _delete_market_graph(
        Market,
        purge,
        visited={},
        report=report,
    )

    remaining_ids = {
        str(value)
        for value in Market.objects.values_list(
            "id",
            flat=True,
        )
    }

    if remaining_ids != keepers:
        raise StagingMarketPurgeError(
            "Final market set is not exactly " "the four audited keepers."
        )

    if Market.objects.count() != 4:
        raise StagingMarketPurgeError("Expected exactly four markets after purge.")

    payments_after = _payment_counts()

    if payments_after != payments_before:
        raise StagingMarketPurgeError(
            "Deposit, Pesapal, withdrawal, or wallet " "transaction row counts changed."
        )

    ledger_ids_after = _ledger_ids()

    if not ledger_ids_before.issubset(
        ledger_ids_after,
    ):
        raise StagingMarketPurgeError("An existing wallet ledger row was deleted.")

    balances_after = _wallet_balances()

    if set(balances_after) != set(balances_before):
        raise StagingMarketPurgeError("Wallet rows changed during purge.")

    for wallet_id, before in balances_before.items():
        after = balances_after[wallet_id]

        before_total = before[0] + before[1]
        after_total = after[0] + after[1]

        if after_total < before_total:
            raise StagingMarketPurgeError("A wallet lost total value during " f"purge: {wallet_id}")

        if after[0] < 0 or after[1] < 0:
            raise StagingMarketPurgeError("A wallet became negative during " f"purge: {wallet_id}")

    if affected_ledger_ids:
        remaining_ledger_ids = {
            str(value)
            for value in (
                LedgerEntry.objects.filter(
                    id__in=affected_ledger_ids,
                ).values_list(
                    "id",
                    flat=True,
                )
            )
        }

        if remaining_ledger_ids != affected_ledger_ids:
            raise StagingMarketPurgeError("A market-related wallet ledger row " "was deleted.")

    still_linked = (
        LedgerEntry.objects.filter(
            id__in=ledger_ids_after,
        )
        .filter(
            Q(market_id__in=purge) | Q(order__market_id__in=purge) | Q(fill__market_id__in=purge)
        )
        .exists()
    )

    if still_linked:
        raise StagingMarketPurgeError(
            "A preserved ledger entry still points " "to purged market-domain data."
        )

    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "snapshot_digest": SNAPSHOT_DIGEST,
        "deleted_market_count": len(purge),
        "remaining_market_count": 4,
        "voided_market_count": len(
            report.voided_market_ids,
        ),
        "refunded_market_count": len(
            report.refunded_market_ids,
        ),
        "preserved_existing_ledger_count": len(
            ledger_ids_before,
        ),
        "new_ledger_entry_count": len(
            ledger_ids_after - ledger_ids_before,
        ),
        "wallets_never_lost_value": True,
        "payment_rows_unchanged": True,
        "deleted_by_model": dict(sorted(report.deleted_by_model.items())),
    }
