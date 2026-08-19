"""Celery tasks for market lifecycle automation."""

from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def close_due_markets():
    """Close every OPEN/SUSPENDED market whose closes_at has passed.

    closes_at already blocks new order placement/matching on its own — this
    is only about keeping Market.status accurate once trading has stopped,
    not a trading-integrity race. Per-item try/except so one bad market
    doesn't block the rest of the sweep.
    """
    from accounts.models import User
    from markets.management.commands.bootstrap_market_automation_actor import (
        AUTOMATION_ACTOR_EMAIL,
    )
    from markets.models import Market
    from markets.services.lifecycle_service import MarketLifecycleService

    actor = User.objects.filter(email=AUTOMATION_ACTOR_EMAIL).first()
    if actor is None:
        logger.error(
            "Market automation actor not found (%s) — run "
            "'python manage.py bootstrap_market_automation_actor' before this task can run.",
            AUTOMATION_ACTOR_EMAIL,
        )
        return

    due_markets = Market.objects.filter(
        status__in=[Market.Status.OPEN, Market.Status.SUSPENDED],
        closes_at__lte=timezone.now(),
    )
    for market in due_markets:
        try:
            MarketLifecycleService.close(
                market_id=market.id,
                actor=actor,
                notes="Automatically closed at scheduled closes_at.",
            )
        except Exception:
            logger.exception("Failed to auto-close market %s", market.id)
