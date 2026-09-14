# League OS Fantasy Scoring Specification & Implementation Plan

> Produced: 2026-08-21
> Basis: Live codebase inspection — NO code was modified.
> Status: SPECIFICATION ONLY — awaiting review before implementation.

---

## TABLE OF CONTENTS

1. Part 1 — Complete Scoring Pipeline Trace
2. Part 2 — Match Statistics vs Player Points vs Fan Team Points
3. Part 3 — Scoring Rule System Design
4. Part 4 — Multi-Sport Design
5. Part 5 — Position-Specific Scoring
6. Part 6 — Threshold Scoring
7. Part 7 — Player Points Breakdown
8. Part 8 — Fan-Side Experience
9. Part 9 — Admin-Side Experience
10. Part 10 — Gameweek Scoring Lifecycle
11. Part 11 — Real Fantasy Application Comparison
12. Part 12 — Auto-Substitution
13. Part 13 — Bonus Points
14. Part 14 — Data Model Review
15. Part 15 — API Review
16. Part 16 — Test Strategy
17. Part 17 — Implementation Order
18. Part 18 — Final Decision Table
19. Summary: Architecture, Gaps, Minimum Changes, Recommended First Task

---

---

## PART 1 — COMPLETE SCORING PIPELINE TRACE

### Verified from actual code (not assumed)

The following is the exact, complete data flow as it exists today.

---

### STEP 1 — Real Match Data

**Source:** External sports-data feed ingestion OR admin manual entry

**Models involved:**
- `discovery.MatchCentre` — one record per `SportingEvent` (fixture). Stores
  home/away score, feed_status, data_confidence, is_verified.
  File: `discovery/models.py` line ~398

- `discovery.MatchPlayerStatistic` — one record per (match_centre, participant, stat_type).
  Fields: `match_centre FK`, `participant FK (Participant)`, `stat_type CharField`,
  `value DecimalField(12,2)`.
  File: `discovery/models.py` line ~545
  Unique constraint: `(match_centre, participant, stat_type)`.

- `discovery.MatchLineup` — one record per player in the lineup.
  Fields: `match_centre FK`, `participant FK`, `player FK (nullable)`,
  `side (HOME/AWAY)`, `position`, `shirt_number`, `is_starter`.
  File: `discovery/models.py` line ~509

**What enters:** Raw provider data (goals=1, assists=0, minutes_played=90, etc.)
**What leaves:** Persistent DB rows in `MatchPlayerStatistic` and `MatchLineup`
**Authoritative:** YES — this is the primary source of truth for match facts.

---

### STEP 2 — Fixture / SportingEvent

**Model:** `sports.SportingEvent`
**File:** `sports/models.py`
**Relation to Fantasy:** `FantasyGameweek.fixtures` is a M2M to `SportingEvent`.
Admin assigns fixtures to a gameweek. The scoring engine queries
`gameweek.fixtures.values_list("id", flat=True)` to find the relevant match centres.

**What enters:** Admin assigning fixtures to a gameweek via the admin UI.
**What leaves:** A set of fixture IDs used to scope stat queries.
**Authoritative:** YES

---

### STEP 3 — FantasyScoringRule (rule lookup)

**Model:** `fantasy.FantasyScoringRule`
**File:** `fantasy/models.py` line ~277
**Fields:** `fantasy_competition FK`, `statistic_type CharField(50)`,
`points DecimalField(8,2)`, `conditions JSONField(default=dict)`, `enabled BooleanField`

**Key constraint:** There is a `UniqueConstraint` on `(fantasy_competition, statistic_type, conditions)`.

**Critical current limitation in `score_gameweek()`:**
```python
rules = {
    rule.statistic_type.upper(): rule
    for rule in gameweek.fantasy_competition.scoring_rules.filter(enabled=True, conditions={})
}
```
The filter `conditions={}` means **only rules with an empty conditions dict are used**.
Any rule with a non-empty `conditions` field is silently ignored.
This is intentional (the serializer also rejects non-empty conditions).

**What enters:** Competition ID used to fetch applicable rules.
**What leaves:** A dict mapping `STAT_TYPE_UPPER → FantasyScoringRule instance`.
**Authoritative:** YES — rules are the configuration layer.

---

### STEP 4 — `score_gameweek()` — THE ENGINE

**File:** `fantasy/services.py`
**Function:** `score_gameweek(gameweek)` — decorated with `@transaction.atomic`

**Exact current formula (verified from source):**

```
For each FantasyPlayer in the competition's player_pool:
  1. Fetch all MatchPlayerStatistic rows where:
       match_centre__fixture_id__in = gameweek fixture IDs
       participant = fantasy_player.player (the Participant FK)
  2. For each stat row:
       rule = rules.get(stat.stat_type.upper())
       if rule:
           points = stat.value * rule.points
  3. Sum all points → base_points
  4. Check for latest FantasyScoringCorrection → correction_points
  5. total_points = base + correction
  6. Persist to FantasyPlayerGameweekPoints
```

**IMPORTANT:** There is no position-based logic, no threshold logic, no
appearance-points logic, no differential rules. It is pure:
`stat.value × rule.points` for every matching stat that has an unconditional rule.

**What enters:** A `FantasyGameweek` instance.
**What leaves:** Updated `FantasyPlayerGameweekPoints` rows + updated `FantasyTeamGameweekScore` rows.
**Authoritative:** YES — this is the scoring engine.

---

### STEP 5 — FantasyPlayerGameweekPoints

**Model:** `fantasy.FantasyPlayerGameweekPoints`
**File:** `fantasy/models.py` line ~305
**Fields:**
- `gameweek FK`, `fantasy_player FK`
- `base_points Decimal(10,2)` — computed from stats × rules
- `correction_points Decimal(10,2)` — delta applied by admin correction
- `total_points Decimal(10,2)` = base + correction
- `breakdown JSONField(default=list)` — list of `{statistic_type, value, points}`
- `statistics_available BooleanField` — True if any stats existed for this player

**What enters:** Output of scoring loop per player per gameweek.
**What leaves:** Player-level points record consumed by team scoring.
**Authoritative:** YES for player points. Derived from stats + rules.

---

### STEP 6 — FantasyTeamGameweekScore (team aggregation)

**File:** `fantasy/services.py` — second loop in `score_gameweek()`

**Exact current formula:**

```
For each FantasyTeam in the competition:
  1. starters = selections where is_starter=True
  2. For each starter:
       look up their FantasyPlayerGameweekPoints.total_points
       sum → player_points
  3. Determine effective_captain:
       if vice_captain_fallback enabled AND captain didn't participate
       AND vice-captain DID participate → effective_captain = vice
  4. captain_bonus = effective_captain.total_points × (captain_multiplier - 1)
  5. transfer_penalty = FantasyTeamGameweekState.transfer_penalty
  6. total_points = player_points + captain_bonus - transfer_penalty
  7. Persist to FantasyTeamGameweekScore
```

**bench is NOT scored** — bench player points are calculated via
`FantasyPlayerGameweekPoints` but are NOT included in `FantasyTeamGameweekScore.total_points`.

**What enters:** Player-level point records + team composition.
**What leaves:** `FantasyTeamGameweekScore` with breakdown JSON.
**Authoritative:** YES — this is the definitive team score.

The breakdown JSON stored on `FantasyTeamGameweekScore` includes:
```json
{
  "players": [
    {
      "player_id": "...",
      "player_name": "...",
      "position": "...",
      "base_points": "...",
      "correction_points": "...",
      "captain_bonus": "...",
      "final_points": "...",
      "statistics_available": true,
      "captain": false
    }
  ],
  "vice_captain_fallback": false,
  "effective_captain_id": "..."
}
```

---

### STEP 7 — API Endpoints Serving Fan Frontend

The following endpoints are confirmed in `fantasy/urls.py` and `fantasy/views.py`:

| Endpoint | Method | View/Action | Purpose |
|---|---|---|---|
| `/fantasy/gameweeks/{id}/points/` | GET | `GameweekViewSet.points` | All player points for a gameweek |
| `/fantasy/gameweeks/{id}/leaderboard/` | GET | `GameweekViewSet.leaderboard` | Ranked team scores for a gameweek |
| `/fantasy/competitions/{id}/leaderboard/` | GET | `CompetitionViewSet.leaderboard` | Season totals leaderboard |
| `/fantasy/teams/{id}/points/` | GET | `TeamViewSet.points` | All gameweek scores for a team |
| `/fantasy/leagues/{id}/standings/` | GET | `LeagueViewSet.standings` | League standings |
| `/fantasy/leagues/{id}/members/` | GET | `LeagueViewSet.members` | League members with rankings |

---

### STEP 8 — Fan Frontend Consumption

**File:** `src/services/fantasyService.ts` (referenced but not fully shown)
**Key function:** `fetchTeamPoints(teamId)` → calls `GET /fantasy/teams/{id}/points/`

In `data.ts`, `teamFromApi()` maps the array of `FantasyTeamScore` records:
```typescript
totalPoints: scores.reduce((sum, s) => sum + Number(s.total_points), 0),
gwPoints: Number(latest?.total_points ?? 0),
```

The frontend receives `latest.breakdown.players[]` from the last score record
and renders each player's `final_points` and `statistics_available` flag.
File: `src/pages/fan/fantasy/sections/MyTeam.tsx`

**What enters the frontend:** Serialized `FantasyTeamGameweekScore` array.
**What leaves:** Points display on pitch, bench strip, gameweek summary.

---

### STEP 9 — Automatic Scoring Trigger

**File:** `fantasy/tasks.py`
**Function:** `score_affected_gameweeks(fixture_ids)`
**Trigger:** Called via `transaction.on_commit()` from the sports-data feed ingestion
service when ingestion completes. Uses Celery with 3 retries.

The task:
1. Finds all `FantasyGameweek` records that include any affected fixture.
2. Skips FINALIZED gameweeks.
3. Calls `score_gameweek()` once per affected gameweek.
4. Is fully idempotent.

---

---

## PART 2 — MATCH STATISTICS vs PLAYER FANTASY POINTS vs FAN TEAM POINTS

These are three distinct concepts that must never be conflated.

---

### A. MATCH STATISTICS

Match statistics are raw factual records of what a player did in a game.
They are sport-agnostic by design. Each record is:
`(fixture, player, stat_type, value)`.

**Origin today:** Two paths:
1. Admin manual entry via `POST /fantasy/admin/match-statistics/` which calls
   `MatchStatisticViewSet.create()` in `fantasy/views.py`. This does a
   `get_or_create` on `MatchCentre` and creates a `MatchPlayerStatistic` row.
2. External sports-data feed ingestion (existing in the `discovery` pipeline)
   which populates `MatchPlayerStatistic` directly.

**Approved statistics per sport** (from `fantasy/statistics.py`):

Football: GOALS, ASSISTS, MINUTES_PLAYED, CLEAN_SHEETS, SAVES,
PENALTIES_SAVED, YELLOW_CARDS, RED_CARDS, OWN_GOALS, PENALTIES_MISSED,
GOALS_CONCEDED.

Rugby: TRIES, TRY_ASSISTS, CONVERSIONS, PENALTY_GOALS, DROP_GOALS, TACKLES,
TURNOVERS_WON, YELLOW_CARDS, RED_CARDS, MINUTES_PLAYED.

Basketball: POINTS, REBOUNDS, ASSISTS, STEALS, BLOCKS, TURNOVERS,
THREE_POINTERS_MADE, FREE_THROWS_MADE, MINUTES_PLAYED.

**Key observation:** CLEAN_SHEETS is stored as a player statistic (value=1
if clean sheet achieved). GOALS_CONCEDED is also a player-level stat. This
means the data pipeline must populate these correctly per player, not just
per team. This is a significant data quality requirement.

---

### B. FANTASY PLAYER POINTS

**Current formula** (verified from `fantasy/services.py`):

```python
for stat in stats:
    rule = rules.get(stat.stat_type.upper())
    if rule:
        points = stat.value * rule.points
        base += points
```

This is a **pure multiplication**: `stat_value × rule.points`.

**Examples under current system:**
- `GOALS=1, rule.points=5` → 5 points ✓
- `GOALS=2, rule.points=5` → 10 points ✓
- `MINUTES_PLAYED=90, rule.points=2` → 180 points ✗ WRONG
  (minutes × flat rate is not how appearance points work)
- `YELLOW_CARDS=1, rule.points=-1` → -1 points (works if points is negative)
- `CLEAN_SHEETS=1, rule.points=4` → 4 points (works if data is correct)

**Where the formula is too simplistic for real fantasy scoring:**

1. APPEARANCE POINTS: In real fantasy, a player who plays 60+ minutes gets
   2 points; a player who plays 1–59 minutes gets 1 point. The current system
   would require a rule like `MINUTES_PLAYED × 0.022` which is meaningless.
   A threshold/bracket rule type is required.

2. POSITION-BASED SCORING: Goals scored by a GK are worth more than goals
   by a FWD. The current system has a single `GOALS` rule that applies equally
   to all positions. There is no position filter in the scoring loop.

3. SAVES THRESHOLD: In FPL-style scoring, every 3 saves = 1 bonus point.
   The current system cannot represent `floor(saves / 3)` points.

4. GOALS_CONCEDED THRESHOLD: Every 2 goals conceded = -1 point (common rule).
   Cannot be represented as simple multiplication.

5. CLEAN SHEET + MINUTES GATE: A clean sheet only counts if the player
   played 60+ minutes. The current system cannot express this conditionality.

6. NEGATIVE RULES: Currently possible by setting `rule.points` to a negative
   number. YELLOW_CARDS=-1, RED_CARDS=-3 would work today if the rule is
   configured correctly. This part works.

---

### C. FAN TEAM POINTS

**How `FantasyPlayerGameweekPoints → FantasyTeamGameweekScore` works today:**

1. Only STARTERS contribute to team points. Bench is excluded.
2. Captain multiplier: `captain.total_points × (captain_multiplier - 1)` is
   added as captain_bonus. Default multiplier is 2.0, so captain earns double.
3. Vice-captain fallback: if `vice_captain_fallback=True` on the competition
   AND the captain has no participation record (checked via `_participated()`),
   AND the vice-captain does have a participation record, the vice-captain
   becomes the effective captain. The original captain gets no bonus.
4. Transfer penalty: `FantasyTeamGameweekState.transfer_penalty` is subtracted.
   This is accumulated each time a paid transfer is made.
5. Auto-substitution: NOT IMPLEMENTED. If a starter has no stats, they score 0.
   The bench player's points are calculated but not used.
6. Corrections: Handled via `FantasyScoringCorrection`. When applied, it adjusts
   `FantasyPlayerGameweekPoints.correction_points`, then `score_gameweek()` is
   re-run, which re-aggregates team scores.

**What is currently missing from FAN TEAM POINTS:**
- No auto-substitution (bench player cannot replace non-playing starter)
- No gameweek rank (relative rank among all teams for this gameweek)
- No season rank (overall rank across the whole competition)
- No per-player detailed breakdown visible to the fan with rule descriptions
- No chip support (wildcard, bench boost, triple captain, etc.)
- No pending/live state indicator for team score while match is in progress

---

---

## PART 3 — SCORING RULE SYSTEM DESIGN

### What the current system actually supports

`FantasyScoringRule` has:
- `statistic_type` — the stat code (e.g. "GOALS")
- `points` — a decimal value
- `conditions` — a JSON field, currently always `{}`

The `ScoringRuleSerializer.validate_conditions()` **actively rejects** any
non-empty conditions:
```python
def validate_conditions(self, value):
    if value:
        raise serializers.ValidationError(
            "Conditional scoring rules are not supported; "
            "create an unconditional statistic rule."
        )
    return value
```

And the scoring engine itself filters to `conditions={}` only. This means
the `conditions` field exists but is not functional. It is a structural stub.

The `UniqueConstraint` on `(fantasy_competition, statistic_type, conditions)`
means that if conditions were to differ per rule (e.g. `{"position": "GK"}`),
it would be a different, non-conflicting row — by design. This is the key
architectural hook for the extended rule system.

---

### Rule Types Required for League OS

The following are the rule types we actually need, assessed against real
fantasy requirements for football, basketball, and rugby. This is not
blindly copying FPL.

#### 1. PER_UNIT (EXISTING — works today)
One point value applied per unit of the statistic.
```
GOALS: value=2, rule.points=5 → 10 points
```
Works today. No change needed for this type.

#### 2. FLAT (NEEDS CHANGE)
A fixed number of points awarded when a statistic value meets a condition
(e.g. value > 0). Currently you can approximate this with PER_UNIT if
value is always 0 or 1 (which CLEAN_SHEETS and PENALTIES_SAVED are), but
it is semantically incorrect. A formal FLAT type makes the intent explicit.

#### 3. THRESHOLD / BRACKET (NEW — required)
The most critical missing type. Required for:
- `MINUTES_PLAYED`: 1–59 min → 1 pt; 60+ min → 2 pts
- `SAVES`: every 3 saves → 1 pt (floor division)
- `GOALS_CONCEDED`: every 2 conceded → -1 pt

Two sub-variants:
- **BRACKET**: `min_value` to `max_value` → fixed points
- **PER_N**: `floor(value / n)` × points (for saves, tackles, etc.)

#### 4. POSITION_BASED (NEW — required)
Different points for the same statistic depending on player position.
```
GOALS: GK=10, DEF=6, MID=5, FWD=4
CLEAN_SHEET: GK=4, DEF=4, MID=1, FWD=0
```
Required for any realistic football scoring.

#### 5. NEGATIVE (EXISTING — works today)
Setting `rule.points` to a negative decimal works today.
YELLOW_CARDS=-1, RED_CARDS=-3 are standard and work.

#### 6. CONDITIONAL (NOT needed for v1)
"Clean sheet only if played 60+ minutes" is a conditional rule combining
threshold and a different statistic. This requires a cross-statistic
evaluation that is significantly complex. Defer to v2.

---

### Recommended Approach: Extend `FantasyScoringRule.conditions` JSON

**Comparison of alternatives:**

**Option A: New fields (`rule_type`, `min_value`, `max_value`, `per_n`)**
- Pros: Explicit, DB-queryable, migration-safe
- Cons: Many nullable fields, model grows wide, harder to extend for new sports

**Option B: Extend `conditions` JSON (recommended)**
- Pros: Already exists, no migration to add a new column, flexible, matches
  the unique constraint design (conditions differentiates rules for same stat),
  sport-specific shapes can coexist
- Cons: Less type-safe without explicit validation

**Option C: Separate `ScoringRuleCondition` model**
- Pros: Very explicit, relational
- Cons: Over-engineered for v1, many joins in the scoring engine

**Option D: `rule_type` enum + `conditions` JSON**
- Recommended compromise: add `rule_type` as a new CharField with choices,
  keep `conditions` for rule-type-specific parameters.

**RECOMMENDATION: Option D**

Add a `rule_type` field with choices to `FantasyScoringRule`. Keep `conditions`
for parameters. The `conditions` JSON schema is then defined per rule_type:

```python
class RuleType(models.TextChoices):
    PER_UNIT    = "PER_UNIT",    "Per unit"         # value × points
    FLAT        = "FLAT",        "Flat"              # fixed points if value > 0
    BRACKET     = "BRACKET",     "Bracket"           # points if min <= value <= max
    PER_N       = "PER_N",       "Per N units"       # floor(value/n) × points
    POSITION    = "POSITION",    "Position-based"    # points by position
```

`conditions` JSON schemas per type:
```json
// BRACKET: { "min": 60, "max": null }
// PER_N:   { "per_n": 3 }
// POSITION: { "positions": { "GK": 10, "DEF": 6, "MID": 5, "FWD": 4 } }
// PER_UNIT, FLAT: {} (empty, current default)
```

This approach:
- Is backward compatible (existing rules are PER_UNIT with empty conditions)
- Preserves the unique constraint
- Requires one new DB column (`rule_type`)
- Keeps all rule logic inside the scoring engine in a single function
- Supports multi-sport by allowing sport-specific position codes in the JSON

---

---

## PART 4 — MULTI-SPORT DESIGN

### Current State

The multi-sport infrastructure already exists:
- `FantasyCompetition.competition` → `Competition` → `Competition.sport` → `Sport`
- `FantasyPlayer.position` is a free text field validated against
  `competition.position_rules` keys
- `statistics.py` already defines separate stat catalogues per sport slug
- `statistic_catalogue(sport)` dispatches by `sport.slug` or `sport.name`

### The Central Question

Should we have `FootballScoringEngine`, `BasketballScoringEngine`, `RugbyScoringEngine`?

**No.** The architecture should be: **generic statistics + configurable rules**.

The scoring engine (`score_gameweek()`) should not know what sport it is
scoring. It should only know:
- A player has stats
- There are rules for those stats
- Rules know how to compute points

The sport-specific logic lives in the **rule configuration**, not the engine.

### Sport-Specific Rule Examples

**FOOTBALL (15-player squad typical):**
```
GOALS:         POSITION rule {GK:10, DEF:6, MID:5, FWD:4}
ASSISTS:       PER_UNIT 3 pts
MINUTES_PLAYED: BRACKET {min:1,max:59} → 1pt; BRACKET {min:60,max:null} → 2pts
CLEAN_SHEETS:  POSITION rule {GK:4, DEF:4, MID:1, FWD:0}
SAVES:         PER_N {per_n:3} → 1pt
YELLOW_CARDS:  PER_UNIT -1
RED_CARDS:     PER_UNIT -3
OWN_GOALS:     PER_UNIT -2
PENALTIES_SAVED: FLAT 5pts
PENALTIES_MISSED: FLAT -2pts
GOALS_CONCEDED: PER_N {per_n:2} → -1pt (GK/DEF only, position rule)
```

**BASKETBALL:**
```
POINTS:        PER_N {per_n:2} → 1pt (e.g. 2 pts per game point)
REBOUNDS:      PER_UNIT 1.2 pts
ASSISTS:       PER_UNIT 1.5 pts
STEALS:        PER_UNIT 3 pts
BLOCKS:        PER_UNIT 3 pts
TURNOVERS:     PER_UNIT -1
THREE_POINTERS_MADE: PER_UNIT 0.5 pts bonus
MINUTES_PLAYED: BRACKET {min:1,max:null} → 2pts (appeared)
```

**RUGBY:**
```
TRIES:         PER_UNIT 10 pts
TRY_ASSISTS:   PER_UNIT 6 pts
CONVERSIONS:   PER_UNIT 2 pts
PENALTY_GOALS: PER_UNIT 3 pts
DROP_GOALS:    PER_UNIT 3 pts
TACKLES:       PER_N {per_n:5} → 1pt
TURNOVERS_WON: PER_UNIT 3 pts
YELLOW_CARDS:  PER_UNIT -2
RED_CARDS:     PER_UNIT -4
MINUTES_PLAYED: BRACKET {min:1,max:null} → 2pts
```

**Conclusion:** All three sports can be supported by the same
`FantasyScoringRule` model with different rule_type and conditions
configurations. No sport-specific engine classes are required.
The admin configures the rules per competition. The engine is generic.

---

## PART 5 — POSITION-SPECIFIC SCORING

### What currently prevents position-based scoring

1. `score_gameweek()` loads rules as:
   ```python
   rules = {rule.statistic_type.upper(): rule
            for rule in ...filter(enabled=True, conditions={})}
   ```
   This dict can only hold ONE rule per stat_type. A second GOALS rule with
   `conditions={"position": "GK"}` would be filtered out by `conditions={}`.

2. In the scoring loop, `player.position` is never consulted:
   ```python
   rule = rules.get(stat.stat_type.upper())
   if rule:
       points = stat.value * rule.points
   ```
   Even if a position-based rule existed, the engine would not use it.

3. `ScoringRuleSerializer.validate_conditions()` actively raises a
   ValidationError for any non-empty conditions dict.

### Proposed Conditions Structure for Position Rules

The `POSITION` rule_type uses:
```json
{
  "positions": {
    "GK": 10,
    "DEF": 6,
    "MID": 5,
    "FWD": 4
  }
}
```

A position value of `0` means "no points awarded" (e.g. FWD clean sheet).
A missing position means "not applicable" (same as 0 for that position).

For rugby: `{"positions": {"FR": 4, "LK": 4, "BR": 2, "HB": 2, "CT": 1, "B3": 0}}`
For basketball: position rules are less common but can be similarly expressed.

### Required Changes for Position-Based Scoring

1. **`FantasyScoringRule`:** Add `rule_type` field.
2. **`ScoringRuleSerializer`:** Remove the blanket rejection of non-empty
   conditions. Validate by rule_type.
3. **`score_gameweek()`:** Change rule lookup to support multiple rules per
   stat_type (keyed by stat_type + position). Change scoring loop to consult
   player position for POSITION rules.
4. **`admin UI`:** Scoring rules panel in `FantasyAdminPage.tsx` needs to
   allow selecting rule_type and editing conditions JSON.

### Validation Requirements

- For `POSITION` rules: `conditions.positions` must be a dict; keys must be
  valid positions for the competition (from `position_rules`); values must be
  numeric.
- For `BRACKET` rules: `conditions` must have `min` (integer ≥ 0); `max` is
  optional (null = no upper bound). Points value applies when
  `min <= stat.value` and (max is null or `stat.value <= max`).
- For `PER_N` rules: `conditions.per_n` must be a positive integer.

---

---

## PART 6 — THRESHOLD SCORING

### Use Cases Requiring Thresholds

1. **MINUTES_PLAYED / Appearance points:**
   - 0 minutes → 0 points
   - 1–59 minutes → 1 point
   - 60+ minutes → 2 points

2. **SAVES (football GK):**
   - Every 3 saves = 1 bonus point
   - e.g. saves=5 → floor(5/3) = 1 pt; saves=6 → 2 pts

3. **GOALS_CONCEDED:**
   - Every 2 goals conceded → -1 point
   - e.g. conceded=3 → floor(3/2) = -1 pt

4. **TACKLES (rugby):**
   - Every 5 tackles = 1 point
   - Similar to saves

### Comparison of Approaches

**Option A: `min_value` / `max_value` fields on `FantasyScoringRule`**
- Would cover the bracket case (min=60, max=null → 2 pts)
- Cannot cover PER_N (floor division)
- Requires adding 2 new nullable DB columns
- Verdict: PARTIAL — covers brackets but not per-N

**Option B: `rule_type` + `conditions` JSON (RECOMMENDED)**
```json
// Minutes 1-59 → 1pt
{"rule_type": "BRACKET", "conditions": {"min": 1, "max": 59}, "points": 1}

// Minutes 60+ → 2pts  
{"rule_type": "BRACKET", "conditions": {"min": 60, "max": null}, "points": 2}

// Every 3 saves → 1pt
{"rule_type": "PER_N", "conditions": {"per_n": 3}, "points": 1}
```
- BRACKET requires two rule rows for minutes (one for each bracket)
- Handles all threshold cases
- The unique constraint `(competition, statistic_type, conditions)` allows
  two MINUTES_PLAYED rules to coexist because their conditions differ
- Verdict: COMPLETE — recommended

**Option C: Separate `ScoringRuleCondition` model**
- Over-engineered for current scale
- Adds join complexity to scoring engine
- Verdict: REJECT for v1

**Option D: Another approach — computed rules in service**
- Hardcode some logic in `score_gameweek()` per stat type
- e.g. special case MINUTES_PLAYED with bracket logic
- Verdict: REJECT — breaks the configurable rules architecture

**RECOMMENDATION: Option B (rule_type + conditions JSON)**

Implementation in `score_gameweek()` for each rule_type:
```python
def apply_rule(rule, stat_value, player_position):
    if rule.rule_type == "PER_UNIT":
        return stat_value * rule.points
    elif rule.rule_type == "FLAT":
        return rule.points if stat_value > 0 else 0
    elif rule.rule_type == "BRACKET":
        min_v = rule.conditions.get("min", 0)
        max_v = rule.conditions.get("max")  # None = no upper bound
        if stat_value >= min_v and (max_v is None or stat_value <= max_v):
            return rule.points
        return 0
    elif rule.rule_type == "PER_N":
        n = rule.conditions.get("per_n", 1)
        return (int(stat_value) // n) * rule.points
    elif rule.rule_type == "POSITION":
        pts = rule.conditions.get("positions", {}).get(player_position, 0)
        return stat_value * Decimal(str(pts))
    return 0
```

The scoring engine rule-lookup must change to collect ALL rules per stat_type
(not just one), then evaluate each, summing all matching rules. This is a
key structural change to `score_gameweek()`.

---

---

## PART 7 — PLAYER POINTS BREAKDOWN

### Current State

`FantasyPlayerGameweekPoints.breakdown` is a JSONField storing a list:
```json
[
  {"statistic_type": "GOALS", "value": "1", "points": "5.00"},
  {"statistic_type": "ASSISTS", "value": "1", "points": "3.00"}
]
```

This is populated in `score_gameweek()` for each matching stat × rule pair.

**What is currently MISSING from the breakdown:**
1. The rule_type and conditions that produced each points entry
2. The position of the player at time of scoring
3. An entry for statistics that exist but have no matching rule (zero-point stats)
4. An entry for appearance/minutes scoring (currently not possible)
5. Whether each stat was manually corrected (original vs corrected value)
6. A `rule_description` field for human-readable display (e.g. "GK Goal ×10")
7. The captain bonus per-player (currently only in the team breakdown, not the player breakdown)

### What the fan needs to see

```
Player: John Doe | Position: GK | Team: Arsenal

Stat               Value    Rule Applied       Points
─────────────────────────────────────────────────────
Minutes played       90     60+ mins            +2
Goals                 1     GK Goal             +10
Clean sheet           1     GK/DEF CS           +4
Saves                 6     per 3 saves         +2
Yellow card           1     Yellow card         -1
─────────────────────────────────────────────────────
Base total                                      +17
Captain bonus (×2)                              +17
─────────────────────────────────────────────────────
Final total                                     +34
```

### Proposed Enhanced Breakdown Structure

The breakdown should be enhanced to include per-entry context:
```json
[
  {
    "statistic_type": "MINUTES_PLAYED",
    "value": "90",
    "rule_type": "BRACKET",
    "rule_description": "60+ minutes played",
    "points": "2.00"
  },
  {
    "statistic_type": "GOALS",
    "value": "1",
    "rule_type": "POSITION",
    "rule_description": "GK Goal",
    "points": "10.00"
  }
]
```

**The minimum additional fields required:**
- `rule_type` — so the UI can render the rule category
- `rule_description` — human-readable label (e.g. "GK Goal", "60+ min")

The `rule_description` should be generated from the rule at scoring time,
not computed client-side, so it is consistent across admin and fan views.

### Who benefits from an enhanced breakdown

| Consumer | Use |
|---|---|
| Fan | Understand why they got those points |
| Admin | Audit that rules fired correctly |
| Correction workflow | Know what to override and why |
| Debugging | Trace unexpected scores |

**No data duplication is required.** The breakdown stores computed results.
The raw stats remain in `MatchPlayerStatistic`. The rules remain in
`FantasyScoringRule`. The breakdown is a computed audit trail.

---

---

## PART 8 — FAN-SIDE EXPERIENCE

### Current Fan Fantasy Frontend Trace

**Main entry:** `src/pages/fan/fantasy/FantasyCompetitions.tsx`
**Navigation:** `hub → competition → build/team/transfers/leagues`
**Core sections:**
- `FantasyHub.tsx` — competition cards + league badges
- `CompetitionDetail.tsx` — competition rules + create team CTA
- `SquadBuilder.tsx` — initial squad selection, position-based filtering, budget
- `MyTeam.tsx` — pitch view with player avatars, bench strip, captain/vice UI, points summary
- `Transfers.tsx` — swap players, preview cost/penalty
- `Leagues.tsx` — create/join leagues, member list, join code flow
- `GameweekFixtures.tsx` — browse fixtures by gameweek with scores

**Data services:**
- `src/services/fantasyService.ts` — API calls to `/fantasy/*`
- `src/services/fantasyAdminService.ts` — admin endpoints
- `src/pages/fan/fantasy/data.ts` — transformation functions
  (`competitionFromApi`, `playerFromApi`, `teamFromApi`, etc.)

### What the fan currently sees in MyTeam.tsx

When viewing their team, the fan sees:
1. **Stat row:** Gameweek points, overall rank (null), free transfers, budget
2. **Pitch:** Visual formation with player avatars, captain (C) badge, vice (V) badge
3. **Per-player label:** Shows points OR "Awaiting statistics" (determined by
   `statistics_available` flag on `FantasyTeamGameweekScore.breakdown.players[]`)
4. **Bench strip:** Shows bench players with points/awaiting stats
5. **Actions:** "Make transfers", "View points breakdown" (opens a drawer)
6. **Captain picker:** Modal to change captain/vice for the current gameweek

### What the fan currently sees in the points breakdown drawer

- Gameweek points (team total)
- Total points (season cumulative)
- Captain points
- Best player points (highest single player)
- Bench points (labelled "Not counted")
- Overall rank (currently null)
- Per-player list: avatar, name, club, final_points

**What is currently MISSING from the breakdown drawer:**
- No per-player detailed breakdown (goals=1, assists=0, etc.)
- No rule descriptions (e.g. "Goal by GK +10 pts")
- No captain bonus shown per player (only aggregated)
- No indication that a correction was applied
- No "pending" vs "final" state indicator
- No gameweek rank

The frontend has all the infrastructure to render the enhanced breakdown.
It just needs the backend to provide richer data in `breakdown.players[]`.

### Design for Ideal Scoring Experience

The fan should see:

**1. Team summary (already exists):**
- Gameweek points, season points, gameweek rank, overall rank
- Free transfers available, budget remaining

**2. Pitch view (already exists):**
- Player points OR "Awaiting stats" OR "Did not play"
- Captain bonus shown visually (e.g. player points × 2)
- Vice-captain fallback indicator if it occurred

**3. Detailed breakdown (NEEDS ENHANCEMENT):**
- Per-player list including:
  - Player name, position, club
  - Each scored stat: "90 min (Appearance +2)", "1 goal (GK Goal +10)"
  - Subtotal for that player
  - Captain bonus if applicable
  - "Did not play" if statistics_available=false
- Bench section: "Not counted in your total"
- Transfer penalty: "−4 (extra transfer)"
- Corrections indicator: "Admin correction applied ✓"

**4. Gameweek rank & overall rank:**
- Show the team's rank in the competition leaderboard
- Show the team's rank in each private league they've joined

**5. Live vs final indicator:**
- If gameweek status = LIVE or SCORING → "Live points (subject to change)"
- If gameweek status = FINALIZED → "Final verified points ✓"

---

### APIs that already provide required data

| Data needed | Endpoint | Status |
|---|---|---|
| Team points per gameweek | `GET /fantasy/teams/{id}/points/` | EXISTS ✓ |
| Player points per gameweek | `GET /fantasy/gameweeks/{id}/points/` | EXISTS ✓ |
| Gameweek leaderboard (rank) | `GET /fantasy/gameweeks/{id}/leaderboard/` | EXISTS ✓ |
| Season leaderboard (rank) | `GET /fantasy/competitions/{id}/leaderboard/` | EXISTS ✓ |
| League standings | `GET /fantasy/leagues/{id}/standings/` | EXISTS ✓ |

These APIs already power `rank_rows()` which assigns ranks based on tie-breaker
rules. The frontend just needs to read and display the `rank` field.

### Frontend areas that need modification

**File:** `src/pages/fan/fantasy/sections/MyTeam.tsx`
**Change:** Expand the "View points breakdown" drawer to show per-player
detailed stats from `breakdown.players[].stats` (once the backend provides it).

**File:** `src/pages/fan/fantasy/data.ts`
**Change:** The `teamFromApi()` function should parse `overallRank` from the
leaderboard API response when available.

**File:** `src/pages/fan/fantasy/types.ts`
**Change:** Extend the `FantasyTeam` type to include `gwRank` and populate it
from the gameweek leaderboard API.

**No new endpoints required.**

---

---

## PART 9 — ADMIN-SIDE EXPERIENCE

### Current Admin Fantasy Flow (verified from code)

**Main page:** `src/pages/admin/fantasy/FantasyAdminPage.tsx`
**Tabs:** overview, competitions, players, gameweeks, scoring, corrections,
leaderboards, leagues, match-stats

**Match statistics review:** `src/pages/admin/fantasy/MatchStatisticsReview.tsx`

**Current admin workflow:**

1. **Enter statistics:**
   - Test entry: `POST /fantasy/admin/match-statistics/` (creates `MatchPlayerStatistic`)
   - Production: external feed ingestion populates `MatchPlayerStatistic` automatically

2. **Review statistics:**
   - `GET /fantasy/admin/match-statistics/review/` → grouped player+fixture rows
   - Shows: player, club, fixture, gameweek, fantasy_points, review_status
   - Filter by: competition, gameweek, fixture, player search, review_status

3. **Inspect detail:**
   - `GET /fantasy/admin/match-statistics/review/{fixture}/{participant}/`
   - Shows: raw stats, full fantasy scoring breakdown (statistic, value, rule, points)
   - Existing `MatchStatisticsReview.tsx` already renders a breakdown table

4. **Correct statistics:**
   - `POST /fantasy/admin/match-statistics/correct/`
   - Corrects `MatchPlayerStatistic.value`, re-runs `score_gameweek()` automatically

5. **Approve:**
   - `POST /fantasy/admin/match-statistics/approve/`
   - Creates/updates `FantasyStatisticReview` status to APPROVED

6. **Recalculate:**
   - `POST /fantasy/gameweeks/{id}/recalculate/`
   - Manually triggers `score_gameweek()` for a gameweek

7. **Finalize:**
   - `POST /fantasy/gameweeks/{id}/finalize/`
   - Requires all fixtures COMPLETED/CANCELLED/ABANDONED
   - Runs final `score_gameweek()`, then locks to FINALIZED status

### What the admin needs to verify scoring (gap analysis)

**Currently shown in the review detail drawer:**
```
Statistic    Value    Rule           Points
Goals          1      × 5.00 pts      +5
Assists        1      × 3.00 pts      +3
Total: 8 pts
```

**Missing from admin view:**
- The `rule_type` is not shown (admin cannot see if it's POSITION vs PER_UNIT)
- The player's position is not shown in the breakdown context
- No indication of which rules were evaluated but did not fire (e.g. no MINUTES_PLAYED stat)
- Corrections history: there is a `corrections` tab but it doesn't link back to the
  player+fixture view
- No column showing "review pending" per gameweek summary (how many players not yet approved)

### Design for Admin Scoring Verification

**Extend the existing `MatchStatisticsReview` component to show:**

In the "Fantasy Scoring" section of the detail drawer, add:
- Player position label
- Rule type for each breakdown row (shows PER_UNIT, POSITION, etc.)
- For POSITION rules: shows "GK Goal → 10 pts" rather than just "× 10 pts"
- A "Stats evaluated but no rule" section listing stats that existed but
  had no matching scoring rule (visibility aid for rule configuration gaps)

**In the review list table, add:**
- A "GW Points" column showing each player's total_points (already there ✓)
- A "Correction" indicator on rows where correction_points ≠ 0

**No new pages required.** All enhancements fit within `MatchStatisticsReview.tsx`.

---

---

## PART 10 — GAMEWEEK SCORING LIFECYCLE

### Current Status Transitions (verified from views.py)

```
DRAFT → OPEN → LOCKED → LIVE → SCORING → FINALIZED
                       ↑                ↓
                      (SCORING ← back to LIVE)
                      (FINALIZED ← back to SCORING)
```

From `GameweekViewSet.transition()`:
```python
allowed = {
    "DRAFT":     {"OPEN"},
    "OPEN":      {"LOCKED"},
    "LOCKED":    {"LIVE", "SCORING"},
    "LIVE":      {"SCORING"},
    "SCORING":   {"FINALIZED", "LIVE"},
    "FINALIZED": {"SCORING"},
}
```

### Full Lifecycle Analysis

**DRAFT → OPEN:**
- Admin creates the gameweek, assigns fixtures, configures dates
- Fans can read the gameweek but cannot select yet
- Statistics: not yet relevant
- Scoring: not relevant
- Fan scores: not visible

**OPEN:**
- Fans can create teams, make transfers, set lineups
- Statistics: may arrive from live fixtures (but lineup changes still allowed)
- Scoring: `score_gameweek()` can be called (idempotent), but results are
  "live/provisional" — no fan-facing finality
- Fan scores: visible but labeled "provisional"
- Transfer penalty accumulation: active

**LOCKED:**
- `deadline_at` has passed OR admin manually locked it
- Lineup and transfer changes blocked (`deadline_locked()` returns True)
- Statistics: still arriving (matches may not have started)
- Fan scores: visible but provisional

**LIVE:**
- Matches are in progress
- The automatic scoring task (`score_affected_gameweeks`) runs on feed ingestion
- Admin can manually trigger `recalculate/`
- Fan scores: visible, updating live, labeled "LIVE"
- Transfer changes: blocked

**SCORING:**
- Matches complete, statistics being finalized
- `score_gameweek()` runs on each admin recalculate
- Admin correction workflow is active
- Fan scores: visible, labeled "SCORING (subject to change)"

**FINALIZED:**
- `finalize/` endpoint: checks all fixtures are COMPLETED/CANCELLED/ABANDONED
- Runs one final `score_gameweek()`
- Status set to FINALIZED
- Notifications sent to all team owners
- The automatic `score_affected_gameweeks` task SKIPS FINALIZED gameweeks
- Fan scores: visible, labeled "FINAL ✓"
- Admin can revert to SCORING (allowed by the transition map)

---

### Lifecycle Rules — What protects what

| Event | Rule |
|---|---|
| Stat entry | Allowed in any status except FINALIZED (automatic task skips it) |
| Scoring | Manual recalculate allowed in LOCKED/LIVE/SCORING; automatic task runs for non-FINALIZED |
| Score changes | Allowed until FINALIZED; admin can revert FINALIZED → SCORING |
| Corrections | `FantasyScoringCorrection` can be created in any status; triggers re-score |
| Finalization | Requires status=SCORING and all fixtures in terminal state |
| Fan lineup changes | Blocked once deadline_at has passed OR status is LOCKED or beyond |
| Transfer penalty | Accumulated during DRAFT/OPEN phase before deadline |

---

### Identified Inconsistencies and Missing Safeguards

1. **No explicit "live match in progress" guard for corrections:**
   An admin can apply a correction to a player while their match is still live.
   The auto-scoring task will re-run and overwrite the correction. This needs
   a safeguard: corrections should ideally only be applied after the match ends.
   Recommendation: add a warning in the correction UI when fixture_status is not COMPLETED.

2. **Postponed/cancelled fixtures:**
   If a fixture is assigned to a gameweek and then postponed, the gameweek
   cannot be finalized (the endpoint requires all fixtures to be COMPLETED,
   CANCELLED, or ABANDONED). This is correctly handled — the admin would need
   to transition the fixture to CANCELLED or remove it from the gameweek.
   The transition endpoint for fixtures is outside the fantasy app (in sports/discovery).
   Recommendation: document this dependency for operations teams.

3. **Incomplete statistics:**
   The `statistics_available` flag on `FantasyPlayerGameweekPoints` indicates
   whether any stats existed. If a player played but their stats were not
   entered, `statistics_available=False` and points=0. This is surfaced to
   fans as "Awaiting statistics". This is correct behavior but must be
   communicated clearly in the UI.

4. **Score on correction but not on finalization re-run:**
   When a correction is applied, `score_gameweek()` is re-run immediately.
   The correction delta is `(latest_correction.new_value - base_points)`.
   This means the correction survives a re-score. Verified correct.

5. **FINALIZED revert scenario:**
   When FINALIZED → SCORING (allowed), the auto-task will not re-score (it
   skips SCORING status... actually it does NOT skip SCORING, only FINALIZED).
   A reverted gameweek will be re-scored by the next feed ingestion. This is
   likely correct behavior. Recommend documenting it.

6. **No "gameweek scoring lock" for team composition:**
   Team composition (which players are starters/bench) is locked at deadline.
   But `score_gameweek()` reads the current `FantasyTeamPlayer` rows at
   scoring time. If an admin somehow changed a lineup after the deadline,
   it would affect scoring. The `deadline_locked()` guard prevents the API
   from accepting lineup changes, but there's no DB-level snapshot of the
   lineup at deadline time.
   Recommendation: take a lineup snapshot at the time of LOCK transition
   for v2. For v1, trust the deadline guard.

---

---

## PART 11 — REAL FANTASY APPLICATION COMPARISON

### A. Common Fantasy Principles We Should Adopt

These are universal fantasy sports principles that apply regardless of FPL:

1. **Appearance threshold:** Players should earn points for playing, not just
   for events (goals, assists). A simple "played = 2 pts" or tiered
   "1-59 min = 1 pt, 60+ = 2 pts" is standard. → CRITICAL, not in v0.

2. **Per-event scoring with multipliers:** Goals, assists, saves score
   per occurrence. This already works for PER_UNIT rules. → EXISTS ✓

3. **Negative scoring:** Cards, own goals, penalties missed penalize.
   Works today if rules are configured with negative points. → EXISTS ✓

4. **Captain double:** Captain earns ×2 (or configurable). → EXISTS ✓

5. **Vice-captain fallback:** If captain doesn't play, vice gets the bonus.
   → EXISTS ✓

6. **Transfer penalty:** Extra transfers beyond the free allocation incur
   a configurable point deduction. → EXISTS ✓

7. **Gameweek finalization:** Once a gameweek is finalized, scores are locked
   and visible as "final". → EXISTS ✓

8. **Season cumulative scoring:** Season total = sum of all gameweek scores.
   → EXISTS ✓ (leaderboard API aggregates with Sum)

9. **Overall and gameweek leaderboards:** Both already exist. → EXISTS ✓

10. **Corrections mechanism:** Admin can correct stats and re-score.
    → EXISTS ✓

### B. FPL-Specific Mechanics We DO NOT Need for v1

1. **Chips:** Wildcard, Bench Boost, Triple Captain, Free Hit. Complex
   state management. Not required for v1. Defer to v2.

2. **FPL-specific bonus points system:** BPS (Bonus Point System) based on
   complex in-match performance scoring. We do not need this. We can have
   simpler scoring without a BPS tier.

3. **Price changes:** Player prices fluctuating based on ownership and
   transfers. Not relevant for our current competition model. Defer.

4. **FPL's specific point values:** GK goal=6, DEF goal=6, MID goal=5,
   FWD goal=4 are FPL-specific. Our admins configure values per competition.
   These are NOT hardcoded.

5. **Dream Team:** FPL's "best XI" virtual team. Not required.

6. **Auto-save on deadline:** FPL auto-selects a default lineup if a fan
   forgets. Not required for v1.

### C. League OS-Specific Requirements

1. **Multi-sport from day one:** Football, basketball, rugby must work with
   the same infrastructure. All rule configuration is per-competition (and
   therefore per-sport) via the admin.

2. **Admin-configurable everything:** Captain multiplier, squad size, budget,
   position rules, scoring rules — all configured per competition, not hardcoded.
   This exists and should be preserved.

3. **Stat review and approval workflow:** The `FantasyStatisticReview` model
   and the review/approve admin endpoints are a League OS differentiator
   vs raw FPL. Preserve this. Club Admins submit stats; Platform Admins approve.

4. **Competition-scoped leagues:** Private and public leagues scoped to a
   fantasy competition. Join codes for private leagues. Already exists.

5. **Multi-gameweek coverage per fixture:** A fixture can be in only one
   gameweek (the M2M allows it but the natural assumption is one GW per fixture).
   Verify no edge case where a fixture appears in two GWs.

---

---

## PART 12 — AUTO-SUBSTITUTION

### What Auto-Substitution Requires

When a starting player does not play (no stats recorded), the first eligible
bench player in bench_order who DID play should automatically substitute in
and earn their points for the team's total.

### Current Data Sufficiency Analysis

**Required data:**
1. Did the starter play? → `_participated(gameweek, fantasy_player)` in services.py
   already checks this. It looks for `MatchPlayerStatistic` OR `MatchLineup` rows.
   Available ✓

2. Did the bench player play? → Same `_participated()` function. Available ✓

3. Is there a valid substitution? → Must check:
   - Formation validity: bringing on a bench player must not violate `formation_rules`
   - Example: bringing on a second GK from bench when you already have 1 GK playing
     might violate formation rules
   - Available: `FantasyTeamPlayer.bench_order`, `FantasyPlayer.position`,
     `FantasyCompetition.formation_rules` — all available ✓

4. What are the bench player's points? → `FantasyPlayerGameweekPoints` — available ✓

### What is Missing for Auto-Substitution

Nothing critical is missing from the data model. All required data already exists.

**However**, implementing auto-substitution requires non-trivial logic:

1. For each team, iterate starters in position order.
2. For each non-participating starter, find first bench player (by bench_order)
   who DID participate AND whose substitution would not violate formation_rules.
3. Use the bench player's points instead of the starter's 0.
4. Record the substitution in the team score breakdown.
5. The formation validity check is the hard part: you need to simulate the
   resulting starting lineup after all substitutions and validate it against
   `formation_rules`.

**Current implementation gap:**
`score_gameweek()` does not include any auto-substitution logic. Bench players
are scored but their points are never applied to the team total.

The vice-captain fallback already demonstrates the pattern (if captain doesn't
play, use vice). Auto-substitution is the same concept extended to all starters.

### Recommendation

Do NOT implement auto-substitution in Phase 1. The logic is complex enough
(especially the formation validity check with multiple simultaneous substitutions)
that it warrants its own phase. Mark it as Phase 5.

---

## PART 13 — BONUS POINTS

### What Bonus Points Would Require

A typical bonus system works as follows:
1. After a fixture ends, rank all players in the fixture by a "performance score"
2. Award bonus points (e.g. 3/2/1) to top performers
3. The performance score itself requires a weighted formula across stats

### Current Data Sufficiency for Bonus Points

**Required data:**
- All player stats for a fixture → `MatchPlayerStatistic` available ✓
- Player positions → `FantasyPlayer.position` available ✓
- A weighting formula → NOT present. Would require a new configuration model or
  hardcoded formula per sport.

### What is Missing

The current system has no "fixture-level performance ranking" concept. Implementing
a bonus system would require:

1. A way to define a performance scoring formula per sport (e.g. goal=32 bps,
   assist=24 bps, save=2 bps, etc.)
2. A per-fixture ranking job that runs after all stats are entered
3. A new model or field to store bonus points separately from base points
4. Logic to award 3/2/1 (or configurable tiers) to top performers

### Recommendation

Bonus points are a v3 feature. The data substrate exists but the
configuration and ranking infrastructure does not. Do NOT implement in v1 or v2.

---

---

## PART 14 — DATA MODEL REVIEW

### FantasyCompetition — KEEP (no change needed)
All fields are appropriate and configurable. `captain_multiplier`,
`vice_captain_fallback`, `free_transfers_per_gameweek`, `transfer_penalty`,
`position_rules`, `formation_rules`, `tie_break_rules` are all well-designed.

### FantasyGameweek — KEEP
Status enum, fixture M2M, deadline/start/end dates are correct.

### FantasyPlayer — KEEP
`position` as a free text field validated against `competition.position_rules`
is the right approach for multi-sport. `starting_points` field is a useful
admin-configurable baseline. No changes needed.

### FantasyTeam — KEEP
Clean model. No changes needed.

### FantasyTeamPlayer — KEEP
Captain/vice-captain unique constraints, bench_order, is_starter are all correct.

### FantasyTransfer — KEEP
`penalty_points` tracks per-transfer cost. No changes needed.

### FantasyTeamGameweekState — KEEP
Transfer accounting snapshot. The `transfer_penalty` accumulation model is correct.

### FantasyScoringRule — MODIFY

**Current fields:** `fantasy_competition FK`, `statistic_type`, `points`,
`conditions JSONField`, `enabled`.

**Required addition:** `rule_type CharField` with choices:
`PER_UNIT` (default), `FLAT`, `BRACKET`, `PER_N`, `POSITION`.

**Migration:** Add `rule_type` with `default='PER_UNIT'`. Backward compatible.
All existing rules remain valid as PER_UNIT rules.

**Serializer change:** Remove the blanket rejection of non-empty conditions.
Add per-rule-type conditions validation.

**Admin UI change:** The scoring rules panel in `FantasyAdminPage.tsx` needs
a `rule_type` selector and a conditional `conditions` editor.

### FantasyPlayerGameweekPoints — MODIFY (breakdown only)

**Current breakdown:** `[{statistic_type, value, points}]`

**Required enhancement:**
`[{statistic_type, value, rule_type, rule_description, points}]`

Add `rule_type` and `rule_description` to each breakdown entry.
This is a JSON field change — no migration required, backward compatible.

### FantasyTeamGameweekScore — NO CHANGE NEEDED for v1

The breakdown JSON already contains per-player detail including base_points,
correction_points, captain_bonus, final_points, statistics_available, captain flag.
Minor extension needed: add `vice_captain_fallback_description` when fallback occurs.

### FantasyScoringCorrection — KEEP
Tracks admin corrections with reason and actor. No changes needed.

### FantasyStatisticReview — KEEP
The PENDING/APPROVED workflow is correct. No changes needed.

### NEW MODEL REQUIRED: None for v1

Auto-substitution and bonus points would require new models but are deferred.

---

---

## PART 15 — API REVIEW

### Principle: Reuse Existing APIs Where Possible

### Existing Endpoints — Assessment

**`GET /fantasy/gameweeks/{id}/points/`**
Returns all `FantasyPlayerGameweekPoints` for a gameweek via `PlayerPointsSerializer`.
This includes the `breakdown` JSON.
STATUS: EXISTS ✓ — will benefit from enhanced breakdown (rule_description) but
no endpoint changes required.

**`GET /fantasy/teams/{id}/points/`**
Returns all `FantasyTeamGameweekScore` records for a team in order.
Frontend uses this for gameweek points, season total, and breakdown.
STATUS: EXISTS ✓ — no changes required.

**`GET /fantasy/competitions/{id}/leaderboard/`**
Returns season-total leaderboard with rank applied.
STATUS: EXISTS ✓ — no changes required.

**`GET /fantasy/gameweeks/{id}/leaderboard/`**
Returns gameweek leaderboard with rank.
STATUS: EXISTS ✓ — no changes required. Frontend just needs to consume `rank` field.

**`GET /fantasy/leagues/{id}/standings/`**
Returns standings for a league with rank.
STATUS: EXISTS ✓ — no changes required.

**`POST /fantasy/gameweeks/{id}/recalculate/`**
Triggers `score_gameweek()` manually.
STATUS: EXISTS ✓ — no changes required.

**`POST /fantasy/gameweeks/{id}/finalize/`**
Finalizes a gameweek.
STATUS: EXISTS ✓ — no changes required.

**`POST /fantasy/admin/match-statistics/correct/`**
Corrects a stat value and re-runs scoring.
STATUS: EXISTS ✓ — no changes required.

**`POST /fantasy/admin/match-statistics/approve/`**
Approves a player+fixture review.
STATUS: EXISTS ✓ — no changes required.

**`GET /fantasy/admin/match-statistics/review/`** and detail
STATUS: EXISTS ✓ — no changes required for v1.

**`GET/POST/PATCH/DELETE /fantasy/admin/scoring-rules/`**
STATUS: EXISTS ✓ — PATCH to serializer validation required to support non-empty
conditions for new rule types.

### Endpoints That Need Changes (Serializer/Engine changes only)

**`POST /fantasy/admin/scoring-rules/`** — serializer must accept `rule_type`
field and validate `conditions` by rule_type.

**`GET /fantasy/gameweeks/{id}/points/`** — breakdown will contain richer data
once the scoring engine is updated (no endpoint change, richer payload).

### Genuinely Missing Endpoints

None for v1. The existing API surface covers all required functionality.

**Potential v2 additions:**
- `GET /fantasy/teams/{id}/gameweek/{gw_id}/auto-sub-preview/` — show what
  auto-substitutions would apply (v2)
- `GET /fantasy/players/{id}/history/` — player points history across all gameweeks
  (nice to have, can be derived from existing `/fantasy/gameweeks/{gw}/points/` with filter)

---

---

## PART 16 — TEST STRATEGY

The following test scenarios are specified before any implementation.
Format: INPUT → EXPECTED PLAYER POINTS → EXPECTED TEAM POINTS → EXPECTED LEADERBOARD

---

### Scoring Engine Tests

**T01: Player scores one goal (FWD position)**
- Input: GOALS=1, rule: POSITION {FWD:4}
- Player points: 4
- Team points: 4 (assuming no captain, no penalty)
- Leaderboard: team appears in rank order

**T02: Player scores two goals (FWD)**
- Input: GOALS=2, rule: POSITION {FWD:4}
- Player points: 8
- Team: 8

**T03: Player plays 30 minutes**
- Input: MINUTES_PLAYED=30, rules: BRACKET {min:1,max:59,pts:1}
- Player points: 1
- Team: 1

**T04: Player plays 60 minutes**
- Input: MINUTES_PLAYED=60, rules: BRACKET {min:60,max:null,pts:2}
- Player points: 2
- Team: 2

**T05: Player plays 90 minutes**
- Input: MINUTES_PLAYED=90, rules: BRACKET {min:60,max:null,pts:2}
- Player points: 2
- Team: 2

**T06: GK scores (goal)**
- Input: GOALS=1, player position=GK, rule: POSITION {GK:10,DEF:6,MID:5,FWD:4}
- Player points: 10
- Note: Same rule, different position → different points

**T07: DEF scores**
- Input: GOALS=1, position=DEF, same rule
- Player points: 6

**T08: MID scores**
- Input: GOALS=1, position=MID → 5 points

**T09: FWD scores**
- Input: GOALS=1, position=FWD → 4 points

**T10: Yellow card**
- Input: YELLOW_CARDS=1, rule: PER_UNIT -1
- Player points: -1

**T11: Red card**
- Input: RED_CARDS=1, rule: PER_UNIT -3
- Player points: -3

**T12: Clean sheet for GK**
- Input: CLEAN_SHEETS=1, position=GK, rule: POSITION {GK:4,DEF:4,MID:1,FWD:0}
- Player points: 4

**T13: Clean sheet for FWD**
- Input: CLEAN_SHEETS=1, position=FWD, same rule
- Player points: 0

**T14: Player has no statistics at all**
- Input: No MatchPlayerStatistic rows, no MatchLineup row
- Player points: 0, statistics_available=False
- Team: player contributes 0 if starter; labeled "Awaiting statistics"

**T15: GK makes 3 saves**
- Input: SAVES=3, rule: PER_N {per_n:3, pts:1}
- Player points: 1

**T16: GK makes 6 saves**
- Input: SAVES=6, same rule
- Player points: 2

**T17: GK makes 2 saves (below threshold)**
- Input: SAVES=2, same rule
- Player points: 0

---

### Team Scoring Tests

**T18: Captain plays, earns 10 points**
- Setup: captain_multiplier=2.0
- Player points: 10
- Captain bonus: 10 × (2-1) = 10
- Team total: (10 + ... other starters) + 10 captain_bonus - penalties

**T19: Captain does NOT play (vice_captain_fallback=True)**
- Captain: no stats, not in MatchLineup
- Vice captain: earns 8 points
- Expected: vice becomes effective captain, bonus = 8
- Captain earns 0 points, no bonus applied to captain

**T20: Captain does NOT play (vice_captain_fallback=False)**
- Expected: no captain bonus at all (captain earns 0, fallback disabled)
- Team total: sum of starters only, no bonus

**T21: Bench player plays**
- Bench player earns 7 points
- Team total: unchanged (bench not counted in v1)
- Bench points shown in breakdown as "Not counted"

**T22: Bench player does NOT play**
- Bench player points: 0, statistics_available=False

**T23: Transfer penalty — 1 extra transfer**
- competition.transfer_penalty = 4
- FantasyTeamGameweekState.transfer_penalty = 4
- Team total reduced by 4

**T24: Two extra transfers**
- State.transfer_penalty = 8
- Team total reduced by 8

**T25: Free transfer (within free allocation)**
- State.free_transfers_remaining > 0 → penalty_points = 0
- Team total: no reduction

---

### Correction and Lifecycle Tests

**T26: Statistic correction**
- Player originally scored: GOALS=0 → 0 pts
- Admin corrects GOALS to 1 → scoring re-runs → base_points=5
- correction_points = 0 (base now reflects correct stats)
- total_points = 5

**T27: Correction to player points directly (FantasyScoringCorrection)**
- Player base_points = 5
- Admin creates correction with new_value = 8
- correction_points = 8 - 5 = 3
- total_points = 8

**T28: Gameweek recalculation**
- Add ASSISTS=1 stat after initial scoring
- Recalculate → base_points increases by assists rule value
- Old correction_points preserved (relative delta)

**T29: Finalized gameweek — automatic scoring skipped**
- Status: FINALIZED
- Feed ingestion fires score_affected_gameweeks
- Task skips this gameweek
- No change to scores

**T30: Multiple gameweeks — season total**
- GW1: team scores 45 pts
- GW2: team scores 52 pts
- Season leaderboard: 97 pts total
- Rank computed by rank_rows() with configured tie_break_rules

---

### Leaderboard Tests

**T31: League ranking — tie break by total_points**
- Team A: 100 pts, Team B: 95 pts
- Rank A=1, Rank B=2

**T32: League ranking — tie break by fewer_transfer_penalties**
- Team A: 100 pts, 4 penalty
- Team B: 100 pts, 0 penalty
- rank_rows with ["total_points", "fewer_transfer_penalties"]
- Rank B=1 (fewer penalties), Rank A=2

**T33: Overall competition leaderboard vs league leaderboard**
- Same teams, same scores
- Competition leaderboard: all teams in competition
- League leaderboard: only member teams
- Both use rank_rows() with same tie_break_rules ✓

---

---

## PART 17 — IMPLEMENTATION ORDER

### Dependency-Aware Phased Plan

---

### PHASE 0 — Specification & Architecture (CURRENT PHASE)
- This document.
- No code changes.
- Review with team before proceeding.

---

### PHASE 1 — Core Scoring Engine Improvements

This is the highest-value phase. Everything downstream depends on it.

**Task 1.1 — Add `rule_type` to `FantasyScoringRule`**
- File: `fantasy/models.py`
- Change: Add `rule_type = CharField(max_length=20, choices=RuleType.choices, default='PER_UNIT')`
- Why: Required for all new rule types
- Dependencies: None
- Migration: Required (add column with default)
- Tests: T01–T17 (scoring with new rule types)
- Risk: LOW — backward compatible, existing rules default to PER_UNIT

**Task 1.2 — Update `ScoringRuleSerializer` validation**
- File: `fantasy/serializers.py`
- Change: Remove blanket conditions rejection; add per-rule-type validation
- Why: Allow POSITION, BRACKET, PER_N rules to be created via admin API
- Dependencies: Task 1.1
- Tests: Serializer validation tests for each rule type
- Risk: LOW — serializer only

**Task 1.3 — Update `score_gameweek()` engine**
- File: `fantasy/services.py`
- Change: Replace single-rule-per-stat-type dict with multi-rule list;
  add `apply_rule(rule, stat_value, player_position)` dispatcher;
  pass `player.position` to apply_rule for POSITION rules;
  collect all matching rules per stat, sum their points;
  enhance breakdown entries with `rule_type` and `rule_description`
- Why: This is the critical gap. Without this, no real scoring is possible.
- Dependencies: Task 1.1
- Tests: ALL of T01–T17
- Risk: MEDIUM — core business logic change. Must have comprehensive test coverage before merge.

**Task 1.4 — Appearance points (MINUTES_PLAYED as BRACKET rules)**
- File: `fantasy/statistics.py` — verify MINUTES_PLAYED is in all sport catalogues ✓ (it is)
- Action: Admin configures BRACKET rules for MINUTES_PLAYED per competition.
  No code change required beyond Task 1.3. This is a data/configuration task.
- Documentation: Update admin guide to explain BRACKET rule configuration.
- Dependencies: Tasks 1.1, 1.2, 1.3
- Tests: T03, T04, T05
- Risk: LOW

---

### PHASE 2 — Backend API Adjustments

**Task 2.1 — `ScoringRuleViewSet` — confirm accepts rule_type**
- File: `fantasy/views.py` (ScoringRuleViewSet)
- Change: Minimal — serializer update in Task 1.2 handles this. Verify admin
  list/create/update endpoints work with rule_type field.
- Dependencies: Task 1.2
- Tests: API integration test for rule CRUD
- Risk: LOW

**Task 2.2 — Verify leaderboard rank field consumed by frontend**
- File: `fantasy/views.py` (CompetitionViewSet.leaderboard, GameweekViewSet.leaderboard)
- Change: None to the endpoint. Frontend needs to read the `rank` field.
  Document the response shape clearly for frontend.
- Dependencies: None
- Risk: NONE

---

### PHASE 3 — Admin Scoring Interface

**Task 3.1 — Add rule_type selector to scoring rules panel**
- File: `src/pages/admin/fantasy/FantasyAdminPage.tsx`
- Change: In the "scoring" tab, add a `rule_type` dropdown (PER_UNIT, FLAT,
  BRACKET, PER_N, POSITION) and conditionally show a conditions editor.
- Existing component: The scoring rules form already shows `statistic_type`
  and `points`. Add `rule_type` between them.
- Dependencies: Task 1.2
- Tests: Manual admin test
- Risk: LOW

**Task 3.2 — Show rule_type in match statistics review breakdown**
- File: `src/pages/admin/fantasy/MatchStatisticsReview.tsx`
- Change: In the "Fantasy Scoring" breakdown table, show the rule_type column.
  The breakdown data will contain `rule_type` and `rule_description` after
  Task 1.3 is complete.
- Existing component: The breakdown table already has Statistic/Value/Rule/Points.
  Replace "Rule" column with `rule_description` (or `rule_type + points`).
- Dependencies: Task 1.3
- Risk: LOW

---

### PHASE 4 — Fan Scoring Interface

**Task 4.1 — Show per-player detailed breakdown in points drawer**
- File: `src/pages/fan/fantasy/sections/MyTeam.tsx`
- Change: In the "View points breakdown" drawer, expand per-player rows to
  show the stat-level breakdown from `breakdown.players[].stats` (once the
  backend provides richer breakdown from Task 1.3).
- Currently: per-player list shows avatar, name, club, final_points only.
- Target: show each stat row ("90 min +2", "1 goal +4") below player name.
- Dependencies: Task 1.3 (richer breakdown), Task 3.2 (confirm data shape)
- Risk: LOW

**Task 4.2 — Show gameweek rank and overall rank**
- File: `src/pages/fan/fantasy/FantasyCompetitions.tsx`
  and `src/pages/fan/fantasy/data.ts`
- Change: After loading, make an additional call to the gameweek leaderboard
  and competition leaderboard to retrieve the team's rank. Store in `FantasyTeam`
  state as `gwRank` and `overallRank`.
- Existing infrastructure: Leaderboard endpoints return `rank` field already.
- Currently: `overallRank` is always `null` in `teamFromApi()`.
- Dependencies: None (leaderboard APIs exist)
- Risk: LOW — additional API call on load

**Task 4.3 — Live vs Final indicator**
- File: `src/pages/fan/fantasy/sections/MyTeam.tsx`
- Change: Show a badge based on `competition.api.current_gameweek.status`.
  "LIVE — points updating" | "SCORING — subject to change" | "FINAL ✓"
- Dependencies: None — gameweek status already available in `competition.api`
- Risk: NONE

---

### PHASE 5 — Auto-Substitution

**Task 5.1 — Implement auto-substitution in `score_gameweek()`**
- File: `fantasy/services.py`
- Change: After scoring individual players, in the team aggregation loop,
  for each non-participating starter, find first eligible bench player by
  bench_order who DID participate and whose substitution preserves formation
  rules. Use their points instead of the starter's 0.
- Record substitutions in team score breakdown.
- Dependencies: Tasks 1.1–1.4 complete. Lineup snapshot safeguard recommended.
- Tests: T21, T22, plus new auto-sub specific tests
- Risk: HIGH — complex formation validity logic. Requires thorough test suite.

---

### PHASE 6 — Advanced Features (v2+)

- Chips (wildcard, bench boost, triple captain)
- Price fluctuations
- Bonus points system
- Player points history API
- Gameweek lineup snapshot at deadline lock

---

---

## PART 18 — FINAL DECISION TABLE

| Feature | Existing | Modify | New | Priority | Dependency |
|---|---|---|---|---|---|
| Flat scoring (PER_UNIT) | ✓ Works | rule_type label | — | P0 | None |
| Per-unit scoring | ✓ Works | rule_type label | — | P0 | None |
| Threshold scoring (BRACKET) | ✗ Missing | engine+model | — | P1 CRITICAL | rule_type field |
| Per-N scoring | ✗ Missing | engine+model | — | P1 CRITICAL | rule_type field |
| Position-based scoring | ✗ Missing | engine+serializer | — | P1 CRITICAL | rule_type field |
| Negative scoring | ✓ Works (if configured) | — | — | P0 | None |
| Appearance points | ✗ Missing | BRACKET rule config | — | P1 CRITICAL | BRACKET rule type |
| Goals | ✓ PER_UNIT works | POSITION rule | — | P1 | Position scoring |
| Assists | ✓ PER_UNIT works | — | — | P0 | None |
| Clean sheets | ✓ PER_UNIT works | POSITION rule | — | P1 | Position scoring |
| Saves | ✓ PER_UNIT exists | PER_N rule | — | P1 | PER_N rule type |
| Yellow cards | ✓ PER_UNIT (neg pts) | — | — | P0 | None |
| Red cards | ✓ PER_UNIT (neg pts) | — | — | P0 | None |
| Penalties saved | ✓ FLAT works | FLAT rule_type | — | P1 | rule_type field |
| Penalties missed | ✓ PER_UNIT (neg) | — | — | P0 | None |
| Own goals | ✓ PER_UNIT (neg) | — | — | P0 | None |
| Player breakdown | ✓ Basic | Add rule_description | — | P1 | Engine update |
| Captain | ✓ Works | — | — | P0 | None |
| Vice captain fallback | ✓ Works | — | — | P0 | None |
| Bench (points calc) | ✓ Calculated | Not counted → display | — | P1 | Frontend |
| Auto-substitution | ✗ Missing | Engine | — | P2 | Phase 5 |
| Transfer penalties | ✓ Works | — | — | P0 | None |
| Corrections | ✓ Works | — | — | P0 | None |
| Gameweek finalization | ✓ Works | — | — | P0 | None |
| Gameweek leaderboard | ✓ Works | Frontend consume rank | — | P1 | Frontend |
| Season totals | ✓ Works | — | — | P0 | None |
| Overall rank | ✓ API exists | Frontend consume | — | P1 | Frontend |
| Gameweek rank | ✓ API exists | Frontend consume | — | P1 | Frontend |
| Bonus points | ✗ Missing | — | New system | P3 | Phase 6 |
| Chips | ✗ Missing | — | New models | P3 | Phase 6 |
| Multi-sport scoring | ✓ Catalogue exists | Engine generics | — | P1 | Engine update |
| Stat review/approve | ✓ Works | — | — | P0 | None |
| Live vs final indicator | ✗ Frontend only | Frontend badge | — | P1 | Frontend |

Legend: P0=already works or trivial config, P1=Phase 1-4 work, P2=Phase 5, P3=Phase 6+

---

---

## SUMMARY

### 1. CURRENT ARCHITECTURE — What We Already Have and Should Preserve

The existing architecture is **sound and well-designed**. Do not rewrite it.

**What is already solid:**
- `FantasyCompetition` as the root config object with fully configurable squad
  rules, formation rules, captain multiplier, transfer settings, and tie-break rules.
- `FantasyGameweek` with correct DRAFT→OPEN→LOCKED→LIVE→SCORING→FINALIZED lifecycle.
- `FantasyScoringRule` with `(competition, statistic_type, conditions)` uniqueness
  — this constraint already anticipates multiple rules per stat_type.
- `score_gameweek()` as the central, idempotent, transactional scoring function.
- `FantasyPlayerGameweekPoints` tracking base, correction, and total separately.
- `FantasyTeamGameweekScore` with captain bonus, transfer penalty, and full breakdown.
- `FantasyScoringCorrection` for auditable stat corrections.
- `FantasyStatisticReview` for the admin review/approve workflow.
- Automatic scoring via Celery task (`score_affected_gameweeks`) on feed ingestion.
- Multi-sport stat catalogue (`fantasy/statistics.py`) — clean, extensible.
- Vice-captain fallback logic — already implemented and correct.
- Transfer penalty accumulation — already implemented and correct.
- Leaderboards with configurable tie-break rules — already implemented.
- Complete admin UI for competitions, players, gameweeks, scoring rules,
  match statistics review, corrections, and leaderboards.
- Fan UI for squad building, lineup, transfers, captain, leagues, and basic points view.

---

### 2. CRITICAL GAPS — What Prevents a Proper Fantasy Application Today

In priority order:

**GAP 1 (BLOCKER): No threshold/bracket rule type**
Minutes played is the most fundamental fantasy scoring stat. The current
`value × points` formula produces nonsensical results for MINUTES_PLAYED
(e.g. 90 × 2 = 180 points instead of 2 points). Without threshold rules,
appearance scoring is impossible.
Affected: `fantasy/models.py`, `fantasy/services.py`, `fantasy/serializers.py`

**GAP 2 (BLOCKER): No position-based scoring**
Goals, clean sheets, and goals conceded score differently by position in every
real fantasy application. The engine has no awareness of player position.
Affected: `fantasy/services.py` — the scoring loop does not pass position to rule evaluation.

**GAP 3 (SIGNIFICANT): Scoring engine only handles one rule per stat_type**
The rule lookup builds a `{stat_type: rule}` dict — if two rules exist for the
same stat_type (e.g. MINUTES_PLAYED with different brackets), only one survives.
Affected: `fantasy/services.py` line 11 of `score_gameweek()`.

**GAP 4 (SIGNIFICANT): Conditions field validation blocks all non-PER_UNIT rules**
`ScoringRuleSerializer` raises a ValidationError for any non-empty `conditions`
dict, preventing BRACKET, PER_N, and POSITION rules from being created.
Affected: `fantasy/serializers.py` `validate_conditions()`.

**GAP 5 (MODERATE): Player breakdown lacks rule context**
The fan breakdown drawer shows total points per player but not the rule-by-rule
explanation. This is the primary engagement feature of any fantasy product.
Affected: `fantasy/services.py` (breakdown generation) + `MyTeam.tsx` (rendering).

**GAP 6 (MODERATE): Overall rank and gameweek rank not surfaced to fan**
The APIs exist and return `rank`. The frontend sets `overallRank = null` always.
Affected: `src/pages/fan/fantasy/data.ts` `teamFromApi()`.

**GAP 7 (MINOR): No live/final status indicator in fan UI**
Fans cannot tell if their score is live, provisional, or final.
Affected: `src/pages/fan/fantasy/sections/MyTeam.tsx`.

---

### 3. MINIMUM CHANGES REQUIRED — Smallest Set for Production-Ready v1

These five changes produce a fully production-ready fantasy application:

1. **Add `rule_type` field to `FantasyScoringRule`** (+ migration)
   File: `fantasy/models.py`
   One new field, backward compatible, defaults to PER_UNIT.

2. **Update `ScoringRuleSerializer` to accept and validate new rule types**
   File: `fantasy/serializers.py`
   Remove blanket conditions rejection; add per-rule-type validation.

3. **Update `score_gameweek()` engine**
   File: `fantasy/services.py`
   - Change rule lookup to collect all rules per stat_type (list, not dict)
   - Add `apply_rule(rule, stat_value, player_position)` dispatcher
   - Pass player position into the scoring loop
   - Enhance breakdown entries with `rule_type` and `rule_description`

4. **Update admin scoring rules UI to support rule_type**
   File: `src/pages/admin/fantasy/FantasyAdminPage.tsx`
   Add rule_type selector in scoring rules form. Show conditions editor by rule type.

5. **Populate overall rank and gameweek rank in fan frontend**
   File: `src/pages/fan/fantasy/data.ts` and `FantasyCompetitions.tsx`
   Fetch leaderboard after team load; set `overallRank` and `gwRank`.

With these five changes and correctly configured rules (appearance points as
BRACKET rules, position scoring as POSITION rules, saves as PER_N rules),
the system will behave as a proper fantasy application.

---

### 4. OPTIONAL ADVANCED FEATURES — Should NOT Block v1

- Auto-substitution (Phase 5) — complex, deferred
- Chips/wildcard (Phase 6) — not requested for v1
- Bonus points system (Phase 6) — requires BPS config infrastructure
- Player price changes — not relevant to current product scope
- Lineup snapshot at deadline lock — nice safeguard, not blocking
- Player points history endpoint — derivable from existing API

---

### 5. RECOMMENDED FIRST CODING TASK

**Task: Add `rule_type` to `FantasyScoringRule` and update `score_gameweek()`**

This is the single highest-leverage change in the entire plan.
It unblocks all other improvements (position scoring, threshold scoring,
admin rule configuration, breakdown descriptions) because everything else
depends on the engine correctly dispatching by rule type.

**Exact files:**
1. `fantasy/models.py` — add `rule_type` CharField with RuleType choices
2. `fantasy/services.py` — rewrite the rule lookup and scoring loop
3. `fantasy/serializers.py` — update conditions validation by rule_type
4. `fantasy/tests/test_fantasy.py` — add tests T01–T17 before writing code

**Recommended sequence:**
1. Write failing tests for T01–T09 (position scoring) and T03–T05 (threshold)
2. Add `rule_type` to model + generate migration
3. Update serializer validation
4. Rewrite scoring loop
5. Run tests → all pass
6. Deploy → admin can now configure production-quality scoring rules

This task affects 3 backend files, requires one migration, and delivers the
most visible improvement: actual realistic fantasy scores instead of the
current linear-multiplication approximation.

---

*End of League OS Fantasy Scoring Specification & Implementation Plan*
*Document produced from live codebase inspection — no code was modified.*
