# LOGIC_EDGE_CASE_REPORT.md

## Executive summary

No P0 logic issue was found in the inspected active paths. I found four P1 issues that are small enough to fix safely with regression tests:

- P1: `create_clinic_account` can create an invalid blank or short-password account when called directly.
- P1: `update_clinic_profile` swallows Drive rename failure and still renames the clinic in Sheets.
- P1: `delete_clinic_account_and_data` trashes the Drive dataset before sheet row deletion succeeds.
- P1: `build_statistics_team_frame` can crash if action records are missing optional tracker columns.

Lower-priority issues are listed but should not be fixed in this pass.

## Scope and method

Reviewed active code paths in `reminders_app_v3.py` around:

- account creation, login helpers, profile update, password update, account deletion
- dataset loading, upload parsing, dataset publishing, clear-data flow
- reminder action marking, undo, action tracker reduction
- statistics filtering, grouping, and sorting
- settings row writes, tracker writes, network/database failure handling
- existing `test_ci_*.py` and characterization tests

Commands used included targeted `sed`, `grep`, `git status --short`, and manual inspection.

## P1 issues to fix now

### P1-1: Direct local account creation accepts blank clinic names and weak/empty passwords

Evidence:

- `reminders_app_v3.py:4740` to `4767` in `create_clinic_account`
- UI validation exists at `reminders_app_v3.py:5599` to `5606`, but the helper itself does not validate `clinic_id` or password length before writing.

Why it matters:

- Tests and future call sites can call `create_clinic_account` directly.
- A blank clinic row or empty-password account would corrupt auth data and make duplicate/lookup behavior ambiguous.

Failing test idea:

- Call `create_clinic_account("   ", "United States", "secret-password")` and assert it raises before reading/writing Sheets.
- Call `create_clinic_account("Clinic", "United States", "123")` and assert it raises before writing Sheets.

Recommended fix:

- Add direct helper validation matching the UI: nonblank clinic name and password length at least 6.

Safe in isolation:

- Yes. It rejects invalid states that the UI already rejects.

### P1-2: Profile rename can leave stale dataset metadata when Drive rename fails

Evidence:

- `reminders_app_v3.py:4966` to `4998` in `update_clinic_profile`
- `reminders_app_v3.py:4986` to `4993` catches and ignores `drive_rename_file` exceptions, then continues updating the clinic name in Sheets.

Why it matters:

- If a clinic has a saved dataset file and Drive rename fails, the clinic ID changes but the saved dataset filename/pointer metadata may remain stale.
- This is a partial failure that can confuse dataset recovery, support, and later cleanup.

Failing test idea:

- Patch `drive_rename_file` to raise.
- Assert `update_clinic_profile` raises and does not call `update_settings_row_fields` or `update_rows_with_clinic_id`.

Recommended fix:

- Treat Drive rename failure as blocking when the clinic ID is changing and a dataset file exists.

Safe in isolation:

- Yes. Only failure behavior changes.

### P1-3: Account deletion trashes the dataset before sheet deletion succeeds

Evidence:

- `reminders_app_v3.py:5021` to `5042` in `delete_clinic_account_and_data`
- `reminders_app_v3.py:5030` to `5032` calls `drive_trash_file(file_id)` before iterating worksheets and deleting rows.

Why it matters:

- If a later worksheet read/delete fails, the account row can remain while the saved dataset file has already been trashed.
- This is a user-visible partial failure and potential data loss.

Failing test idea:

- Patch a worksheet `delete_rows` call to raise.
- Assert `drive_trash_file` is not called when sheet deletion fails.

Recommended fix:

- Delete matching sheet rows first, then trash the Drive file after sheet deletion succeeds.

Safe in isolation:

- Yes. It changes destructive operation ordering to avoid trashing data before row deletion succeeds.

### P1-4: Statistics team frame crashes on malformed action records missing optional columns

Evidence:

- `reminders_app_v3.py:8569` to `8585` in `build_statistics_team_frame`
- `df_actions.get("Actioned By", "")` returns a string if the column is missing, then `.fillna(...)` is called on that string.
- `df_actions.get("Action", "")` has the same issue.

Why it matters:

- Action tracker records can be legacy, partially migrated, or malformed after external sheet edits.
- Statistics should show "Unknown" / zero counts rather than crashing the tab.

Failing test idea:

- Call `build_statistics_team_frame([{"ActionedAt": "2026-05-16T09:00:00"}], "Today", today=date(2026, 5, 16))`.
- Assert it returns one `Unknown` row with `Actioned == 1`, `Sent == 0`, and `Declined == 0`.

Recommended fix:

- Convert missing optional columns to empty `pd.Series` aligned to the DataFrame index before using string operations.

Safe in isolation:

- Yes. It only affects malformed or incomplete action records.

## Lower-priority issues to leave for later

### P2: Empty upload reports "needs a readable date" instead of "does not contain any usable rows"

Evidence:

- `reminders_app_v3.py:4035` to `4046` checks readable date before `df.empty`.
- Current characterization test expects the readable-date message for an empty canonical frame.

Failing test idea:

- Empty canonical DataFrame should raise `UploadValidationError` matching "does not contain any usable rows."

Recommendation:

- Leave as-is until copy/UX behavior is intentionally changed.

### P2: Large uploads have no explicit file size, row count, or column count guard

Evidence:

- `reminders_app_v3.py:7093` to `7097` accepts CSV/XLS/XLSX.
- `reminders_app_v3.py:4083` and `4091` parse with pandas without app-level size checks.

Failing test idea:

- Oversized uploaded blob is rejected before `pd.read_csv` or `pd.read_excel` is called.

Recommendation:

- Add upload limits in a dedicated upload-hardening PR.

### P2: Direct dataset publish can save a replacement as new if existing dataset download fails

Evidence:

- `reminders_app_v3.py:2721` to `2726` in `publish_dataset_for_clinic` catches existing dataset load errors, warns, and continues with `existing_df = None`.
- The UI pre-check at `reminders_app_v3.py:7245` to `7266` stops on existing load failure, but direct helper behavior differs.

Failing test idea:

- Patch `load_existing_shared_df` to raise and assert direct `publish_dataset_for_clinic` does not overwrite/publish unless explicitly allowed.

Recommendation:

- Leave for a separate dataset publishing behavior PR because direct helper behavior may be intentional for recovery.

### P2: Clear clinic data clears pointer before optional Drive trash and does not restore on settings write failure

Evidence:

- `reminders_app_v3.py:7355` to `7389` clears the settings pointer and local state.
- Drive trash is commented out.

Failing test idea:

- Patch `clear_clinic_dataset_pointer` to raise and assert local/session state is not cleared.

Recommendation:

- Add transaction-style clear-data tests before changing behavior.

### P2: Tracker writes fail silently

Evidence:

- `reminders_app_v3.py:4241` to `4262` returns `False` on all append failures.

Failing test idea:

- Tracker append failure records a fallback warning or state flag for diagnostics.

Recommendation:

- Leave for observability PR; security audit already tracks this.

### P2: Date/time helpers mix UTC, GST display time, and timezone-naive datetimes

Evidence:

- `gst_now_iso` at `reminders_app_v3.py:625` formats GST.
- Many action and dataset timestamps use `datetime.utcnow().isoformat()`.
- `_parse_reminder_log_time` at `reminders_app_v3.py:3205` strips timezone information.

Failing test idea:

- A UTC timestamp near midnight should not appear in the wrong local-day period after parsing.

Recommendation:

- Leave for dedicated timezone PR with explicit product decisions.

### P2: Double-click upload/save idempotency relies on session keys after successful save

Evidence:

- `last_saved_upload_key` is set after publish success at `reminders_app_v3.py:7338`.
- A rapid duplicate submit during the first save can still enter the same save path before rerun state lands.

Failing test idea:

- Simulate two calls to `save_uploaded_dataset` with the same `current_upload_key` before rerun and assert only one Drive upload happens.

Recommendation:

- Add an in-progress upload lock in a separate UI-state PR.

### P2: Missing settings record during shared dataset load clears local uploaded data first

Evidence:

- `reminders_app_v3.py:2055` calls `reset_uploaded_data_state(clear_cache=False)` before confirming the clinic record exists.
- If the record is missing or transiently unavailable, the active local dataset state is cleared.

Failing test idea:

- With `working_df` present and `get_fresh_settings_row_values` plus fallback returning no record, `load_shared_dataset_for_clinic` should not clear local data.

Recommendation:

- Leave for shared dataset load behavior PR because stale-data semantics need product review.

### P3: Sorting missing dates has inconsistent default position between active and actioned reminders

Evidence:

- `sort_reminder_table` uses pandas `na_position="last"`.
- `actioned_reminder_sort_value` uses `datetime.max` or `datetime.min` depending on sort direction.

Failing test idea:

- Rows with missing reminder dates should sort consistently across active/actioned tables.

Recommendation:

- Leave unless users report confusing sort behavior.

## Fix sequence

Apply separate patches:

1. P1-1: validate `create_clinic_account` helper inputs.
2. P1-2: make profile rename fail before sheet updates if Drive rename fails.
3. P1-3: move Drive trash after successful sheet row deletion in account delete.
4. P1-4: make statistics team frame tolerate missing optional columns.

Each patch should include a regression test and run:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```
