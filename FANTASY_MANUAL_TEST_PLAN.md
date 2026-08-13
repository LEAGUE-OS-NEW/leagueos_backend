# Fantasy manual test plan

Start local Docker, run `python manage.py seed_fantasy_demo_data --confirm` inside `web`, provision roles/accounts explicitly with the existing local bootstrap/admin workflow, and keep browser network tools open.

## 1. Visitor

Open `/fantasy`; confirm three backend competitions. Open each card and verify `/fantasy/{id}`, canonical fixtures, rules, schedule and empty leaderboard state. Refresh; the same records remain. Participation redirects to login. No prizes render when metadata is empty.

## 2. Fan A

Log in and open `/fan/fantasy`. Select each sport and inspect real demo players, clubs, positions and prices. Build a rule-valid team, starters, ordered bench, captain and distinct vice captain; save and refresh. Change lineup and refresh again. Preview then confirm a same-position transfer and verify budget, free transfers, history and persistence. Create public and private leagues; record the backend invite code. Points must say Awaiting statistics.

## 3. Fan B

Create a team in the same competition, refresh, join Fan A's private league by code, and inspect member list/standings. Confirm private league cannot be read anonymously. Leave and refresh; membership remains removed.

## 4. Fantasy Admin

Open `/dashboard/admin/fantasy`. Create/edit using canonical competition and season selectors. Edit Fantasy-only rules. Add a canonical athlete, set position/price/eligibility/availability, assign existing fixtures to a gameweek, add an approved statistic rule, and verify correction requires a real points record and reason. Confirm finalize lifecycle validation. Refresh after each save.

## 5. Sports Data & Statistics Admin

Open `/dashboard/admin/sports-data`; locate a canonical fixture and its match centre. Verify whether the current UI can select a canonical athlete and persist MatchPlayerStatistic. If unavailable, record this as the known PARTIAL step; do not enter statistics through Fantasy. When supported, recalculate from Fantasy admin and verify persisted player/team points and leaderboard after refresh.

## 6. Super Admin

Verify access to Sports Data and Fantasy Admin through the existing General Admin navigation. Repeat one Fantasy edit and confirm it persists. Confirm no separate Super Admin Fantasy role exists and permission denial occurs for an unprivileged fan.
