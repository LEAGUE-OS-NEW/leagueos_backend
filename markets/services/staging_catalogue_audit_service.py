from collections import Counter

from django.core.exceptions import ObjectDoesNotExist
from django.db.models.deletion import PROTECT

from markets.models import Market

CANONICAL_QUESTIONS = (
    "Will Vipers SC beat KCCA FC?",
    "Will Vipers SC vs KCCA FC have over 2.5 goals?",
    "Will KOBS Rugby Club beat Platinum Credit Heathens?",
    "Will City Oilers beat Namuwongo Blazers?",
)

HISTORICAL_STATUSES = {
    Market.Status.CLOSED,
    Market.Status.RESOLVED,
    Market.Status.VOIDED,
    Market.Status.REJECTED,
}


def _optional_related(instance, attribute):
    try:
        return getattr(instance, attribute)
    except ObjectDoesNotExist:
        return None


def _relation_count(market, relation):
    accessor = relation.get_accessor_name()

    try:
        value = getattr(market, accessor)
    except ObjectDoesNotExist:
        return 0

    if relation.one_to_one:
        return 1

    try:
        return value.count()
    except AttributeError:
        return 0


def _market_history(market):
    liquidity = _optional_related(
        market,
        "liquidity_configuration",
    )
    collateral_pool = _optional_related(
        market,
        "collateral_pool",
    )
    settlement = _optional_related(
        market,
        "settlement",
    )

    return {
        "order_count": market.orders.count(),
        "fill_count": market.fills.count(),
        "position_count": market.positions.count(),
        "complete_set_issuance_count": (market.complete_set_issuances.count()),
        "collateral_entry_count": (market.collateral_entries.count()),
        "status_transition_count": (market.status_transitions.count()),
        "watchlist_count": market.watchlist_entries.count(),
        "recent_view_count": market.recent_views.count(),
        "has_liquidity_configuration": liquidity is not None,
        "liquidity_status": (liquidity.status if liquidity is not None else ""),
        "initial_liquidity_ugx": (
            liquidity.initial_liquidity_ugx if liquidity is not None else None
        ),
        "has_collateral_pool": collateral_pool is not None,
        "locked_collateral": (
            collateral_pool.locked_collateral if collateral_pool is not None else None
        ),
        "has_settlement": settlement is not None,
    }


def _classification(market, question_counts):
    if market.question in CANONICAL_QUESTIONS:
        if question_counts[market.question] > 1:
            return "CANONICAL_CANDIDATE"
        return "KEEP_CANONICAL"

    if market.status in HISTORICAL_STATUSES:
        return "HIDE_HISTORICAL"

    return "HIDE_NONCANONICAL"


def _deletion_safety(market):
    blockers = []

    for relation in Market._meta.related_objects:
        count = _relation_count(
            market,
            relation,
        )

        if not count:
            continue

        accessor = relation.get_accessor_name()
        on_delete = relation.field.remote_field.on_delete
        on_delete_name = getattr(
            on_delete,
            "__name__",
            str(on_delete),
        )

        reason = None

        if on_delete is PROTECT:
            reason = "PROTECTED_RELATION"
        elif accessor == "ledger_entries":
            # LedgerEntry uses SET_NULL, but deleting the market
            # would remove the market reference from financial history.
            reason = "FINANCIAL_LEDGER_HISTORY"
        elif accessor == "status_transitions":
            # Status transitions use CASCADE, but are immutable
            # lifecycle/audit evidence that we do not want to erase.
            reason = "LIFECYCLE_AUDIT_HISTORY"

        if reason:
            blockers.append(
                {
                    "accessor": accessor,
                    "model": (relation.related_model._meta.label),
                    "on_delete": on_delete_name,
                    "count": count,
                    "reason": reason,
                }
            )

    reasons = {blocker["reason"] for blocker in blockers}

    if "PROTECTED_RELATION" in reasons:
        deletion_safety = "PRESERVE_PROTECTED_HISTORY"
    elif "FINANCIAL_LEDGER_HISTORY" in reasons:
        deletion_safety = "PRESERVE_FINANCIAL_HISTORY"
    elif "LIFECYCLE_AUDIT_HISTORY" in reasons:
        deletion_safety = "PRESERVE_LIFECYCLE_HISTORY"
    else:
        deletion_safety = "DELETE_CANDIDATE"

    return {
        "deletion_safety": deletion_safety,
        "deletion_blockers": blockers,
    }


def build_staging_market_catalogue_audit():
    markets = list(
        Market.objects.select_related(
            "sport",
            "category",
            "liquidity_configuration",
            "collateral_pool",
            "settlement",
        ).order_by(
            "-created_at",
            "-id",
        )
    )

    question_counts = Counter(
        market.question for market in markets if market.question in CANONICAL_QUESTIONS
    )

    rows = []

    for market in markets:
        deletion = _deletion_safety(
            market,
        )

        rows.append(
            {
                "id": market.id,
                "question": market.question,
                "sport": market.sport.code,
                "category": market.category.name,
                "status": market.status,
                "is_featured": market.is_featured,
                "is_catalog_visible": (market.is_catalog_visible),
                "created_at": market.created_at,
                "classification": _classification(
                    market,
                    question_counts,
                ),
                "deletion_safety": deletion["deletion_safety"],
                "deletion_blockers": deletion["deletion_blockers"],
                "history": _market_history(market),
            }
        )

    summary = Counter(row["classification"] for row in rows)

    deletion_summary = Counter(row["deletion_safety"] for row in rows)

    canonical_groups = []

    for question in CANONICAL_QUESTIONS:
        candidates = [row for row in rows if row["question"] == question]

        canonical_groups.append(
            {
                "question": question,
                "candidate_count": len(candidates),
                "candidate_ids": [row["id"] for row in candidates],
                "needs_keeper_selection": (len(candidates) > 1),
            }
        )

    return {
        "canonical_questions": list(CANONICAL_QUESTIONS),
        "total_markets": len(rows),
        "summary": dict(summary),
        "deletion_summary": dict(deletion_summary),
        "canonical_groups": canonical_groups,
        "rows": rows,
    }
