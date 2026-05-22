# Performance Report Second Pass

Date: 2026-05-19

Scope: fresh performance audit of the current repository. This report revalidates `PERFORMANCE_REPORT.md` against the current code and treats the older report as historical context only. No application code was changed during this pass.

Reviewed:

- `PERFORMANCE_REPORT.md`
- `CODEBASE_AUDIT.md`
- `QUALITY_GATES_REPORT.md`
- `ERROR_HANDLING_REPORT.md`
- `ARCHITECTURE_REFACTOR_PLAN.md`
- `reminders_app_v3.py`
- `tests/`
- `scripts/`

## 1. Executive Summary

The current highest-confidence performance risks are still Google Sheets and Google Drive latency on hot paths, plus Streamlit rerun cost in the Stats and Reminders screens. The app has improved since the first performance report: upload parsing has a 50 MB per-file limit, upload parsing is cached, Drive transfers have elapsed-time guards, reminders and stats tables are now paginated at 50 rows, and several statistics helpers are cached. Those are meaningful fixes.

The biggest likely user-visible bottlenecks today are:

- Login and settings load can still trigger full Google Sheets scans and full action tracker loads.
- Stats rendering calculates all Stats subtabs eagerly because `st.tabs` executes every tab body during a rerun.
- Stats CSV export bytes are generated for every non-empty Stats subtab on every render, even when the user does not download a CSV.
- Upload save still serializes and uploads the whole merged clinic dataset as CSV.
- Search-term edits and many small UI controls still make synchronous Google Sheets writes.

Lowest-risk quick wins:

- Add timing and call-count measurement around Google Sheets, Drive, Stats build, upload parse/save, and settings save.
- Cache or defer Stats CSV byte generation.
- Reuse already-loaded action records during Stats refresh instead of reloading unless explicitly syncing.
- Batch obvious multi-row tracker writes.
- Add regression tests for Google call counts and Stats view render costs before larger changes.

Compared with the old `PERFORMANCE_REPORT.md`, the old findings are mostly still relevant but several are less severe. The old unbounded reminder table render issue is partially fixed by pagination. The old upload cache nesting issue is mostly fixed. The old "external calls have no timeout" finding is now partially fixed for Drive, but Sheets retries still lack an elapsed-time budget.

## 2. Old Findings Revalidated

### P1: Full Google Sheets scans on login and account lookup

Classification: Still valid.

Evidence:

- `authenticate_user()` calls `sheet.get_all_records()` and scans every clinic row in `reminders_app_v3.py:7069`.
- `get_clinic_row()` also calls `sheet.get_all_records()` in `reminders_app_v3.py:7089`.
- `get_clinic_row_by_google_identity()` scans all records for Google identity matching in `reminders_app_v3.py:7100`.

Current severity: P1.

Backlog: Keep. This is one of the highest-confidence backend/API latency and quota risks as clinic count grows.

Smallest safe next step: add fake-sheet call-count tests around login helpers, then introduce a row-indexed lookup path for ClinicID and Google identity without changing auth behavior.

### P1: Action tracker full sheet load during settings load

Classification: Still valid, with some caching.

Evidence:

- `load_settings()` calls `load_action_tracker_records_for_clinic()` in `reminders_app_v3.py:4403`.
- `load_action_tracker_records_for_clinic()` reads `sheet.get_all_values()` for the whole action tracker, filters by clinic, reduces records, and caches in session state in `reminders_app_v3.py:5235`.

Current severity: P1.

Backlog: Keep. The session cache helps within one browser session, but initial login and explicit refresh can still read the full tracker sheet.

Smallest safe next step: split "current hidden/action state needed for reminders" from "full outcome history needed for Stats", then load the larger history only when Stats or actioned history needs it.

### P1: Reminder table renders every row with many widgets and per-row CSS

Classification: Partially valid.

Evidence:

- `render_table_with_buttons()` now calls `paginate_dataframe()` with `REMINDER_TABLE_PAGE_SIZE = 50` before rendering row widgets in `reminders_app_v3.py:11637`.
- It still injects action-button CSS per rendered row through `render_reminder_action_button_styles()` in `reminders_app_v3.py:11682`.
- Each rendered active row still creates multiple Streamlit columns and three buttons.
- `render_actioned_reminders_tab()` still renders rows with Streamlit columns/buttons and does not use the shared paginator in the inspected code path in `reminders_app_v3.py:11380`.

Current severity: P2 for active reminders after pagination; P1/P2 for actioned reminders if a clinic has many actioned rows and selects "All".

Backlog: Keep, downgraded for active reminders. Add pagination to actioned reminders and move repeated CSS injection out of row loops.

### P1: Badge calculation repeats filtering and grouping work

Classification: Still valid.

Evidence:

- `get_active_reminder_badge_count()` rebuilds prepared reminders, filters by date/exclusions, groups reminders, converts grouped rows to dicts, and filters hidden reminders in `reminders_app_v3.py:10100`.
- Main rendering calls it for tab badge and again inside Reminders screen paths.

Current severity: P1/P2 depending on dataset size.

Backlog: Keep. It is likely visible on reruns with large datasets.

Smallest safe next step: cache badge count by data version, rules fingerprint, exclusion fingerprint, date controls, and action-history version.

### P1: Settings autosave performs synchronous Sheets writes

Classification: Still valid.

Evidence:

- `save_settings()` performs row lookup, optional remote read, JSON merge, `batch_update`, and sometimes `update_settings_row_fields()` or `append_row` in `reminders_app_v3.py:4593`.
- `save_settings_quietly()` is used as the `on_change` callback for many controls across Search Terms, Reminders, Stats, Exclusions, and account flows.
- Search-term row edits each call `save_settings_quietly()` in `render_search_terms_editor()` in `reminders_app_v3.py:14763` onward.

Current severity: P1.

Backlog: Keep. Correctness protections are valuable, but the write path remains synchronous and high-latency.

Smallest safe next step: add no-op write guards and timing/call-count tests before any debounce or queued-save change.

### P2: Upload cache retains large file bytes/DataFrames in multiple layers

Classification: Partially fixed.

Evidence:

- `process_file()` is cached with `@st.cache_data` in `reminders_app_v3.py:6330`.
- `summarize_uploads()` is cached in `reminders_app_v3.py:8246`.
- Upload blobs are created from all selected files with `_to_blob()` and fingerprinted; file size/count/row/column limits now exist at `reminders_app_v3.py:6184`.
- The old nested cached-resource wrapper called out in the old report is no longer present.

Current severity: P2.

Backlog: Keep as memory pressure risk, but downgrade. Current limits reduce crash risk, yet a 5 x 50 MB upload can still produce large cached byte and DataFrame objects.

Smallest safe next step: measure memory and cache size for 1, 3, and 5 max-size uploads before changing cache shape.

### P2: Upload publishing serializes and uploads the entire merged dataset

Classification: Still valid.

Evidence:

- `publish_dataset_for_clinic()` merges existing and new data, then runs `merged_df.to_csv(index=False).encode("utf-8")` and uploads the full bytes to Drive in `reminders_app_v3.py:4006`.
- The upload flow also loads the existing shared dataset before publish in `reminders_app_v3.py:10793`.

Current severity: P1/P2. It is user-visible for large clinics and can consume memory proportional to the whole dataset.

Backlog: Keep. The behavior is simple and reliable but becomes expensive as dataset history grows.

Smallest safe next step: add timing and byte-size metrics for merged CSV generation and Drive upload, then consider split storage or append-only snapshots later.

### P2: Multiple tracker events during multi-file upload are written one row at a time

Classification: Partially valid.

Evidence:

- `append_tracker_rows()` exists and uses `append_rows()` when available in `reminders_app_v3.py:6518`.
- Upload save still loops `saved_history_rows` and calls `record_dataset_tracker_event()` for each file in `reminders_app_v3.py:10829`.
- `record_dataset_tracker_event()` ultimately calls single-row `append_tracker_row()` in `reminders_app_v3.py:6613`.

Current severity: P2.

Backlog: Keep. This is a low-risk quota and latency win.

Smallest safe next step: create a batched dataset tracker helper for the upload-save loop only.

### P2: Tracker sheet/header setup synchronously enumerates worksheets

Classification: Still valid, partially mitigated.

Evidence:

- `ensure_tracking_sheets()` runs after main navigation setup in `reminders_app_v3.py:8727`.
- `ensure_tracking_sheets_once()` is cache-resource wrapped, but its first execution calls `spreadsheet.worksheets()` and may touch headers for every tracker worksheet in `reminders_app_v3.py:6877`.

Current severity: P2.

Backlog: Keep, but not urgent. The cache limits repeat cost per process.

Smallest safe next step: defer tracker-sheet setup until the first tracker write or first logged-in flow that requires trackers.

### P2: Statistics rebuilds row dictionaries several times per render

Classification: Partially valid, changed.

Evidence:

- Stats is now folded into `render_stats_tab()` and uses cached `build_reminder_outcomes()` plus cached generated rows.
- It still builds all Stats tab frames every render: item group, item actioning, team, sent reminders, and successes in `reminders_app_v3.py:14513`.
- Several helpers still call `to_dict("records")`, including `filter_generated_for_statistics_period()` and `build_statistics_item_frame()` in `reminders_app_v3.py:12481` and `reminders_app_v3.py:12663`.

Current severity: P1/P2. The old exact implementation changed, but eager Stats-tab execution is now the larger issue.

Backlog: Keep, rewritten as "Stats eager render and repeated frame/export building".

### P2: Rule matching loops over every rule with vector operations per rule

Classification: Still valid.

Evidence:

- `map_intervals_vec()` loops over every configured search term and runs `item_norm.str.contains(term, regex=False)` over the full item series for each term in `reminders_app_v3.py:9662`.
- `ensure_reminder_columns()` calls `map_intervals_vec()` for prepared reminders in `reminders_app_v3.py:9787`.

Current severity: P2 for normal clinics; P1 if clinics add many rules or upload large datasets.

Backlog: Keep, but measure first. The code is straightforward and covered by tests, so a trie/regex rewrite should not happen before profiling.

### P2: External Google API calls lack timeout controls

Classification: Partially fixed.

Evidence:

- Drive download and upload now enforce elapsed-time budgets around `next_chunk()` loops in `drive_download_bytes()` and `drive_upsert_csv_bytes()` in `reminders_app_v3.py:3107` and `reminders_app_v3.py:3448`.
- `_gspread_retry()` retries transient Sheets errors but has no overall elapsed-time budget and sleeps inline in `reminders_app_v3.py:3619`.

Current severity: P2.

Backlog: Keep for Sheets. Drive timeout part is no longer accurate.

### P3: Repeated JSON serialization for settings comparison

Classification: Needs measurement before action.

Evidence:

- `save_settings()` still serializes the full settings blob with `json.dumps(settings_data)` in `reminders_app_v3.py:4769`.
- The save path does significant merge and remote read work, so JSON serialization is likely not the dominant cost.

Current severity: P3.

Backlog: Keep only as a cleanup item after Google call counts are measured.

## 3. New Findings

### P1: Stats renders every subtab eagerly

Location: `render_stats_tab()` in `reminders_app_v3.py:14513`.

Hot path: opening Stats, changing success windows, clicking Refresh Stats, and any Streamlit rerun while Stats is active.

Why it matters: Streamlit `st.tabs()` executes all tab bodies on every rerun. The current code builds Item, Item Actioning, Team, Sent Reminders, and Successes frames in one pass, then prepares display/export data for each non-empty tab.

Expected user impact: Stats can feel slow or hang for large clinics even when the user only wants one subtab.

How to measure: wrap timers around each Stats subtab block and record row counts, output rows, and elapsed milliseconds to the Performance tracker or a local debug log.

Smallest safe fix: replace Stats subtabs with a segmented control/radio that renders only the selected view, preserving labels and table behavior.

Validation plan: add tests for selected-view frame creation if extracted; run `python -m unittest tests.test_ci_statistics` and `python -m unittest discover -s tests -p "test_ci_*.py"`.

Tests before fixing: Yes. Add a characterization test around a small extracted `build_stats_view_frame(view_name, ...)` helper before changing rendering control flow.

### P2: Stats CSV bytes are generated for every visible export button

Location: `render_stats_csv_export()` in `reminders_app_v3.py:14354`.

Hot path: every Stats render with non-empty tables.

Why it matters: `render_stats_csv_export()` copies the whole frame, prepares display/export formatting, converts to CSV bytes, and creates a download button. Because all Stats tab bodies execute, this can happen multiple times per Stats render.

Expected user impact: extra CPU and memory on Stats, especially for all-time Sent Reminders and large item tables.

How to measure: record elapsed time and bytes length from `stats_export_csv_bytes()` per view.

Smallest safe fix: cache export bytes by view name plus data fingerprint, or render export generation behind an explicit "Prepare CSV" button for the active view only.

Validation plan: add a unit test for export formatting and one fake render/call-count test if an export helper is extracted.

Tests before fixing: Yes for formatting; optional for caching behavior.

### P1: Refresh Stats can reload large action history and saved dataset synchronously

Location: `refresh_outcome_results_state()` in `reminders_app_v3.py:14463`.

Hot path: clicking Refresh Stats.

Why it matters: when called with `sync_remote=True` or when future callers set it, the function invalidates the action cache, reloads full action tracker records, may reload the shared dataset, then recalculates Stats.

Expected user impact: page overlay/hang during refresh, especially after search-term edits or large tracker growth.

How to measure: record elapsed time and row counts for action tracker load, dataset reload, outcome build, generated-row build, and final render.

Smallest safe fix: keep normal Refresh Stats local unless the user explicitly requests "Sync latest data", and make any remote sync report progress by stage.

Validation plan: call-count tests around refresh with fake tracker/dataset loaders.

Tests before fixing: Yes.

### P1: Synchronous performance/error tracking can add more Google writes to slow paths

Location: `record_performance_tracker_event()` in `reminders_app_v3.py:6685`, `record_error_tracker_event()` near `reminders_app_v3.py:6640`, and upload callers around `reminders_app_v3.py:10653`.

Hot path: upload parse/save errors, dataset publish, Drive failures, and any instrumented path.

Why it matters: tracker writes are helpful but each event can become a Google Sheets append. During failures the app can make extra remote writes while already under latency or quota pressure.

Expected user impact: slower failures and possible quota amplification.

How to measure: count tracker append calls per upload save, upload failure, and refresh.

Smallest safe fix: batch multiple tracker rows in one helper where the rows are naturally known together, starting with dataset upload saved events.

Validation plan: fake `append_rows` and assert one batch call for multi-file upload event rows.

Tests before fixing: Yes.

### P2: Broad `st.cache_data.clear()` can evict unrelated expensive caches

Location: `reset_uploaded_data_state()` in `reminders_app_v3.py:560`.

Hot path: dataset reset and other upload/reset flows.

Why it matters: clearing all Streamlit data caches can invalidate unrelated parsed files, prepared reminders, generated Stats rows, and outcome caches. That makes the next rerun do more work than needed.

Expected user impact: slower first rerun after removing/changing upload data.

How to measure: add counters for `process_file`, `ensure_reminder_columns`, `cached_statistics_generated_rows`, and `build_reminder_outcomes` before and after reset flows.

Smallest safe fix: replace global cache clear with targeted `.clear()` calls for known dataset-derived caches.

Validation plan: unit test that reset clears runtime session keys and targeted cache clear functions are called.

Tests before fixing: Yes.

### P2: Current action history is stored as large session-state lists

Location: `load_action_tracker_records_for_clinic()` caches records in `_action_tracker_records_cache` in `reminders_app_v3.py:5235`; merged action rows are also stored in `deleted_reminders` and `wa_reminder_log` during `load_settings()`.

Hot path: login, Reminders, Stats, actioned reminders.

Why it matters: full action history is kept in memory and repeatedly copied with `[dict(record) ...]`. This is okay for small clinics but grows with every action.

Expected user impact: memory pressure and slower reruns for busy clinics.

How to measure: record action record count, approximate serialized bytes, and copy time during `load_settings()` and Stats render.

Smallest safe fix: store a compact current-action index separately from full history, and only hydrate full records for Stats/actioned views.

Validation plan: characterization tests for hidden reminder filtering and actioned table behavior.

Tests before fixing: Yes.

### P2: Active reminder badge does full grouping even when Reminders tab is not active

Location: `get_active_reminder_badge_count()` in `reminders_app_v3.py:10100` and main render around `reminders_app_v3.py:15176`.

Hot path: logged-in reruns on any main tab with a working dataset.

Why it matters: tab badge labels are useful, but badge count generation can prepare/filter/group reminders and examine action state even when the user is editing Search Terms or Exclusions.

Expected user impact: slower tab switching and settings edits on large datasets.

How to measure: time badge count by tab, dataset rows, generated due rows, grouped rows, and action records.

Smallest safe fix: memoize badge count with a narrow key and invalidate only when data/rules/exclusions/date/action state changes.

Validation plan: tests around badge count invalidation keys and existing `tests/test_ci_reminders_badge.py`.

Tests before fixing: Yes.

### P2: Search Terms autosave can write once per field edit

Location: `render_search_terms_editor()` save callbacks in `reminders_app_v3.py:14763` and following.

Hot path: editing rule days, reminder steps, visible text, use-quantity, deleting/resetting rules.

Why it matters: each field change does a synchronous settings save and then writes a settings audit event. Multiple edits can create repeated Sheets reads/writes and tracker writes.

Expected user impact: laggy settings editing and quota risk for clinics with many rules.

How to measure: count settings reads/writes and audit writes during editing three fields in one rule.

Smallest safe fix: add no-op guards to avoid saving/auditing when a value did not materially change; later consider explicit "Save changes".

Validation plan: tests for save callback no-op and changed-value behavior.

Tests before fixing: Yes.

### P2: Upload parse and publish duplicate large DataFrame copies

Location: upload flow around `reminders_app_v3.py:10631` and `publish_dataset_for_clinic()` in `reminders_app_v3.py:4006`.

Hot path: uploading and saving sales exports.

Why it matters: the flow builds upload blobs, cached parsed DataFrames, concatenated working DataFrames, sanitized copies, canonical-schema copies, existing dataset copies, merged DataFrames, and CSV bytes.

Expected user impact: memory spikes and slower saves for large exports.

How to measure: record rows, columns, upload byte size, merged CSV byte size, and elapsed time for parse, concat, sanitize, merge, and upload.

Smallest safe fix: measure first. Then remove avoidable copies only where tests cover schema and upload behavior.

Validation plan: existing upload/dataset tests plus a new synthetic large DataFrame benchmark script.

Tests before fixing: Yes.

### P2: Google Sheets retries have no total elapsed-time budget

Location: `_gspread_retry()` in `reminders_app_v3.py:3619`.

Hot path: almost every settings/tracker/account Sheets operation.

Why it matters: transient retries sleep inline and then make a final call after the retry loop. A slow underlying call can still hang a Streamlit run.

Expected user impact: page appears frozen during Sheets incidents.

How to measure: fake slow/transient gspread calls and record max elapsed time.

Smallest safe fix: add optional elapsed-time budget to `_gspread_retry()` with conservative default and user-safe timeout error.

Validation plan: unit tests with fake API errors and sleep patched to no-op.

Tests before fixing: Yes.

### P3: Stats column config objects are rebuilt on each render

Location: `outcome_display_column_config()`, `stats_item_actioning_column_config()`, and `stats_team_column_config()` around `reminders_app_v3.py:14380`.

Hot path: Stats table rendering.

Why it matters: small CPU cleanup; not likely the dominant cost.

Expected user impact: minor.

How to measure: profile render with and without cached config builders.

Smallest safe fix: cache pure column config dictionaries where Streamlit objects are stable, or leave alone if profiling shows negligible time.

Validation plan: visual smoke only.

Tests before fixing: No.

## 4. Big Wins

### 1. Indexed clinic/account lookup

User action affected: password login, staff access login, Google login/signup matching, account profile flows.

Expected impact: faster login and lower Sheets quota use as clinic count grows.

Implementation risk: medium. Auth behavior is sensitive.

Files likely touched: `reminders_app_v3.py`, `tests/test_ci_auth_session.py`, `tests/test_ci_streamlit_login_render.py`, possibly new account lookup tests.

Tests needed: fake settings sheet call-count and behavior tests for password, staff, and Google identity matching.

One small PR: Yes, if limited to lookup helpers and tests.

### 2. Split action-history loading by use case

User action affected: login, normal Reminders view, Stats view, actioned history.

Expected impact: faster login and lower memory for clinics with long action histories.

Implementation risk: medium/high because action state affects hidden reminders and success outcomes.

Files likely touched: `reminders_app_v3.py`, `tests/test_ci_settings_save_state.py`, `tests/test_ci_statistics.py`, `tests/test_ci_reminder_workflows.py`.

Tests needed: current-action index tests and outcome-history tests before refactor.

One small PR: No. Start with measurement and characterization tests.

### 3. Lazy-render Stats views

User action affected: opening Stats, switching Stats subtabs, Refresh Stats.

Expected impact: high for large clinics. Users only pay for the selected view.

Implementation risk: medium. UI changes from tabs to selected view must preserve behavior.

Files likely touched: `reminders_app_v3.py`, `tests/test_ci_statistics.py`, visual CSS tests if styling changes.

Tests needed: extracted Stats view builder tests.

One small PR: Possible after tests are added.

### 4. Cache or defer Stats CSV export generation

User action affected: Stats rendering.

Expected impact: moderate. Reduces CPU and memory on every Stats render.

Implementation risk: low/medium.

Files likely touched: `reminders_app_v3.py`, `tests/test_ci_statistics.py`.

Tests needed: export formatting and "all rows included" tests.

One small PR: Yes.

### 5. Reduce whole-dataset upload/save cost

User action affected: upload save/publish, replacing overlapping date ranges.

Expected impact: high for large clinics.

Implementation risk: high if storage semantics change.

Files likely touched: `reminders_app_v3.py`, `settings_pointer_utils.py`, dataset tests.

Tests needed: extensive dataset merge/pointer/Drive fake tests.

One small PR: No. Start with instrumentation and measurement. Avoid storage redesign until there is evidence.

## 5. Small Wins

1. Add performance timing around `build_reminder_outcomes()`.
   - Code area: `render_stats_tab()` and `build_reminder_outcomes()`.
   - Safe because it only records diagnostics.
   - Impact: makes Stats slowness measurable.
   - Validation: `python -m unittest tests.test_ci_statistics`.

2. Add Sheets call-count tests for login lookup helpers.
   - Code area: `authenticate_user()`, `get_clinic_row()`, `get_clinic_row_by_google_identity()`.
   - Safe because tests only characterize behavior.
   - Impact: protects future indexed lookup work.
   - Validation: `python -m unittest tests.test_ci_auth_session`.

3. Batch upload-saved dataset tracker events.
   - Code area: upload save loop near `reminders_app_v3.py:10829`.
   - Safe because tracker writes are append-only diagnostics and `append_tracker_rows()` already exists.
   - Impact: fewer Sheets writes during multi-file uploads.
   - Validation: `python -m unittest tests.test_ci_dataset_update`.

4. Cache Stats CSV bytes by frame fingerprint.
   - Code area: `render_stats_csv_export()`.
   - Safe if formatting stays identical.
   - Impact: lower repeated CPU/memory on Stats reruns.
   - Validation: `python -m unittest tests.test_ci_statistics`.

5. Add no-op guard for unchanged Search Terms field saves.
   - Code area: nested callbacks in `render_search_terms_editor()`.
   - Safe if unchanged fields currently save redundantly.
   - Impact: fewer settings writes and audit rows.
   - Validation: targeted callback helper tests after extracting thin helpers.

6. Add paginator to actioned reminders "All" view.
   - Code area: `render_actioned_reminders_tab()`.
   - Safe because active reminders already use shared pagination.
   - Impact: prevents widget explosion for large action histories.
   - Validation: `python -m unittest tests.test_ci_reminder_workflows`.

7. Move per-row reminder action CSS to one stylesheet plus state classes.
   - Code area: `render_reminder_action_button_styles()` and `render_table_with_buttons()`.
   - Safe if visual behavior is verified.
   - Impact: less markdown injection per row.
   - Validation: visual manual smoke plus `python -m unittest tests.test_ci_visual_theme_css`.

8. Avoid `st.cache_data.clear()` broad cache invalidation.
   - Code area: `reset_uploaded_data_state()`.
   - Safe after targeted cache clear tests.
   - Impact: fewer expensive recomputes after upload reset.
   - Validation: new reset-state test plus `python -m unittest discover -s tests -p "test_ci_*.py"`.

9. Record upload byte counts and merged CSV byte size.
   - Code area: upload blob creation and `publish_dataset_for_clinic()`.
   - Safe diagnostic-only change.
   - Impact: supports decisions about storage format and limits.
   - Validation: `python -m unittest tests.test_ci_dataset_update`.

10. Defer tracker worksheet setup until first tracker write.
    - Code area: `ensure_tracking_sheets()` call site and tracker helpers.
    - Safe if tracker writes still create sheets lazily.
    - Impact: lower first logged-in rerun cost.
    - Validation: fake tracker-sheet tests plus startup tests.

11. Cache or precompute normalized client/item exclusions.
    - Code area: `apply_reminder_exclusion_filters()` and exclusion save/load helpers.
    - Safe with current exclusion tests.
    - Impact: lower repeated filtering cost for Reminders and Stats generated rows.
    - Validation: `python -m unittest tests.test_ci_reminder_workflows tests.test_ci_logic_edge_cases`.

12. Add a Stats selected-view helper before changing UI.
    - Code area: `render_stats_tab()`.
    - Safe as extraction/characterization if behavior is preserved.
    - Impact: enables lazy Stats rendering.
    - Validation: `python -m unittest tests.test_ci_statistics`.

## 6. Measurement Plan

Add timing hooks around these locations:

- `_gspread_retry()`: function name, status, retries, elapsed milliseconds.
- `drive_download_bytes()` and `drive_upsert_csv_bytes()`: file bytes, elapsed milliseconds, chunk count if available.
- `load_settings()`: settings row read, settings JSON parse, action tracker load, merge logs.
- `load_action_tracker_records_for_clinic()`: total sheet rows, clinic rows, reduced rows, elapsed milliseconds.
- `process_file()` and `summarize_uploads()`: file count, bytes, rows, columns, elapsed milliseconds.
- `publish_dataset_for_clinic()`: existing rows, new rows, merged rows, CSV bytes, Drive upload elapsed milliseconds, pointer update elapsed milliseconds.
- `get_active_reminder_badge_count()`: prepared rows, date-filtered rows, grouped rows, hidden-filtered rows, elapsed milliseconds.
- `render_table_with_buttons()` and `render_actioned_reminders_tab()`: source rows, rendered rows, widget count estimate, elapsed milliseconds.
- `render_stats_tab()`: outcome rows, generated rows, action records, per-subtab frame rows, per-subtab elapsed milliseconds, CSV byte generation elapsed milliseconds.
- `save_settings()`: fresh read elapsed, merge elapsed, write elapsed, settings JSON bytes.

Record these row/file/API-call counts:

- Settings rows scanned.
- Action tracker rows scanned and clinic rows retained.
- Dataset tracker rows written.
- Error/performance/settings audit tracker rows written.
- Uploaded file count and file bytes.
- Parsed rows and columns per file.
- Merged dataset rows and CSV bytes.
- Prepared reminder rows.
- Active due rows before and after exclusions.
- Grouped reminder rows.
- Outcome sent rows, success rows, pending rows, no-match rows.
- Stats export CSV bytes per view.

User actions to measure:

- Password login.
- Google login/signup.
- Staff access login.
- Upload parse with 1 small CSV, 1 large CSV, and 5 files.
- Upload save/publish with and without existing dataset.
- Removing saved clinic data.
- Reminder refresh/open Reminders tab.
- Active reminder table render.
- Actioned reminder table render, especially "All".
- Mark one reminder sent.
- Mark all listed reminders sent.
- Open Stats.
- Click Refresh Stats after editing Search Terms.
- Switch each Stats subtab/view.
- Export CSV for each Stats view.
- Edit reminder lookback/ahead/group settings.
- Edit Search Terms rule days and visible text.

Suggested fake tests for call counts:

- Login helper uses at most one row lookup call once an index helper exists.
- Refresh Stats without remote sync does not call `load_action_tracker_records_for_clinic()`.
- Multi-file upload saved events call `append_rows()` once.
- Stats render selected-view helper builds only the selected frame.
- Stats CSV export helper includes all rows but is called only for the selected view.
- `reset_uploaded_data_state()` clears targeted caches and does not call global `st.cache_data.clear()`.

Suggested manual Streamlit profiling steps:

1. Add temporary debug-only timing output controlled by a local flag or session key.
2. Use the same clinic dataset for before/after comparisons.
3. Capture browser-perceived time from click to stable page for login, upload save, Reminders, Stats, Refresh Stats, and CSV export.
4. Capture Performance tracker rows for the same actions.
5. Compare p50 and worst observed times across three runs after one warm-up run.
6. For large upload tests, record process memory before parse, after parse, after publish, and after rerun.

Before/after metrics to compare:

- Login elapsed milliseconds and Google Sheets calls.
- Settings load elapsed milliseconds and action tracker rows scanned.
- Upload parse elapsed milliseconds, max memory, and parsed rows/sec.
- Upload publish elapsed milliseconds, merged CSV bytes, Drive upload time.
- Reminders tab elapsed milliseconds and active rows rendered.
- Stats tab elapsed milliseconds and rows/CSV bytes per view.
- Refresh Stats elapsed milliseconds and remote calls.
- Settings save elapsed milliseconds and Sheets calls per edited field.

## 7. Recommended Patch Order

1. Title: Add performance timing and call-count tests.
   - Goal: create measurement confidence before optimizing.
   - Scope: thin fake tests and optional internal timing wrappers.
   - Files likely touched: `reminders_app_v3.py`, `tests/test_ci_statistics.py`, `tests/test_ci_auth_session.py`, maybe a new `tests/test_ci_performance_call_counts.py`.
   - Risk: low.
   - Validation: `python -m unittest discover -s tests -p "test_ci_*.py"`.
   - Needs new tests first: yes.

2. Title: Batch dataset tracker rows during upload save.
   - Goal: reduce Google Sheets appends for multi-file uploads.
   - Scope: upload save tracker event loop only.
   - Files likely touched: `reminders_app_v3.py`, `tests/test_ci_dataset_update.py`.
   - Risk: low.
   - Validation: `python -m unittest tests.test_ci_dataset_update`.
   - Needs new tests first: yes.

3. Title: Avoid generating Stats CSV bytes until needed or cache them.
   - Goal: reduce Stats rerun CPU/memory.
   - Scope: `render_stats_csv_export()` and export helper tests.
   - Files likely touched: `reminders_app_v3.py`, `tests/test_ci_statistics.py`.
   - Risk: low/medium.
   - Validation: `python -m unittest tests.test_ci_statistics`.
   - Needs new tests first: yes.

4. Title: Add actioned-reminder pagination.
   - Goal: prevent all-row widget rendering in actioned history.
   - Scope: `render_actioned_reminders_tab()` only.
   - Files likely touched: `reminders_app_v3.py`, reminder workflow tests.
   - Risk: low.
   - Validation: `python -m unittest tests.test_ci_reminder_workflows`.
   - Needs new tests first: optional but recommended.

5. Title: Memoize active reminder badge count.
   - Goal: reduce repeated reminder prep/filter/group work on reruns.
   - Scope: badge helper and invalidation key.
   - Files likely touched: `reminders_app_v3.py`, `tests/test_ci_reminders_badge.py`.
   - Risk: medium.
   - Validation: `python -m unittest tests.test_ci_reminders_badge`.
   - Needs new tests first: yes.

6. Title: Extract Stats selected-view builder.
   - Goal: prepare for lazy Stats rendering without changing UI yet.
   - Scope: pure/helper extraction from `render_stats_tab()`.
   - Files likely touched: `reminders_app_v3.py`, `tests/test_ci_statistics.py`.
   - Risk: medium.
   - Validation: `python -m unittest tests.test_ci_statistics`.
   - Needs new tests first: yes.

7. Title: Render only one Stats view at a time.
   - Goal: avoid eager `st.tabs()` work.
   - Scope: Stats subtab UI and selected-view rendering.
   - Files likely touched: `reminders_app_v3.py`, visual CSS tests.
   - Risk: medium.
   - Validation: `python -m unittest tests.test_ci_statistics tests.test_ci_visual_theme_css`.
   - Needs new tests first: yes, from PR 6.

8. Title: Add no-op guards to Search Terms autosaves.
   - Goal: reduce unnecessary settings writes.
   - Scope: search-term edit callbacks.
   - Files likely touched: `reminders_app_v3.py`, new callback tests if helpers extracted.
   - Risk: medium.
   - Validation: `python -m unittest discover -s tests -p "test_ci_*.py"`.
   - Needs new tests first: yes.

9. Title: Add elapsed-time budget to `_gspread_retry()`.
   - Goal: reduce hang risk during Sheets incidents.
   - Scope: `_gspread_retry()` and timeout/error tests.
   - Files likely touched: `reminders_app_v3.py`, `tests/test_ci_error_handling.py`.
   - Risk: medium.
   - Validation: `python -m unittest tests.test_ci_error_handling`.
   - Needs new tests first: yes.

10. Title: Indexed settings row lookup for clinic/account auth.
    - Goal: reduce login/account Sheets scans.
    - Scope: lookup helpers only.
    - Files likely touched: `reminders_app_v3.py`, auth/session tests.
    - Risk: medium.
    - Validation: `python -m unittest tests.test_ci_auth_session tests.test_ci_streamlit_login_render`.
    - Needs new tests first: yes.

11. Title: Split current action state from full action history.
    - Goal: reduce login memory and full action tracker reads.
    - Scope: action tracker loader, hidden reminder filter inputs, Stats history load.
    - Files likely touched: `reminders_app_v3.py`, action/reminder/statistics tests.
    - Risk: high.
    - Validation: full CI tests plus manual reminder send/undo smoke.
    - Needs new tests first: yes.

12. Title: Measure and redesign large dataset storage only if needed.
    - Goal: reduce whole-dataset publish cost for large clinics.
    - Scope: measurement first; storage changes later.
    - Files likely touched: `reminders_app_v3.py`, `settings_pointer_utils.py`, dataset tests.
    - Risk: high.
    - Validation: full local gates and live Google smoke if credentials are available.
    - Needs new tests first: yes.

## 8. Commands

Commands found in the repo that should pass before performance PRs:

```bash
python -m py_compile reminders_app_v3.py settings_pointer_utils.py
python -m pip check
python -m unittest discover -s tests -p "test_ci_*.py"
python -m unittest discover -s tests
bash scripts/pre_merge_check.sh
```

Pilot release check, when validating a release-sized performance change:

```bash
bash scripts/pilot_release_check.sh
```

Notes:

- `scripts/pilot_release_check.sh` includes `python -m pip install --dry-run -r requirements.txt`, compile checks, `pip check`, CI tests, pointer tests, `git diff --check`, and live Google smoke checks when credentials are available.
- `python -m unittest discover -s tests` is broader than the CI-pattern command and should be run for performance changes that touch helper behavior beyond `test_ci_*.py`.
- No repo-owned formatter, linter, type checker, dependency vulnerability audit, static security scan, browser E2E command, or production build command is currently configured as a reliable gate.

Proposed measurement commands, not existing gates:

```bash
python -m unittest tests.test_ci_performance_call_counts
python -m streamlit run reminders_app_v3.py
```

The proposed call-count test module does not exist yet. The Streamlit command is for manual profiling only.
