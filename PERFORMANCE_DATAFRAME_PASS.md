# Performance DataFrame Pass

Date: 2026-05-19

## Executive Summary

The current DataFrame hot paths are concentrated in reminder generation, active reminder badge calculation, Stats outcome matching, Stats grouping/export, and upload parsing/merging. Several earlier performance risks have been reduced: reminder/actioned tables are paginated, action-button CSS duplication has been reduced, Stats generated rows are cached, and the outcome matcher is cached. The remaining highest-confidence DataFrame issue is repeated derivation of the same reminder-window data in one render, especially the active reminder badge and the Reminders tab table.

The safest next improvements are small reuse/caching patches, not broad rewrites. The best first patch is to memoize or pass through the already-computed active reminder window results so `get_active_reminder_badge_count()` does not rebuild/filter/group reminders separately from the active Reminders view.

## 1. Hot-Path DataFrame Transformations

### Upload parsing and merge

- `process_file()` at `reminders_app_v3.py:6383`
  - Reads CSV/XLS/XLSX into a DataFrame, cleans headers, drops duplicate columns, applies PMS mappings, validates limits, and normalizes canonical columns.
  - Current repeated work: multiple copies during empty-row cleanup, alias mapping, duplicate-column cleanup, PMS normalization, and final schema handling.
  - Cache status: `@st.cache_data(show_spinner=False)` keyed by file bytes/name.

- `summarize_uploads()` at `reminders_app_v3.py:8462`
  - Calls `process_file()` per file, validates each DataFrame, parses `ChargeDate`, appends `(pms_name, df)` tuples and summary rows.
  - Current repeated work: `parse_dates(df["ChargeDate"])` runs for summary even though downstream publish/merge also needs normalized dates.
  - Cache status: `@st.cache_data(show_spinner=False)`.

- `merge_dedupe()` / dataset publishing path around `reminders_app_v3.py:3576` and Upload Data flow around `reminders_app_v3.py:11054`
  - Concatenates existing/new data, creates row keys, sorts by charge date, and drops duplicates.
  - Current repeated work: large frame copies are expected here, but should remain measured before changing.

### Reminder preparation

- `ensure_reminder_columns()` around `reminders_app_v3.py:9970`
  - Copies the working DataFrame, parses `ChargeDate`, maps rules, creates due/reminder date columns, formats dates, and normalizes matched-item lists.
  - Cache status: `@st.cache_data(show_spinner=False)`.
  - Current repeated work: called through `get_prepared_df()` and also through `build_prepared_reminder_rows()` for date-filtered sources.

- `map_intervals_vec()` around `reminders_app_v3.py:9861`
  - Loops over every search rule and applies `item_norm.str.contains()` against the full item column.
  - Current repeated work: each rule scans the item column, then loops over matching indexes to append matched labels/search terms.
  - Cache status: indirectly cached when called through `ensure_reminder_columns()`.

- `drop_early_duplicates_fast()` around `reminders_app_v3.py:10040`
  - Converts matched items to strings, sorts by client/animal/item/date, groups, and shifts to keep the latest record in each cycle.
  - Current repeated work: same prepared rows may be deduped again when badge and Reminders view are computed separately.

- `expand_reminder_dates()` around `reminders_app_v3.py:9932`
  - Builds a day-frame, filters valid rows, converts selected rows to records, then emits one output row per reminder date.
  - Repeated conversions: `work.to_dict("records")` plus `day_frame.itertuples(...)`.

### Reminder window rendering and badge

- `filter_sales_as_of_date()` at `reminders_app_v3.py:10158`
  - Parses `ChargeDate` and filters data up to the anchor/as-of date.
  - Current repeated work: date parsing can repeat even when `ChargeDate` is already datetime-like.

- `get_active_reminder_badge_count()` at `reminders_app_v3.py:10315`
  - Calls `get_prepared_df()`, filters reminder dates, applies exclusions, groups rows, converts grouped rows to records, filters hidden reminders.
  - Repeated conversions: `grouped.to_dict("records")`.
  - Repeated work: this duplicates the active Reminders tab window calculation around `reminders_app_v3.py:15556-15591`.

- Active Reminders main path around `reminders_app_v3.py:15556-15591`
  - Filters sales as-of date, builds prepared reminder rows, filters window dates, applies exclusions, groups reminders.
  - Current repeated work: similar to badge, but not fully sharing the same prepared/filter/group result.

- `bundle_client_reminders_by_window()` at `reminders_app_v3.py:9795`
  - Copies due rows, parses/sorts reminder dates, converts sorted rows to records, clusters per client/window, and summarizes each cluster.
  - Repeated conversions: `work.sort_values(...).to_dict("records")`.
  - Hot path: active reminder rendering, badge calculation, and Stats generated rows.

- `apply_reminder_exclusion_filters()` at `reminders_app_v3.py:10090`
  - Copies the frame, computes display plan item, maps client/patient keys, loops client-item exclusions, builds regex for item exclusions.
  - Current repeated work: the same exclusion filters can run for badge, active reminder table, and Stats generated rows in one render.

### Statistics and outcomes

- `cached_statistics_generated_rows()` at `reminders_app_v3.py:12745`
  - Cached wrapper around `build_statistics_generated_rows()`.
  - Cache key includes prepared DataFrame, rules, group days, period, today, data version, rules fingerprint, exclusion fingerprint, and schema version.

- `build_statistics_generated_rows()` at `reminders_app_v3.py:12721`
  - Filters prepared reminders by period, applies exclusions, groups reminders.
  - Repeated work: calls the same exclusion/grouping helpers used by active reminders and badge.

- `filter_generated_for_statistics_period()` at `reminders_app_v3.py:12774`
  - Converts generated rows to records and applies Python date parsing per row.
  - Repeated conversions: `generated_df.to_dict("records")`.
  - Used by `statistics_summary_for_period()`, `build_statistics_daily_frame()`, and older/covered statistics helpers.

- `statistics_summary_for_period()` at `reminders_app_v3.py:12840`
  - Calls `filter_generated_for_statistics_period()`, converts generated rows to records, builds generated keys, then filters action records.
  - Current repeated work: if combined with item/team daily views, it recomputes period membership and row keys.

- `build_statistics_item_frame()` at `reminders_app_v3.py:12949`
  - Converts generated DataFrame to records, expands grouped reminder details, filters by period, dedupes generated/action cycles, and counts by item.
  - Current repeated work: expands grouped action records independently from outcome matching.

- `build_reminder_outcomes()` at `reminders_app_v3.py:13684`
  - Cached outcome matcher. Prepares sales, reduces action records, expands grouped actions, dedupes sent cycles, creates outcome rows, builds item match maps, computes overall purchase gaps, merges sales matches, computes success candidates.
  - Cache status: `@st.cache_data(show_spinner=False, max_entries=8)`.
  - Current repeated work inside one call: repeated `pd.to_datetime` conversions for `Charge Date`, `Sent Date`, `OutcomeChargeDate`, and outcome frame date columns after earlier preparation.

- `build_average_sales_purchase_gap_map()` around `reminders_app_v3.py:13600`
  - Merges match keys to sales, drops duplicate client/patient/date purchases, groups by `_GapID`, computes counts, average revenue, gaps, and repeat rates.
  - Good current reuse: this replaced the older per-item `average_sales_purchase_gap()` path for outcome groups.

- `summarize_outcomes()` around `reminders_app_v3.py:13970`
  - Converts numeric columns repeatedly, drops duplicates by item, and computes summary metrics.
  - Repeated work: called once for summary cards and once per group inside `build_outcome_group_frame()`.

- `build_outcome_group_frame()` at `reminders_app_v3.py:14235`
  - Copies source, normalizes group column, groups, and calls `summarize_outcomes()` for each group.
  - Current repeated work: item and sender group frames each recompute summaries from `period_rows`; team tab currently calls `build_outcome_group_frame(period_rows, "Sender", ...)` inside `build_stats_team_frame()`.

- `build_stats_team_frame()` at `reminders_app_v3.py:14296`
  - Builds action team frame and merges it with outcome sender frame.
  - Current repeated work: `build_statistics_team_frame()` converts action records to a DataFrame and parses action times each render.

- `prepare_outcome_dataframe_for_display()` at `reminders_app_v3.py:14447`
  - Copies visible/current frame, maps date formatter over date columns, multiplies percent columns, rounds currency columns.
  - Current repeated work: used for display after pagination and also for full-view export via `render_stats_csv_export()`.

- `render_stats_csv_export()` at `reminders_app_v3.py:14727`
  - Copies the full active view frame, optionally subsets columns, optionally runs display preparer, formats CSV export values, and converts to bytes.
  - Current repeated work: CSV bytes are generated during render even if the user does not click export.

- `render_stats_tab()` at `reminders_app_v3.py:14887`
  - Builds outcomes, generated rows, summary, item frame, item actioning frame, team frame, sent/success filtered rows, export bytes, sort controls, paginated display frames.
  - Current repeated work: several views are eagerly computed even though only one `st.tabs()` subtab is visible to the user in the browser.

## 2. Repeated Conversions and Transformations

### `to_dict("records")`

Hot current uses:

- `expand_reminder_dates()` around `reminders_app_v3.py:9932`: row expansion by reminder day.
- `_summarize_client_cluster()` / `bundle_client_reminders_by_window()` around `reminders_app_v3.py:9720` and `reminders_app_v3.py:9795`: cluster summaries and sorted row records.
- `get_active_reminder_badge_count()` at `reminders_app_v3.py:10315`: grouped reminder date-range filtering.
- `filter_generated_for_statistics_period()` at `reminders_app_v3.py:12774`: period filtering using Python row functions.
- `statistics_summary_for_period()` at `reminders_app_v3.py:12840`: generated key creation.
- `build_statistics_item_frame()` at `reminders_app_v3.py:12949`: generated rows expansion.
- `render_table_with_buttons()` at `reminders_app_v3.py:11922`: visible active reminder row records for widgets and Send All.

Notes:

- Some conversions are reasonable because grouped reminder details are nested dict/list structures and Streamlit buttons need row dict payloads.
- The highest-value reductions are avoiding duplicate calls to the same converter in the same render, not eliminating all row dicts.

### `iterrows()` / `itertuples()`

Hot current uses:

- `expand_reminder_dates()` uses `day_frame.itertuples(...)` plus record dicts.
- `average_sales_purchase_gap()` still uses group iteration and date diffing, although the current grouped outcome path mostly uses `build_average_sales_purchase_gap_map()`.
- `build_reminder_outcomes()` uses `itertuples()` to expand `_OutcomeSentDates` into sent date rows.
- `render_table_with_buttons()` uses `df.iterrows()` for the 50-row active reminders page. This is bounded now, so it is not a priority.

### Repeated filtering

- Badge path and Reminders tab both filter reminder dates and apply exclusions.
- Stats generated rows apply period filters and exclusions separately from active reminders.
- Sent Reminders and Successes subtabs filter/sort `period_rows` after the full outcomes DataFrame is built.
- `filter_generated_for_statistics_period()` can be called by multiple statistics helpers if those older helper paths are used together.

### Repeated grouping

- `bundle_client_reminders_by_window()` can run for badge, active reminder display, and Stats generated rows.
- `build_outcome_group_frame()` groups once by item and once by sender, each calling `summarize_outcomes()` per group.
- `summarize_outcomes()` internally builds per-item unique gap/revenue frames for each group, which is useful but repeated across groups.

### Repeated sorting

- `bundle_client_reminders_by_window()` sorts due reminders.
- `sort_reminder_table()` sorts active reminder pages before pagination.
- `apply_stats_global_sort_controls()` sorts full Stats frames before pagination.
- Sent and Successes subtabs sort the filtered outcome rows, then `render_outcome_dataframe()` may also apply user-selected global sort.

### Repeated date parsing

- `filter_sales_as_of_date()` parses `ChargeDate`.
- `ensure_reminder_columns()` parses `ChargeDate`.
- `filter_prepared_for_statistics_period()` calls `pd.to_datetime` on reminder date columns.
- `build_reminder_outcomes()` repeatedly parses record date strings and DataFrame date columns.
- `prepare_outcome_dataframe_for_display()` formats date columns after pagination, which is bounded and acceptable.

## 3. Same Derived Data Computed In One Render

### Active reminder window

Derived data:

- Prepared reminder rows.
- Date-window filtered rows.
- Exclusion-filtered rows.
- Grouped reminders.
- Hidden-filtered active reminders.

Current duplication:

- `get_active_reminder_badge_count()` computes this independently.
- Reminders tab active table computes nearly the same date-window/exclusion/grouping pipeline.

Impact:

- This is the clearest current DataFrame duplication in a normal render path.

### Stats outcome group frames

Derived data:

- Outcome rows from `build_reminder_outcomes()`.
- Item group frame.
- Sender group frame.
- Team frame merging sender outcomes and actioning.

Current duplication:

- `build_outcome_group_frame(period_rows, "Sender", ...)` is built inside the Team tab even if the Team tab is not being inspected.
- Each group calls `summarize_outcomes()` and repeats numeric conversions and item-level aggregation.

Impact:

- User-visible mainly on Stats reruns for large action histories.

### Stats CSV export frames

Derived data:

- Display-prepared/CSV-prepared full frame and CSV bytes.

Current duplication:

- Render path prepares export bytes for the active subtab frame before the user clicks download.
- Display path separately prepares the paginated visible frame.

Impact:

- Moderate. Correct but eager.

### Generated/actioned item rows

Derived data:

- Expanded grouped generated reminders.
- Expanded grouped action records.
- Deduped item purchase cycles.

Current duplication:

- `build_statistics_item_frame()` expands/dedupes generated and action rows independently from outcome matching and action summaries.

Impact:

- Moderate, mostly Stats tab.

## 4. Precomputed Data That Could Be Passed Through

- Pass active reminder window results from the Reminders tab to the badge/banner instead of recomputing in `get_active_reminder_badge_count()`.
- Pass `action_records = statistics_current_action_records()` into helpers that currently call or reconstruct action subsets.
- Pass the already-built sender outcome frame into Team logic only once if the Team tab needs it.
- Pass prepared period rows from `filter_prepared_for_statistics_period()` to both Stats generated and any future daily/item summaries.
- Pass `item_match_map` and gap map products only within `build_reminder_outcomes()`; do not expose until tests cover the current output shape.

## 5. Cache Candidates and Invalidation Keys

### Active reminder badge/window cache

- Candidate functions: `get_active_reminder_badge_count()` and a new pure helper for active reminder window rows.
- Suggested key:
  - `data_version`
  - `_rules_fp(get_applied_reminder_rules())`
  - `statistics_exclusion_fp()` or a narrower reminder-exclusion fingerprint
  - `today`
  - `reminder_lookback_days`
  - `reminder_window_days`
  - `client_group_days`
  - action/hidden-reminder version or a fingerprint of `deleted_reminders` hidden keys
  - `PREPARED_SCHEMA_VERSION`
- Risk: stale badge/actioned state if hidden-reminder changes are not in the key.

### Stats CSV export bytes

- Candidate functions: `render_stats_csv_export()`, `prepare_stats_csv_export_frame()`, `stats_export_csv_bytes()`.
- Suggested key:
  - view name
  - selected columns
  - display-preparer identity/version
  - data version or stable hash of frame values/columns
  - export formatting version
- Risk: moderate if frame hashing is expensive or misses formatting changes. Safer first step is a two-click "Prepare CSV" gate, but that changes UX.

### Statistics group frames

- Candidate functions: `build_outcome_group_frame()`, `build_statistics_item_frame()`, `build_stats_team_frame()`.
- Suggested key:
  - outcome cache key from `build_reminder_outcomes()`
  - action tracker version/fingerprint
  - group column
  - period
  - schema/display version
- Risk: stale Stats rows after action changes unless action versioning is explicit.

### Reminder prepared rows

- Existing cache: `ensure_reminder_columns()` and `get_prepared_df()`.
- Candidate improvement: cache as-of filtered prepared rows by `data_version`, rules fingerprint, `as_of_date`, and schema version, then run dedupe/expand only once for current view/badge.
- Risk: behavior around purchases after anchor date must remain exact.

## 6. Empty-DataFrame Early Returns

Already good:

- `ensure_reminder_columns()` returns shaped empty frames.
- `expand_reminder_dates()` returns early for empty/no valid day rows.
- `build_statistics_generated_rows()` returns early for empty prepared/filtered frames.
- `build_reminder_outcomes()` returns early when no sent records or no outcome rows.
- `render_stats_csv_export()` returns early for empty frames.

Potential improvements:

- `prepare_outcome_dataframe_for_display()` should return early for `None`/empty before copying, matching other display helpers.
- `stats_sort_dataframe()` already returns early for empty/missing column.
- `summarize_outcomes()` has a strong empty return, but group callers still repeatedly call it per group; the issue is not empty handling.
- `filter_sales_as_of_date()` could skip `parse_dates()` when `ChargeDate` is already datetime64.
- `apply_reminder_exclusion_filters()` could return earlier if all exclusion lists are empty and `"Plan Item"` does not need to be computed for the caller.

## 7. Findings

### P1: Active reminder badge duplicates active reminder table DataFrame work

- Function: `get_active_reminder_badge_count()` at `reminders_app_v3.py:10315`; main Reminders path around `reminders_app_v3.py:15556-15591`.
- Current repeated work: prepared rows, reminder date filtering, exclusion filtering, client grouping, grouped-row record conversion, hidden-reminder filtering.
- Proposed reuse/cache/early-return: extract a small helper that returns active grouped reminders for a date window and reuse it for badge/banner and active table. Alternatively memoize badge count with a key that includes data/rules/exclusions/date/group/action state.
- Risk: medium. A stale badge would be user-visible, and hidden-reminder actions must invalidate correctly.
- Test needed: extend `tests/test_ci_reminders_badge.py` to prove badge changes after sent/declined/undo and after lookback/group/exclusion changes. Add a call-count style test with monkeypatched `bundle_client_reminders_by_window()` proving the same render does not regroup twice.
- Validation command: `python -m unittest tests.test_ci_reminders_badge tests.test_ci_reminder_workflows tests.test_ci_reminder_grouping`.

### P1: Stats tab eagerly builds all subtab frames and CSV bytes

- Function: `render_stats_tab()` at `reminders_app_v3.py:14887`; `render_stats_csv_export()` at `reminders_app_v3.py:14727`.
- Current repeated work: item frame, item actioning frame, team frame, sent rows, success rows, and CSV bytes are prepared during a Stats render even though only one subtab is visible in the browser.
- Proposed reuse/cache/early-return: start with CSV export because it is isolated: cache export-prepared bytes by active frame fingerprint or require an explicit "Prepare CSV" action before byte generation. For subtab frames, consider replacing `st.tabs()` with segmented navigation later so only the active view computes.
- Risk: low for cached CSV bytes if tests cover content; medium for changing tab rendering behavior.
- Test needed: existing CSV formatting tests plus a new test that `render_stats_csv_export()` does not call `to_csv()` when the frame is empty and, if cached, does not recompute for the same view/frame key.
- Validation command: `python -m unittest tests.test_ci_statistics`.

### P1: Outcome group summaries repeat expensive per-item summary logic per group

- Function: `build_outcome_group_frame()` at `reminders_app_v3.py:14235`; `summarize_outcomes()` around `reminders_app_v3.py:13970`.
- Current repeated work: each group calls `summarize_outcomes()`, which re-parses numeric columns and rebuilds item-level unique gap/revenue frames for that group.
- Proposed reuse/cache/early-return: keep behavior but add a vectorized aggregation helper for common count/revenue fields first. Leave nuanced item-gap/revenue metrics in `summarize_outcomes()` until characterization is stronger.
- Risk: medium, because outcome totals and revenue metrics are business-facing.
- Test needed: strengthen `tests/test_ci_statistics.py` with item/sender group summaries over mixed success/pending/no-match rows and compare old/new outputs exactly.
- Validation command: `python -m unittest tests.test_ci_statistics`.

### P2: `filter_generated_for_statistics_period()` repeatedly converts generated DataFrames to records

- Function: `filter_generated_for_statistics_period()` at `reminders_app_v3.py:12774`.
- Current repeated work: `generated_df.to_dict("records")` and Python date parsing per row.
- Proposed reuse/cache/early-return: if `Reminder Date` can be represented as a primary timestamp column in generated rows, use vectorized date filtering for simple one-date rows and fall back to row parsing only for grouped `|` dates.
- Risk: medium. Grouped reminders can contain multiple reminder dates; vectorized filtering must preserve "any date in period" semantics.
- Test needed: generated rows with single dates, grouped pipe-separated dates, blank dates, and all-time period.
- Validation command: `python -m unittest tests.test_ci_statistics`.

### P2: `bundle_client_reminders_by_window()` converts sorted DataFrames to records in every caller

- Function: `bundle_client_reminders_by_window()` at `reminders_app_v3.py:9795`.
- Current repeated work: copies due rows, parses/sorts `_ReminderDateTs`, converts to records, then summarizes clusters.
- Proposed reuse/cache/early-return: do not change internals yet. First reduce duplicate callers by reusing active reminder window data. Later, consider accepting a pre-sorted/preparsed frame or records for callers that already did the work.
- Risk: medium because grouping affects user-facing reminders and outcome actioning.
- Test needed: existing grouping tests plus explicit stable grouping order tests for grouped Rabies/Tricat style reminders.
- Validation command: `python -m unittest tests.test_ci_reminder_grouping tests.test_ci_statistics`.

### P2: Date parsing repeats across reminder and outcome paths

- Function: `filter_sales_as_of_date()` at `reminders_app_v3.py:10158`; `ensure_reminder_columns()` around `reminders_app_v3.py:9970`; `outcome_as_of_date()` around `reminders_app_v3.py:13500`; `build_reminder_outcomes()` at `reminders_app_v3.py:13684`.
- Current repeated work: `ChargeDate`, reminder dates, sent/action dates, and outcome charge dates are parsed multiple times in related flows.
- Proposed reuse/cache/early-return: add early return in `filter_sales_as_of_date()` when `ChargeDate` is already datetime64; add tests first. Larger date-normalization reuse should wait for stronger coverage.
- Risk: low for datetime64 early return; medium for broader date normalization changes.
- Test needed: `filter_sales_as_of_date()` with datetime64, strings, invalid/missing dates, and no `ChargeDate`.
- Validation command: `python -m unittest tests.test_ci_reminder_workflows tests.test_ci_statistics`.

### P2: Upload summary reparses charge dates after processing

- Function: `summarize_uploads()` at `reminders_app_v3.py:8462`.
- Current repeated work: `process_file()` finalizes upload data, then `summarize_uploads()` parses `ChargeDate` again to compute from/to dates. Later publish/merge paths parse/normalize dates again.
- Proposed reuse/cache/early-return: measure first. If `finalize_processed_upload_df()` guarantees `ChargeDate` datetime-like, skip reparsing or reuse parsed series in summary and publish.
- Risk: medium because PMS-specific parsing behavior is brittle.
- Test needed: upload summary date range tests for canonical CSV, VETport, ezyVet, Xpress, invalid dates, and empty uploads.
- Validation command: `python -m unittest tests.test_ci_dataset_update tests.test_ci_upload_validation`.

### P2: Stats display and export prepare similar formatting twice

- Function: `prepare_outcome_dataframe_for_display()` at `reminders_app_v3.py:14447`; `prepare_stats_csv_export_frame()` at `reminders_app_v3.py:14704`; `render_stats_csv_export()` at `reminders_app_v3.py:14727`.
- Current repeated work: display-preparer runs for full export frame and separately for paginated display frame.
- Proposed reuse/cache/early-return: add empty early return to display preparer; then consider caching export-prepared full frames.
- Risk: low for empty early return; low-medium for cache.
- Test needed: empty-frame display/export tests and CSV formatting tests.
- Validation command: `python -m unittest tests.test_ci_statistics`.

### P3: Active reminder row rendering still uses `iterrows()` but is bounded

- Function: `render_table_with_buttons()` at `reminders_app_v3.py:11922`.
- Current repeated work: converts visible page rows with `iterrows()`/`row.to_dict()`.
- Proposed reuse/cache/early-return: leave alone for now. Pagination caps this at 50 rows, and widget callbacks need row dicts.
- Risk: higher than value if changed now.
- Test needed: none unless touched.
- Validation command: existing reminder workflow tests.

## 8. Top 5 Safe Improvements

1. Memoize or reuse active reminder window results for badge/banner/table.
   - Function: `get_active_reminder_badge_count()` plus Reminders tab active path.
   - Risk: medium.
   - Test needed: badge invalidation and call-count characterization.
   - Validation: `python -m unittest tests.test_ci_reminders_badge tests.test_ci_reminder_workflows tests.test_ci_reminder_grouping`.

2. Add an empty-frame early return to `prepare_outcome_dataframe_for_display()`.
   - Function: `prepare_outcome_dataframe_for_display()`.
   - Risk: low.
   - Test needed: empty frame returns empty without mutating columns.
   - Validation: `python -m unittest tests.test_ci_statistics`.

3. Avoid date reparsing in `filter_sales_as_of_date()` when `ChargeDate` is already datetime64.
   - Function: `filter_sales_as_of_date()`.
   - Risk: low.
   - Test needed: datetime64/string/missing date coverage.
   - Validation: `python -m unittest tests.test_ci_reminder_workflows tests.test_ci_statistics`.

4. Cache or defer Stats CSV export generation.
   - Function: `render_stats_csv_export()`.
   - Risk: low-medium.
   - Test needed: CSV content unchanged and repeated render does not recompute bytes for same frame if caching is used.
   - Validation: `python -m unittest tests.test_ci_statistics`.

5. Add vectorized fast path to `filter_generated_for_statistics_period()` for simple single-date rows.
   - Function: `filter_generated_for_statistics_period()`.
   - Risk: medium.
   - Test needed: grouped pipe-date semantics, all-time period, empty/malformed dates.
   - Validation: `python -m unittest tests.test_ci_statistics`.

## 9. Recommended Patch Order

1. Add tests around active badge invalidation and active reminder grouping reuse.
2. Implement active reminder window reuse or badge memoization.
3. Add low-risk empty/datetime early returns in display/date helpers.
4. Cache or defer Stats CSV export byte generation.
5. Characterize `filter_generated_for_statistics_period()` grouped-date behavior.
6. Add vectorized generated-period fast path.
7. Characterize grouped outcome summary outputs.
8. Optimize `build_outcome_group_frame()` common aggregations only after characterization.

## 10. Validation Commands

Existing commands to run before any DataFrame performance PR:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest tests.test_ci_statistics
python -m unittest tests.test_ci_reminders_badge
python -m unittest tests.test_ci_reminder_workflows
python -m unittest tests.test_ci_reminder_grouping
python -m unittest tests.test_ci_dataset_update
python -m unittest discover -s tests -p "test_ci_*.py"
```

For upload-specific patches:

```bash
python -m unittest tests.test_ci_dataset_update tests.test_ci_upload_validation
```

For release-level validation if available in the environment:

```bash
bash scripts/pre_merge_check.sh
bash scripts/pilot_release_check.sh
python -m pip check
```

## 11. Measurement Plan

Add temporary timing with `time.perf_counter()` around:

- `get_active_reminder_badge_count()`: working rows, prepared rows, due rows, grouped rows, hidden-filtered rows.
- Active Reminders main path: as-of filtered rows, prepared rows, due rows, grouped rows.
- `bundle_client_reminders_by_window()`: input row count, output group count, elapsed ms.
- `build_reminder_outcomes()`: action records, expanded sent records, deduped sent records, sales rows, item match map rows, merged candidate rows, elapsed ms.
- `build_outcome_group_frame()`: group count, input rows, elapsed ms.
- `render_stats_csv_export()`: rows, columns, CSV byte length, elapsed ms.
- `summarize_uploads()`: files, bytes, parsed rows, elapsed ms.

Before/after metrics to compare:

- Reminders tab rerun time with 1k, 10k, 50k sales rows and 0/50/500 hidden action records.
- Stats tab rerun time with 100, 1k, 10k action records.
- CSV export render overhead for 50, 500, 5,000 Stats rows.
- Upload summary time for 1, 3, and 5 files at representative sizes.

## 12. Stop Point

This pass is report-only. No performance fixes were implemented.
