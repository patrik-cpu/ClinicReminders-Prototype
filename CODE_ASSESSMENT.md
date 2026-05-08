# Code Assessment — ClinicReminders Prototype

_Date: 2026-05-04_
_Branch: dev-reminders_
_Primary file reviewed: `reminders_app_v3.py`_

## Scope
This is an initial architectural and code-quality assessment of the current prototype. No application behavior was modified.

---

## What works

1. **End-to-end prototype capability is strong**
   - The app appears to support ingestion, normalization, reminder generation, analytics views, and feedback capture in a single workflow.
   - Google Drive / Sheets integrations are present for shared dataset persistence and settings management.

2. **Defensive data hygiene is already in place in several areas**
   - Column normalization and duplicate-column handling exist.
   - There are helper functions for schema preparation and sanitization.

3. **Caching is used in important parts of the app**
   - `st.cache_data` / `st.cache_resource` are used to avoid repeated expensive operations.
   - Some expensive computed datasets are clearly memoized.

4. **Some resilience for external API calls exists**
   - Retry logic is implemented for transient Google Sheets API errors.

5. **Data deduplication strategy exists for published datasets**
   - A deterministic row key is built and used for merge+dedupe before republishing.

---

## Main risks

1. **Single-file monolith risk (high)**
   - ~4k lines of UI, ETL, business rules, persistence, and analytics in one file increases regression risk and slows safe iteration.

2. **Settings/Sheet access patterns are repetitive and network-heavy (high)**
   - Multiple paths read full sheet contents and then update individual cells one at a time.
   - This can be slow and more vulnerable to API limits/transient failures at scale.

3. **Rule sprawl / keyword sprawl (medium-high)**
   - Extensive in-code keyword lists are hard to validate, tune, and version.
   - Overlaps and exclusions can become inconsistent over time.

4. **Cache invalidation strategy is broad in places (medium)**
   - Global cache clears can over-invalidate and trigger expensive recomputes unrelated to the action performed.

5. **Row-wise pandas operations in hot paths (medium)**
   - Multiple `.apply(...)`, group custom lambdas, and `iterrows()` patterns may degrade performance on larger datasets.

6. **Operational coupling to Google services (medium)**
   - Heavy reliance on remote state (Sheets/Drive) means latency and quota behavior directly affects UX.

---

## Bugs or likely bugs

> Note: These are assessment-level findings (not yet fixed), based on static review.

1. **Duplicate import / code drift indicators**
   - `time` is imported twice in different import statements. Not functional breakage, but indicates maintainability drift.

2. **Potential inconsistent update behavior in settings writes**
   - Multiple related fields are updated via separate `update_cell` calls. If one call fails mid-sequence, data pointer fields can become partially updated.

3. **Possible stale-cache edge cases**
   - With broad cache clearing and many cached layers, there is potential for stale/partially refreshed state around rule changes and upload merges.

4. **Classification false positive/negative risk**
   - Keyword/exclusion approaches are practical, but with this many terms there is high probability of edge-case misclassification (especially with overlapping medical/product terms).

5. **Schema drift handling risk**
   - Several code paths conditionally create/massage columns; future source-format variation could still trigger silent downstream behavior changes if assumptions diverge.

---

## Suggested refactor priorities

### Priority 1 (high impact, low-to-medium disruption)
1. **Extract Google Sheets access layer**
   - Create a small module for clinic-row lookup, pointer reads/writes, and batch updates.
   - Replace repeated full-sheet scan + multiple `update_cell` calls with one helper and batched writes where possible.

2. **Narrow cache invalidation**
   - Replace global cache clear patterns with targeted invalidation/versioning for specific computed artifacts.

3. **Isolate constants/rules from app runtime code**
   - Move keyword/exclusion/rule definitions into a dedicated config module (or JSON/YAML), with validation on load.

### Priority 2 (performance and correctness hardening)
4. **Vectorize hot pandas paths**
   - Replace `iterrows` and expensive row-wise apply usage in reminder/analytics paths where feasible.

5. **Introduce lightweight domain models / typed interfaces**
   - Add explicit schemas for expected columns at each pipeline stage to reduce hidden coupling.

6. **Improve write atomicity patterns**
   - Ensure related settings updates are committed together or retried as a unit.

### Priority 3 (maintainability / delivery speed)
7. **Split monolith into modules**
   - Suggested structure: `io/`, `transform/`, `rules/`, `analytics/`, `ui/`, `auth/`.

8. **Add focused tests around critical transformations**
   - Deduping row-key stability, date parsing, interval mapping, and reminder generation should get baseline tests first.

---

## Next steps (careful, slow rollout)

To reduce risk and avoid breaking the app, begin with **only Phase 1** below.

### Step 1.1 — Baseline and safety checks (no code changes)
- Confirm current behavior with a small, known sample upload per PMS type currently supported.
- Record baseline timings manually: app load, file upload-to-ready, reminder generation, and one analytics tab render.
- Record current known outputs (row counts, reminder counts, key metrics) so parity can be checked after each later change.

### Step 1.2 — Inventory and map repeated Sheets operations (no code changes)
- Identify every function that reads full sheet values and every function that performs per-cell updates.
- Document which fields are read/written in each path and where partial-write risk exists.
- Produce a simple table of call sites to guide a safe helper extraction later (without implementing it yet).

### Step 1.3 — Define a strict non-functional refactor guardrail
- Lock scope: **no feature changes, no rule changes, no UI behavior changes** in the first refactor slice.
- Define acceptance criteria for first slice:
  - identical outputs for baseline sample files,
  - no increase in error rate,
  - measurable reduction in Sheets write/read calls where touched.
- Prepare rollback plan: one commit per small change, verify after each commit, and revert immediately on parity failure.

> After Steps 1.1–1.3 are completed and documented, proceed to implementation in very small slices.

---

## Quick conclusion
The prototype is functionally rich and already includes useful caching, sanitization, and dedupe patterns. The main opportunity is to improve reliability and speed by reducing repeated remote I/O patterns, narrowing cache invalidation, and modularizing the monolithic script.
