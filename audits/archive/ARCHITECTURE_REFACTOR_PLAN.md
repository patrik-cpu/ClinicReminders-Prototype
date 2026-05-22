# ARCHITECTURE_REFACTOR_PLAN.md

## Executive summary

The app works, but its architecture is concentrated in one file: `reminders_app_v3.py` is 11,037 lines and owns Streamlit UI, session state, auth, Google Sheets/Drive I/O, upload parsing, settings persistence, reminder generation, action tracking, statistics, dormant admin/debug tooling, and tracker/audit logging.

The safest refactor path is not a framework migration or a rewrite. It is a sequence of small extraction passes that keep `reminders_app_v3.py` as the public compatibility layer while moving pure logic and low-level I/O behind clearer module boundaries. Each pass should preserve behavior, keep existing public functions callable from `reminders_app_v3.py`, add tests before moving behavior, and run the repo-required checks.

Recommended target shape:

- `reminders_app_v3.py`: Streamlit composition layer and backwards-compatible wrappers.
- `clinic_app/state.py`: session-state keys and small state helpers.
- `clinic_app/settings_store.py`: settings sheet schema, row lookups, and settings writes.
- `clinic_app/google_clients.py`: credential loading and Google client construction.
- `clinic_app/dataset_store.py`: Drive dataset pointer/load/publish helpers.
- `clinic_app/uploads.py`: file parsing, PMS detection, validation, and dataset history helpers.
- `clinic_app/reminders.py`: reminder rules, grouping, action-state pure helpers.
- `clinic_app/statistics.py`: statistics frames and summaries.
- `clinic_app/trackers.py`: tracker row builders and append helpers.
- `clinic_app/auth.py`: password hashes, Google identity matching, account operations.
- `clinic_app/ui/`: optional later split for tab/dialog renderers.

Do not introduce those modules all at once. Extract one boundary at a time.

## Current structure

Files:

- `reminders_app_v3.py`: 11,037 lines, main Streamlit app.
- `settings_pointer_utils.py`: 32 lines, single helper for dataset pointer batch updates.
- `tests/test_ci_*.py`: active CI-discovered characterization/regression tests.
- Supporting docs/reports and one CI workflow.

Local import graph:

- `reminders_app_v3.py` imports `settings_pointer_utils`.
- Tests import `reminders_app_v3.py`.
- `settings_pointer_utils.py` imports no local app module.

No circular dependency exists today, but the lack of modules means most boundaries are implicit instead of enforced.

## Oversized files and functions

Oversized file:

- `reminders_app_v3.py`: 11,037 lines.

Largest active functions by line count:

- `render_search_terms_editor`: 299 lines at `reminders_app_v3.py:8817`
- `render_whatsapp_tools`: 190 lines at `reminders_app_v3.py:8143`
- `save_settings`: 182 lines at `reminders_app_v3.py:2994`
- `process_file`: 131 lines at `reminders_app_v3.py:4069`
- `render_actioned_reminders_tab`: 122 lines at `reminders_app_v3.py:7914`
- `render_statistics_tab`: 116 lines at `reminders_app_v3.py:8700`
- `load_shared_dataset_for_clinic`: 114 lines at `reminders_app_v3.py:2049`
- `prepare_session_bundle`: 113 lines at `reminders_app_v3.py:5357`
- `render_table_with_buttons`: 104 lines at `reminders_app_v3.py:8038`
- `load_settings`: 95 lines at `reminders_app_v3.py:2762`

Dormant but still parsed functions inside `if False` blocks also inflate the module and should be handled through the dead-code sequence, not mixed into behavior-preserving refactors.

## Boundary findings

### Business logic inside UI components

Examples:

- `render_search_terms_editor` mutates `st.session_state["rules"]`, validates reminder intervals, saves settings, records audit events, and renders all UI in one function.
- Reminder tab top-level code around `reminders_app_v3.py:9127` computes windows, prepares data, saves settings, renders controls, and routes to statistics/exclusions.
- Exclusions UI around `reminders_app_v3.py:9271` directly mutates exclusion lists and persists settings.
- `render_whatsapp_tools` owns UI state, message template controls, and settings persistence.

Risk:

- UI changes can accidentally alter persistence behavior.
- Pure behavior is harder to test without importing the full Streamlit app.

### Database and external-service logic scattered across UI and helpers

Examples:

- Settings row helpers are near the top of the file.
- Drive helpers are mixed with dataset loading/publishing.
- Account create/update/delete functions directly call settings sheet and Drive helpers.
- Upload UI contains direct calls to `get_existing_dataset_pointer`, `load_existing_shared_df`, and `publish_dataset_for_clinic`.
- Tracker writes are called from upload, account, settings, reminders, and statistics flows.

Risk:

- Object ownership and transaction ordering are difficult to reason about.
- Google API failure handling differs by caller.

### Inconsistent state management

The app uses at least 86 distinct `st.session_state` keys. High-frequency keys include:

- `clinic_id`, `logged_in`, `auth_provider`
- `working_df`, `data_version`, `bundle`
- `rules`, `exclusions`, `client_exclusions`, `patient_exclusions`
- `deleted_reminders`, `wa_reminder_log`
- `dataset_upload_history`, `shared_dataset_loaded`, `shared_dataset_error`
- `_settings_row_cache`, `_remote_settings_cache`, `_tracker_sheet_cache`

Risk:

- State ownership is unclear.
- Cache invalidation can drift from data writes.
- Tests must know raw string keys.

### Unclear module ownership

Current ownership is mostly by comment section, not module boundary:

- Auth owns account rows, password hashing, Google identity, remember-login, and session setup.
- Settings owns JSON settings, settings row writes, and parts of action history migration.
- Dataset owns upload history, Drive CSV files, and saved data status.
- Reminder actions own tracker rows, local actioned state, and settings compatibility logs.
- Statistics owns prepared reminder frames and action tracker records.

Risk:

- Several flows cross all of these boundaries in one call stack.

### Circular dependencies

No current circular dependency exists because there is only one large app module plus a tiny helper. Future extraction could easily create cycles if UI modules import stores and stores import UI/session helpers.

Rule for future modules:

- Pure/domain modules must not import Streamlit.
- Store/client modules must not import UI modules.
- UI modules may import domain and store modules.
- `reminders_app_v3.py` may temporarily re-export moved functions for compatibility.

### Abstractions used only once

Examples:

- `settings_pointer_utils.update_dataset_pointer_cells` is used through a single wrapper but is covered by tests and can stay until settings writes are consolidated.
- Several dialog HTML builders are one-off abstractions: `data_privacy_dialog_html`, `google_onboarding_dialog_html`, `profile_dialog_html`, `delete_account_dialog_html`.
- Dormant admin/factoids/feedback helpers are not active paths and should not be extracted into new modules until the product decision is clear.

Recommendation:

- Do not add more one-off helper modules just to reduce line count.
- Extract only when there is a stable boundary and tests.

### Helpers with misleading or overloaded names

Examples:

- `load_settings` does more than load settings: it migrates legacy actions, loads action tracker records, mutates many session keys, and may save settings.
- `save_settings` merges remote/local settings, strips action logs from JSON, writes settings, updates row fields, caches settings, and tracks users.
- `process_file` reads bytes, chooses parser, detects PMS, validates schema, normalizes columns, and returns multiple values.
- `sanitize_working_df` suggests light cleanup but enforces canonical schema and duplicate handling.
- `record_wa_button_tracker` is now a legacy wrapper around action tracker behavior.

Recommendation:

- Rename only inside new modules first, while keeping old wrapper names in `reminders_app_v3.py`.
- Do not break existing tests or external console workflows that import helpers from `reminders_app_v3.py`.

### Functions doing too many things

Highest priority:

- `save_settings`
- `load_settings`
- `load_shared_dataset_for_clinic`
- `process_file`
- `render_search_terms_editor`
- `render_whatsapp_tools`
- `render_table_with_buttons`
- `render_actioned_reminders_tab`
- `render_statistics_tab`
- `prepare_session_bundle`

### Public APIs unstable or undocumented

The app has no package-level public API, but many tests and likely console workflows import functions directly from `reminders_app_v3.py`. Treat these as de facto public until intentionally changed:

- Auth/account: `authenticate_user`, `get_clinic_row`, `create_clinic_account`, `create_google_clinic_account`, `update_clinic_profile`, `delete_clinic_account_and_data`, `update_clinic_password`
- Settings: `load_settings`, `save_settings`, `save_settings_quietly`, `update_settings_row_fields`
- Dataset: `process_file`, `publish_dataset_for_clinic`, `merge_dataset_update`, `load_existing_shared_df`
- Reminder logic: `hidden_reminder_key`, `merge_deleted_reminders`, `record_action_tracker`, `build_whatsapp_message_for_row`, `bundle_client_reminders_by_window`
- Statistics: `build_statistics_*`, `statistics_summary_for_period`

Refactor rule:

- Move implementations behind wrappers, but keep these names callable from `reminders_app_v3.py` until explicitly approved.

## Refactor passes

### Pass 1: Create a package shell and move no behavior

Goal:

- Establish `clinic_app/` as the future home for extracted code without changing runtime behavior.

Changes:

- Add `clinic_app/__init__.py`.
- Optionally add empty module files with docstrings only if useful.
- Do not import them from the app yet unless tests require it.

Tests:

- No behavior tests needed beyond existing suite.
- Add a tiny smoke test only if package creation affects import behavior.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

### Pass 2: Extract pure tracker row sanitization and row-value helpers

Goal:

- Move pure observability helpers without touching Google writes.

Candidate functions:

- `tracker_cell_value`
- `sanitize_diagnostic_message`
- tracker row construction helper if introduced

Boundary:

- New module should not import Streamlit.
- Keep `record_*_tracker_event` in `reminders_app_v3.py` for now because it reads `st.session_state` and appends to Sheets.

Tests:

- Move or duplicate existing sanitizer tests to import from the new module.
- Keep wrapper tests asserting `reminders_app_v3.sanitize_diagnostic_message` still works.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

### Pass 3: Extract settings sheet write primitives

Goal:

- Put A1 range calculation and settings row payload creation behind a small tested module.

Candidate functions:

- `_settings_col_index`
- `_column_number_to_letter`
- `_row_range_a1`
- `settings_row_values`
- pure payload construction for settings updates

Keep in app as wrappers:

- `_update_dataset_pointer_cells`
- `_update_settings_cells`
- `_update_password_cells`
- `update_settings_row_fields`

Tests:

- Existing pointer and batch tests must keep passing.
- Add tests for missing headers, non-contiguous header updates, and ignored unknown fields.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
python -m unittest tests.test_settings_batch_helpers tests.test_settings_pointer_helpers tests.test_reminders_pointer_wrapper
```

### Pass 4: Extract pure upload parsing and dataset history helpers

Goal:

- Separate file/PMS/dataframe logic from Streamlit UI and Google Drive persistence.

Candidate functions:

- `drop_duplicate_columns`
- `normalize_vetport_to_patrikedit`
- `detect_pms`
- `validate_upload_dataframe`
- `has_readable_canonical_upload_schema`
- `finalize_processed_upload_df`
- pure parts of `process_file`
- dataset history helpers such as `normalize_dataset_upload_history`, `merge_dataset_upload_history`, date-bound helpers

Keep in app as wrappers:

- `process_file`
- cached `process_file` wrapper if Streamlit caching stays there

Tests:

- Upload validation tests for CSV and Excel-like dataframe paths.
- Current dataset update tests must still pass.
- Add tests for empty, invalid, and duplicate-column uploads before moving behavior.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

### Pass 5: Extract reminder domain logic

Goal:

- Move reminder grouping, hidden/actioned reminder keys, and pure action reduction away from UI.

Candidate functions:

- `_hidden_reminder_key_part`
- `hidden_reminder_key`
- `merge_deleted_reminders`
- `reduce_action_tracker_records`
- `action_records_to_wa_log`
- `filter_hidden_reminders`
- reminder date/window helpers
- `bundle_client_reminders_by_window`

Keep in app as wrappers:

- `mark_reminder_sent_action`
- `decline_reminder_action`
- `remove_actioned_reminder_action`
- UI render functions

Tests:

- Existing reminder grouping, badge, and settings-save action tests must keep passing.
- Add characterization tests for sent-to-declined and undo behavior before moving stateful helpers.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

### Pass 6: Extract statistics pure functions

Goal:

- Move statistics calculations to a Streamlit-free module.

Candidate functions:

- `statistics_period_start`
- `parse_statistics_dates`
- `statistics_row_dates`
- `statistics_primary_reminder_date`
- `statistics_actioned_date`
- `filter_prepared_for_statistics_period`
- `build_statistics_generated_rows`
- `statistics_summary_for_period`
- `build_statistics_daily_frame`
- `build_statistics_team_frame`
- `build_statistics_item_frame`

Keep in app as wrappers:

- `cached_statistics_generated_rows`
- `render_statistics_tab`

Tests:

- Existing statistics tests must import through `reminders_app_v3.py` and pass.
- Add direct pure-module tests after extraction for missing columns, malformed dates, and period boundaries.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

### Pass 7: Extract Google credential/client construction

Goal:

- Stop repeating credential loading across Drive, settings sheet, and feedback sheet clients.

Candidate behavior:

- Load service account info from `st.secrets["gcp_service_account"]` or `google-credentials.json`.
- Build Drive credentials for `google-api-python-client`.
- Build gspread client for Sheets.

Boundary:

- A low-level module can accept a `secrets` object and fallback path rather than importing Streamlit directly.
- Callers keep their current error behavior: Drive/settings may raise; feedback may return `None`.

Tests:

- Secrets-first path.
- File fallback path.
- Missing credentials path.
- Scopes are passed through unchanged.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

### Pass 8: Extract settings repository behind wrappers

Goal:

- Centralize settings sheet row lookup, caching, schema ensure, and writes.

Candidate functions:

- `ensure_settings_sheet_columns`
- `get_or_create_settings_worksheet`
- `_get_settings_row_for_clinic`
- `get_cached_settings_row_values`
- `update_cached_settings_row_fields`
- `update_settings_row_fields`
- `get_fresh_settings_row_values`
- `get_remote_settings`

Boundary:

- Avoid importing Streamlit inside the repository module initially; pass cache/session adapter in or keep cache wrappers in app.
- Keep public wrappers in `reminders_app_v3.py`.

Tests:

- Existing auth/settings tests.
- Add row-cache invalidation tests for update and append paths.
- Add tests for legacy worksheet migration behavior before moving `get_or_create_settings_worksheet`.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

### Pass 9: Extract dataset Drive store

Goal:

- Separate Drive object operations and dataset pointer orchestration from upload UI.

Candidate functions:

- `drive_download_bytes`
- `drive_find_file_id_by_name`
- `drive_upsert_csv_bytes`
- `drive_trash_file`
- `drive_rename_file`
- `get_existing_dataset_pointer`
- `load_existing_shared_df`
- `publish_dataset_for_clinic`

Boundary:

- Keep raw Drive helpers separate from dataset-level helpers.
- Preserve current helper names in `reminders_app_v3.py`.

Tests:

- Fake Drive service tests for create/update upload paths.
- Existing dataset update tests.
- Error-path tests for existing dataset load failure and pointer update failure.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

### Pass 10: Extract auth/account service

Goal:

- Group password hashing, Google identity matching, clinic lookup, account create/update/delete, and remember-login token behavior.

Candidate functions:

- `hash_pw`
- `password_hash_for_storage`
- `verify_password`
- `normalize_email`
- `normalize_clinic_id_key`
- `google_identity_matches_row`
- `authenticate_user`
- `get_clinic_row`
- `get_clinic_row_by_google_identity`
- remember-login token helpers
- `create_clinic_account`
- `create_google_clinic_account`
- `update_clinic_profile`
- `delete_clinic_account_and_data`
- `update_clinic_password`

Boundary:

- Do not move the Streamlit login form in this pass.
- Inject settings repository and Drive store functions, or keep wrappers that call app-level dependencies.

Tests:

- Existing auth session and audit characterization tests.
- Add object-level permission failure tests before deeper changes.
- Add token handling tests if changing remember-login internals.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

### Pass 11: Introduce a session-state adapter

Goal:

- Reduce raw string-key usage and make state ownership visible.

Small first step:

- Add constants for core state keys.
- Add tiny helpers for the highest-risk groups:
  - account session
  - dataset state
  - settings caches
  - actioned reminders

Do not:

- Replace all 86 keys in one PR.
- Introduce a complex state framework.

Tests:

- Tests for `clear_account_session_state`, `reset_uploaded_data_state`, and cache invalidation.
- Existing CI suite.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

### Pass 12: Split UI renderers by tab

Goal:

- Move UI rendering only after domain and store functions are better separated.

Candidate modules:

- `clinic_app/ui/account.py`
- `clinic_app/ui/upload.py`
- `clinic_app/ui/reminders.py`
- `clinic_app/ui/search_terms.py`
- `clinic_app/ui/exclusions.py`
- `clinic_app/ui/statistics.py`

Boundary:

- UI modules may import Streamlit.
- UI modules should call domain/store services rather than owning business rules.
- Keep the top-level app composition in `reminders_app_v3.py`.

Tests:

- Before moving each renderer, add tests around the state mutation helper it uses.
- Full Streamlit UI tests are optional later, but not required for the first extraction if wrappers preserve behavior.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

## Passes to avoid for now

- Do not migrate away from Streamlit.
- Do not replace Google Sheets/Drive storage in a refactor PR.
- Do not rename public helper functions without explicit approval.
- Do not delete dormant `if False` sections as part of a boundary refactor; use the `DEAD_CODE_REPORT.md` deletion sequence.
- Do not introduce a broad dependency injection framework.
- Do not convert all session state into classes in one PR.

## Suggested first three PRs

1. Extract tracker sanitization helpers into a Streamlit-free module.
2. Extract settings row payload/range helpers while keeping app wrappers.
3. Extract pure statistics helpers.

These are low-risk because they are mostly pure functions, already have tests, and do not change Google API behavior or Streamlit screen flow.

## Standard validation for every refactor PR

Required by `AGENTS.md`:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Recommended when touching extracted modules:

```bash
python -m py_compile reminders_app_v3.py settings_pointer_utils.py
python -m unittest discover -s tests
```

Recommended when touching settings pointer or settings write helpers:

```bash
python -m unittest tests.test_settings_batch_helpers tests.test_settings_pointer_helpers tests.test_reminders_pointer_wrapper
```
