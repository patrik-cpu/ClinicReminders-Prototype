# DUPLICATION_REPORT.md

## Executive summary

The most important duplication is concentrated in `reminders_app_v3.py`, which mixes UI rendering, Google API access, persistence, auth, upload parsing, reminders, and statistics in one file. Most duplicate code is not exact copy/paste; it is near-duplicate behavior with small differences.

Highest-value clusters:

- Google credential and service setup is repeated for Drive, settings Sheets, and feedback Sheets.
- Settings-row mutation repeats A1 range building and `batch_update` payload construction.
- Clinic-row lookups repeatedly fetch all records and scan by normalized clinic or Google identity.
- Account creation repeats defaults, settings schema setup, tracker writes, and row append logic.
- Dialog rendering repeats the same `st.dialog` / `st.experimental_dialog` / `st.expander` fallback shape.
- Date parsing and text normalization have several subtly different implementations.
- Reminder and actioned-reminder sorting duplicate session-state sort handling.
- Tracker event writers repeat timestamp, clinic/user context, truncation, and append logic.

I did not refactor anything. Before changing any cluster, add characterization tests for every affected call site.

## Method

Commands and checks used:

- `git status --short`
- Python AST function inventory for `reminders_app_v3.py` and related tests
- Targeted `grep` because `rg` is not installed in this Codespace
- Manual reads of duplicate-heavy sections:
  - credentials/API setup
  - settings row writes
  - tracker writes
  - auth/account helpers
  - dialog renderers
  - upload validation/parsing
  - reminder/statistics date helpers
  - sort state helpers

## Cluster 1: Google credential and service setup

Evidence:

- `reminders_app_v3.py:1889` to `1897`: `get_drive_service` reads `st.secrets["gcp_service_account"]`, falls back to `google-credentials.json`, builds Drive service with `google.oauth2.service_account.Credentials`.
- `reminders_app_v3.py:4203` to `4212`: `get_settings_spreadsheet` reads the same secret/file, builds `oauth2client.service_account.ServiceAccountCredentials`, authorizes gspread, opens settings sheet.
- `reminders_app_v3.py:10659` to `10673`: `get_feedback_sheet` repeats secret/file handling and gspread authorization for a different sheet.
- `reminders_app_v3.py:2264` to `2271`: `get_drive_service_uncached` repeats Drive credential setup and is unused per `DEAD_CODE_REPORT.md`.

Why it matters:

- Credential source behavior can drift between Drive, settings, and feedback.
- Error handling differs: settings raises, feedback returns `None`, Drive falls back silently.
- This is security-sensitive because it controls which Google credential and scope are active.

Recommendation:

- Extract helper, but not as the first refactor unless tests are added.
- Introduce a shared credential loader such as `load_gcp_service_account_info()` and small wrappers for Drive/gspread scopes.
- Keep caller-specific error behavior explicit: settings may raise, feedback may return `None`.
- Delete the unused `get_drive_service_uncached` path separately as dead code.

Characterization tests before refactor:

- `get_drive_service` uses `st.secrets` when present.
- `get_drive_service` falls back to `google-credentials.json` when secrets are missing.
- `get_settings_spreadsheet` authorizes gspread and opens `SETTINGS_SHEET_ID`.
- `get_feedback_sheet` returns `None` when no credentials file exists.
- Credential loader preserves scope lists passed by each caller.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

## Cluster 2: Settings row update payloads

Evidence:

- `reminders_app_v3.py:510` to `522`: `_settings_col_index`, `_column_number_to_letter`, `_row_range_a1`.
- `reminders_app_v3.py:629` to `640`: `_update_dataset_pointer_cells` delegates a specific 3-column range update to `settings_pointer_utils.update_dataset_pointer_cells`.
- `reminders_app_v3.py:643` to `650`: `_update_settings_cells` builds a single range payload for `SettingsJSON:UpdatedAt`.
- `reminders_app_v3.py:653` to `667`: `_update_password_cells` builds one-cell payloads for password columns and `UpdatedAt`.
- `reminders_app_v3.py:720` to `737`: `update_settings_row_fields` repeats the per-header batch payload pattern.
- `reminders_app_v3.py:4937` to `4963`: `update_rows_with_clinic_id` builds the same `range` / `values` dict shape across worksheets.

Why it matters:

- A1 range and `batch_update` payload shape are repeated across several write paths.
- Different functions update contiguous fields versus individual cells, so a naive merge could change batch semantics.
- Tests already exist for parts of this behavior, but not every writer.

Recommendation:

- Introduce a small shared helper, for example `cell_update_payload(headers, row_idx, values_by_header)` and `batch_update_cells(sheet, headers, row_idx, values_by_header)`.
- Keep `_update_dataset_pointer_cells` separate until pointer-specific tests are stable.
- Do not merge all settings writes in one PR.

Characterization tests before refactor:

- Existing pointer tests should remain.
- Add tests for `_update_password_cells` with missing optional columns.
- Add tests for `update_settings_row_fields` ignoring headers that do not exist.
- Add tests for `update_rows_with_clinic_id` updating only matching rows across worksheets.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
python -m unittest tests.test_settings_batch_helpers tests.test_settings_pointer_helpers tests.test_reminders_pointer_wrapper
```

## Cluster 3: Clinic-row lookups and auth scans

Evidence:

- `reminders_app_v3.py:4513` to `4522`: `authenticate_user` fetches all records, normalizes `ClinicID`, verifies password.
- `reminders_app_v3.py:4524` to `4532`: `get_clinic_row` fetches all records, normalizes `ClinicID`, returns row.
- `reminders_app_v3.py:4535` to `4543`: `get_clinic_row_by_google_identity` fetches all records and scans using `google_identity_matches_row`.
- `reminders_app_v3.py:670` to `693`: `_get_settings_row_for_clinic` scans raw sheet values for a matching clinic key and caches row metadata.

Why it matters:

- The app has multiple ways to find a clinic row, each with slightly different return shape and caching behavior.
- Repeated full-sheet scans increase latency and make auth/object-level access bugs harder to reason about.

Recommendation:

- Introduce shared lookup helpers, not a broad auth rewrite.
- Example split:
  - `iter_settings_records()`
  - `find_clinic_record_by_id(records, clinic_id)`
  - `find_clinic_record_by_google(records, google_user)`
- Keep raw row-index lookup separate because mutation needs row numbers.

Characterization tests before refactor:

- Password auth returns the row only for a matching normalized clinic and valid password.
- `get_clinic_row` handles non-string sheet values.
- Google lookup requires `is_logged_in` and matches subject before email fallback.
- `_get_settings_row_for_clinic` cache behavior remains unchanged.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

## Cluster 4: Account creation row assembly

Evidence:

- `reminders_app_v3.py:4740` to `4767`: `create_clinic_account`
- `reminders_app_v3.py:4770` to `4815`: `create_google_clinic_account`

Repeated logic:

- Normalize `clinic_id` and `country`.
- Reject duplicate clinic names.
- Fetch settings sheet and headers.
- Ensure settings schema.
- Build default settings JSON.
- Set created/login timestamps.
- Append a settings row with `settings_row_values`.
- Write user tracker event.

Differences:

- Password account writes `PasswordHash` and provider `"password"`.
- Google account requires email, checks existing Google identity, writes Google identity columns, and leaves password hash blank.

Recommendation:

- Introduce shared schema/type or builder helper.
- Good target: `build_account_settings_values(...)` that returns `values_by_header`.
- Leave write side effects (`append_row`, tracker event) in the two public functions unless tests are very strong.

Characterization tests before refactor:

- Local account writes hashed password, blank `PlainPassword`, defaults, country, timestamps, and tracker event.
- Google account rejects missing email, duplicate clinic, and duplicate Google identity.
- Google account writes provider/email/subject/name and blank password fields.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

## Cluster 5: Password form validation

Evidence:

- `reminders_app_v3.py:5599` to `5606`: signup validates missing fields, minimum password length 6, and confirmation mismatch.
- `reminders_app_v3.py:5657` to `5666`: change-password validates missing fields, confirmation mismatch, minimum password length 6, and current password.

Why it matters:

- Password policy is duplicated and already identified as too weak in `SECURITY_AUDIT.md`.
- When policy changes, signup and password-change can drift.

Recommendation:

- Extract helper, but do it as part of the security/password-policy PR.
- Example: `validate_new_password_fields(password, confirmation, *, label="Password") -> str | None`.

Characterization tests before refactor:

- Signup error order remains: missing fields, length, mismatch.
- Change-password error order remains: missing fields, mismatch, length, current password.
- Valid input reaches `create_clinic_account` / `update_clinic_password`.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

## Cluster 6: Dialog rendering compatibility wrapper

Evidence:

- `reminders_app_v3.py:3825` to `3850`: `render_data_privacy_dialog`
- `reminders_app_v3.py:4875` to `4925`: `render_google_onboarding_dialog`
- `reminders_app_v3.py:5073` to `5117`: `render_profile_dialog`
- `reminders_app_v3.py:5166` to `5212`: `render_delete_account_dialog`

Repeated logic:

- Early return based on session flag.
- Nested `_render_dialog_body`.
- Prefer `st.dialog`.
- Fall back to `st.experimental_dialog`.
- Fall back to `st.expander`.
- Then call `_render_dialog_body`.

Why it matters:

- Every dialog repeats framework compatibility logic.
- Future Streamlit API changes or modal styling fixes must be copied to every dialog.

Recommendation:

- Extract helper.
- Example: `render_dialog_compat(title, body_fn, *, open_key=None, on_dismiss=None, width=None, expander_expanded=True)`.
- This is a good early refactor cluster because behavior is easy to characterize with monkeypatched fake `st`.

Characterization tests before refactor:

- Each render function returns without rendering when its session flag is false.
- With `st.dialog`, body function is called through the dialog wrapper.
- With only `st.experimental_dialog`, body function is called through the experimental wrapper.
- With neither dialog API, body function renders inside an expander.
- Dismiss callbacks still close the right session key where currently configured.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

## Cluster 7: Tracker event writers

Evidence:

- `reminders_app_v3.py:4221` to `4238`: `get_or_create_tracker_sheet`
- `reminders_app_v3.py:4241` to `4262`: `append_tracker_row` and `append_tracker_rows`
- `reminders_app_v3.py:4280` to `4312`: `record_dataset_tracker_event`
- `reminders_app_v3.py:4315` to `4337`: `record_settings_audit_event`
- `reminders_app_v3.py:4340` to `4360`: `record_error_tracker_event`
- `reminders_app_v3.py:4363` to `4385`: `record_performance_tracker_event`
- `reminders_app_v3.py:4666` to `4710`: `upsert_user_tracker`
- `reminders_app_v3.py:4713` to `4737`: `record_settings_account_event`

Repeated logic:

- Compute `now` and `gst_now_iso(now)`.
- Read `clinic_id` and `user_name` from session.
- Apply `tracker_cell_value`.
- Append to a sheet with fixed headers.
- Swallow append failures by returning false.

Recommendation:

- Introduce shared schema/type or helper for tracker records.
- Example: `tracker_context(now)`, `tracker_row(headers, values_by_header)`, or small per-sheet dataclasses.
- Do not merge all tracker functions into one variadic function; that would make audit logs less readable.

Characterization tests before refactor:

- Each tracker writer produces exactly the current row order.
- Long/error values are truncated by `tracker_cell_value`.
- Missing session values produce blanks.
- Append failures return `False`.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

## Cluster 8: Text and header normalization

Evidence:

- `reminders_app_v3.py:480` nested `_norm_col` inside `drop_duplicate_columns`.
- `reminders_app_v3.py:937` to `944`: `_norm_header_key`.
- `reminders_app_v3.py:1956` to `1976`: `normalize_key_series`.
- `reminders_app_v3.py:3918` to `3925`: `normalize_columns`.
- `reminders_app_v3.py:4101` nested `clean_header` inside `process_file`.
- `reminders_app_v3.py:4458`: `normalize_email`.
- `reminders_app_v3.py:4462` to `4470`: `normalize_clinic_id_key`.
- `reminders_app_v3.py:6710`: `_exclusion_key`.
- `reminders_app_v3.py:8282` to `8294`: `normalize_display_case`.
- `reminders_app_v3.py:8299` nested `normalized_text_list` inside `statistics_exclusion_fp`.

Why it matters:

- Similar Unicode, whitespace, lowercasing, and null handling rules are repeated with small differences.
- It is easy for upload detection, duplicate matching, exclusions, statistics fingerprints, and auth keys to drift.

Recommendation:

- Leave as-is until better characterization exists.
- Then introduce narrowly named helpers:
  - `normalize_header_key`
  - `normalize_lookup_key`
  - `normalize_optional_text`
- Do not force email, clinic IDs, display case, and dataset duplicate keys through one generic normalizer.

Characterization tests before refactor:

- Header normalization handles NBSP, BOM, repeated whitespace, case.
- Dataset duplicate keys preserve expected behavior for nulls, Arrow-backed strings, and whitespace.
- Clinic ID normalization handles `None`, NaN-like values, and case.
- Exclusion fingerprints remain stable.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

## Cluster 9: Date parsing and formatting

Evidence:

- `reminders_app_v3.py:2427` to `2431`: `parse_history_date`
- `reminders_app_v3.py:3952` to `3989`: `parse_dates`
- `reminders_app_v3.py:6235` to `6243`: `format_due_date`
- `reminders_app_v3.py:6268` to `6286`: `format_due_dates_for_message`
- `reminders_app_v3.py:6771` to `6787`: `parse_reminder_date_parts`
- `reminders_app_v3.py:8338` to `8354`: `parse_statistics_dates`
- `reminders_app_v3.py:8327` to `8334`: `statistics_period_start`
- `reminders_app_v3.py:7777` to `7785`: `actioned_reminder_period_start`

Why it matters:

- The app parses upload dates, saved upload-history dates, grouped reminder dates, actioned reminder periods, and statistics periods differently.
- Some duplication is legitimate because upload parsing handles Excel serial dates and mixed date formats, while reminder/statistics helpers parse `|`-delimited display strings.

Recommendation:

- Leave upload parsing `parse_dates` as-is.
- Extract only the split-delimited reminder/statistics parser after tests.
- Consider a shared period-start helper only if the UI labels are unified.

Characterization tests before refactor:

- `parse_dates` handles Excel serial dates, `dayfirst`, ISO, and existing datetime series.
- `parse_reminder_date_parts` and `parse_statistics_dates` preserve current handling of `|`, blanks, `datetime`, and `date`.
- Period helpers preserve inclusive date ranges.
- Message formatting preserves "soon", two-date grammar, and multi-date grammar.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

## Cluster 10: Upload schema validation

Evidence:

- `reminders_app_v3.py:4035` to `4046`: `validate_upload_dataframe` checks required columns, readable charge date, and emptiness.
- `reminders_app_v3.py:4049` to `4054`: `has_readable_canonical_upload_schema` repeats required-column and readable-date checks as boolean logic.
- `reminders_app_v3.py:4016` to `4022`: `find_column_ci` performs case-insensitive column matching.
- `reminders_app_v3.py:4025` to `4032`: `apply_vetport_alias_columns` applies alias mapping using `find_column_ci`.

Why it matters:

- Validation and boolean capability checks can drift.
- Current behavior intentionally has different outputs: one raises user-facing errors; one returns true/false for compatibility/mixed upload decisions.

Recommendation:

- Introduce shared schema/type.
- Example: `inspect_upload_schema(df) -> UploadSchemaResult` with `missing_columns`, `has_readable_date`, and `is_empty`.
- Keep `validate_upload_dataframe` as the raising wrapper and `has_readable_canonical_upload_schema` as the boolean wrapper.

Characterization tests before refactor:

- Missing columns produce current `UploadValidationError` message.
- No readable date produces current message.
- Empty data produces current message.
- Boolean helper returns false for the same invalid states and true for valid canonical frames.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

## Cluster 11: Sort-state helpers

Evidence:

- `reminders_app_v3.py:7645` to `7659`: `set_reminder_table_sort` and `get_reminder_table_sort`.
- `reminders_app_v3.py:7822` to `7836`: `set_actioned_reminder_sort` and `get_actioned_reminder_sort`.
- `reminders_app_v3.py:7661` to `7683`: `sort_reminder_table`.
- `reminders_app_v3.py:7838` to `7859`: `actioned_reminder_sort_value` and `sort_actioned_reminders`.

Why it matters:

- Sort toggling and default state logic are duplicated.
- Differences are small but meaningful: actioned reminders default to descending `Actioned Date`; reminder table defaults to ascending `Reminder Date`.

Recommendation:

- Extract helper for session-state sort toggling only.
- Leave actual sort-value logic separate because table types differ.

Characterization tests before refactor:

- Clicking same column toggles ascending.
- Clicking a new column resets to each table's default direction.
- Invalid session sort state falls back to the current default.
- Date/text sorting preserves current missing-value behavior.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

## Cluster 12: Session-state cleanup and account dialog state

Evidence:

- `reminders_app_v3.py:369` to `388`: `reset_uploaded_data_state`.
- `reminders_app_v3.py:391` to `458`: `ACCOUNT_SCOPED_SESSION_KEYS`.
- `reminders_app_v3.py:460` to `468`: `clear_account_session_state`.
- `reminders_app_v3.py:3798` to `3824`: `close_account_dialogs`, `account_dialog_is_open`, `upload_widget_has_files`, `open_account_dialog`.
- Dialog close functions at `reminders_app_v3.py:3787`, `5069`, and `5162`.

Why it matters:

- Session state is managed with long string lists and repeated explicit flag manipulation.
- Dialog state is mostly centralized but individual close functions still duplicate single-key assignments.

Recommendation:

- Leave as-is for now.
- If refactoring, introduce shared dialog-state helpers after dialog rendering is extracted.
- Do not convert the large session key list while auth/session tests are still being built out.

Characterization tests before refactor:

- Logout clears all clinic-scoped keys but keeps app-level keys expected by login UI.
- Upload reset clears dataset/prepared/bundle state and increments uploader reset when requested.
- Opening one account dialog closes the others.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

## Cluster 13: Repeated constants and string literals

Evidence:

- Constants exist for settings columns at `reminders_app_v3.py:203` to `219`.
- Some code still uses literal names:
  - `reminders_app_v3.py:643`: `"SettingsJSON"`
  - `reminders_app_v3.py:644`: `"UpdatedAt"`
  - `reminders_app_v3.py:654` to `656`: `"PlainPassword"`, `"PasswordHash"`, `"UpdatedAt"`
  - `reminders_app_v3.py:4939` and `4950`: `"ClinicID"`
  - `reminders_app_v3.py:4980`: `"ClinicID"` and `"UpdatedAt"`
  - `reminders_app_v3.py:5229` to `5231`: `"PlainPassword"`, `"PasswordHash"`, `"UpdatedAt"`

Why it matters:

- Typos in sheet column names become runtime bugs.
- Constants already exist, so mixed literal/constant usage is unnecessary.

Recommendation:

- Introduce shared schema/type or consistently use existing constants.
- This is low risk but can create noisy diffs; do it in a dedicated mechanical cleanup after tests.

Characterization tests before refactor:

- Existing settings write tests should assert exact column/range behavior.
- Add one test for profile update values and one for password update values.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

## Cluster 14: Error handling around external operations

Evidence:

- `reminders_app_v3.py:1899` to `1916`: Drive download catches `HttpError`, displays details, re-raises.
- `reminders_app_v3.py:2237` to `2262`: Drive folder access diagnostic has similar `HttpError` display.
- `reminders_app_v3.py:4241` to `4262`: tracker append helpers swallow all exceptions and return `False`.
- `reminders_app_v3.py:7145` to `7199`: upload parsing catches validation and general exceptions separately, records tracker events.
- `reminders_app_v3.py:7262` to `7300`: existing dataset load/save errors record tracker events and display UI errors.
- `reminders_app_v3.py:4875`, `5073`, `5166`: account dialog flows catch `ValueError` separately from generic exceptions.

Why it matters:

- Some external failures are silent, some expose raw details, and some produce generic messages.
- Security audit already identified raw exception leakage.

Recommendation:

- Extract helper only after security behavior is decided.
- Candidate helpers:
  - `user_error(message_key, exception=None)`
  - `record_external_error(event, stage, source, exception)`
- Do not collapse `ValueError` user-validation paths into generic exception handling.

Characterization tests before refactor:

- Tracker append failure remains non-fatal.
- Upload validation errors show current user-facing messages and tracker event status.
- Generic upload/save failures show generic UI messages and record tracker events.
- Auth/profile/delete flows preserve current `ValueError` messages.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

## Cluster 15: Duplicate tests for pointer helpers

Evidence:

- `tests/test_settings_pointer_helpers.py:22`: tests `_update_dataset_pointer_cells` batching.
- `tests/test_settings_batch_helpers.py:14`: tests `_update_dataset_pointer_cells` batching again.
- `tests/test_reminders_pointer_wrapper.py:8`: tests wrapper argument forwarding.
- These are outside required CI because CI uses `test_ci_*.py`.

Why it matters:

- Some overlap exists, but each file still has at least one unique assertion.
- Deleting one now could lose coverage that is currently only manually runnable.

Recommendation:

- Merge tests rather than delete immediately.
- Preferred path: move unique pointer-helper coverage into a `tests/test_ci_settings_batch_helpers.py` or existing `test_ci_settings_save_state.py`, then delete the duplicate non-CI files.

Characterization tests before refactor:

- Keep all existing assertions when moving/consolidating.
- Run both CI discovery and full unittest discovery.

Validation commands:

```bash
python -m unittest discover -s tests -p "test_ci_*.py"
python -m unittest discover -s tests -p "test*.py"
```

## Cluster 16: Dormant duplicate analytics/admin paths

Evidence:

- `reminders_app_v3.py:9411`: hidden Factoids block behind `if False`.
- `reminders_app_v3.py:10721`: hidden admin clinic management block behind `if False`.
- `reminders_app_v3.py:10772`: hidden keyword-debugging and quarterly export block behind `if False`.
- `DEAD_CODE_REPORT.md` already documents these as unreachable.

Why it matters:

- The dormant analytics block duplicates active statistics concepts and contains local helper functions that are never defined at runtime.
- The dormant admin blocks duplicate account-management concerns in a different, hidden permission model.

Recommendation:

- Delete duplicate path, but only as a dedicated dead-code PR after product confirmation.
- Do not extract helpers from unreachable code.

Characterization tests before refactor:

- Not needed for unreachable code deletion beyond compile and active CI tests.
- If any dormant behavior is revived instead, add tests first.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

## Recommended refactor sequence

### PR 1: Dialog compatibility helper

Why first:

- It is visible duplication with a narrow behavior surface.
- It does not touch persistence, auth, or data transforms.
- Characterization tests can monkeypatch `st.dialog`, `st.experimental_dialog`, and `st.expander`.

Affected call sites:

- `render_data_privacy_dialog`
- `render_google_onboarding_dialog`
- `render_profile_dialog`
- `render_delete_account_dialog`

Required tests before refactor:

- Add tests covering all three rendering modes for the shared helper.
- Add one call-site test per dialog to verify the correct title, session flag, and close callback behavior.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

### PR 2: Sort-state helper

Affected call sites:

- `set_reminder_table_sort`
- `get_reminder_table_sort`
- `set_actioned_reminder_sort`
- `get_actioned_reminder_sort`

Required tests before refactor:

- Toggle same column.
- Switch to new column.
- Invalid session state fallback.
- Different default direction per table.

### PR 3: Upload schema inspection result

Affected call sites:

- `validate_upload_dataframe`
- `has_readable_canonical_upload_schema`

Required tests before refactor:

- Missing columns, unreadable date, empty frame, valid frame.

### PR 4: Account creation value builder

Affected call sites:

- `create_clinic_account`
- `create_google_clinic_account`

Required tests before refactor:

- Existing account creation characterization tests plus new assertions for exact settings row values.

### PR 5: Settings update payload helper

Affected call sites:

- `_update_settings_cells`
- `_update_password_cells`
- `update_settings_row_fields`
- `update_rows_with_clinic_id`

Required tests before refactor:

- Exact `batch_update` payloads for every writer.

### PR 6: Credential loader

Affected call sites:

- `get_drive_service`
- `get_settings_spreadsheet`
- `get_feedback_sheet`

Required tests before refactor:

- Secrets path, file fallback path, missing-file feedback behavior, scope preservation.

## Clusters to leave as-is for now

- Upload `parse_dates`: complex and higher risk because it handles Excel serial dates and mixed formats.
- Text normalization: extract only after more behavior tests; different call sites intentionally normalize differently.
- Error handling: should wait for security decision on raw exception exposure.
- Tracker writers: useful to simplify, but the row order is audit-critical.
- Auth lookups: performance and maintainability issue, but auth behavior is sensitive.

## Validation baseline

Any duplication refactor should run at least:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

For clusters touching non-CI helper tests, also run:

```bash
python -m unittest discover -s tests -p "test*.py"
```
