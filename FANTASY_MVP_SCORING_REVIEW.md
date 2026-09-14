# League OS Fantasy — Football MVP Scoring: Product-Level Review

> Produced: 2026-08-21
> Basis: Live codebase inspection of fantasy/models.py, fantasy/services.py,
> fantasy/serializers.py, fantasy/statistics.py, discovery/models.py,
> src/services/fantasyService.ts, src/pages/fan/fantasy/data.ts, types.ts.
> Status: REVIEW DOCUMENT — no code was modified.

---

## PART 1 — OFFICIAL FOOTBALL MVP SCORING MATRIX

All 11 statistics in `fantasy/statistics.py` are covered.
No invented statistics. Every stat listed here has a confirmed `MatchPlayerStatistic`
row path: `stat_type` is a free-text CharField(100) on the model, so any of
these codes can be stored today.


### 1.1 Complete Scoring Matrix

| Statistic | When it applies | Calc type | GK | DEF | MID | FWD | +/− | Example |
|---|---|---|---|---|---|---|---|---|
| MINUTES_PLAYED | Every appearance | BRACKET (two rules) | same | same | same | same | + | 90 min → +2 pts |
| GOALS | Per goal scored | POSITION | +10 | +6 | +5 | +4 | + | DEF scores → 6 pts |
| ASSISTS | Per assist | PER_UNIT | +3 | +3 | +3 | +3 | + | 2 assists → 6 pts |
| CLEAN_SHEETS | Per clean sheet kept | POSITION | +4 | +4 | +1 | 0 | + | GK clean sheet → 4 pts |
| SAVES | Per 3 saves (GK) | PER_N (n=3) | +1/3 | n/a | n/a | n/a | + | 6 saves → 2 pts |
| PENALTIES_SAVED | Per penalty saved | FLAT | +5 | n/a | n/a | n/a | + | 1 saved pen → 5 pts |
| PENALTIES_MISSED | Per penalty missed | PER_UNIT | −2 | −2 | −2 | −2 | − | 1 miss → −2 pts |
| GOALS_CONCEDED | Per 2 goals conceded | PER_N (n=2) | −1/2 | −1/2 | 0 | 0 | − | GK concedes 4 → −2 pts |
| YELLOW_CARDS | Per yellow card | PER_UNIT | −1 | −1 | −1 | −1 | − | 1 yellow → −1 pt |
| RED_CARDS | Per red card | PER_UNIT | −3 | −3 | −3 | −3 | − | 1 red → −3 pts |
| OWN_GOALS | Per own goal | PER_UNIT | −2 | −2 | −2 | −2 | − | 1 OG → −2 pts |


**Notes on "n/a" cells:**
- SAVES: only relevant for GK. Admin configures a POSITION rule where DEF/MID/FWD = 0,
  or simply does not create a SAVES rule for non-GK positions.
- PENALTIES_SAVED: only GK can save a penalty. Same approach — position 0 for field players
  or restrict rule to GK via POSITION type.
- GOALS_CONCEDED: Applied to GK and DEF only. MID and FWD receive 0 via POSITION rule.

**Rule type key:**
- BRACKET: fixed points when stat value falls within [min, max]
- PER_UNIT: value × points (works for integers like goals, assists, cards)
- PER_N: floor(value / n) × points (for saves, goals conceded)
- POSITION: points lookup by player position key (GK/DEF/MID/FWD)
- FLAT: fixed points when value > 0 (used for binary stats like penalties_saved)


---

## PART 2 — FANTASY DESIGN PRINCIPLES: RULE-BY-RULE JUSTIFICATION

| Rule | Why it exists | Common in fantasy? | League OS should adopt? | Data supports it today? |
|---|---|---|---|---|
| Appearance points (BRACKET) | Rewards participation, not just events. A player who plays 89 min shouldn't score 0. | Universal | YES — critical | YES: MINUTES_PLAYED stat exists |
| Position-based goals | GK/DEF goals are rare, should be worth more to reward that rarity | Universal | YES | YES: player.position available at score time |
| Assists | Rewards creativity, not just finishing | Universal | YES | YES: ASSISTS stat exists |
| Clean sheets (position-tiered) | Rewards defensive contribution; FWD clean sheet is irrelevant to FWD's role | Universal | YES | YES: CLEAN_SHEETS stat exists as player-level flag |
| Saves (PER_N) | Rewards GK shot-stopping without over-inflating for routine saves | Universal (FPL uses 3 saves = 1pt) | YES | YES: SAVES stat exists |
| Penalties saved (FLAT) | Rare, high-skill event, deserves a significant flat reward | Common | YES | YES: PENALTIES_SAVED stat exists |
| Penalties missed (negative) | Penalises wasteful finishing, creates stake in shooting accurately | Common | YES | YES: PENALTIES_MISSED stat exists |
| Goals conceded (PER_N, GK+DEF only) | Penalises defensive failures proportionally | Common | YES | YES: GOALS_CONCEDED stat exists as player-level value |
| Yellow card (negative) | Penalises reckless play | Universal | YES | YES: YELLOW_CARDS stat exists |
| Red card (negative) | Severe penalty for worst disciplinary offence | Universal | YES | YES: RED_CARDS stat exists |
| Own goals (negative) | Penalises the error directly | Universal | YES | YES: OWN_GOALS stat exists |

**Items that require new data (none for the 11 stats above):**
All 11 statistics in `FANTASY_STATISTICS["football"]` are already in the catalogue.
`MatchPlayerStatistic` can store any of them today via the free-text `stat_type` field.
The data quality question is whether the upstream feed/admin actually populates
CLEAN_SHEETS and GOALS_CONCEDED at the individual player level — see Part 6.


---

## PART 3 — THE MINUTES PROBLEM

### 3.1 Why `minutes × points` is wrong

The current engine does `stat.value × rule.points`.
For MINUTES_PLAYED, any flat-rate rule produces nonsense:
- 90 min × 0.022 = 1.98 pts (meaningless fraction, admin can never explain this)
- 1 min × 2 = 2 pts (same reward for 1 minute as a full game)
- 90 min × 2 = 180 pts (catastrophically wrong)

### 3.2 The correct bracket rule

Two separate `FantasyScoringRule` rows for MINUTES_PLAYED:

| Row | statistic_type | rule_type | conditions | points |
|---|---|---|---|---|
| 1 | MINUTES_PLAYED | BRACKET | `{"min": 1, "max": 59}` | 1 |
| 2 | MINUTES_PLAYED | BRACKET | `{"min": 60, "max": null}` | 2 |

Logic: `if min <= value AND (max is null OR value <= max): return points`

The `UniqueConstraint` on `(fantasy_competition, statistic_type, conditions)` allows
both rows to coexist because their `conditions` dicts differ.

**0 minutes case:** A player with `MINUTES_PLAYED=0` matches neither bracket.
Both rules return 0. Total appearance points = 0. Correct.

**Missing stat case:** A player with no MINUTES_PLAYED row at all scores 0
appearance points. `statistics_available` will be False if no stats exist at all.
This is correct — the system correctly marks them as "Awaiting statistics".

### 3.3 Five test examples

| Player | MINUTES_PLAYED value | Bracket 1 fires? | Bracket 2 fires? | Points |
|---|---|---|---|---|
| Did not play | 0 | No (min=1) | No (min=60) | 0 |
| Came on at 89' | 1 | YES (1≤1≤59) | No | **1** |
| Subbed off at 45' | 45 | YES (1≤45≤59) | No | **1** |
| Played exactly 60' | 60 | No (60>59) | YES (60≥60) | **2** |
| Played full 90' | 90 | No (90>59) | YES (90≥60) | **2** |

Note: a player subbed on at 60'+1 and playing to the end gets MINUTES_PLAYED=30,
which falls into bracket 1 (1 pt). This is intentional — appearance points reward
significant participation. The 60-minute threshold is the standard used by FPL
and most major fantasy products.


---

## PART 4 — POSITION-SPECIFIC GOALS

### 4.1 Reasoning for League OS values

FPL uses GK=6, DEF=6, MID=5, FWD=4. We are not bound to these.
The reasoning for each value:

**GK goal → 10 points**
A goalkeeper scoring is exceptionally rare and entertaining. The high reward
reflects that rarity and gives fans a reason to celebrate a freak result.
10 pts (rather than FPL's 6) creates a memorable spike — League OS is a local
league context where an unexpected GK goal is a talking point. High value
amplifies that moment.

**DEF goal → 6 points**
Defenders score occasionally from set pieces. 6 pts is the FPL standard and
is well-established. It rewards a significant attacking contribution from a
defensive player. League OS adopts this value.

**MID goal → 5 points**
Midfielders are the engine of the team. Goals are expected but still noteworthy.
5 pts positions them between DEF and FWD. This is the FPL standard. League OS adopts it.

**FWD goal → 4 points**
Forwards score the most goals — goals are their primary function. Lower
per-goal value balances the playing field against positions that score less
frequently but score big when they do. This is the FPL standard. League OS adopts it.

### 4.2 The POSITION rule structure

One `FantasyScoringRule` row for GOALS:
```json
{
  "statistic_type": "GOALS",
  "rule_type": "POSITION",
  "conditions": { "positions": { "GK": 10, "DEF": 6, "MID": 5, "FWD": 4 } },
  "points": 0
}
```
(`points` field is unused for POSITION rules — the points are inside `conditions.positions`)

### 4.3 Test examples

| Player | Position | Goals | Points |
|---|---|---|---|
| John (GK) | GK | 1 | 10 |
| Mike (DEF) | DEF | 1 | 6 |
| Mike (DEF) | DEF | 2 | 12 |
| Sarah (MID) | MID | 1 | 5 |
| Tom (FWD) | FWD | 1 | 4 |
| Tom (FWD) | FWD | 3 | 12 |
| GK hattrick | GK | 3 | 30 |


---

## PART 5 — CLEAN SHEETS

### 5.1 Which positions receive clean-sheet points?

| Position | Clean sheet points |
|---|---|
| GK | 4 |
| DEF | 4 |
| MID | 1 |
| FWD | 0 |

**Reasoning:** GK and DEF are directly responsible for defensive solidity.
MID gets a reduced reward (1pt) because midfielders contribute defensively but
it is not their primary role. FWD gets nothing — clean sheets are outside
their remit and awarding points here would confuse fans.

This matches the FPL standard and is adopted by League OS.

### 5.2 Minimum minutes required

**60 minutes.**

A clean sheet only counts if the player was on the pitch for the majority of
the game. If a player is substituted off at minute 59 and the team keeps a
clean sheet, they do NOT receive clean sheet points.

**Implementation note:** This is a CONDITIONAL rule (MINUTES_PLAYED ≥ 60 AND
CLEAN_SHEETS = 1). The current architecture cannot express cross-statistic
conditions in v1. There are two safe approaches:

**Option A (MVP — recommended):** The admin / data pipeline is responsible for
populating CLEAN_SHEETS=1 ONLY for players who played 60+ minutes. The scoring
engine applies the POSITION rule to CLEAN_SHEETS as a simple stat value.
No cross-statistic logic needed. The rule is: if CLEAN_SHEETS stat exists and
equals 1 → award position points. The data layer enforces the 60-min gate.

**Option B (v2):** Implement a conditional rule type that evaluates
`if MINUTES_PLAYED >= 60 and CLEAN_SHEETS == 1`. Deferred.

**Recommendation: Option A for MVP.** Document clearly in the admin guide that
CLEAN_SHEETS=1 should only be entered/ingested for players who met the 60-min threshold.

### 5.3 Substitution scenarios

| Scenario | Gets clean sheet? | Why |
|---|---|---|
| Starter plays full 90 min, team keeps clean sheet | YES | 90 min ≥ 60 min threshold |
| Starter subbed off at 59 min, team keeps clean sheet | NO | Data pipeline sets CLEAN_SHEETS=0 for this player |
| Starter subbed off at 61 min, team keeps clean sheet | YES | 61 min ≥ 60 min threshold |
| Bench player comes on at 80 min, team keeps clean sheet | NO | Only 10 min played, below threshold |
| Player enters late (sub at 60+1), team keeps clean sheet | NO | < 30 min played, below threshold |
| GK plays full match, team concedes in 90+3 | NO | Team did not keep clean sheet |

### 5.4 Data sufficiency

`CLEAN_SHEETS` is listed in `FANTASY_STATISTICS["football"]` and can be stored
as a `MatchPlayerStatistic` row with `value=1` or `value=0`. The architecture
supports it. The data quality requirement is that the feed or admin correctly
sets this per player respecting the 60-minute gate.


---

## PART 6 — GOALS CONCEDED

### 6.1 The two options

**Option A: Direct player statistic**
Store `GOALS_CONCEDED=N` on each relevant player's `MatchPlayerStatistic` row.
The scoring engine applies the PER_N rule: `floor(N / 2) × −1`.

**Option B: Derive from fixture result**
Use `MatchCentre.home_score` / `away_score` to determine how many goals the
GK's team conceded, then compute points in the scoring engine.

### 6.2 Decision: Option A is safer for MVP

**Reasons:**

1. **Consistency:** The entire scoring engine is built on `MatchPlayerStatistic`
   rows. Introducing a derivation from `MatchCentre` scores would require the
   engine to join across models and know which team each player belongs to.
   This is a significant increase in engine complexity.

2. **The model already supports it:** `GOALS_CONCEDED` is in
   `FANTASY_STATISTICS["football"]`. The stat can be stored as-is.

3. **Partial participation:** Option B gives the same goals_conceded count to
   a GK who played 10 minutes and one who played 90 minutes. With Option A,
   the data pipeline can store different values per player reflecting when they
   were on the pitch.

4. **No duplication risk:** We are not storing the match result twice —
   `MatchCentre.home_score`/`away_score` stores the team result; GOALS_CONCEDED
   on `MatchPlayerStatistic` stores the player-level fantasy stat. These are
   different purposes.

**Data quality requirement:** The admin or feed must populate `GOALS_CONCEDED=N`
correctly per player. This is a data operations concern, not an architecture concern.

### 6.3 Scoring formula

One `FantasyScoringRule` row:
```json
{
  "statistic_type": "GOALS_CONCEDED",
  "rule_type": "PER_N",
  "conditions": { "per_n": 2 },
  "points": -1
}
```

Result: `floor(goals_conceded / 2) × −1`

| Goals conceded | Points |
|---|---|
| 0 | 0 |
| 1 | 0 |
| 2 | −1 |
| 3 | −1 |
| 4 | −2 |
| 5 | −2 |
| 6 | −3 |

Only applies to GK and DEF. MID and FWD get 0 — implement via POSITION rule
(positions: {GK: −0.5, DEF: −0.5, MID: 0, FWD: 0} per-N).

**Cleaner approach:** Create GOALS_CONCEDED as a POSITION rule where GK and DEF
receive −1 per 2 (use PER_N with positions overlay). Since PER_N and POSITION
are separate rule types, for v1 the simplest option is to configure only one
GOALS_CONCEDED PER_N rule and rely on the data pipeline to only populate
GOALS_CONCEDED for GK and DEF players. MID and FWD simply never receive a
GOALS_CONCEDED stat row, so the rule never fires for them.


---

## PART 7 — ASSISTS

### 7.1 What constitutes an assist?

An assist is an official attribution to the player whose pass or action directly
led to a goal. There is no ambiguity definition engine to build here because:

**League OS does NOT define assists.** The upstream data source defines them.

When the admin enters `ASSISTS=1` for a player via the match statistics panel,
or the external feed ingests `ASSISTS=1`, that is the canonical fact. The
scoring engine applies the rule to whatever value the stat has.

**Do not implement an assist-definition engine.** This would be re-implementing
the responsibility of the data provider. If the admin or feed says a player had
1 assist, the engine trusts that.

### 7.2 What the system receives

Confirmed from `fantasy/statistics.py`: `"ASSISTS": "Assists"` is in the
football catalogue. The admin can enter it via `POST /fantasy/admin/match-statistics/`
and the external feed can write it to `MatchPlayerStatistic`.

**Recommended rule:**
```json
{
  "statistic_type": "ASSISTS",
  "rule_type": "PER_UNIT",
  "conditions": {},
  "points": 3
}
```

3 points per assist. Same for all positions. Reasoning: an assist is a positive
contribution regardless of position. 3 pts is the FPL standard and is well understood.

---

## PART 8 — SAVES

### 8.1 Scoring formula

Every 3 saves = 1 point.

```json
{
  "statistic_type": "SAVES",
  "rule_type": "PER_N",
  "conditions": { "per_n": 3 },
  "points": 1
}
```

Formula: `floor(saves / 3) × 1`

### 8.2 Rounding examples

| Saves | Calculation | Points |
|---|---|---|
| 0 | floor(0/3) = 0 | 0 |
| 1 | floor(1/3) = 0 | 0 |
| 2 | floor(2/3) = 0 | 0 |
| 3 | floor(3/3) = 1 | **1** |
| 4 | floor(4/3) = 1 | **1** |
| 5 | floor(5/3) = 1 | **1** |
| 6 | floor(6/3) = 2 | **2** |
| 7 | floor(7/3) = 2 | **2** |
| 8 | floor(8/3) = 2 | **2** |
| 9 | floor(9/3) = 3 | **3** |

**Rounding rule:** Always floor (integer division). Never round up.
A GK who makes 5 saves gets 1 pt, not 2. This is standard.

### 8.3 Why PER_N not PER_UNIT?

`PER_UNIT` would give 5 saves × 1 = 5 pts. That would over-reward shot-stopping
and trivialise the stat. PER_N prevents inflation while still rewarding a
busy GK.


---

## PART 9 — NEGATIVE EVENTS

### 9.1 Yellow Card

**Rule:** −1 point per yellow card.
```json
{ "statistic_type": "YELLOW_CARDS", "rule_type": "PER_UNIT", "conditions": {}, "points": -1 }
```

Applies to all positions equally. A yellow card is a disciplinary offence
regardless of position.

### 9.2 Red Card

**Rule:** −3 points per red card.
```json
{ "statistic_type": "RED_CARDS", "rule_type": "PER_UNIT", "conditions": {}, "points": -3 }
```

### 9.3 The Double-Yellow / Red Card Stacking Question

**Scenario:** A player receives two yellow cards. The second yellow triggers
an automatic red card. The data pipeline typically stores:
`YELLOW_CARDS=2, RED_CARDS=1` OR `YELLOW_CARDS=1, RED_CARDS=1`.

**League OS decision:**

This depends entirely on what the upstream feed/admin enters. Two rules apply:

**If the data source stores YELLOW_CARDS=2 and RED_CARDS=1:**
- YELLOW_CARDS rule fires: 2 × −1 = −2
- RED_CARDS rule fires: 1 × −3 = −3
- Total: −5 pts

**If the data source stores YELLOW_CARDS=1 and RED_CARDS=1 (FPL convention):**
- YELLOW_CARDS: 1 × −1 = −1
- RED_CARDS: 1 × −3 = −3
- Total: −4 pts

**Recommendation:** Adopt the FPL convention for consistency.
When a player receives a second yellow (leading to red), store:
`YELLOW_CARDS=1, RED_CARDS=1`.
The yellow card penalty stacks with the red card penalty: **−4 total**.
This is the most common approach and is what fans expect.

Document this clearly in the admin statistics entry guide so manual entries
follow the convention.

### 9.4 Own Goal

**Rule:** −2 points per own goal.
```json
{ "statistic_type": "OWN_GOALS", "rule_type": "PER_UNIT", "conditions": {}, "points": -2 }
```

Applies to all positions. An own goal is a significant error that directly
harms the team.

### 9.5 Penalty Miss

**Rule:** −2 points per penalty missed.
```json
{ "statistic_type": "PENALTIES_MISSED", "rule_type": "PER_UNIT", "conditions": {}, "points": -2 }
```

Applies to all positions (any player can take a penalty). The penalty miss
is always a negative event — even if the team scores from the rebound, the
original miss should still cost points.

### 9.6 Summary of all negative rules

| Event | Rule type | Points | Stacking note |
|---|---|---|---|
| Yellow card | PER_UNIT | −1 | Stacks with red if second yellow |
| Red card | PER_UNIT | −3 | Stacks with yellow |
| Own goal | PER_UNIT | −2 | Stacks per own goal |
| Penalty miss | PER_UNIT | −2 | Stacks per miss |
| Goals conceded (GK/DEF) | PER_N (n=2) | −1 per 2 | See Part 6 |


---

## PART 10 — CORRECTIONS

### 10.1 How the correction architecture works today

Verified from `fantasy/services.py`:

```python
latest = record.corrections.order_by("created_at", "id").last()
correction = (latest.new_value - base_points) if latest else Decimal("0")
record.base_points = base
record.correction_points = correction
record.total_points = base + correction
```

The correction is a **delta**: `correction_points = new_value - base_points`.
When `score_gameweek()` re-runs (e.g. after new stats arrive), `base_points`
is recalculated from current stats. The latest correction's `new_value` remains
anchored, so `correction_points` adjusts to compensate.

### 10.2 Concrete example

**Initial state:**

Admin enters: Player A, GOALS=1, ASSISTS=0.
Rules: GOALS POSITION (FWD=4), ASSISTS PER_UNIT 3, MINUTES_PLAYED BRACKET 60+=2.
Assume player played 90 minutes.

```
base_points  = GOALS(1×4) + MINUTES_PLAYED(bracket→2) = 6
correction   = 0
total_points = 6
```

Team with Player A as starter, no captain bonus, no penalty:
`team.total_points = 6`

Leaderboard: Team A at 6 pts.

**Admin correction: GOALS was actually 2 (VAR confirmed second goal)**

Admin calls `POST /fantasy/admin/match-statistics/correct/` with `stat_id=goals_row, value=2`.
This updates `MatchPlayerStatistic.value` to 2 and re-runs `score_gameweek()`.

```
base_points  = GOALS(2×4) + MINUTES_PLAYED(bracket→2) = 10
```

No existing correction on this player, so `correction_points = 0`.
```
total_points = 10
```

Team recalculated:
`team.total_points = 10`

**Net change:** +4 pts to the player and team.

Leaderboard: Team A moves up from 6 pts to 10 pts. All other teams unchanged.
Re-ranking runs via `rank_rows()` — confirmed in `services.py`.

**If admin previously applied a `FantasyScoringCorrection` directly
(e.g. `new_value=8`):**
After stat correction re-runs base to 10, `correction_points = 8 - 10 = -2`.
`total_points = 8`. The manual correction anchors the total at 8 regardless
of what the stats compute.

### 10.3 Architecture verdict

The correction architecture is **sufficient and correct** for v1.
The `FantasyScoringCorrection.new_value` acts as an anchor. The stat correction
path updates raw data and re-scores. Both paths are idempotent. No changes needed.


---

## PART 11 — CAPTAIN / VICE CAPTAIN

### 11.1 Confirmed desired behavior

| Scenario | Behavior |
|---|---|
| Captain plays any minutes | Captain gets ×`captain_multiplier` (default ×2). Bonus = captain.total_points × (multiplier − 1) |
| Captain plays exactly 1 minute | Captain DOES count. 1 minute = participation confirmed. No minimum. |
| Captain does not play, vice_captain_fallback=True, vice plays | Vice becomes effective captain. Vice gets the multiplier bonus. Captain gets 0. |
| Captain does not play, vice_captain_fallback=True, vice also doesn't play | No captain bonus at all. |
| Captain does not play, vice_captain_fallback=False | No captain bonus at all. |
| Neither plays | No captain bonus. |

This is confirmed from `services.py` lines:
```python
if (captain and vice
    and gameweek.fantasy_competition.vice_captain_fallback
    and not _participated(gameweek, captain.fantasy_player)
    and _participated(gameweek, vice.fantasy_player)):
    effective_captain, fallback = vice, True
```

### 11.2 How participation is determined

`_participated(gameweek, fantasy_player)` checks:

1. Does a `MatchPlayerStatistic` row exist for this player in any fixture
   assigned to the gameweek? → Participated.
2. OR does a `MatchLineup` row exist for this player? → Participated.

**This means:** A player who appears in the lineup but has zero stats (e.g.
was named in the XI but the stats weren't entered yet) IS counted as participated
via the MatchLineup check. This is correct — if they're in the lineup sheet,
they were available.

**Edge case:** A player who played 1 minute and has MINUTES_PLAYED=1 in stats
will be caught by check #1. A player who has a lineup entry but no stats will
be caught by check #2. Either way, the captain logic works correctly.

**No change needed to `_participated()` for v1.**

### 11.3 Frontend type confirmation

`FantasyTeam.captainId` and `FantasyTeam.viceCaptainId` are populated correctly
from `row.selections.find(s => s.is_captain)` in `data.ts`. No changes needed.
The `FantasyPlayerScoreBreakdown` already has a `captain: boolean` field which
the frontend can use to show the captain indicator.


---

## PART 12 — BENCH / AUTO-SUBSTITUTION

### 12.1 Decision: DEFER auto-substitution

**For MVP, bench works as follows:**
- Bench player points ARE calculated and stored in `FantasyPlayerGameweekPoints`.
- Bench player points do NOT count toward `FantasyTeamGameweekScore.total_points`.
- No automatic substitution occurs if a starter does not play.
- A starter who does not play contributes 0 pts. No replacement happens.

This is confirmed by the current `services.py` implementation where only
`is_starter=True` selections are iterated in the team scoring loop.

### 12.2 What the fan sees

- Bench players show their points in the bench strip (already rendered in `MyTeam.tsx`).
- Bench points are labeled "Not counted" — already implemented.
- No indication of "would have auto-subbed" — this is v2.

### 12.3 Prerequisites for future auto-substitution

Auto-substitution can only be safely built when:

1. The scoring engine supports the `rule_type` extensions (Part 17, Phase 1).
   Formation validity check needs position-aware player data.
2. A lineup snapshot is taken at deadline lock time (to prevent retroactive
   lineup changes affecting auto-sub eligibility).
3. Formation rules validation is extracted into a reusable function that can
   be called from within `score_gameweek()` to test the post-sub lineup.
4. A suite of tests covers all multi-substitution edge cases (e.g. two starters
   don't play, two bench players available, but only one sub maintains a legal formation).

**Do not implement auto-substitution in Phase 1.**

---

## PART 13 — BONUS POINTS

### 13.1 Decision: DEFER to v3

Bonus points require:
1. A performance-score weighting formula per sport (e.g. goal=32 BPS, assist=24 BPS).
2. A per-fixture ranking job that runs after all stats are entered.
3. A new model or field to store bonus points separately from base points.
4. Tie-breaking logic for equal BPS scores.

None of this infrastructure exists today. Building it would double the complexity
of Phase 1 without materially improving the fan experience for launch.

**The absence of bonus points does not prevent launch.** FPL has them; League OS
does not need to match FPL exactly.

**Verdict:** Bonus points are a v3 feature. Do not implement in v1 or v2.


---

## PART 14 — CHIPS / BOOSTERS

### 14.1 Decision: NOT in MVP

| Chip | MVP? | Reason |
|---|---|---|
| Triple captain (×3 instead of ×2) | NO | Requires per-gameweek chip state, one-per-season enforcement |
| Bench boost (count all bench players) | NO | Requires auto-sub infrastructure first |
| Wildcard (free unlimited transfers) | NO | Requires transfer system override, state tracking |
| Free hit (temporary wildcard squad) | NO | Requires temporary squad snapshot separate from main squad |

None of these require data the system doesn't have — they are pure logic features.
But each one introduces state that must be tracked per team per season, validated
on use (once-per-season limits), and respected during scoring.

**These do NOT block the scoring system.** The `captain_multiplier` field on
`FantasyCompetition` already supports configuring the multiplier value; a future
"triple captain chip" would temporarily override it for one team for one gameweek.
That override path does not exist yet.

**Verdict:** Chips are a v2+ feature. The scoring architecture does not need
to account for them in v1.

---

## PART 15 — MULTI-SPORT ARCHITECTURE

### 15.1 The key question

Will `score_gameweek()` need to be rewritten when basketball and rugby are added?

**No — with the proposed architecture.**

### 15.2 How the generic engine works

The engine is already sport-agnostic in its loop structure:
```python
for player in competition.player_pool.all():
    stats = MatchPlayerStatistic.objects.filter(...)
    for stat in stats:
        rule = rules.get(stat.stat_type.upper())
        if rule:
            points = stat.value * rule.points
```

After the v1 changes, the loop becomes:
```python
for player in competition.player_pool.all():
    stats = MatchPlayerStatistic.objects.filter(...)
    for stat in stats:
        applicable_rules = rules_for_stat(stat.stat_type.upper(), player.position)
        for rule in applicable_rules:
            points = apply_rule(rule, stat.value, player.position)
```

`rules_for_stat()` and `apply_rule()` dispatch by `rule_type`.
They contain no sport-specific logic. The sport-specific logic is entirely
in the `FantasyScoringRule` configuration rows created by the admin.

### 15.3 Sport-specific examples that prove the architecture works

**Football GOALS:**
`FantasyScoringRule`: GOALS, POSITION, `{"positions": {"GK":10,"DEF":6,"MID":5,"FWD":4}}`

**Basketball POINTS:**
`FantasyScoringRule`: POINTS, PER_N, `{"per_n": 2}`, points=1

**Rugby TRIES:**
`FantasyScoringRule`: TRIES, PER_UNIT, points=10

The engine's `apply_rule()` function handles all of these without knowing what sport
it is scoring. `score_gameweek()` does not need a `if sport == "football"` branch.

### 15.4 The position codes are competition-specific

Football uses: GK, DEF, MID, FWD
Basketball uses: PG, SG, SF, PF, C
Rugby uses: FR, LK, BR, HB, CT, B3

All confirmed in `types.ts`. The POSITION rule's `conditions.positions` dict
uses whatever keys the competition's `position_rules` defines. No hardcoding.

**Verdict:** The architecture correctly supports multi-sport without engine rewrites.


---

## PART 16 — FINAL DATA MODEL RECOMMENDATION

### 16.1 FantasyScoringRule — the only model that needs a new field

**Existing fields (confirmed from models.py):**

| Field | Type | Current state |
|---|---|---|
| `id` | UUIDField (PK) | Keep |
| `fantasy_competition` | FK → FantasyCompetition | Keep |
| `statistic_type` | CharField(50) | Keep |
| `points` | DecimalField(8,2) | Keep — used by PER_UNIT, PER_N, BRACKET, FLAT; unused (0) for POSITION |
| `conditions` | JSONField(default=dict) | Keep — schema varies by rule_type |
| `enabled` | BooleanField | Keep |
| `created_at`, `updated_at` | DateTimeField | Keep |

**New field to add:**

| Field | Type | Choices | Default | Validation |
|---|---|---|---|---|
| `rule_type` | CharField(20) | PER_UNIT, FLAT, BRACKET, PER_N, POSITION | `PER_UNIT` | Required; must be in choices |

**Why only this one field?**

The `conditions` JSONField already exists and its schema varies by rule_type.
Adding separate `min_value`, `max_value`, `per_n` columns would widen the model
with many nullable fields. The `conditions` JSON is the right home for these
parameters because the `UniqueConstraint` on `(competition, statistic_type, conditions)`
already differentiates rules by their condition parameters — this is by design.

### 16.2 conditions JSON schema by rule_type

| rule_type | conditions schema | points field role |
|---|---|---|
| `PER_UNIT` | `{}` (empty) | value × points |
| `FLAT` | `{}` (empty) | awarded if value > 0 |
| `BRACKET` | `{"min": int, "max": int or null}` | awarded if min ≤ value ≤ max (max=null = no upper bound) |
| `PER_N` | `{"per_n": int}` | floor(value / per_n) × points |
| `POSITION` | `{"positions": {"GK": num, "DEF": num, ...}}` | unused (0); position lookup provides points |

### 16.3 Validation rules

- `rule_type` must be one of the five choices. No other values accepted.
- For `BRACKET`: `conditions.min` must be int ≥ 0; `conditions.max` must be int > min or null.
- For `PER_N`: `conditions.per_n` must be int ≥ 1.
- For `POSITION`: `conditions.positions` must be a dict; keys must be valid for the competition's
  `position_rules`; values must be numeric.
- For `PER_UNIT` and `FLAT`: `conditions` must be empty `{}`.
- Remove the existing blanket rejection of non-empty conditions in `ScoringRuleSerializer`.
  Replace with per-rule-type validation as above.
- The `points` field: for POSITION rules, `points` should be 0 (convention); validation
  should warn but not error if a non-zero value is provided (it will be ignored).

### 16.4 UniqueConstraint behavior with new rules

The existing constraint `(fantasy_competition, statistic_type, conditions)` is preserved.
Two MINUTES_PLAYED rules can coexist:
- Row 1: `(comp, MINUTES_PLAYED, {"min":1,"max":59})` — unique ✓
- Row 2: `(comp, MINUTES_PLAYED, {"min":60,"max":null})` — unique ✓

**No constraint changes needed.**

### 16.5 Migration required

```python
# Migration: Add rule_type with default PER_UNIT
# Backward compatible: all existing rules remain valid as PER_UNIT
migrations.AddField(
    model_name='fantasyscordingrule',
    name='rule_type',
    field=models.CharField(
        max_length=20,
        choices=[
            ('PER_UNIT', 'Per unit'),
            ('FLAT', 'Flat'),
            ('BRACKET', 'Bracket'),
            ('PER_N', 'Per N units'),
            ('POSITION', 'Position-based'),
        ],
        default='PER_UNIT',
    ),
)
```


---

## PART 17 — FINAL SCORING ENGINE DESIGN

### 17.1 `apply_rule()` pseudocode

```
function apply_rule(rule, stat_value, player_position):

    if rule.rule_type == PER_UNIT:
        return stat_value × rule.points

    if rule.rule_type == FLAT:
        if stat_value > 0:
            return rule.points
        return 0

    if rule.rule_type == BRACKET:
        min_v = rule.conditions["min"]          # always present, int ≥ 0
        max_v = rule.conditions.get("max")      # None = no upper bound
        if stat_value >= min_v AND (max_v is None OR stat_value <= max_v):
            return rule.points
        return 0

    if rule.rule_type == PER_N:
        n = rule.conditions["per_n"]            # int ≥ 1
        return floor(stat_value / n) × rule.points

    if rule.rule_type == POSITION:
        pts = rule.conditions["positions"].get(player_position, 0)
        return stat_value × Decimal(pts)        # pts is the per-unit value for this position

    return 0  # unknown rule_type — safe default
```

### 17.2 `score_gameweek()` pseudocode

```
function score_gameweek(gameweek):

    fixture_ids = gameweek.fixtures.all().ids

    # Load ALL enabled rules (not just conditions={})
    # Group by statistic_type → list of rules (multiple rules per stat now possible)
    all_rules = FantasyScoringRule
        .filter(fantasy_competition=gameweek.competition, enabled=True)
    rules_by_stat = group_by(all_rules, key=stat_type.upper())
    # e.g. {"MINUTES_PLAYED": [bracket1, bracket2], "GOALS": [position_rule], ...}

    # ── PLAYER SCORING ──────────────────────────────────────────────────────
    for player in gameweek.competition.player_pool.all():

        stats = MatchPlayerStatistic
            .filter(match_centre.fixture_id in fixture_ids, participant=player.player)

        base = Decimal("0")
        breakdown = []

        for stat in stats:
            applicable_rules = rules_by_stat.get(stat.stat_type.upper(), [])
            for rule in applicable_rules:
                pts = apply_rule(rule, stat.value, player.position)
                if pts != 0:
                    base += pts
                    breakdown.append({
                        "statistic_type": stat.stat_type,
                        "value": stat.value,
                        "rule_type": rule.rule_type,
                        "rule_description": describe_rule(rule, player.position),
                        "points": pts,
                    })

        # Fetch latest manual correction anchor
        record = get_or_create FantasyPlayerGameweekPoints(gameweek, player)
        latest_correction = record.corrections.last()
        correction = (latest_correction.new_value - base) if latest_correction else 0

        record.base_points = base
        record.correction_points = correction
        record.total_points = base + correction
        record.breakdown = breakdown
        record.statistics_available = stats.exists()
        record.save()

    # ── TEAM SCORING ─────────────────────────────────────────────────────────
    for team in gameweek.competition.teams.all():

        starters = team.selections.filter(is_starter=True)

        # Determine effective captain (vice fallback if needed)
        captain = starters.find(is_captain=True)
        vice = starters.find(is_vice_captain=True)
        effective_captain = captain
        fallback = False
        if vice_captain_fallback AND captain is not None AND vice is not None:
            if NOT participated(gameweek, captain) AND participated(gameweek, vice):
                effective_captain = vice
                fallback = True

        # ── [FUTURE AUTO-SUB HOOK] ──────────────────────────────────────
        # for each non-participating starter (in position order):
        #     find first bench player (by bench_order) who participated
        #     and whose substitution maintains a valid formation
        #     replace starter with bench player in the effective lineup
        # ── [END FUTURE AUTO-SUB HOOK] ──────────────────────────────────

        total_player_points = Decimal("0")
        captain_bonus = Decimal("0")
        detail = []

        for selection in starters:
            pts_record = FantasyPlayerGameweekPoints.get(gameweek, selection.player)
            points = pts_record.total_points if pts_record else 0
            total_player_points += points

            player_captain_bonus = Decimal("0")
            if selection == effective_captain:
                captain_bonus = points × (competition.captain_multiplier - 1)
                player_captain_bonus = captain_bonus

            detail.append({
                player_id, player_name, position,
                base_points, correction_points,
                captain_bonus: player_captain_bonus,
                final_points: points + player_captain_bonus,
                statistics_available: pts_record.statistics_available,
                captain: (selection == effective_captain),
            })

        transfer_penalty = get_gameweek_state(team, gameweek).transfer_penalty

        FantasyTeamGameweekScore.update_or_create(
            team=team,
            gameweek=gameweek,
            defaults={
                player_points: total_player_points,
                captain_bonus: captain_bonus,
                transfer_penalty: transfer_penalty,
                total_points: total_player_points + captain_bonus - transfer_penalty,
                breakdown: { players: detail, vice_captain_fallback: fallback, ... },
            }
        )

    return gameweek
```

### 17.3 `describe_rule()` helper

```
function describe_rule(rule, player_position):
    if rule.rule_type == POSITION:
        pts = rule.conditions["positions"].get(player_position, 0)
        return f"{player_position} {rule.statistic_type.lower().replace('_', ' ')} (+{pts})"
        # e.g. "GK goal (+10)" or "DEF clean sheet (+4)"

    if rule.rule_type == BRACKET:
        min_v = rule.conditions["min"]
        max_v = rule.conditions.get("max")
        if max_v:
            return f"{min_v}–{max_v} minutes played"
        else:
            return f"{min_v}+ minutes played"

    if rule.rule_type == PER_N:
        return f"per {rule.conditions['per_n']} {rule.statistic_type.lower()}"
        # e.g. "per 3 saves"

    # PER_UNIT or FLAT
    return rule.statistic_type.replace("_", " ").title()
```


---

## PART 18 — EXACT IMPLEMENTATION PLAN

### PHASE 1 — Backend scoring rule model + engine
**The critical path. Everything else depends on this.**

---

**Task 1.1 — Add `rule_type` to `FantasyScoringRule`**

- File: `fantasy/models.py`
- Change: Add `RuleType` TextChoices inner class with 5 values.
  Add `rule_type = CharField(max_length=20, choices=RuleType.choices, default='PER_UNIT')`.
- Migration: Required. One column, backward-compatible default.
- Tests: Model field presence; default value for existing records.

---

**Task 1.2 — Update `ScoringRuleSerializer`**

- File: `fantasy/serializers.py`
- Change: Remove `validate_conditions()` blanket rejection.
  Add per-rule-type validation of `conditions` JSON schema.
  Add `rule_type` to serializer fields.
- Migration: None.
- Tests: Serializer accepts BRACKET, PER_N, POSITION rules with valid conditions.
  Rejects malformed conditions (e.g. BRACKET without `min`, PER_N with per_n=0).

---

**Task 1.3 — Update `score_gameweek()` engine**

- File: `fantasy/services.py`
- Changes:
  1. Replace `rules = {type: rule for rule in ...filter(conditions={})}` with
     `rules_by_stat = group_by(all_rules, key=stat_type)` — no conditions filter.
  2. Add `apply_rule(rule, stat_value, player_position)` function.
  3. Add `describe_rule(rule, player_position)` function.
  4. In the stat scoring loop: iterate all applicable rules per stat; call
     `apply_rule()`; sum points; append enhanced breakdown entry.
  5. Pass `player.position` into the loop.
- Migration: None.
- Tests: ALL tests T01–T17 from the existing spec, plus new tests for
  BRACKET edge cases (0 min, 59 min, 60 min, 90 min), PER_N rounding (saves),
  POSITION dispatch (all 4 positions for GOALS), FLAT (penalties_saved > 0),
  negative rules stacking.

---

**Task 1.4 — Update frontend `FantasyScoringRule` type**

- File: `src/services/fantasyService.ts`
- Change: Add `rule_type` field to `FantasyScoringRule` interface.
  Change `conditions: Record<string, never>` to `conditions: Record<string, unknown>`.
- Migration: None.
- Tests: None required (type-only change; TypeScript will verify).

---

### PHASE 2 — Admin Scoring Configuration UI

---

**Task 2.1 — Add rule_type selector to scoring rules panel**

- File: `src/pages/admin/fantasy/FantasyAdminPage.tsx`
- Change: In the "scoring" tab form for creating/editing scoring rules:
  Add `<select>` for `rule_type` (PER_UNIT, FLAT, BRACKET, PER_N, POSITION).
  Conditionally show a `conditions` editor pane depending on selected rule_type:
  - BRACKET: show `min` (number input) and `max` (number input + "no upper bound" checkbox)
  - PER_N: show `per_n` (integer input)
  - POSITION: show one numeric input per position defined in `competition.position_rules`
  - PER_UNIT / FLAT: no conditions inputs needed
- Migration: None.
- Tests: Manual admin test with each rule type.

---

**Task 2.2 — Show rule_type in match statistics review breakdown**

- File: `src/pages/admin/fantasy/MatchStatisticsReview.tsx`
- Change: Expand the "Fantasy Scoring" breakdown table to show
  `rule_description` (from the enhanced breakdown JSON) instead of the
  current plain "× N pts" column. Show player position in the detail header.
- Depends on: Task 1.3 (richer breakdown from engine).
- Migration: None.
- Tests: Manual review — verify GK goal shows "GK goal (+10)" not "× 10.00 pts".

---

### PHASE 3 — Tests

---

**Task 3.1 — Backend scoring engine tests**

- File: `fantasy/tests/test_scoring_engine.py` (new file or extend existing)
- Tests to write:
  - T01–T09: position-based goals (all 4 positions)
  - T03–T05: appearance brackets (0, 1, 30, 59, 60, 90 minutes)
  - T10–T11: yellow/red card negative scoring
  - T12–T13: clean sheet with position (GK=4, FWD=0)
  - T14: player with no stats (statistics_available=False)
  - T15–T17: saves PER_N (2, 3, 5, 6, 7 saves)
  - T18–T25: team scoring (captain, fallback, bench exclusion, transfer penalty)
  - T26–T28: corrections workflow
  - T29–T30: finalized gameweek skip, season totals
  - Red card stacking (yellow + red = −4)
  - Goals conceded PER_N (0, 1, 2, 3, 4 goals)
- Migration: None.
- Rule: Write tests BEFORE implementing Task 1.3.

---

### PHASE 4 — Fan Scoring Interface

---

**Task 4.1 — Show per-player stat breakdown in points drawer**

- File: `src/pages/fan/fantasy/sections/MyTeam.tsx`
- Change: In the "View points breakdown" drawer, expand per-player rows to
  show each stat entry from `breakdown.players[].stats` using `rule_description`.
  Show subtotal per player. Show captain bonus line when `captain=true`.
- Depends on: Task 1.3 (richer breakdown). Backend provides it; frontend renders it.
- Migration: None.
- Tests: Visual/manual.

---

**Task 4.2 — Populate `overallRank` and add `gwRank`**

- File: `src/pages/fan/fantasy/data.ts`
- Change: `teamFromApi()` currently hardcodes `overallRank: null`.
  After loading team points, make an additional call to
  `fetchCompetitionLeaderboard(competition.id)` and find the team's `rank`.
  Set `overallRank` from the result.
- File: `src/pages/fan/fantasy/FantasyCompetitions.tsx`
  Add call to `fetchGameweekLeaderboard()` for the current gameweek to
  retrieve `gwRank`.
- Migration: None.
- Tests: Verify that rank is shown on the team stat row.

---

**Task 4.3 — Live vs Final indicator**

- File: `src/pages/fan/fantasy/sections/MyTeam.tsx`
- Change: Read `competition.api.current_gameweek.status`. Show:
  - LIVE → "Live — points updating"
  - SCORING → "Scoring — subject to change"
  - FINALIZED → "Final ✓"
  - Other statuses → no indicator (or hide points section)
- Migration: None.
- Tests: Visual/manual.

---

### PHASE 5 — Auto-Substitution (deferred)

See Part 12 for prerequisites. Do not begin until Phases 1–4 are complete
and stable in production.

---

### PHASE 6 — Advanced Features (v2+)

- Chips (wildcard, bench boost, triple captain, free hit)
- Bonus points system
- Player price changes
- Player points history API
- Lineup snapshot at deadline lock


---

## PART 19 — STOP CONDITION

This document contains no code changes. No files were modified.
No migrations were created. No models, services, or serializers were edited.

The only output of this review is this document and the scoring contract below.

---

---

## RECOMMENDED MVP SCORING CONTRACT

This table is the concrete scoring agreement to approve before implementation begins.
All values are configurable per competition via the admin. These are the recommended
defaults for a football competition.

| # | Statistic | Rule type | Conditions | GK | DEF | MID | FWD | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | MINUTES_PLAYED | BRACKET | `{"min":1,"max":59}` | 1 | 1 | 1 | 1 | Short appearance |
| 2 | MINUTES_PLAYED | BRACKET | `{"min":60,"max":null}` | 2 | 2 | 2 | 2 | Full appearance |
| 3 | GOALS | POSITION | `{"positions":{"GK":10,"DEF":6,"MID":5,"FWD":4}}` | 10 | 6 | 5 | 4 | Rarity-weighted |
| 4 | ASSISTS | PER_UNIT | `{}` | 3 | 3 | 3 | 3 | Universal |
| 5 | CLEAN_SHEETS | POSITION | `{"positions":{"GK":4,"DEF":4,"MID":1,"FWD":0}}` | 4 | 4 | 1 | 0 | 60-min gate enforced by data |
| 6 | SAVES | PER_N | `{"per_n":3}` | 1/3 | — | — | — | Populate only for GK |
| 7 | PENALTIES_SAVED | FLAT | `{}` | +5 | — | — | — | Populate only for GK |
| 8 | PENALTIES_MISSED | PER_UNIT | `{}` | −2 | −2 | −2 | −2 | Any position |
| 9 | GOALS_CONCEDED | PER_N | `{"per_n":2}` | −1/2 | −1/2 | — | — | Populate only for GK/DEF |
| 10 | YELLOW_CARDS | PER_UNIT | `{}` | −1 | −1 | −1 | −1 | Any position |
| 11 | RED_CARDS | PER_UNIT | `{}` | −3 | −3 | −3 | −3 | Stacks with yellow |
| 12 | OWN_GOALS | PER_UNIT | `{}` | −2 | −2 | −2 | −2 | Any position |

**Captain:** ×2 multiplier (configurable). Vice fallback enabled by default.
**Transfer penalty:** −4 pts per extra transfer (configurable).
**Bench:** Points calculated, not counted. No auto-substitution in MVP.
**Corrections:** Supported via admin correction workflow. Idempotent re-scoring.
**Double yellow + red:** Store YELLOW_CARDS=1 + RED_CARDS=1 → total −4 pts.

---

## IMPLEMENTATION START POINT

**File:** `fantasy/models.py`
**Change:** Add `RuleType` TextChoices and `rule_type` field to `FantasyScoringRule`.

This is the first and only unblocking change. Everything else — the engine rewrite,
the serializer update, the frontend type update, and the admin UI — all depend
on this field existing.

Exact sequence:
1. Write tests in `fantasy/tests/test_scoring_engine.py` (failing tests for T01–T17)
2. Add `rule_type` to `FantasyScoringRule` in `fantasy/models.py`
3. Generate and apply migration
4. Update `ScoringRuleSerializer` in `fantasy/serializers.py`
5. Rewrite scoring loop in `fantasy/services.py`
6. Run tests → confirm all pass
7. Add `rule_type` to `FantasyScoringRule` interface in `src/services/fantasyService.ts`
8. Update admin scoring rules form in `FantasyAdminPage.tsx`

---

## WHAT WE SHOULD NOT BUILD YET

The following are explicitly deferred and should not be started until the MVP
scoring contract above is live and stable:

1. **Auto-substitution** — Formation validity logic is complex; defer to Phase 5.
2. **Chips** (wildcard, bench boost, triple captain, free hit) — Requires per-team
   per-season chip state management. Phase 6.
3. **Bonus points system** — Requires BPS weighting config and per-fixture ranking
   job. No infrastructure exists. Phase 6+.
4. **Player price changes** — Not relevant to current competition model.
5. **Lineup snapshot at deadline lock** — Useful safeguard but not blocking. Phase 5.
6. **Conditional rules (cross-statistic)** — e.g. "clean sheet only if 60+ min played"
   expressed as a single rule. The 60-min gate is enforced by the data pipeline
   in v1. True conditional rule evaluation is Phase 2+.
7. **Dream Team / Best XI** — No business requirement exists for this. Not planned.
8. **Free Hit chip** — Requires a temporary squad snapshot separate from the main squad.

---

*End of League OS Fantasy Football MVP Scoring Review*
*Document produced from live codebase inspection — no code was modified.*
*Approved values above form the scoring contract for Phase 1 implementation.*
