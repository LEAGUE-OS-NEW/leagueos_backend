# Fantasy operations

Fantasy owns competition rules, player eligibility/prices, squads, gameweeks, leagues, transfers, and scores. It references canonical `Sport`, `Competition`, `Season`, athlete `Participant`, `PlayerProfile.club`, `SportingEvent`, and match-centre statistics; it never creates those records.

Fantasy Admin permissions are split across competition configuration, player pools, scoring, and finalization. `platform.fantasy.manage` remains the broad override and Super Admin inherits through existing RBAC.

Local Docker commands:

```console
docker compose exec -T web python manage.py migrate
docker compose exec -T web python manage.py seed_fantasy_demo_data --confirm
docker compose exec -T web python manage.py transition_fantasy_gameweeks --dry-run
docker compose exec -T web python manage.py transition_fantasy_gameweeks
```

The transition command safely opens drafts, locks at deadline, moves started gameweeks live, and moves completed-fixture gameweeks to scoring. Finalization is explicit. Run it every minute with a Render cron/worker scheduler. Recalculation rebuilds player and team scores from authoritative statistics, preserves the latest audited correction, and applies the stored gameweek transfer penalty once.

Draft gameweeks open only when `starts_at` has arrived. The command is idempotent and `--dry-run` reports without writing. It never finalizes a gameweek.

Corrections require a reason and actor and are immutable through the product API. Conditional scoring rules are rejected until semantics are approved. Auto-substitution is not applied because current match-lineup data does not reliably distinguish unused substitutes across every sport; the UI must show awaiting participation/statistics rather than infer it. Prize metadata is descriptive only and does not imply automated wallet payout.

Sports Data currently has no statistic-definition/provider-mapping catalogue. Fantasy therefore owns a minimal approved, sport-specific definition map for Football, Rugby, and Basketball whose keys match imported `MatchPlayerStatistic.stat_type` provider keys. Admins can configure those approved definitions before fixtures are played; observed historical values are discovery metadata only and arbitrary free text is rejected. The seed command creates rules from definitions and never fabricates match statistics. Player candidate scoping proves ATHLETE role and sport. The current canonical domain has no reliable competition/season roster registration relation, so membership cannot be asserted beyond those facts without duplicating or inventing registration logic.

Rankings apply supported `tie_break_rules` in configured order: `total_points` descending, `fewer_transfer_penalties` ascending, and `earlier_registration` ascending. Unsupported `gameweek_points` was removed because it was not an independent value. Team UUID is the deterministic final tie breaker. Competition, gameweek, and fan-league ranking use the same implementation.

Fantasy events use the existing `FANTASY_TEAM_UPDATES` notification category. Transfer saves, league joins, scoring finalization, and scoring corrections create idempotent inbox notifications when that category is seeded. Approaching-deadline notifications are not emitted: no approved Fantasy scheduling rule exists beyond the lifecycle command.
