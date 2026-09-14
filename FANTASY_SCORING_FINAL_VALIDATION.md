# League OS Fantasy — Final Scoring Validation

> Produced: 2026-08-21
> Basis: Full inspection of all three MatchPlayerStatistic write paths,
> _participated() logic, and MatchLineup data model.
> Status: VALIDATION ONLY — no code was modified.

---

## QUESTION 1 — CLEAN SHEET 60-MINUTE GATE

### 1A. Is the 60-minute requirement guaranteed at the data layer?

**NO. It is not guaranteed. There is no enforcement anywhere.**

There are exactly three paths that write `MatchPlayerStatistic` rows:

---

**Path 1: Admin manual entry**
`POST /fantasy/admin/match-statistics/`
Handler: `MatchStatisticViewSet.create()` in `fantasy/views.py`

Validation performed (confirmed from source):
- `MatchPlayerStatisticCreateSerializer.validate()` checks that `stat_type`
  is in the sport's approved catalogue (`statistic_catalogue(sport)`).
- `value >= 0` is enforced.
- Duplicate `(match_centre, participant, stat_type)` is blocked.

Validation NOT performed:
- Nothing checks whether the player played at all.
- Nothing checks whether the player played ≥ 60 minutes.
- An admin can POST `{stat_type: "CLEAN_SHEETS", value: 1}` for a player
  who played 1 minute. The system accepts it without question.

**Verdict: No gate. Admin has full discretion over the value.**

---

**Path 2: Club Admin CSV upload**
`clubs/services/match_data_service.py`, function `import_csv_for_club()`

Validation performed (confirmed from source):
- Column presence check (`fixture_id`, `player_id`, `stat_type`, `value`).
- `stat_type` validated against `statistic_catalogue(fixture.sport)`.
- `value >= 0` enforced.
- Player sport must match fixture sport.
- Intra-file duplicate detection.

Validation NOT performed:
- No check of MINUTES_PLAYED vs CLEAN_SHEETS.
- No check that CLEAN_SHEETS=1 is valid only when player played ≥ 60 minutes.
- A Club Admin can upload a CSV row `CLEAN_SHEETS, 1` for a player who was
  substituted off at minute 30. The system upserts the row without objection.

**Verdict: No gate. Club Admin can upload any valid stat value freely.**

---

**Path 3: Sports feed ingestion (external provider)**
`discovery/services/sports_feed_service.py`, `complete_ingestion()`

This service records ingestion metadata and triggers `score_affected_gameweeks`
via `transaction.on_commit()`. It does **not** write `MatchPlayerStatistic` rows
itself — the actual stat writing is done by the external feed adapter (not
present in this codebase). The `discovery/views.py` and fixture admin service
contain no `MatchPlayerStatistic` write logic either.

**What this means:** External feed data arrives through an adapter that writes
`MatchPlayerStatistic` rows directly. That adapter is outside the codebase.
Its validation logic (if any) is unknown and cannot be audited. It could
correctly enforce the 60-minute gate, or it could provide raw stats with no
interpretation. League OS cannot assume anything about it.

**Verdict: Unknown. Cannot be relied upon. No server-side gate exists in the
discovery pipeline to catch incorrect values from an external feed.**

---

### 1B. Can an admin manually create CLEAN_SHEETS=1 for a player who played 20 minutes?

**YES. Confirmed.**

The `MatchPlayerStatisticCreateSerializer` validates:
1. `stat_type` is in the football catalogue → CLEAN_SHEETS is in the catalogue ✓
2. `value >= 0` → 1 >= 0 ✓
3. No duplicate (match_centre, participant, CLEAN_SHEETS) for this fixture ✓

That is all. The system creates the row. The scoring engine then fires the
CLEAN_SHEETS POSITION rule and awards 4 pts to a GK who played 20 minutes.
This is a real data quality vulnerability — not a theoretical one.

The same applies to the Club Admin CSV path. The CSV row:
```
<fixture_id>, <gk_player_id>, CLEAN_SHEETS, 1
```
...passes all validation even if the player was substituted at minute 15.

---

### 1C. Where should the validation live?

The correct place is the **scoring engine** (`score_gameweek()`), not the
data entry layer. Here is why:

**Why NOT at the data entry layer:**
1. There are three separate entry points (admin UI, CSV upload, external feed).
   Defending each one independently creates N copies of the same gate logic,
   each of which can drift or be missed.
2. The MINUTES_PLAYED stat may arrive in a separate row, in a separate request,
   or even at a different time than CLEAN_SHEETS. At data entry time, you cannot
   guarantee both stats are present yet.
3. The external feed path cannot be controlled — it is outside the codebase.

**Why YES at the scoring engine:**
1. By the time `score_gameweek()` runs, all stats for the fixture are in the
   database. The MINUTES_PLAYED stat can be read alongside CLEAN_SHEETS in a
   single stat fetch: `MatchPlayerStatistic.objects.filter(match_centre__fixture_id__in=fixture_ids, participant=player.player)`.
2. The engine already fetches all stats for the player in a single queryset.
   Reading `MINUTES_PLAYED` from that queryset is free — it's already in memory.
3. One enforcement point serves all three entry paths simultaneously. Nothing leaks.
4. It is testable: a test can set CLEAN_SHEETS=1 and MINUTES_PLAYED=30 and
   verify 0 clean-sheet points are awarded.

**Why NOT a separate conditional rule type:**
The review document proposed deferring cross-stat conditions to v2. That is
still the right call for a general-purpose conditional rule system. But the
60-minute clean-sheet gate is specific, high-value, and well-understood enough
to handle directly in `apply_rule()` or `score_gameweek()` as a named exception
for CLEAN_SHEETS, without building a full cross-stat condition engine.

---

### 1D. Should the scoring engine itself enforce the gate?

**YES. The scoring engine should enforce it.**

The gate is not a validation of input data — it is a scoring rule. The rule
is: "clean sheet points are only awarded if the player was on the pitch for
at least 60 minutes." This is a scoring decision, and scoring decisions belong
in the scoring engine.

The implementation cost is minimal: the engine already fetches all player stats
into a `stats` queryset. Reading `MINUTES_PLAYED` from that queryset before
evaluating the CLEAN_SHEETS rule requires one `.get(stat_type='MINUTES_PLAYED')`
call on the already-fetched stats — no extra database query.

---

### 1E. Would enforcing it in score_gameweek() require additional statistics?

**NO new statistics are required.**

`MINUTES_PLAYED` is already in `FANTASY_STATISTICS["football"]` in
`fantasy/statistics.py`. It is already a supported stat type. If the data
pipeline populates it correctly (which it should for any stat that has a
scoring rule configured), it will be present in the fetched stats queryset.

The only operational requirement is that whoever enters match statistics
(admin, club CSV, external feed) must enter MINUTES_PLAYED per player. This
is already required for appearance points to work at all. The same stat serves
double duty: it drives appearance points AND gates clean-sheet eligibility.

**No new model fields. No migration. No new stat codes. No schema changes.**

---

### 1F. Recommended approach (definitive)

**Enforce the gate inside `score_gameweek()` when evaluating CLEAN_SHEETS rules.**

The implementation logic in pseudocode:

```
when applying a CLEAN_SHEETS rule for a player:
    minutes = stat_value_for(player, "MINUTES_PLAYED", default=0)
    if rule.rule_type == POSITION:
        if minutes < 60:
            return 0  # gate: did not play long enough
        pts = rule.conditions["positions"].get(player.position, 0)
        return stat_value × Decimal(pts)
```

This does NOT require a new rule_type. It does NOT require a general conditional
rule engine. It is a single named gate check inside `apply_rule()` or in the
caller when rule.statistic_type == "CLEAN_SHEETS".

The recommended implementation:
- In `score_gameweek()`, before evaluating any rule for a player, build a
  `stat_map = {stat.stat_type.upper(): stat.value for stat in stats}` from
  the already-fetched stats queryset.
- Pass `stat_map` into `apply_rule()`.
- In `apply_rule()`, for any CLEAN_SHEETS rule, read `stat_map.get("MINUTES_PLAYED", 0)`.
  If `< 60`, return 0.

This approach:
- Adds no extra DB queries (stat_map is built from the already-fetched queryset)
- Enforces the gate for all three entry paths
- Is fully testable
- Does not require a new stat code or model field
- Correctly handles CLEAN_SHEETS=1 submitted by a mistaken admin for a 20-min player

---

## QUESTION 2 — PARTICIPATION DETECTION

### 2A. Current `_participated()` implementation (verified from services.py)

```python
def _participated(gameweek, fantasy_player):
    fixture_ids = gameweek.fixtures.values_list("id", flat=True)
    participant_id = fantasy_player.player_id
    if MatchPlayerStatistic.objects.filter(
        match_centre__fixture_id__in=fixture_ids, participant_id=participant_id
    ).exists():
        return True
    return MatchLineup.objects.filter(
        match_centre__fixture_id__in=fixture_ids, participant_id=participant_id
    ).exists()
```

This returns a boolean. It answers only: did this player participate or not?
It cannot answer: how many minutes did they play?

### 2B. Reliability of each data source for each question

---

**"Did not play" (0 minutes)**

| Source | Reliability |
|---|---|
| `MatchPlayerStatistic MINUTES_PLAYED = 0` | RELIABLE if the stat is always populated. But if the stat is absent (no row), it is ambiguous — absent could mean "did not play" or "stats not yet entered". |
| `MatchPlayerStatistic` has no rows for this player | UNRELIABLE — absence of stats means "no data entered", not "did not play". This is why `statistics_available=False` exists. |
| `MatchLineup.is_starter=False` AND no lineup entry | UNRELIABLE for the same reason — absence of lineup could mean data not entered. |
| `MatchPlayerStatistic MINUTES_PLAYED = 0` (explicit zero) | RELIABLE — if the data pipeline explicitly writes 0, this means did not play. |

**Verdict:** The most reliable signal is an explicit `MINUTES_PLAYED=0` row.
The absence of any stat row is ambiguous and must be interpreted as "data not available",
not "did not play".

---

**"Player played" (any minutes > 0)**

| Source | Reliability |
|---|---|
| `MatchPlayerStatistic MINUTES_PLAYED > 0` | MOST RELIABLE — positive explicit value confirms play. |
| Any `MatchPlayerStatistic` row exists for player | RELIABLE as a proxy — if a player has any stats (goals, assists, etc.), they must have played. But a player could play and only have MINUTES_PLAYED with no events. |
| `MatchLineup` row exists | RELIABLE proxy — presence in lineup means they were named, but NOT that they played. A named substitute who never came on would have a lineup entry. |

**Verdict:** `MINUTES_PLAYED > 0` is the gold standard. `MatchLineup` alone
is not sufficient to confirm play; it confirms squad selection, not on-pitch time.

---

**"Played less than 60 minutes" (1–59 min)**

| Source | Reliability |
|---|---|
| `MatchPlayerStatistic MINUTES_PLAYED` value between 1–59 | ONLY RELIABLE SOURCE — this is the only stat that carries a minutes value. |
| `MatchLineup.position` or `is_starter` | Cannot determine minutes. Only states whether they started. |
| `MatchCentre.home_score / away_score` | Irrelevant to individual minutes. |

**Verdict:** `MINUTES_PLAYED` stat value is the only source for < 60 minutes.
No alternative exists in the current data model.

---

**"Played 60+ minutes" (60 or more)**

Same as above. `MINUTES_PLAYED >= 60` in `MatchPlayerStatistic` is the only
reliable source. `MatchLineup.is_starter=True` is necessary but not sufficient
(a starter could be subbed off at minute 30).

---

### 2C. The `_participated()` function: gap analysis

The current function uses two checks in sequence:
1. `MatchPlayerStatistic` row exists → True
2. `MatchLineup` row exists → True

**Gap 1:** MatchLineup check can produce false positives.
A named substitute who never played will have a `MatchLineup` row with
`is_starter=False`. `_participated()` will return True for them.
For captain fallback purposes this could cause the vice-captain bonus to be
denied when the actual vice-captain did NOT play (only sat on the bench).

**Confirmed from MatchLineup model (discovery/models.py):**
```python
is_starter = models.BooleanField(default=True, db_index=True)
```
There is an `is_starter` field. A named substitute has `is_starter=False`.
But there is no `did_play` field — `MatchLineup` has no way to distinguish
"named substitute who came on" from "named substitute who stayed on bench".

**Gap 2:** MatchPlayerStatistic absence is ambiguous.
If no stats exist AND no lineup entry exists, `_participated()` returns False.
This is the right behavior for captain fallback. But if stats simply haven't
been entered yet (data lag), a participating captain gets no bonus until stats
arrive. This is acceptable behavior but must be documented.

---

### 2D. Recommended participation sources by use case

| Use case | Recommended source | Fallback |
|---|---|---|
| Captain/vice fallback (did player appear at all?) | `MINUTES_PLAYED > 0` in `MatchPlayerStatistic` | Fall back to `MatchLineup` row where `is_starter=True OR minutes > 0` — note the risk |
| Appearance points (1–59 min bracket) | `MINUTES_PLAYED` stat value, bracket 1–59 | None — if absent, 0 points |
| Appearance points (60+ min bracket) | `MINUTES_PLAYED` stat value, bracket 60+ | None — if absent, 0 points |
| Clean sheet gate (was player on pitch 60+ min?) | `MINUTES_PLAYED >= 60` in `MatchPlayerStatistic` | None — if absent, no clean sheet points (safe default) |
| statistics_available flag | `stats.exists()` (any stat row) | No change needed |

**Recommendation for `_participated()`:**

For captain fallback, the current MatchLineup fallback is acceptable but has
the named-substitute false-positive risk. The preferred order is:

1. Check `MatchPlayerStatistic MINUTES_PLAYED > 0` → most precise, confirms play
2. Fall back to `MatchPlayerStatistic` any row exists → confirms play via events
3. Fall back to `MatchLineup is_starter=True` row only → confirms started (not just named)

Do NOT fall back to any `MatchLineup` row unconditionally. Restrict the lineup
fallback to `is_starter=True` to reduce false positives.

The current implementation uses `MatchLineup.objects.filter(...)` without an
`is_starter=True` filter. This is the gap.

---

## QUESTION 3 — FINAL RECOMMENDATION

```
CLEAN_SHEET_GATE = ENFORCE IN score_gameweek() USING stat_map["MINUTES_PLAYED"]
                   When evaluating any CLEAN_SHEETS rule, read MINUTES_PLAYED
                   from the already-fetched stat_map for the player.
                   If MINUTES_PLAYED < 60 (or absent), return 0 points.
                   No new stat codes. No new model fields. No migration.
                   One stat_map dict lookup — zero extra DB queries.

PARTICIPATION_SOURCE = MatchPlayerStatistic MINUTES_PLAYED > 0 (primary)
                       ANY MatchPlayerStatistic row exists (secondary)
                       MatchLineup is_starter=True ONLY as last resort
                       NOT: MatchLineup any row (named-sub false positive risk)

MINUTES_SOURCE = MatchPlayerStatistic stat_type='MINUTES_PLAYED', value field
                 This is the sole reliable source for exact minutes played.
                 MatchLineup has no minutes field.
                 MatchCentre has no per-player minutes field.
                 No alternative exists in the current data model.

DATA_PIPELINE_CHANGE = NO
                       No new stat codes are required.
                       MINUTES_PLAYED already exists in the football catalogue.
                       Operational requirement: whoever enters stats must
                       populate MINUTES_PLAYED per player per fixture.
                       This is already required for appearance points to work.

SCORING_ENGINE_CHANGE = YES
                        Two targeted changes needed in fantasy/services.py:

                        Change 1 — stat_map:
                        In score_gameweek(), when iterating player stats,
                        build a stat_map dict from the already-fetched stats
                        queryset: {stat.stat_type.upper(): stat.value for stat in stats}.
                        Pass stat_map into apply_rule() alongside stat_value
                        and player_position.

                        Change 2 — CLEAN_SHEETS gate in apply_rule():
                        When rule.statistic_type == "CLEAN_SHEETS":
                            minutes = stat_map.get("MINUTES_PLAYED", 0)
                            if minutes < 60: return 0
                        Otherwise evaluate the POSITION rule normally.

                        Change 3 — _participated() tighten (recommended):
                        Change the MatchLineup fallback to filter
                        is_starter=True rather than any lineup row,
                        to prevent named-substitute false positives for
                        captain fallback decisions.
```

---

*End of Final Scoring Validation*
*No code was modified. These findings update the scoring contract in FANTASY_MVP_SCORING_REVIEW.md.*
