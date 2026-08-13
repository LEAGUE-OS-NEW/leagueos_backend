# Fantasy Existing Capability Audit

Audit date: 2026-08-12. Audited branches: backend `feature/fantasy-leagues-completion` at `ee6ef8f` (base `develop`), frontend `feature/fantasy-leagues-completion` at `d57128d` (base `development`). Both worktrees were clean and on the required branches before this file was created.

## A. Existing backend Fantasy functionality

There is no backend Fantasy app, persisted Fantasy domain, Fantasy URL configuration, or Fantasy REST API. The only explicit Fantasy backend support is notification catalogue metadata in `notifications/management/commands/seed_notification_data.py` (`FANTASY_COMPETITIONS` and `FANTASY_TEAM_UPDATES`). `config/settings.py` mentions fantasy only in the OpenAPI description.

## B. Existing frontend Fantasy functionality

- Public presentation: `src/pages/fantasy/Fantasy.tsx` and `src/pages/fantasy/sections/*`; landing cards in `src/pages/landing/sections/FantasyLeagues.tsx`.
- Fan experience: `src/pages/fan/fantasy/FantasyCompetitions.tsx` plus `src/pages/fan/fantasy/section/*`. It contains competition browsing, squad selection, sport-specific lineup surfaces, captain/vice captain selection, transfers, gameweek display, live-points presentation, league creation/join UI, notifications, and standings.
- Admin experience: `src/pages/admin/fantasy/FantasyAdminPage.tsx` supports in-memory player and league creation.
- Shared in-memory service: `src/services/fantasyAdminService.ts`.
- Routes in `src/App.tsx`: `/fantasy`, `/fan/fantasy`, and `/dashboard/admin/fantasy`.

These are UI prototypes, not durable product workflows.

## C-D. Shared domain/infrastructure Fantasy must reuse

- Sports: `sports/models.py::Sport`.
- Real competitions: `sports/models.py::Competition`.
- Real participants (teams and athletes): `sports/models.py::Participant`.
- Canonical fixtures/events and participants: `sports/models.py::SportingEvent`, `EventParticipant`.
- Seasons: `discovery/models.py::Season`.
- Clubs: `profiles/models.py::Club`; public extensions in `discovery/models.py::ClubProfile`; club-admin workspace/content in `clubs/models.py`.
- Players: athlete `sports.models.Participant` records with `discovery/models.py::PlayerProfile` for club, position, number, availability, biography, and season.
- Results/statistics: `discovery/models.py::MatchCentre`, `MatchLineup`, `MatchPlayerStatistic`, `MatchTeamStatistic`, and `MatchTimelineEvent`. Public access and aggregation exist in `discovery/views.py`, `discovery/serializers.py`, and `discovery/services/match_centre_service.py`.
- Fixture discovery: `discovery/services/fixture_service.py`, `discovery/views.py`, and `discovery/urls.py`.
- Notifications: models and delivery/policy services under `notifications/`, especially `notifications/services/notification_service.py` and the existing Fantasy preference categories in `notifications/management/commands/seed_notification_data.py`.
- Permissions/RBAC: `authentication/models.py` (`Permission`, `Role`, `UserRole`, `UserPermission`), `authentication/services/permission_service.py`, `authentication/permissions.py`, and role administration under `platform_admin/`.
- Wallet/rewards: auditable wallet and ledger models/services in `wallets/models.py` and `wallets/services/`. No approved Fantasy prize-settlement workflow exists.

## E. Existing Fantasy-related database models

None. Notification categories are generic notification records rather than Fantasy domain models.

## F. Existing Fantasy endpoints

None. Existing public sports endpoints under `discovery/urls.py` expose competitions, fixtures/results, player/club discovery, and match-centre statistics that Fantasy should consume internally or compose.

## G. Existing Fantasy admin workflows

`src/pages/admin/fantasy/FantasyAdminPage.tsx` can add mock players and mock competition/league cards through `src/services/fantasyAdminService.ts`. Changes last only for the JavaScript module lifetime. There are no gameweek, fixture-assignment, scoring, correction, finalization, or durable moderation APIs.

## H. Existing Fan Fantasy workflows

`src/pages/fan/fantasy/FantasyCompetitions.tsx` implements a broad interactive prototype: browse/select competition, choose squad, configure lineup/captain/vice captain, simulate transfers, create/join leagues, show gameweek fixtures, standings, notifications, corrections, and live points. All business state is React/module memory and is lost on reload/relogin.

## I. Existing public Fantasy workflows

`src/pages/fantasy/*` and `src/pages/landing/sections/FantasyLeagues.tsx` render landing content, featured leagues, leaderboard, gameweeks, tips/statistics, and prizes. The business records are hardcoded and no competition detail API workflow exists.

## J. Existing hardcoded/in-memory Fantasy data

- `src/services/fantasyAdminService.ts`: nine competitions/leagues, football/rugby/basketball player pools, generated IDs, delayed fake async persistence, prices, expected points, manager counts, prizes, and rules.
- `src/pages/fan/fantasy/FantasyCompetitions.tsx`: `SQUAD_RULES`, `SCORING_EXAMPLES`, `SEASON`, `FIXTURES`, `STANDINGS`, `CORRECTIONS`, `INITIAL_NOTIFICATIONS`, random invite codes/member counts, local squads, transfers, lineup, team, and league membership state.
- `src/pages/fan/fantasy/section/LivePointsPanel.tsx`: deterministic simulated scoring event pools.
- `src/pages/fantasy/sections/FeaturedLeagues.tsx`, `FeaturedLeaderboard.tsx`, `UpcomingGameweeks.tsx`, and `PrizesBanner.tsx`: public business-data mocks.
- `src/pages/landing/sections/FantasyLeagues.tsx`: featured Fantasy business-data cards.

Layout coordinates, labels, icons, sport names, and formation display metadata are legitimate UI constants, not business records.

## K. Existing tests

No backend Fantasy tests and no focused frontend Fantasy tests exist. Shared sports/discovery behavior is tested in `sports/tests/` and `discovery/tests/`, including canonical fixture reuse, public fixtures/results, match lineups, and player statistics.

## L. Local/remote branch and history findings

- Backend local and remote history contains no Fantasy implementation. The feature branch equals `develop`/`origin/develop` at audit start.
- Frontend Fantasy commits including `606eef5` (admin Fantasy), `e4c8242`, and `1fdd3f7` (integrated Fantasy module) are ancestors of the current `development` state; `origin/feature/my-work` contains no additional unmerged Fantasy solution beyond what is already present.
- No local branch contains a separate persisted Fantasy backend or a newer complete Fantasy frontend.

## M. Preserved Markets/KYC patch overlap (read-only inspection)

Inspected only as text: `../_wip_snapshots/2026-08-12-markets-pricing-kyc/backend-complete-stash.patch` and `frontend-complete-stash.patch`. They were not applied or modified.

### Already solved in current bases

The current repositories already contain the shared foundations the patches build on: canonical sports/competitions/events, RBAC permission service, notification delivery, wallet ledger/reservation services, market lifecycle/settlement/void services, baseline KYC sessions/callbacks/compliance views, market order book/pricing APIs, and frontend API/auth/market service conventions. Some current settings and KYC/compliance structures overlap conceptually with patch edits, so a later restoration must re-diff rather than blindly apply.

### Genuinely missing from current bases

The preserved backend patch adds Markets-only manual KYC identity submissions/evidence and admin decisions, quote-summary endpoints, collateral-backed opening liquidity (`MarketLiquidityProvision`), liquidity readiness/transition commands, lifecycle gates, and related tests/operations documentation. The frontend patch adds the corresponding market quote display, liquidity/admin pricing changes, manual KYC evidence flow, compliance administration, and pricing normalization. These are not Fantasy dependencies.

### Conflicting approaches / changes that should not later be blindly restored

- Do not restore the patch wholesale: it edits files that have continued evolving on the current base, including `config/settings.py`, `markets/models.py`, lifecycle/settlement/void services, URLs, admin views, frontend market pages, wallet UI, and identity stores.
- Do not restore patch versions of shared RBAC, wallet, notification, sports, or authentication concepts over current implementations; port only the smallest still-missing Markets behavior against the then-current contracts.
- Do not restore generated/static pricing fallbacks or client-side identity state where current live API/store behavior is newer.
- Do not introduce `MarketLiquidityProvision`, new KYC evidence models, or quote APIs on this Fantasy branch. No Fantasy implementation should depend on them.

## Audit conclusion

Fantasy must be implemented as a new Fantasy-specific backend domain referencing the existing `sports`, `discovery`, accounts/RBAC, and notification records. It must replace the frontend prototypes' module/React business persistence with genuine REST APIs. Monetary prize payout remains an explicit product dependency unless a separately approved Fantasy-to-wallet settlement contract is supplied.
