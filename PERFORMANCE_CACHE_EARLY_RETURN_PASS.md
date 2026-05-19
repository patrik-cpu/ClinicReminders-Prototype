# Performance Cache And Early Return Pass

Date: 2026-05-19

## Executive Summary

Cache use is generally directionally appropriate: expensive Google client objects are cached as resources, upload parsing and reminder/statistics builders are cached as data, and several session-scoped caches avoid repeated Google Sheets row reads or repeated render work.

The highest-risk cache concerns are not correctness bugs seen in the current code, but stale or oversized cache inputs on hot paths. `prepare_session_bundle()`, `ensure_reminder_columns()`, `cached_statistics_generated_rows()`, and `build_reminder_outcomes()` all accept full DataFrames or long record lists, so Streamlit must hash large payloads before a cache hit can be used. Several cached functions return mutable DataFrames that callers sometimes store in `session_state`; Streamlit normally returns copies for `st.cache_data`, but manual session caches must continue copying on return.

The safest next improvements are small early returns and narrower invalidation: skip settings saves when unchanged, skip upload summary parsing when an already-saved upload has history rows, skip outcome sales preparation when there are no sent reminders, avoid broad `st.cache_data.clear()` where possible, and remove or isolate dormant nested caches in the disabled Factoids section.

## 1. All `@st.cache_data`, `@st.cache_resource`, And `@lru_cache` Usage

### Streamlit resource caches

- `get_drive_service()` at `reminders_app_v3.py:3100`
  - Cached object: Google Drive API client.
  - Invalidation inputs: none. Depends on `st.secrets["gcp_service_account"]`, local `google-credentials.json`, and `DRIVE_SCOPE`.
  - Notes: appropriate resource cache; secret changes require process/cache reset.

- `get_settings_spreadsheet()` at `reminders_app_v3.py:6547`
  - Cached object: gspread spreadsheet handle.
  - Invalidation inputs: none. Depends on settings credentials and `SETTINGS_SHEET_ID`.
  - Notes: appropriate resource cache; secret/sheet-id changes require process/cache reset.

- `get_settings_sheet()` at `reminders_app_v3.py:6560`
  - Cached object: settings worksheet handle.
  - Invalidation inputs: none; nested on `get_settings_spreadsheet()`.
  - Notes: appropriate, but sheet recreation/rename would need cache clear or restart.

- `ensure_tracking_sheets_once()` at `reminders_app_v3.py:7003`
  - Cached object: dict of tracker worksheet handles.
  - Invalidation inputs: none. Depends on `TRACKER_SHEET_DEFINITIONS`, worksheet existence, and headers.
  - Notes: useful one-time setup cache, but header definition changes need cache clear/restart.

- `get_feedback_sheet()` at `reminders_app_v3.py:17696`
  - Cached object: Feedback worksheet handle or `None`.
  - Invalidation inputs: none. Depends on credentials and `FEEDBACK_SHEET_ID`.
  - Notes: caches failures as `None`; credential availability changes need cache clear/restart.

### Streamlit data caches

- `process_file(file_bytes, filename)` at `reminders_app_v3.py:6410`
  - Cached value: parsed and normalized upload DataFrame plus PMS metadata.
  - Key inputs: full file bytes and filename.
  - Notes: high-value cache, `max_entries=8`; key can be large because bytes are hashed.

- `prepare_session_bundle(df, cache_key)` at `reminders_app_v3.py:8525`
  - Cached value: sanitized full DataFrame, masks, transaction frames, and monthly patient series.
  - Key inputs: full DataFrame plus explicit cache key.
  - Notes: key hashing can be large; `cache_key` exists but does not prevent Streamlit from hashing `df`.

- `format_due_dates_for_message(due_date_value)` at `reminders_app_v3.py:9671`
  - Cached value: formatted due-date string.
  - Key inputs: scalar due date text.
  - Notes: tiny cache; safe, but likely low impact.

- `ensure_reminder_columns(df, rules)` at `reminders_app_v3.py:10044`
  - Cached value: reminder-enriched DataFrame.
  - Key inputs: full DataFrame and full rules dict.
  - Notes: expensive but useful; key hashing may dominate on large datasets.

- `cached_statistics_generated_rows(_prepared, _rules, group_days, period, today_iso, data_version, rules_fp, exclusion_fp, schema_version)` at `reminders_app_v3.py:12972`
  - Cached value: generated reminder rows for Stats.
  - Key inputs: full prepared DataFrame and full rules dict, plus explicit fingerprints.
  - Notes: underscore args are excluded from Streamlit hashing, so correctness depends on `data_version`, `rules_fp`, `exclusion_fp`, date, group days, period, and schema version.

- `build_reminder_outcomes(action_records, sales_df, ..., rules, action_records_reduced, expanded_sent_records)` at `reminders_app_v3.py:13963`
  - Cached value: outcome DataFrame.
  - Key inputs: action record list, sales DataFrame, windows, today, attribution/rules flags, rules, and optional expanded sent records.
  - Notes: high-value cache with `max_entries=8`, but key hashing can be large because it includes full action histories, sales DataFrames, and possibly duplicated expanded records.

- Disabled Factoids nested caches at `reminders_app_v3.py:16461`, `16549`, and `16603`
  - Cached values: full monthly core metrics, revenue breakdown, and patient breakdown percentages.
  - Key inputs: `data_key`, full `df_full`, masks, transactions, and patient series.
  - Notes: currently inside `if False and st.session_state["factoids_unlocked"]`; not executed, but if re-enabled the nested function definitions plus full-DataFrame hashing should be revisited.

- `fetch_feedback(limit=500)` at `reminders_app_v3.py:17736`
  - Cached value: last feedback rows.
  - Key inputs: limit. TTL 600 seconds.
  - Notes: depends on `get_feedback_sheet()`.

- `fetch_feedback_cached(limit=500)` at `reminders_app_v3.py:17747`
  - Cached value: wrapper around `fetch_feedback()`. TTL 30 seconds.
  - Notes: redundant nested cache over another cached function.

### Non-Streamlit cache

- `parse_statistics_date_part(value)` at `reminders_app_v3.py:12829`
  - Cached value: parsed date part. `maxsize=8192`.
  - Key inputs: scalar text.
  - Notes: appropriate for repeated grouped reminder date strings.

## 2. Cache Keys That May Be Too Large

### Finding P1: Upload parse key hashes full file bytes

- Function/location: `process_file()` at `reminders_app_v3.py:6410`; callers in upload flow around `reminders_app_v3.py:11000-11120`.
- Hot path: selecting/reselecting uploaded CSV/XLS/XLSX files.
- Expected memory/API cost: Streamlit hashes full uploaded bytes and also stores cached DataFrames; bounded by `max_entries=8`, but large uploads can still create noticeable CPU and memory pressure.
- Safest fix: keep behavior but route through a digest-keyed helper, for example cached parse by `(sha256, filename, schema_version)` with bytes stored only for the active upload path, or keep current cache and add parse timing/size metrics first.
- Behavior risk exists: medium if bytes are no longer part of the cache key; digest calculation must remain collision-resistant and include filename/parser schema.
- Tests needed: same file contents with same filename reuse parse; changed contents with same filename reparse; same contents with different filename preserve PMS detection behavior.
- Validation command: `python -m unittest tests.test_ci_dataset_update`.

### Finding P1: Reminder and bundle caches hash full DataFrames

- Function/location: `prepare_session_bundle()` at `reminders_app_v3.py:8525`; `ensure_reminder_columns()` at `reminders_app_v3.py:10044`.
- Hot path: app reruns after upload/settings changes and Reminders/Stats preparation.
- Expected memory/API cost: hashing and copying large DataFrames before cache hit; cached DataFrames duplicate working data in memory.
- Safest fix: keep current output, but use explicit immutable keys and underscore DataFrame args only where there is a reliable `data_version`/schema fingerprint. Start with measurement fields before changing cache signatures.
- Behavior risk exists: medium. Missing invalidation would cause stale reminders or stats.
- Tests needed: changing uploaded data, search rules, grouping, exclusions, and schema version invalidates outputs.
- Validation command: `python -m unittest tests.test_ci_reminders_badge tests.test_ci_statistics`.

### Finding P1: Outcome cache key can include duplicated action inputs

- Function/location: `build_reminder_outcomes()` at `reminders_app_v3.py:13963`; Stats caller at `reminders_app_v3.py:15357-15370`.
- Hot path: Stats render.
- Expected memory/API cost: Streamlit hashes the reduced action list, full sales DataFrame, rules dict, and `expanded_sent_records`; expanded records can duplicate action data already present in `action_records`.
- Safest fix: use one compact action fingerprint and sales/data version in a wrapper, or remove `expanded_sent_records` from the cache key by making it an underscore arg only after adding explicit invalidators.
- Behavior risk exists: medium. Outcome matching is user-visible.
- Tests needed: sent/declined/undo changes invalidate outcomes; rule/search-term changes invalidate matched item outcomes; window settings invalidate pending/success results.
- Validation command: `python -m unittest tests.test_ci_statistics tests.test_ci_reminders_badge`.

### Finding P2: Stats export fingerprint hashes full export frames

- Function/location: `stats_export_csv_cache_key()` / `stats_export_frame_fingerprint()` at `reminders_app_v3.py:15061`.
- Hot path: Stats render with export buttons.
- Expected memory/API cost: hashing entire DataFrames to avoid CSV reserialization. For very large result tables, this still scans every exported cell.
- Safest fix: keep current cache but include table source version keys where available, or cache only within a render context after source frames are built.
- Behavior risk exists: low if used only as an optimization.
- Tests needed: export bytes unchanged; cache invalidates when frame values, columns, display preparer, or view name change.
- Validation command: `python -m unittest tests.test_ci_statistics`.

## 3. Cache Keys That May Be Missing Invalidation Inputs

### Finding P1: `prepare_session_bundle()` explicit cache key may not cover all bundle logic

- Function/location: `prepare_session_bundle(df, cache_key)` at `reminders_app_v3.py:8525`.
- Hot path: uploaded/saved dataset prep.
- Expected memory/API cost: cache is useful; stale risk depends on `cache_key` composition at call sites.
- Safest fix: ensure all callers include `SESSION_BUNDLE_SCHEMA_VERSION` and `data_version` in the key; add a test that changing schema version changes cache result.
- Behavior risk exists: low if only key tests are added; medium if cache signature changes.
- Tests needed: cache miss when `cache_key` changes; empty input shape preserved.
- Validation command: `python -m unittest tests.test_ci_dataset_update`.

### Finding P1: `cached_statistics_generated_rows()` trusts explicit fingerprints

- Function/location: `cached_statistics_generated_rows()` at `reminders_app_v3.py:12972`.
- Hot path: Stats render.
- Expected memory/API cost: avoids hashing `_prepared` and `_rules`, which is good.
- Safest fix: verify the current call includes all behavior inputs: `data_version`, `_rules_fp(rules)`, `statistics_exclusion_fp()`, group days, period, today, and `STATISTICS_GENERATED_SCHEMA_VERSION`. Current Stats caller includes these.
- Behavior risk exists: low currently; future callers could omit an input.
- Tests needed: exclusion/rules/group-days changes invalidate generated rows.
- Validation command: `python -m unittest tests.test_ci_statistics`.

### Finding P2: Resource caches do not include credential or sheet IDs

- Function/location: `get_drive_service()`, `get_settings_spreadsheet()`, `get_feedback_sheet()`.
- Hot path: login/upload/publish/tracker/feedback.
- Expected memory/API cost: resource caching prevents repeated client creation.
- Safest fix: leave as-is for normal app operation; document that changing secrets/sheet IDs requires cache reset/restart. If runtime switching is supported later, add explicit parameters.
- Behavior risk exists: low now; runtime secret rotation is not represented.
- Tests needed: none for current behavior.
- Validation command: manual smoke: `python -m unittest tests.test_ci_streamlit_startup`.

### Finding P2: Manual `_hidden_reminders_index_cache` key uses list identity and length

- Function/location: `get_hidden_reminders_index()` at `reminders_app_v3.py:5155`.
- Hot path: reminder hiding/filtering.
- Expected memory/API cost: cheap lookup, but stale if the existing `deleted_reminders` list is mutated in place without length change.
- Safest fix: either invalidate this cache on every action mutation or use the existing action fingerprint as the key.
- Behavior risk exists: medium if stale; low if only invalidation is added at mutation points.
- Tests needed: changing an existing action in place changes hidden index result.
- Validation command: `python -m unittest tests.test_ci_reminders_badge`.

## 4. Nested Or Redundant Caches

### Finding P2: Feedback has two TTL caches for the same data

- Function/location: `fetch_feedback()` at `reminders_app_v3.py:17736` and `fetch_feedback_cached()` at `reminders_app_v3.py:17747`.
- Hot path: hidden/admin feedback use.
- Expected memory/API cost: small, but confusing TTL layering: the 30-second wrapper cannot force freshness while the inner 600-second cache is warm.
- Safest fix: keep one cached function and make the wrapper uncached, or remove the wrapper if no live call sites need it.
- Behavior risk exists: low; feedback UI is currently hidden.
- Tests needed: feedback fetch call still returns last `limit` rows.
- Validation command: `python -m py_compile reminders_app_v3.py`.

### Finding P2: Disabled Factoids section defines nested cached functions

- Function/location: nested definitions at `reminders_app_v3.py:16461`, `16549`, `16603` inside `if False`.
- Hot path: none currently.
- Expected memory/API cost: zero while disabled; high if re-enabled because large frames are cached and function definitions live inside render scope.
- Safest fix: leave disabled code untouched for now; if re-enabled, move helpers to module scope and add explicit invalidation keys.
- Behavior risk exists: none while disabled.
- Tests needed: none unless Factoids are restored.
- Validation command: `python -m py_compile reminders_app_v3.py`.

### Finding P2: Tracker worksheet cache exists both as resource return and session cache

- Function/location: `ensure_tracking_sheets_once()` at `reminders_app_v3.py:7003`; `_tracker_sheet_cache` in `get_or_create_tracker_sheet()` at `reminders_app_v3.py:6566`.
- Hot path: tracker logging and setup.
- Expected memory/API cost: small; duplicate references to worksheet objects.
- Safest fix: no immediate change, but ensure account/session clear removes `_tracker_sheet_cache` as it currently does.
- Behavior risk exists: low.
- Tests needed: tracker setup still appends rows after account switch.
- Validation command: `python -m unittest tests.test_ci_error_handling tests.test_ci_auth_session`.

## 5. Cached Functions Returning Mutable Objects Later Modified

### Finding P1: Cached DataFrames should be treated as immutable by callers

- Function/location: `process_file()`, `prepare_session_bundle()`, `ensure_reminder_columns()`, `cached_statistics_generated_rows()`, `build_reminder_outcomes()`.
- Hot path: upload parsing, reminder building, Stats.
- Expected memory/API cost: Streamlit data cache generally returns a copy, which protects cache contents but increases memory use for large frames.
- Safest fix: maintain caller copies before mutation. For helpers that are only used internally, consider returning immutable fingerprints plus session-owned DataFrames later.
- Behavior risk exists: medium if cache returns are mutated and Streamlit copy semantics change or a manual cache replaces `st.cache_data`.
- Tests needed: cached output repeated calls are stable after caller mutation.
- Validation command: `python -m unittest tests.test_ci_dataset_update tests.test_ci_statistics`.

### Finding P2: Manual session caches require explicit copies

- Function/location: `_active_reminder_window_cache` at `reminders_app_v3.py:10260-10287`, `_settings_row_cache`, `_remote_settings_cache`, `_action_tracker_records_cache`, `_stats_export_csv_cache`.
- Hot path: reminders, settings, Stats exports.
- Expected memory/API cost: low-to-medium depending on cached DataFrame/bytes sizes.
- Safest fix: keep copy-on-return conventions. `_active_reminder_window_cache` already stores and returns DataFrame copies; settings/action caches return copied lists/dicts.
- Behavior risk exists: low if conventions are preserved.
- Tests needed: modifying returned cached rows does not mutate session cache.
- Validation command: `python -m unittest tests.test_ci_auth_session tests.test_ci_reminders_badge tests.test_ci_statistics`.

## 6. Heavy Functions That Should Early-Return

### Empty DataFrame

- Already handled:
  - `prepare_session_bundle()` returns empty bundle at `reminders_app_v3.py:8536`.
  - `ensure_reminder_columns()` returns an empty shaped frame at `reminders_app_v3.py:10046`.
  - `build_active_reminder_window()` returns empty grouped frame at `reminders_app_v3.py:10258`.
  - `build_statistics_generated_rows()` returns empty generated frame at `reminders_app_v3.py:12956`.
  - `filter_outcomes_for_period()`, `summarize_outcomes()`, `build_outcome_group_frame()`, and `render_stats_csv_export()` all have empty guards.
- Cleanup candidate:
  - `build_reminder_outcomes()` currently calls `prepare_sales_for_outcomes(sales_df)` before confirming there are sent records. Reorder to reduce work when there are no sent reminders.

### No uploaded files

- Already handled:
  - Upload tab only parses inside `if files:` at `reminders_app_v3.py:11017`.
  - File-list changes call `load_shared_dataset_for_clinic()` when current files become empty.
- Cleanup candidate:
  - When an upload has already been saved and `dataset_upload_history` is present, the skip path still attempts `summarize_uploads()` to repair missing summary rows. It can skip parsing when history rows already exist.

### No rules

- Current behavior:
  - `ensure_reminder_columns()` still maps intervals with an empty rules dict and returns rows with no intervals.
  - `build_prepared_reminder_rows()` then drops rows during reminder date expansion.
- Cleanup candidate:
  - If there are no applied rules, return an empty prepared reminder frame before calling `ensure_reminder_columns()`. This is safe only if no downstream UI expects the intermediate non-expanded columns from prepared rows.

### No reminders

- Already handled:
  - `get_active_reminder_badge_count()` returns 0 for missing/empty `working_df`.
  - `build_active_reminder_window()` returns empty for empty prepared rows.
  - `render_stats_csv_export()` returns before building download buttons for empty frames.
- Cleanup candidate:
  - `render_table_with_buttons()` and actioned reminder rendering can avoid static style/button setup when the filtered table is empty.

### No logged-in user

- Already handled:
  - `finish_authenticated_session()` gates session setup.
  - `load_shared_dataset_for_clinic()` returns when no clinic id.
  - `ensure_tracking_sheets()` returns when no clinic id.
  - upload save/clear paths stop on missing clinic id.
- Cleanup candidate:
  - `record_*_tracker_event()` calls append helpers even when no clinic id for some app-level diagnostics. This may be intentional; do not change without deciding whether anonymous diagnostics are wanted.

### Inactive tab

- Already handled:
  - Main section gating means upload parsing only runs on Upload Data, Stats render only runs on Stats, and action tracker loading only runs on Reminders/Stats.
- Cleanup candidate:
  - Stats uses `st.tabs()`, so all subtab bodies still render during a Stats run. Prior statistics passes already reduced some repeated work; selected-subview rendering would be a larger UI behavior change and should be split.

### Unchanged settings

- Already handled:
  - Numeric reminder/outcome saves use `numeric_setting_is_clean_and_unchanged()`.
- Cleanup candidate:
  - `save_settings_quietly()` is still called from some flows after local state changes that may already be persisted; add narrow no-op checks only where the old/new serialized settings can be compared cheaply.

## 7. Cache Clear Calls And Whether They Are Too Broad

- `reset_uploaded_data_state(clear_cache=True)` at `reminders_app_v3.py:556`
  - Clears all Streamlit data caches via `st.cache_data.clear()`.
  - Risk: broad. It flushes upload parsing, session bundle, reminder columns, Stats generated rows, outcomes, feedback caches, and dormant Factoids caches.
  - Safer option: call targeted clears (`process_file.clear()`, `prepare_session_bundle.clear()`, `ensure_reminder_columns.clear()`, `cached_statistics_generated_rows.clear()`, `build_reminder_outcomes.clear()`) based on what actually changed.

- `clear_upload_parse_caches()` at `reminders_app_v3.py:8518`
  - Attempts to clear `process_file` and `summarize_uploads`.
  - Current note: `summarize_uploads()` is no longer cached, so that second clear is harmless but redundant.
  - Safer option: clear only `process_file` or leave generic guarded helper with a comment.

- `refresh_outcome_results_state()` at `reminders_app_v3.py:15230`
  - Clears `build_reminder_outcomes` and `cached_statistics_generated_rows`.
  - Risk: targeted and appropriate for Refresh Stats.

- `invalidate_action_tracker_records_cache()` at `reminders_app_v3.py:5337`
  - Clears only `_action_tracker_records_cache`.
  - Risk: targeted. Called after tracker writes and refresh requests.

- Account/session clearing at `clear_account_session_state()` and delete-account flows
  - Clears session caches including settings, profile, remote settings, tracker sheet, badge, export, and hidden reminders.
  - Risk: appropriate on account switch/delete.

## 8. Top 10 Small Safe Cleanups

### 1. Skip upload summary parsing when saved history already exists

- Exact function: Upload Data branch around `upload_save_can_be_skipped()` at `reminders_app_v3.py:11031`.
- Why safe: current summary parsing is only used to repair missing history rows. If normalized history rows already exist, reparsing cannot change UI state.
- Expected benefit: avoids repeated upload parse/hash/DataFrame work for already-saved uploads.
- Test/validation command: `python -m unittest tests.test_ci_dataset_update`.

### 2. Reorder no-sent-reminder early return before sales preparation

- Exact function: `build_reminder_outcomes()` at `reminders_app_v3.py:13963`.
- Why safe: if there are no sent records, output is always `empty_outcome_frame()` and sales matching is impossible.
- Expected benefit: avoids preparing the full sales DataFrame on Stats renders with no sent reminders.
- Test/validation command: `python -m unittest tests.test_ci_statistics`.

### 3. Remove redundant `summarize_uploads` clear target

- Exact function: `clear_upload_parse_caches()` at `reminders_app_v3.py:8518`.
- Why safe: `summarize_uploads()` is not currently decorated with `@st.cache_data`, so clearing it is a no-op.
- Expected benefit: small clarity improvement and fewer misleading cache assumptions.
- Test/validation command: `python -m unittest tests.test_ci_dataset_update`.

### 4. Replace broad upload reset cache clear with targeted clears

- Exact function: `reset_uploaded_data_state(clear_cache=True)` at `reminders_app_v3.py:556`.
- Why safe: only if each caller is audited; many existing callers already pass `clear_cache=False`.
- Expected benefit: avoids flushing unrelated Stats/feedback caches when only uploaded data state changes.
- Test/validation command: `python -m unittest discover -s tests -p "test_ci_*.py"`.

### 5. Add no-rules early return in prepared reminder building

- Exact function: `build_prepared_reminder_rows()` at `reminders_app_v3.py:10194`.
- Why safe: with no rules, no reminder intervals can be produced; output should be empty prepared reminders.
- Expected benefit: avoids cached reminder-column construction and duplicate/expand passes for clinics with no search terms.
- Test/validation command: `python -m unittest tests.test_ci_reminders_badge tests.test_ci_statistics`.

### 6. Use action fingerprint for hidden reminder index cache

- Exact function: `get_hidden_reminders_index()` at `reminders_app_v3.py:5155`.
- Why safe: fingerprint reflects action content, not only list identity and length.
- Expected benefit: prevents stale cache if a list entry is updated in place with same length.
- Test/validation command: `python -m unittest tests.test_ci_reminders_badge`.

### 7. Keep only one feedback data cache

- Exact function: `fetch_feedback()` / `fetch_feedback_cached()` at `reminders_app_v3.py:17736-17748`.
- Why safe: admin feedback UI is hidden and wrapper exists for compatibility.
- Expected benefit: removes confusing TTL layering and duplicate cache entries.
- Test/validation command: `python -m py_compile reminders_app_v3.py`.

### 8. Add early return in tracker append batch after sanitization

- Exact function: `record_dataset_tracker_events()` at `reminders_app_v3.py:6965` and `append_tracker_rows()` at `reminders_app_v3.py:6599`.
- Why safe: empty event lists already result in no useful API call.
- Expected benefit: avoids worksheet lookup when all event rows are filtered out or malformed.
- Test/validation command: `python -m unittest tests.test_ci_error_handling tests.test_ci_dataset_update`.

### 9. Short-circuit active reminder badge when no applied rules

- Exact function: `get_active_reminder_badge_count()` at `reminders_app_v3.py:10493`.
- Why safe: no reminder rules means no active reminders.
- Expected benefit: avoids prepared DataFrame build and window grouping for accounts without search terms.
- Test/validation command: `python -m unittest tests.test_ci_reminders_badge`.

### 10. Add cache measurement fields before changing large cache keys

- Exact function: `process_file()`, `prepare_session_bundle()`, `ensure_reminder_columns()`, and `build_reminder_outcomes()`.
- Why safe: measurement-only tracker fields do not change app output.
- Expected benefit: identifies whether hashing, parsing, or matching dominates before larger cache-key changes.
- Test/validation command: `python -m unittest discover -s tests -p "test_ci_*.py"`.

## Recommended Patch Order

1. Skip already-saved upload summary parsing when upload history exists.
2. Move `build_reminder_outcomes()` no-sent early return before `prepare_sales_for_outcomes()`.
3. Remove the redundant `summarize_uploads` clear target or document it as compatibility no-op.
4. Add no-rules early returns for active reminder badge/prepared reminders with characterization tests.
5. Replace `_hidden_reminders_index_cache` key with a content fingerprint.
6. Add measurement fields for large cache hashing/serialization before changing cache signatures.
7. Split broad `st.cache_data.clear()` usage into targeted clears after each caller is covered.

## Validation Commands

```bash
python -m py_compile reminders_app_v3.py settings_pointer_utils.py
python -m unittest tests.test_ci_dataset_update
python -m unittest tests.test_ci_reminders_badge
python -m unittest tests.test_ci_statistics
python -m unittest tests.test_ci_error_handling
python -m unittest tests.test_ci_auth_session
python -m unittest discover -s tests -p "test_ci_*.py"
bash scripts/pre_merge_check.sh
```
