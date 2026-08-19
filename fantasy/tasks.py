"""Celery tasks for the Fantasy app.

Automatic scoring bridge
------------------------
When a sports-data feed ingestion completes and contains player statistics,
``score_affected_gameweeks`` is dispatched via ``transaction.on_commit()``
from ``SportsFeedService.complete_ingestion()``.

The task:
1. Resolves every FantasyGameweek that contains any of the affected fixtures.
2. Skips FINALIZED gameweeks (they may only be re-scored via the manual
   admin correction flow).
3. Calls the existing ``score_gameweek()`` function once per affected
   gameweek — no duplicate scoring logic is introduced here.
4. Is fully idempotent: ``score_gameweek()`` uses ``get_or_create`` /
   ``update_or_create`` internally, so repeated execution is safe.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

try:
    from celery import shared_task
    from celery.exceptions import MaxRetriesExceededError
except ImportError:  # Celery not installed (e.g. test environments without broker)
    MaxRetriesExceededError = Exception  # type: ignore[misc,assignment]

    def shared_task(*args, **kwargs):  # type: ignore[misc]
        """Minimal no-op decorator so the module imports cleanly without Celery."""
        bind = kwargs.get("bind", False)

        def decorator(func):
            def bound_func(self, *a, **kw):
                return func(self, *a, **kw)

            def unbound_func(*a, **kw):
                return func(*a, **kw)

            def delay_func(*a, **kw):
                if bind:
                    return func(None, *a, **kw)
                return func(*a, **kw)

            def apply_async_func(args=(), kwargs=None, **kw):
                if kwargs is None:
                    kwargs = {}
                if bind:
                    return func(None, *args, **{**kwargs, **kw})
                return func(*args, **{**kwargs, **kw})

            wrapped = bound_func if bind else unbound_func
            wrapped.delay = delay_func
            wrapped.apply_async = apply_async_func
            return wrapped

        if len(args) == 1 and callable(args[0]):
            return decorator(args[0])
        return decorator


logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="fantasy.tasks.score_affected_gameweeks",
)
def score_affected_gameweeks(self, fixture_ids: Sequence[str]) -> dict:
    """Score every non-finalised FantasyGameweek that contains the given fixtures.

    Parameters
    ----------
    fixture_ids:
        List of ``SportingEvent`` UUID strings that were part of a completed
        feed ingestion batch.  String UUIDs are used (not UUID objects) because
        Celery serialises task arguments to JSON.

    Returns
    -------
    dict
        Summary with keys ``scored``, ``skipped_finalized``, ``no_gameweek``,
        and ``fixture_ids``.  Useful for logging and test assertions.
    """
    # Late imports keep the module importable even if the app registry is not
    # fully initialised when the module is first loaded by Celery's autodiscovery.
    from fantasy.models import FantasyGameweek
    from fantasy.services import score_gameweek

    if not fixture_ids:
        logger.info("score_affected_gameweeks: called with empty fixture_ids list — nothing to do.")
        return {"scored": 0, "skipped_finalized": 0, "no_gameweek": 0, "fixture_ids": []}

    logger.info(
        "score_affected_gameweeks: received %d fixture(s): %s",
        len(fixture_ids),
        fixture_ids,
    )

    try:
        # Find all FantasyGameweeks that contain at least one of the affected fixtures.
        # Using __in on the M2M relation; .distinct() prevents duplicates when a
        # gameweek contains multiple affected fixtures.
        candidate_gameweeks = (
            FantasyGameweek.objects.filter(fixtures__id__in=fixture_ids)
            .select_related("fantasy_competition")
            .distinct()
        )

        gameweek_ids = list(candidate_gameweeks.values_list("id", flat=True))
        logger.info(
            "score_affected_gameweeks: discovered %d gameweek(s) for the affected fixtures: %s",
            len(gameweek_ids),
            [str(gid) for gid in gameweek_ids],
        )

        if not gameweek_ids:
            logger.info(
                "score_affected_gameweeks: no FantasyGameweek is linked to the affected "
                "fixtures — skipping scoring."
            )
            return {
                "scored": 0,
                "skipped_finalized": 0,
                "no_gameweek": len(fixture_ids),
                "fixture_ids": list(fixture_ids),
            }

        scored_count = 0
        skipped_count = 0

        for gameweek in candidate_gameweeks:
            if gameweek.status == FantasyGameweek.Status.FINALIZED:
                logger.info(
                    "score_affected_gameweeks: skipping FINALIZED gameweek %s (%s).",
                    gameweek.id,
                    gameweek.name,
                )
                skipped_count += 1
                continue

            logger.info(
                "score_affected_gameweeks: scoring gameweek %s (%s) — status=%s.",
                gameweek.id,
                gameweek.name,
                gameweek.status,
            )
            score_gameweek(gameweek)
            scored_count += 1
            logger.info(
                "score_affected_gameweeks: completed scoring for gameweek %s (%s).",
                gameweek.id,
                gameweek.name,
            )

        logger.info(
            "score_affected_gameweeks: finished — scored=%d, skipped_finalized=%d.",
            scored_count,
            skipped_count,
        )
        return {
            "scored": scored_count,
            "skipped_finalized": skipped_count,
            "no_gameweek": 0,
            "fixture_ids": list(fixture_ids),
        }

    except Exception as exc:
        logger.exception(
            "score_affected_gameweeks: unexpected error for fixture_ids=%s: %s",
            fixture_ids,
            exc,
        )
        raise self.retry(exc=exc) from None
