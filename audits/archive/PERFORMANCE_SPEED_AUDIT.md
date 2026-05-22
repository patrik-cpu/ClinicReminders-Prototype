# Performance Speed Audit

## Previous Performance Work

### 1. Reports read

- `PERFORMANCE_REPORT.md`
- `PERFORMANCE_REPORT_SECOND_PASS.md`
- `PERFORMANCE_GOOGLE_SHEETS_PASS.md`
- `PERFORMANCE_RENDER_GATING_PASS.md`
- `PERFORMANCE_STREAMLIT_RENDER_PASS.md`
- `PERFORMANCE_DATAFRAME_PASS.md`
- `PERFORMANCE_STATISTICS_PASS.md`
- `PERFORMANCE_CACHE_EARLY_RETURN_PASS.md`
- `PERFORMANCE_UPLOAD_PASS.md`
- `QUALITY_GATES_REPORT.md`
- `CODEBASE_AUDIT.md`
- `FINAL_REVIEW.md`

### 2. Previous findings already fixed

- Upload parse cache layering was reduced: the nested Upload Data summary cache described in `PERFORMANCE_REPORT.md` is gone; `summarize_uploads()` is now the module-level cached path at `reminders_app_v3.py:9741`.
- Upload tracker rows are batched for multi-file upload events. `tests/test_ci_error_handling.py` includes `test_dataset_tracker_batch_uses_one_append_rows_call`, covering the old repeated append finding.
- Dataset pointer update avoids the fresh readback after a successful batch update. `tests/test_ci_dataset_update.py` includes `test_update_clinic_dataset_pointer_uses_cached_row_without_fresh_readback`.
- Settings JSON plus country/status metadata are batched in one existing-row write. `save_settings()` builds one batch payload at `reminders_app_v3.py:5531-5558`, with coverage in `tests/test_ci_settings_save_state.py`.
- Active reminder action-button CSS is now batched for the visible page. `render_table_with_buttons()` calls `render_reminder_action_button_batch_styles()` at `reminders_app_v3.py:14146-14150`, with coverage in `tests/test_ci_statistics.py`.
- Actioned reminders are now paginated before row widgets are rendered. `render_actioned_reminders_tab()` calls `paginate_sequence()` at `reminders_app_v3.py:13993-13999`.
- Stats CSV export cache now supports multiple views. `tests/test_ci_statistics.py` includes `test_stats_export_csv_cache_keeps_multiple_views`.
- Google Sheets retry now has an elapsed timeout budget. `_gspread_retry()` checks `SHEETS_OPERATION_TIMEOUT_SECONDS` before and after calls and retry sleeps at `reminders_app_v3.py:4224-4252`.

### 3. Previous findings still valid

- Full settings-sheet scans remain on password login, staff access login, Google identity lookup, remember-session validation, and several account/profile helpers. Evidence: `authenticate_user()` at `reminders_app_v3.py:8035-8063`, `authenticate_clinic_access()` at `reminders_app_v3.py:8066-8094`, `get_clinic_row()` at `reminders_app_v3.py:8096-8134`, and `get_clinic_row_by_google_identity()` at `reminders_app_v3.py:8137-8160`.
- Cold action tracker load still reads the whole Action tracker worksheet and filters client-side. Evidence: `load_action_tracker_records_for_clinic()` at `reminders_app_v3.py:6000-6031`.
- Settings autosave still performs synchronous Google Sheets work for small UI edits. Evidence: `save_settings()` at `reminders_app_v3.py:5321-5640`, `save_settings_quietly()` at `reminders_app_v3.py:5661-5669`, and Search Terms callbacks at `reminders_app_v3.py:18648-18718`.
- Upload save/publish still downloads/merges/serializes/uploads the full clinic dataset synchronously. Evidence: `publish_dataset_for_clinic()` at `reminders_app_v3.py:4669-4800`.
- Large DataFrame-derived cache keys remain a risk on upload/reminder/statistics hot paths. Evidence: cached `process_file()` at `reminders_app_v3.py:7213-7235`, cached `cached_statistics_generated_rows()` at `reminders_app_v3.py:15124-15144`, and cached `build_reminder_outcomes()` at `reminders_app_v3.py:16144-16189`.

### 4. Previous findings no longer relevant

- The old "Stats renders every Streamlit subtab body" finding is no longer current. `render_stats_tab()` now uses `render_stats_subtab_selector()` and an `if`/`elif` branch at `reminders_app_v3.py:18222-18324`, so inactive Stats subviews do not all render their tables.
- The old "Actioned Reminders renders all rows" finding is no longer current because `paginate_sequence()` caps rendered actioned rows at `reminders_app_v3.py:13993-13999`.
- The old "upload saved events append one row at a time" finding is no longer current because batched dataset tracker writes are tested in `tests/test_ci_error_handling.py`.
- The old broad `st.cache_data.clear()` concern is less active than earlier reports suggest. `reset_uploaded_data_state()` still has the broad clear path at `reminders_app_v3.py:663-681`, but current app call sites found by `rg` pass `clear_cache=False`.

### 5. New issues found since the previous reports

- The new Top Unreminded Items section runs full item matching/grouping on the Configure Reminders tab. It is cached in session, but first render and each exclusion/search-term invalidation can scan the full uploaded dataset and every rule. Evidence: `build_top_unreminded_items()` at `reminders_app_v3.py:10815-10862` and render call at `reminders_app_v3.py:18736-18815`.
- Stats has improved from eager subtab rendering, but the selected Stats page still computes all-time generated rows, action rows, outcome rows, item outcome groups, and sender outcome groups before the selected subview branch. Evidence: `render_stats_tab()` at `reminders_app_v3.py:18114-18185`.

## P0/P1 Speed Issues

No P0 speed issues were found in this focused pass.

### SPEED-001

Severity: P1

User action affected: password login, staff access login, Google login, keep-me-logged-in restoration, switching users in one browser.

Impact: Login and restored sessions can spend multiple seconds in synchronous Google Sheets and Drive work before the app is usable. This also increases quota pressure as clinic/account and tracker rows grow.

Current behavior: Authentication scans the settings sheet, then session setup loads settings, attempts shared dataset loading, records account metadata, and upserts the user tracker. Login intentionally defers full action history, but still performs several remote calls in one Streamlit run.

Evidence with file/function/location:

- `authenticate_user()` reads all settings values and scans rows at `reminders_app_v3.py:8035-8063`.
- `authenticate_clinic_access()` reads all settings values and scans rows at `reminders_app_v3.py:8066-8094`.
- `get_clinic_row_by_google_identity()` reads all settings values and scans rows at `reminders_app_v3.py:8137-8160`.
- `finish_authenticated_session()` wraps `load_settings(load_action_history=False)` and `load_shared_dataset_for_clinic()` in the login overlay at `reminders_app_v3.py:9721-9728`, then writes account/user tracker metadata at `reminders_app_v3.py:9728-9738`.
- `load_shared_dataset_for_clinic()` does a fresh settings row read before optional Drive work at `reminders_app_v3.py:3863-3895`.

Whether it was already mentioned in an older report: Yes. `PERFORMANCE_REPORT.md`, `PERFORMANCE_REPORT_SECOND_PASS.md`, and `PERFORMANCE_GOOGLE_SHEETS_PASS.md` all flagged login/account full-sheet scans. Current code has row caching, but the scan remains.

Likely root cause: Settings data is stored as a single worksheet and account lookup is implemented as full-sheet client-side scanning. Session setup also chains independent post-login responsibilities rather than reusing one authenticated row payload across the flow.

Safest fix approach: First add call-count tests for password, staff, Google, and remember-session flows. Then reuse the row/header/row-index already found during authentication through `finish_authenticated_session()` and `load_settings()` where possible. Defer any broader indexed storage redesign.

Test or measurement needed: Fake worksheet tests counting `get_all_values`, `row_values`, `batch_update`, tracker appends, and Drive calls for each login mode. Add timing around auth lookup, settings load, dataset pointer read, Drive download, and tracker writes.

Expected performance improvement: Removes at least one duplicate settings lookup per successful login and gives a measurable path to reduce login Sheets calls as clinic count grows.

### SPEED-002

Severity: P1

User action affected: first Reminders or Identify & Track render after login/session restoration; refresh/rerun when action tracker cache is cold or invalidated.

Impact: A clinic with a large action history can hit a long blank/spinner period because the app reads the whole Action tracker worksheet, filters by clinic, reduces records, then stores merged action state.

Current behavior: Login defers action history by setting `_action_tracker_pending_load_for`. When the active main section is Reminders or Stats, `ensure_action_tracker_loaded_for_current_clinic()` performs the full tracker load synchronously.

Evidence with file/function/location:

- Deferred settings load writes `_action_tracker_pending_load_for` when `load_action_history=False` at `reminders_app_v3.py:5092-5100`.
- `ensure_action_tracker_loaded_for_current_clinic()` calls `load_action_tracker_records_for_clinic()` synchronously at `reminders_app_v3.py:5162-5179`.
- The main render calls that loader whenever active section is Reminders or Stats at `reminders_app_v3.py:12848-12858`.
- `load_action_tracker_records_for_clinic()` calls `sheet.get_all_values()`, filters rows client-side, and reduces them at `reminders_app_v3.py:6000-6031`.

Whether it was already mentioned in an older report: Yes. It appears in `PERFORMANCE_REPORT.md`, `PERFORMANCE_REPORT_SECOND_PASS.md`, `PERFORMANCE_GOOGLE_SHEETS_PASS.md`, and `PERFORMANCE_STATISTICS_PASS.md`.

Likely root cause: The Action tracker worksheet is append-only and not queryable by clinic/date through the current gspread path. Reminders and Stats share the same full-history load even though Reminders needs only current hidden/action state.

Safest fix approach: Add measurement first. Then split action loading into two internal modes: a current reminder state load for Reminders and a full statistics history load for Identify & Track. Keep persisted data format backwards compatible.

Test or measurement needed: Fake tracker call-count tests for first Reminders render, first Stats render, mark sent/decline/undo invalidation, and refresh after cache invalidation. Add synthetic large action-history timing for reduce/merge.

Expected performance improvement: First Reminders render should avoid processing all historical actions once a current-state path exists; Stats can keep the full load only when needed.

### SPEED-003

Severity: P1

User action affected: editing reminder windows, success windows, Search Terms, exclusions, templates, Top Unreminded exclusions, and other saved settings.

Impact: Small UI edits can block on a settings row lookup, optional fresh row read, full JSON merge, settings batch update, and sometimes audit tracker writes. Rapid edits can feel laggy and create Google Sheets quota pressure.

Current behavior: Most settings edits call `save_settings_quietly()`, which defaults to `refresh_remote=True`. Existing rows read or reuse the clinic row, may read remote settings for preservation, build the full settings JSON, then batch-update the row.

Evidence with file/function/location:

- `save_settings()` begins with `_get_settings_row_for_clinic()` and optional `read_remote_settings_for_save(...)` at `reminders_app_v3.py:5321-5340`.
- It rebuilds the full settings blob at `reminders_app_v3.py:5473-5528` and writes with `batch_update` or `append_row` at `reminders_app_v3.py:5531-5575`.
- `save_settings_quietly()` defaults to `refresh_remote=True` at `reminders_app_v3.py:5661-5669`.
- Reminder numeric controls save on change at `reminders_app_v3.py:12170-12249`.
- Search Terms row fields each save on change at `reminders_app_v3.py:18648-18694`; deletes save and rerun at `reminders_app_v3.py:18712-18718`.
- Top Unreminded exclusions save once and then append one audit event per excluded item at `reminders_app_v3.py:10890-10923`.

Whether it was already mentioned in an older report: Yes. `PERFORMANCE_REPORT.md`, `PERFORMANCE_REPORT_SECOND_PASS.md`, `PERFORMANCE_GOOGLE_SHEETS_PASS.md`, and `PERFORMANCE_CACHE_EARLY_RETURN_PASS.md` all flagged synchronous settings saves.

Likely root cause: Correctness-preserving remote merge is coupled directly to widget `on_change` callbacks. The app saves the full settings document for narrow edits, with no no-op guard for many callbacks and no debounce/commit boundary.

Safest fix approach: Add call-count and no-op tests first. Then add narrowly scoped no-op guards for unchanged values and use `refresh_remote=False` only where a dirty-key or loaded-value guard proves the remote state was already current. Avoid queued/background saves until the behavior is characterized.

Test or measurement needed: Per-widget fake Sheets tests for unchanged reminder window, changed reminder window, single search-term edit, bulk Top Unreminded exclusion, and reset defaults. Count settings reads/writes and settings-audit appends.

Expected performance improvement: Removes avoidable writes for unchanged values and reduces per-edit perceived latency where a local loaded-value guard can safely skip fresh remote reads.

### SPEED-004

Severity: P1

User action affected: upload save/publish, removing saved uploads, clear/replace clinic data.

Impact: Large clinics can see long blocking upload saves because the app may download the existing Drive CSV, parse it, merge full DataFrames, serialize the entire merged dataset to CSV bytes, upload synchronously to Drive, update the pointer, save settings, and rerun.

Current behavior: Upload publish is an all-or-nothing Streamlit-run operation over the full merged clinic dataset. It already has limits and some batching, but the core work is still full-dataset synchronous.

Evidence with file/function/location:

- `process_file()` reads uploaded CSV/XLS/XLSX into memory and normalizes the DataFrame at `reminders_app_v3.py:7213-7235`.
- `summarize_uploads()` calls `process_file()` per blob and stores parsed DataFrames in its return value at `reminders_app_v3.py:9741-9759`.
- `publish_dataset_for_clinic()` loads an existing shared dataset if needed at `reminders_app_v3.py:4698-4709`, merges full frames at `reminders_app_v3.py:4711-4716`, serializes full CSV bytes at `reminders_app_v3.py:4718-4727`, uploads to Drive at `reminders_app_v3.py:4743-4757`, then records success at `reminders_app_v3.py:4783-4800`.
- `settings_pointer_utils.py:8-32` batches pointer cell updates, which reduces partial update risk but does not reduce the full CSV upload cost.

Whether it was already mentioned in an older report: Yes. `PERFORMANCE_UPLOAD_PASS.md` has the strongest current description. Earlier reports also flagged upload parse/cache and full dataset publish cost.

Likely root cause: The saved clinic dataset is stored as one CSV file in Drive, so any append/replace/remove rewrites the complete dataset.

Safest fix approach: Measure first. Then reduce memory lifetime and duplicate copies where tests already cover behavior. A storage redesign should be split into a separate project because it changes operational semantics.

Test or measurement needed: Synthetic upload benchmarks recording file bytes, rows, existing rows, merged rows, CSV bytes, parse time, Drive download time, Drive upload time, pointer update time, and peak memory where available.

Expected performance improvement: Near-term copy/lifetime reductions should lower memory spikes. Major latency improvements require changing from whole-file rewrite to a different storage/update model.

### SPEED-005

Severity: P1

User action affected: opening Identify & Track, changing success windows/date range, refreshing stats, viewing large outcome histories.

Impact: Stats can still feel slow for large clinics even after the subview-render fix because the base calculation performs broad generated/action/outcome work before the selected subview branch runs.

Current behavior: `render_stats_tab()` reduces current action records, builds a cache signature, and on cache miss calculates action item rows, actioned rows, expanded sent records, outcome rows, generated rows, item outcome groups, and sender outcome groups before rendering the selected subview.

Evidence with file/function/location:

- `render_stats_tab()` starts the stats calculation path at `reminders_app_v3.py:18045`.
- It gets reduced action records and cache signature at `reminders_app_v3.py:18114-18124`.
- On cache miss it expands/filter actions, builds outcomes, builds generated rows, converts generated rows to records, and builds item/sender outcome frames at `reminders_app_v3.py:18135-18185`.
- Only after that does it choose the active Stats subview at `reminders_app_v3.py:18222-18324`.
- `build_reminder_outcomes()` itself prepares sales and iterates sent records against sales-derived maps at `reminders_app_v3.py:16144-16225`.

Whether it was already mentioned in an older report: Partly. Older reports correctly flagged Stats cost, but the specific "all `st.tabs()` bodies execute" finding is no longer current. The remaining base-calculation cost is still valid.

Likely root cause: The Stats page needs shared summary cards and outcome context, so expensive all-time artifacts are built eagerly for the whole Stats surface. Some work is cached, but the cache key includes large action/sales inputs and cache misses remain expensive.

Safest fix approach: Keep the selected-subview UI. Extract a `StatsRenderContext` with measured phases and add subview-aware lazy calculation only where the summary cards do not need the artifact. Avoid changing outcome semantics.

Test or measurement needed: Timing around action reduction, generated rows, outcome matching, item/sender grouping, CSV export, and selected subview render. Add call/count tests proving only selected-subview-only frames are built.

Expected performance improvement: Lower first-render and refresh cost for Stats subviews that do not need every derived frame; better cache hit diagnostics for large clinics.

### SPEED-006

Severity: P1

User action affected: Send Reminders page load/reruns, tab nav badge render, reminder date/window changes.

Impact: Reminder generation and active badge/window calculation can repeat full DataFrame preparation/filter/group work around one user action, especially when the badge uses one prepared frame and the visible reminder table uses another date-filtered prepared frame.

Current behavior: The main nav allows the active tab to calculate the Reminders badge. The Reminders body separately determines whether the prepared rows/window are cached, then renders the table. Badge calculation can call `get_prepared_df()` and `build_active_reminder_window()`, while the table path uses `get_prepared_reminder_rows_for_date()` and `build_active_reminder_window()`.

Evidence with file/function/location:

- Nav badge calculation allows expensive counts for the active tab at `reminders_app_v3.py:10732-10739`.
- `get_active_reminder_badge_count()` calls `get_prepared_df()`, `build_active_reminder_window()`, converts grouped rows to records, and filters hidden reminders at `reminders_app_v3.py:12322-12355`.
- Reminders render builds/caches date-filtered prepared rows and active window at `reminders_app_v3.py:18934-18990`.
- `get_prepared_df()` and `get_prepared_reminder_rows_for_date()` use different cache entries at `reminders_app_v3.py:11992-12021` and `reminders_app_v3.py:12121-12129`.

Whether it was already mentioned in an older report: Yes. Older reports flagged badge/window duplication. Current cache work reduces some repeated work but has not fully unified badge and table derivation.

Likely root cause: Badge count and table render evolved as separate helpers with separate cache keys and slightly different data inputs.

Safest fix approach: Measure before changing. Then build the visible active window once per Reminders render and pass the count/result into both banner/badge/table where date semantics match. Keep a separate cached global badge only for inactive nav display.

Test or measurement needed: Existing `tests/test_ci_reminders_badge.py` plus new call-count tests around one Reminders render: prepared rows built once, active window built once, badge cache invalidates after sent/decline/undo and rule/exclusion changes.

Expected performance improvement: Fewer large DataFrame transformations per Reminders rerun and fewer "Loading reminders" overlays on already-cached paths.

### SPEED-007

Severity: P1

User action affected: Configure Reminders render after data upload, adding/removing search terms, excluding Top Unreminded Items individually or in bulk.

Impact: The new Top Unreminded Items subsection can make Configure Reminders slow for large uploaded datasets because it runs full search-term matching over every sale item and then groups/sorts the unmatched rows.

Current behavior: The section renders under Current Search Terms whenever Configure Reminders is active. It calls `get_top_unreminded_items()`, which caches by clinic/data/rules/exclusions/refresh version, but cache misses run `map_intervals_vec()` on `Item Name`, `Qty`, and `Amount` for the full working DataFrame.

Evidence with file/function/location:

- `build_top_unreminded_items()` copies the full working frame, calls `map_intervals_vec()`, filters unmatched items, applies exclusions, groups by normalized item, and sorts top 10 by count/revenue at `reminders_app_v3.py:10815-10862`.
- `get_top_unreminded_items()` caches results in session at `reminders_app_v3.py:10865-10880`.
- Bulk and single exclusions save settings, append audit events, invalidate the top-unreminded cache, and rerun at `reminders_app_v3.py:10890-10927`.
- The section is always called after Current Search Terms on the Configure Reminders tab at `reminders_app_v3.py:18736-18815`.

Whether it was already mentioned in an older report: No. This feature was added after the earlier performance reports.

Likely root cause: The feature intentionally answers a full-dataset question, and it currently computes from raw sales rows rather than reusing reminder mapping artifacts or a persisted item aggregate.

Safest fix approach: Add timing and row/rule counts first. Then cache a normalized item aggregate by data version and compute reminder coverage at the unique-item level where behavior matches row-level matching. Keep exact current exclusion behavior in tests.

Test or measurement needed: Synthetic large dataset test for top-unreminded calculation; call-count/timing test proving Exclude all 10 saves once but does not recompute until rerun; correctness test comparing row-level and aggregate-level top 10 outputs.

Expected performance improvement: Reduces Configure Reminders cache-miss cost from scanning all transaction rows per rule to scanning unique item names plus aggregated count/revenue, if implemented safely.

## Top 3 Highest-Impact Speed Fixes

1. Reuse authenticated settings row data across login/session setup and add call-count tests for all login modes.
2. Split action tracker loading into current Reminders state vs full Stats history, with fake tracker call-count tests first.
3. Add measured Stats/Reminders render contexts so one rerun reuses prepared/action/outcome artifacts instead of rebuilding similar frames.

## Suggested Fix Order

1. Add measurement and call-count tests for login, settings save, tracker load, Drive upload/download, Reminders render, Stats render, and Top Unreminded Items.
2. Fix login/session row reuse, because it is low-risk and hits every user.
3. Reduce cold action tracker load cost or at least separate Reminders current-state loading from Stats history loading.
4. Add no-op guards and narrower save paths for unchanged settings edits.
5. Optimize Reminders badge/window reuse.
6. Optimize Stats base context and selected-subview-only work.
7. Optimize Top Unreminded Items using unique-item aggregation after correctness tests.
8. Tackle full-dataset upload/publish only after measurement, because meaningful gains may require a storage design change.

## Existing Validation Commands

- `python -m py_compile reminders_app_v3.py settings_pointer_utils.py scripts/*.py`
- `python -m unittest discover -s tests -p "test_ci_*.py"`
- `python -m unittest discover -s tests`
- `python -m unittest tests.test_ci_auth_session tests.test_ci_streamlit_login_render tests.test_ci_settings_save_state`
- `python -m unittest tests.test_ci_dataset_update tests.test_ci_error_handling`
- `python -m unittest tests.test_ci_reminders_badge tests.test_ci_reminder_workflows`
- `python -m unittest tests.test_ci_statistics`
- `bash scripts/pre_merge_check.sh`
- `bash scripts/pilot_release_check.sh`
- `python -m pip check`

## Measurements Or Call-Count Tests To Add First

- Login call-count tests for password, staff access, Google identity, remember-session restore, and switching clinics in the same browser.
- Action tracker cold-load tests counting `get_all_values()` and reduction time for small, medium, and large fake histories.
- Settings save tests counting row reads, batch updates, and tracker/audit appends for unchanged vs changed widget values.
- Upload publish measurements for parsed rows, existing rows, merged rows, CSV bytes, Drive download/upload time, and settings pointer update time.
- Reminders render measurements for prepared-row build count, active-window build count, visible widget count, and cache-hit/miss state.
- Stats render phase timings for generated rows, action expansion, outcome matching, item/sender grouping, display prep, and CSV export.
- Top Unreminded Items timing by uploaded row count, unique item count, rule count, and exclusion count.
