from django.db import transaction

from markets.models import (
    Market,
    MarketLiquidityConfiguration,
)
from markets.services.staging_catalogue_audit_service import (
    CANONICAL_QUESTIONS,
    build_staging_market_catalogue_audit,
)
from markets.services.staging_catalogue_cleanup_snapshot import (
    CONFIG_ONLY_DELETE_IDS,
    DIRECT_DELETE_IDS,
    HIDE_IDS,
    KEEPER_IDS,
    SNAPSHOT_VERSION,
    SOURCE_TOTAL_MARKETS,
)

CONFIRMATION_PHRASE = "APPLY_STAGING_MARKET_CLEANUP_59_TO_40"


class StagingCatalogueCleanupError(ValueError):
    pass


def _sets():
    keepers = set(KEEPER_IDS)
    direct = set(DIRECT_DELETE_IDS)
    config_only = set(CONFIG_ONLY_DELETE_IDS)
    hidden = set(HIDE_IDS)

    groups = (
        keepers,
        direct,
        config_only,
        hidden,
    )

    combined = set()

    for group in groups:
        if combined & group:
            raise StagingCatalogueCleanupError("Cleanup snapshot groups overlap.")
        combined |= group

    if len(keepers) != 4:
        raise StagingCatalogueCleanupError("Cleanup snapshot must contain four keepers.")

    if len(combined) != SOURCE_TOTAL_MARKETS:
        raise StagingCatalogueCleanupError(
            "Cleanup snapshot size does not match " "the audited source total."
        )

    return keepers, direct, config_only, hidden


def _history_is_empty(row):
    history = row["history"]

    count_fields = (
        "order_count",
        "fill_count",
        "position_count",
        "complete_set_issuance_count",
        "collateral_entry_count",
        "status_transition_count",
        "watchlist_count",
        "recent_view_count",
    )

    return (
        all(history[field] == 0 for field in count_fields)
        and not history["has_collateral_pool"]
        and not history["has_settlement"]
    )


def _validate_keeper_rows(rows, keeper_ids):
    missing = keeper_ids - set(rows)

    if missing:
        raise StagingCatalogueCleanupError("One or more keeper markets are missing.")

    questions = {rows[market_id]["question"] for market_id in keeper_ids}

    if questions != set(CANONICAL_QUESTIONS):
        raise StagingCatalogueCleanupError(
            "Keeper snapshot no longer maps one-to-one " "to the four canonical questions."
        )


def _validate_direct_delete_rows(
    rows,
    direct_ids,
):
    for market_id in direct_ids:
        row = rows.get(market_id)

        if row is None:
            raise StagingCatalogueCleanupError(f"Direct-delete market missing: {market_id}")

        history = row["history"]

        safe = (
            row["status"] == Market.Status.DRAFT
            and row["deletion_safety"] == "DELETE_CANDIDATE"
            and row["deletion_blockers"] == []
            and _history_is_empty(row)
            and not history["has_liquidity_configuration"]
        )

        if not safe:
            raise StagingCatalogueCleanupError(
                "Direct-delete market changed after audit: " f"{market_id}"
            )


def _validate_config_only_rows(
    rows,
    config_only_ids,
):
    for market_id in config_only_ids:
        row = rows.get(market_id)

        if row is None:
            raise StagingCatalogueCleanupError("Config-only delete market missing: " f"{market_id}")

        history = row["history"]

        blocker_accessors = {blocker["accessor"] for blocker in row["deletion_blockers"]}

        safe = (
            row["status"] == Market.Status.DRAFT
            and blocker_accessors == {"liquidity_configuration"}
            and _history_is_empty(row)
            and history["has_liquidity_configuration"]
        )

        if not safe:
            raise StagingCatalogueCleanupError(
                "Config-only delete market changed " f"after audit: {market_id}"
            )


def _final_state(
    *,
    keeper_ids,
    hidden_ids,
):
    keeper_visible = Market.objects.filter(
        id__in=keeper_ids,
        is_catalog_visible=True,
    ).count()

    hidden_visible = Market.objects.filter(
        id__in=hidden_ids,
        is_catalog_visible=True,
    ).count()

    return keeper_visible, hidden_visible


@transaction.atomic
def apply_staging_catalogue_cleanup(
    *,
    confirmation,
):
    if confirmation != CONFIRMATION_PHRASE:
        raise StagingCatalogueCleanupError("Invalid cleanup confirmation phrase.")

    (
        keeper_ids,
        direct_ids,
        config_only_ids,
        hidden_ids,
    ) = _sets()

    deletion_ids = direct_ids | config_only_ids

    preserved_ids = keeper_ids | hidden_ids

    snapshot_ids = preserved_ids | deletion_ids

    locked_existing_ids = {
        str(value)
        for value in (
            Market.objects.select_for_update()
            .filter(
                id__in=snapshot_ids,
            )
            .values_list(
                "id",
                flat=True,
            )
        )
    }

    existing_preserved = locked_existing_ids & preserved_ids

    if existing_preserved != preserved_ids:
        raise StagingCatalogueCleanupError("One or more preserved snapshot markets " "are missing.")

    existing_deletion_ids = locked_existing_ids & deletion_ids

    global_total_before = Market.objects.count()

    if not existing_deletion_ids:
        keeper_visible, hidden_visible = _final_state(
            keeper_ids=keeper_ids,
            hidden_ids=hidden_ids,
        )

        if keeper_visible == 4 and hidden_visible == 0:
            return {
                "snapshot_version": SNAPSHOT_VERSION,
                "already_applied": True,
                "global_total_before": (global_total_before),
                "global_total_after": (global_total_before),
                "deleted_market_count": 0,
                "deleted_liquidity_configuration_count": 0,
                "newly_hidden_count": 0,
                "newly_visible_keeper_count": 0,
                "snapshot_remaining_count": 40,
                "snapshot_visible_count": 4,
            }

        raise StagingCatalogueCleanupError(
            "Deletion snapshot is already absent but "
            "visibility state is not final. Manual "
            "review is required."
        )

    if existing_deletion_ids != deletion_ids:
        raise StagingCatalogueCleanupError(
            "Cleanup snapshot is partially applied. " "Manual review is required."
        )

    audit = build_staging_market_catalogue_audit()

    rows = {str(row["id"]): row for row in audit["rows"]}

    _validate_keeper_rows(
        rows,
        keeper_ids,
    )
    _validate_direct_delete_rows(
        rows,
        direct_ids,
    )
    _validate_config_only_rows(
        rows,
        config_only_ids,
    )

    config_count = MarketLiquidityConfiguration.objects.filter(
        market_id__in=config_only_ids,
    ).count()

    if config_count != len(config_only_ids):
        raise StagingCatalogueCleanupError(
            "Expected exactly one disposable liquidity "
            "configuration for every config-only "
            "delete market."
        )

    MarketLiquidityConfiguration.objects.filter(
        market_id__in=config_only_ids,
    ).delete()

    if MarketLiquidityConfiguration.objects.filter(
        market_id__in=config_only_ids,
    ).exists():
        raise StagingCatalogueCleanupError(
            "Disposable liquidity configuration " "deletion did not complete."
        )

    delete_target_count = Market.objects.filter(
        id__in=deletion_ids,
    ).count()

    if delete_target_count != 19:
        raise StagingCatalogueCleanupError("Expected exactly 19 market deletion " "targets.")

    Market.objects.filter(
        id__in=deletion_ids,
    ).delete()

    if Market.objects.filter(
        id__in=deletion_ids,
    ).exists():
        raise StagingCatalogueCleanupError("One or more deletion targets remain.")

    newly_hidden_count = Market.objects.filter(
        id__in=hidden_ids,
        is_catalog_visible=True,
    ).update(
        is_catalog_visible=False,
    )

    newly_visible_keeper_count = Market.objects.filter(
        id__in=keeper_ids,
        is_catalog_visible=False,
    ).update(
        is_catalog_visible=True,
    )

    keeper_visible, hidden_visible = _final_state(
        keeper_ids=keeper_ids,
        hidden_ids=hidden_ids,
    )

    if keeper_visible != 4:
        raise StagingCatalogueCleanupError(
            "Cleanup invariant failed: all four " "keepers must remain catalogue-visible."
        )

    if hidden_visible != 0:
        raise StagingCatalogueCleanupError(
            "Cleanup invariant failed: preserved " "legacy markets remain catalogue-visible."
        )

    snapshot_remaining_count = Market.objects.filter(
        id__in=preserved_ids,
    ).count()

    if snapshot_remaining_count != 40:
        raise StagingCatalogueCleanupError(
            "Cleanup invariant failed: expected " "40 snapshot markets to remain."
        )

    global_total_after = Market.objects.count()

    if global_total_after != global_total_before - 19:
        raise StagingCatalogueCleanupError(
            "Cleanup invariant failed: global market " "count did not decrease by exactly 19."
        )

    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "already_applied": False,
        "global_total_before": global_total_before,
        "global_total_after": global_total_after,
        "deleted_market_count": 19,
        "deleted_liquidity_configuration_count": (config_count),
        "newly_hidden_count": newly_hidden_count,
        "newly_visible_keeper_count": (newly_visible_keeper_count),
        "snapshot_remaining_count": (snapshot_remaining_count),
        "snapshot_visible_count": keeper_visible,
    }
