# PERFORMANCE_REPORT.md

## Executive summary

The app's highest-confidence performance risks are from external Google I/O and unbounded UI rendering, not from small Python expressions. The main hot paths are:

- full Google Sheets reads for login/settings/action-tracker paths
- all-row rendering for reminders/actioned reminders
- repeated DataFrame-to-record conversion and regrouping during render
- per-row CSS injection and many Streamlit widgets
- upload parsing/publishing that can hold large files/DataFrames in caches
- settings autosave and tracker logging that can create multiple synchronous sheet writes

The original audit was report-only. The 2026-05-18 follow-up below includes one
small performance cleanup.

## Follow-up pass: 2026-05-18

This follow-up pass included both performance review and a user-action smoke
inventory after the live-pilot UI changes.

### What was checked

- Enumerated Streamlit user actions: login, signup, Google signup/login,
  profile save/close, data privacy, account deletion/cancel, logout, upload
  help, file upload, saved-upload removal, clear clinic data, reminder refresh,
  WhatsApp, sent, decline, undo, template update/reset, search-term add/delete,
  search-term reset, exclusion add/delete, statistics rendering, and dormant
  admin/export buttons.
- Re-ran focused Upload Data and Streamlit startup/login checks.
- Re-ran full CI-style tests and release gates.
- Rechecked active upload parsing/cache code against the earlier cache-layering
  finding.

### Change made

Removed the nested `@st.cache_resource` wrapper around upload summarisation in
the Upload Data tab. The wrapper was defined inside the tab render path and
only delegated to `summarize_uploads`, which is already a module-level
`@st.cache_data` function. This reduces cache layering and keeps upload cache
invalidation easier to reason about without changing upload behavior.

Evidence:

- Previous wrapper: `reminders_app_v3.py` Upload Data tab, `load_persistent_dataset`.
- Current calls go directly to `summarize_uploads(file_blobs, UPLOAD_SUMMARY_SCHEMA_VERSION)`.

Validation:

```bash
python -m py_compile reminders_app_v3.py settings_pointer_utils.py scripts/*.py
python -m unittest tests.test_ci_dataset_update tests.test_ci_streamlit_login_render tests.test_ci_streamlit_startup
python -m unittest discover -s tests -p "test_ci_*.py"
bash scripts/pre_merge_check.sh
bash scripts/pilot_release_check.sh
python -m pip check
```

Results:

- Compile passed.
- Focused upload/startup/login checks passed: 33 tests.
- CI-pattern tests passed: 157 tests.
- `scripts/pre_merge_check.sh` passed.
- `scripts/pilot_release_check.sh` passed local checks and skipped live Google
  smoke because no service-account credentials were present locally.
- Dependency consistency passed: `No broken requirements found.`

### User-action status

No local automated failures were found for the covered actions. The strongest
coverage is around state-changing helpers and workflows: auth/session handling,
upload validation and saved-upload state, reminder sent/decline/undo, settings
save state, profile/delete behavior, privacy/copy rendering, statistics
summaries, and Streamlit startup/login rendering.

Remaining gaps:

- This is still not true browser-click E2E coverage of the deployed app.
- Live Google Sheets/Drive writes were not exercised locally because credentials
  were not available in the workspace.
- Visual correctness still depends partly on manual checks in Streamlit Cloud,
  especially dialogs, tabs, and file uploader rendering.

### Remaining performance risks

No new P0 performance issues were found. The main remaining risks are the same
structural risks already listed below:

- Full Google Sheets scans on login/settings/action-history paths.
- Synchronous Google Sheets/Drive writes on user actions.
- Potentially heavy reminder and action-history rendering for large clinics.
- Google Sheets/Drive as the backing store, with no transactional guarantees.

Recommended next performance PR:

Split action-history loading into two paths: a small recent/current-reminder
state load for normal reminder rendering, and a broader history load only when
statistics needs it. This should reduce login/refresh cost as the action tracker
grows.

## Method

Inspected active code paths in `reminders_app_v3.py` for:

- Google Sheets and Drive calls
- cached and uncached DataFrame transformations
- Streamlit render loops
- upload parsing and publishing
- tracker/audit logging
- settings save/load behavior
- rerun triggers
- startup/login work

Useful existing timing hooks:

- `record_performance_tracker_event("shared_dataset_load", ...)`
- `record_performance_tracker_event("upload_parse", ...)`
- `record_performance_tracker_event("dataset_publish", ...)`

Suggested measurement convention for future fixes:

- Record elapsed milliseconds with `time.perf_counter()`.
- Record input sizes: rows, files, bytes, number of reminders rendered, number of Google API calls.
- Use fake sheets/services in tests to assert call counts, and use manual Streamlit profiling for wall-clock render time.

## Findings

### P1: Full Google Sheets scans on login and account lookup paths

Hot path:

- `authenticate_user` calls `sheet.get_all_records()` and scans every row at `reminders_app_v3.py:4513` to `4522`.
- `get_clinic_row` does the same at `reminders_app_v3.py:4524` to `4532`.
- `get_clinic_row_by_google_identity` does the same at `reminders_app_v3.py:4535` to `4543`.
- Account creation/profile/delete paths call these helpers repeatedly.

Estimated user impact:

- Login, Google login, signup, profile, and delete-account latency grows with the number of clinic rows.
- Because these calls are synchronous during render/form submission, the app appears frozen while the sheet responds.

How to measure:

- Add temporary timing around each helper with row count from `len(records)`.
- In tests, use a fake sheet with 1, 100, 1,000, and 10,000 records and assert one sheet read per operation.
- In a staging sheet, measure password login and Google login p50/p95 latency before and after.

Smallest safe fix:

- Introduce one shared clinic-row lookup helper that can reuse records within a single flow.
- For flows that already know the row index, prefer `_get_settings_row_for_clinic` plus `row_values`.
- Avoid calling `get_clinic_row` multiple times in one account flow.

Before validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

After validation:

- Same commands.
- Add call-count tests proving signup/profile/delete do not perform duplicate full-sheet reads.
- Compare measured login/signup/profile latency on a staging sheet with representative row counts.

### P1: Action tracker load reads the entire tracker sheet during settings load

Hot path:

- `load_settings` calls `load_action_tracker_records_for_clinic` at `reminders_app_v3.py:2814`.
- `load_action_tracker_records_for_clinic` calls `get_all_values()` for the full Action tracker at `reminders_app_v3.py:3437` to `3458`.
- This runs after login and whenever settings are reloaded.

Estimated user impact:

- Clinics with long reminder histories pay the cost of every clinic's action tracker rows, not just their own.
- Login and refresh can slow down over time as tracker history grows.

How to measure:

- Add timing and row-count logging around `sheet.get_all_values()` in `load_action_tracker_records_for_clinic`.
- Create a fake tracker sheet with increasing row counts and measure helper time.
- On staging, compare load time with current production tracker row count.

Smallest safe fix:

- Add a bounded recent-history path first, for example load only records needed for current reminder windows plus recent action history.
- If full historical data is required for statistics, split "load current reminder action state" from "load all statistics history."
- Longer term, keep an indexed per-clinic tracker sheet or separate per-clinic tabs/files.

Before validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

After validation:

- Add tests proving current active reminder hiding still works when only relevant tracker rows are loaded.
- Compare login/load p95 with a large fake or staging tracker.

### P1: Reminder table renders every row with many widgets and per-row CSS

Hot path:

- `render_table_with_buttons` loops over all reminder rows at `reminders_app_v3.py:7986` to `8068`.
- Each row creates `st.columns`, markdown cells, three buttons, and calls `render_reminder_action_button_styles`.
- `render_reminder_action_button_styles` emits a `<style>` block per row at `reminders_app_v3.py:7686` to `7759`.
- `render_actioned_reminders_tab` similarly renders all actioned rows for the selected period at `reminders_app_v3.py:7862` to `7983`.

Estimated user impact:

- Large reminder windows or many actioned reminders create a heavy Streamlit DOM and many widget keys.
- The page can feel slow to render, scroll, and respond.
- The client bundle/DOM grows with row count because CSS is repeated per row.

How to measure:

- Record `len(df)` before `render_table_with_buttons` and elapsed render time around the call.
- In browser dev tools, compare DOM node count and transferred HTML/websocket payload for 25, 100, 250, and 500 reminder rows.
- Measure time from rerun start to table visible.

Smallest safe fix:

- Add pagination or a display limit to active and actioned reminder tables.
- Move static button CSS out of per-row rendering; keep only minimal per-row selected-state styling if needed.
- Start with a safe default such as first 50 rows plus "show more".

Before validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

After validation:

- Add tests for pagination boundaries and stable button keys.
- Manually profile render time and DOM size for large reminder sets before/after.

### P1: Badge calculation repeats reminder filtering/grouping work already needed by the main reminders view

Hot path:

- `get_active_reminder_badge_count` prepares, filters, groups, converts grouped rows to records, then filters hidden reminders at `reminders_app_v3.py:6825` to `6857`.
- The main reminders view later filters and groups again at `reminders_app_v3.py:9138` to `9157`.

Estimated user impact:

- Every reminders render can do two similar reminder-window computations.
- Impact grows with uploaded dataset size and number of rules.

How to measure:

- Add timing around `get_active_reminder_badge_count`.
- Add timing around the main `due2` filtering and `bundle_client_reminders_by_window`.
- Compare both timings for small, medium, and large datasets.

Smallest safe fix:

- Cache the badge count by `(data_version, rules_fp, exclusion_fp, lookback_days, group_days, today)`.
- Or compute the badge from already grouped current-window data when the selected window matches the badge window.

Before validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

After validation:

- Add tests that badge count invalidates when rules, exclusions, hidden reminders, or `data_version` change.
- Compare total reminders tab render time before/after on a representative dataset.

### P1: Settings autosave can trigger synchronous Google Sheets writes on small UI edits

Hot path:

- Reminder controls use `on_change=save_settings_quietly` at `reminders_app_v3.py:9127`, `9141`, `9155`, and `9168`.
- Search term field changes call `save_settings_quietly` in nested handlers at `reminders_app_v3.py:8768` to `8829`.
- Exclusion add/delete flows also call `save_settings_quietly` and tracker events around `reminders_app_v3.py:9229` to `9405`.
- `save_settings` can read remote settings, merge JSON-like data, batch-update settings, and sometimes call `update_settings_row_fields` at `reminders_app_v3.py:2994` to `3162`.

Estimated user impact:

- Editing search terms or changing numeric controls can pause the UI while Google Sheets reads/writes finish.
- Multiple rapid edits can stack reruns and sheet writes.

How to measure:

- Count gspread calls during a single search-term edit and a single reminder-control change.
- Add timing around `save_settings_quietly` and `save_settings`.
- Use a fake sheet in tests to assert call count per UI callback.

Smallest safe fix:

- For search terms, stage edits locally and save on an explicit "Apply" or existing refresh action.
- For numeric reminder controls, debounce or only save when values actually changed from remote/base settings.
- Keep current behavior behind characterization tests before changing autosave semantics.

Before validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

After validation:

- Add tests that changed settings persist and unchanged controls do not call Sheets.
- Compare UI callback latency and gspread call count before/after.

### P2: Upload cache can retain large file bytes and DataFrames in multiple layers

Hot path:

- Uploaded files are converted to byte blobs with `_to_blob` and fingerprinted at `reminders_app_v3.py:7129` to `7130`.
- `load_persistent_dataset` is defined with `@st.cache_resource` inside the Upload tab at `reminders_app_v3.py:7088` to `7090`.
- It calls `summarize_uploads`, which is also `@st.cache_data` at `reminders_app_v3.py:5291`.
- The cache key includes `file_blobs`, which contain full file bytes.

Estimated user impact:

- Large uploads can occupy memory in uploaded-file objects, cache keys, cached parse results, and working DataFrames.
- Repeated uploads by the same process can increase memory pressure until cache clears.

How to measure:

- Track total uploaded bytes and DataFrame memory usage with `df.memory_usage(deep=True).sum()`.
- Compare process memory before upload, after parse, after save/rerun, and after `st.cache_data.clear()`.
- Upload representative large CSV/XLSX files in staging.

Smallest safe fix:

- Remove the nested `@st.cache_resource` wrapper and rely on the module-level `summarize_uploads` cache.
- Consider using a hash plus file metadata as the cache key rather than storing full bytes in more than one cache layer.
- Add explicit upload size/row limits before parsing.

Before validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

After validation:

- Add tests proving the same uploaded bytes parse once per fingerprint.
- Manually compare memory after repeated uploads before/after.

### P2: Upload publishing serializes the entire merged dataset and uploads synchronously

Hot path:

- `publish_dataset_for_clinic` merges existing and new data, serializes all rows with `merged_df.to_csv(index=False).encode("utf-8")`, uploads to Drive, then updates settings at `reminders_app_v3.py:2699` to `2750`.
- Existing dataset load can download and parse the full prior dataset before every append/replace at `reminders_app_v3.py:2389` to `2408`.

Estimated user impact:

- Saving a large upload blocks the Streamlit run until download, parse, merge, CSV serialization, Drive upload, and settings update finish.
- Larger clinics will feel this most during upload/save.

How to measure:

- Existing `dataset_publish` performance tracking records duration and row count.
- Add file byte size and existing/new row counts to the performance tracker message or structured fields.
- Benchmark append and replace flows with representative datasets.

Smallest safe fix:

- Keep synchronous behavior for now, but add clearer measurement fields first.
- Then avoid downloading existing data when the current session already has a verified `existing_df`.
- Longer term, store chunked/partitioned data or append delta files, but that is not a small fix.

Before validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

After validation:

- Add tests proving existing session `existing_df` avoids a Drive download.
- Compare `dataset_publish` p50/p95 before/after for append and replace.

### P2: Multiple tracker events during multi-file upload are written one row at a time

Hot path:

- After saving an upload, `save_uploaded_dataset` loops through `saved_history_rows` and calls `record_dataset_tracker_event` once per summary row at `reminders_app_v3.py:7318` to `7335`.
- Each event calls `append_tracker_row`, a separate Google Sheets append at `reminders_app_v3.py:4241` to `4247`.
- `append_tracker_rows` already exists at `reminders_app_v3.py:4250` to `4262`.

Estimated user impact:

- Multi-file uploads make one tracker API call per file, increasing save time and quota pressure.

How to measure:

- Count `append_row` calls for an upload with 1, 5, 10, and 20 files.
- Measure `dataset_publish` plus tracker-write time separately.

Smallest safe fix:

- Build dataset tracker rows in memory and call `append_tracker_rows` once for the upload-saved batch.
- Keep single-row calls for single events elsewhere.

Before validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

After validation:

- Add a test asserting a multi-file upload writes one append batch with the same row contents.
- Compare Google Sheets call count before/after.

### P2: Tracker sheet/header setup does synchronous worksheet enumeration on first logged-in run

Hot path:

- `ensure_tracking_sheets()` runs after login on every rerun at `reminders_app_v3.py:5701`.
- The cached `ensure_tracking_sheets_once` enumerates all worksheets and checks header rows for every tracker sheet at `reminders_app_v3.py:4391` to `4403`.

Estimated user impact:

- First logged-in render pays several Google Sheets calls before the app can settle.
- This is cached per process, so it is mostly startup/cold-container cost.

How to measure:

- Time `ensure_tracking_sheets_once`.
- Count worksheet enumeration and `row_values(1)` calls.
- Compare cold start versus warm rerun.

Smallest safe fix:

- Defer tracker sheet creation/header validation until first tracker write.
- Or keep a session/process flag but skip header checks unless a tracker write fails.

Before validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

After validation:

- Add tests proving a tracker write still creates/validates the needed sheet.
- Measure cold login render time before/after.

### P2: Statistics rebuilds row dictionaries several times per render

Hot path:

- `filter_generated_for_statistics_period` converts generated DataFrame rows to dicts at `reminders_app_v3.py:8465` to `8479`.
- `statistics_summary_for_period`, `build_statistics_daily_frame`, and `build_statistics_item_frame` each call filters/conversions again at `reminders_app_v3.py:8489`, `8524`, and `8588`.
- Statistics rendering calls these helpers in one run at `reminders_app_v3.py:8691` to `8755`.

Estimated user impact:

- Statistics tab does repeated Python-level row iteration over the same generated rows.
- This grows with generated reminder count.

How to measure:

- Time each statistics helper for 100, 1,000, and 10,000 generated reminders.
- Count DataFrame-to-record conversions per statistics render.

Smallest safe fix:

- Compute `generated_period` and filtered action records once in `render_statistics_tab`, then pass them into summary/daily/item builders.
- Keep public helper behavior unchanged or add new lower-level helpers.

Before validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

After validation:

- Add tests that summary/daily/item outputs are identical before/after for mixed periods.
- Compare statistics render timing on large generated frames.

### P2: Rule matching loops over every rule and does vector work per rule

Hot path:

- `map_intervals_vec` loops through every search term/rule and runs `item_norm.str.contains(term, regex=False)` across the full DataFrame at `reminders_app_v3.py:6505` to `6580`.

Estimated user impact:

- Reminder preparation cost grows roughly with `number_of_rules * number_of_rows`.
- This is cached by `prepared_key`, but any rule change or data version change invalidates it.

How to measure:

- Record `len(df)`, `len(rules)`, and elapsed time around `ensure_reminder_columns`.
- Benchmark 10, 100, and 500 rules over realistic row counts.

Smallest safe fix:

- Measure first.
- If confirmed slow, pre-normalize rules once and skip impossible/empty rules before vector scans.
- Consider grouping literal terms into a smaller number of compiled checks only after preserving current "minimum interval among matching rules" behavior.

Before validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

After validation:

- Add characterization tests for overlapping rules and minimum-day behavior.
- Compare preparation time with representative rule counts.

### P2: External Google API calls do not have explicit timeouts

Hot path:

- Drive service is built at `reminders_app_v3.py:1889` to `1897`.
- Drive download/upload/update calls are synchronous at `reminders_app_v3.py:1899`, `2201`, `776`, and `787`.
- gspread calls are wrapped by `_gspread_retry`, but the underlying request timeout is not set in this code at `reminders_app_v3.py:2345` to `2364`.

Estimated user impact:

- A slow network call can hold the Streamlit run and make the UI appear hung.
- Retries help transient API errors but do not bound a single stuck request.

How to measure:

- Simulate slow Google API calls in tests with fake functions that sleep.
- In staging, record elapsed time for Drive and Sheets operations separately.

Smallest safe fix:

- Configure explicit request timeouts for Google clients where supported.
- Add operation-level timing and user-friendly timeout messages before broad client changes.

Before validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

After validation:

- Add tests that timeout exceptions are reported and do not corrupt session state.
- Measure worst-case stalled-call behavior manually with a fake slow client.

### P3: Repeated JSON serialization for settings comparison can add overhead on large settings blobs

Hot path:

- `_settings_copy` does `json.loads(json.dumps(value))` at `reminders_app_v3.py:2862` to `2866`.
- `_settings_equal` does sorted `json.dumps` comparisons at `reminders_app_v3.py:2869` to `2874`.
- Settings save calls these helpers repeatedly while merging rules, exclusions, patient exclusions, and scalar settings.

Estimated user impact:

- Usually low for normal settings sizes.
- Can become noticeable if rules/exclusions grow very large and autosave fires frequently.

How to measure:

- Time `save_settings` merge phase separately from network I/O.
- Generate settings with 10, 100, and 1,000 rules/exclusions and measure serialization time.

Smallest safe fix:

- Do not optimize until measured.
- If measured slow, use `copy.deepcopy` for copying and direct equality for JSON-compatible structures where order is already stable.

Before validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

After validation:

- Add tests proving merge conflict behavior is unchanged.
- Compare merge-only timing before/after.

## Not flagged as findings

- Drive filename search uses `pageSize=1`, so missing Drive pagination is not a meaningful issue for that query.
- The dormant `if False` analytics/admin blocks are large, but they are unreachable and are already covered by `DEAD_CODE_REPORT.md`; they do not affect active render performance.
- `prepare_session_bundle` is heavy, but `PRECOMPUTE_ANALYTICS_BUNDLE = False`, so it is not active in normal renders.
- Existing use of `@st.cache_data` on upload parsing and reminder preparation is directionally appropriate; the issue is cache layering and invalidation, not absence of caching.

## Recommended fix order

1. Add measurement/call-count instrumentation around Google Sheets reads and reminder/statistics rendering.
2. Paginate or limit reminder/actioned reminder table rendering.
3. Reduce full-sheet action tracker reads during login/settings load.
4. Batch dataset tracker writes for multi-file uploads.
5. Remove duplicate upload cache layer and measure memory.
6. Cache or reuse badge calculation.
7. Defer tracker sheet header setup from cold login.

## Baseline validation commands

For any performance patch:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

For changes to non-CI helper tests:

```bash
python -m unittest discover -s tests -p "test*.py"
```
