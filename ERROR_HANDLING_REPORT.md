# ERROR_HANDLING_REPORT.md

## Executive summary

The app has useful beginnings of observability through Google Sheets tracker tabs, especially Dataset tracker, Error tracker, Settings audit, User tracker, Action tracker, and Performance tracker. The main gap is consistency: upload and saved-dataset failures are logged well, while account/profile/delete/login and tracker-write failures are often swallowed or only shown as generic UI messages.

No broad refactor is recommended. Fixes should be made one category at a time with small tests.

Top findings:

- P1: Error tracker rows store raw exception messages, which can leak tokens, file IDs, emails, passwords, or credential fragments.
- P1: Account create, Google onboarding, profile update, delete account, and password change have user-safe messages but little or no error tracker detail on unexpected failures.
- P1: Tracker writes silently fail, so audit, error, action, and performance events can disappear without any local signal.
- P1: Some Drive diagnostics expose raw Google API response bodies to the UI.
- P2: Google Drive upload/download and Sheets calls have retries in some places but no app-level timeout controls.
- P2: Dataset publish can fall back to "save as new" after existing dataset load failure when called directly.
- P2: Several fallbacks use broad `except Exception` without recording why the fallback was needed.

## Scope and method

Reviewed:

- `reminders_app_v3.py`
- existing `test_ci_*.py`
- `.github/workflows/ci.yml`
- `scripts/pre_merge_check.sh`
- previous audit reports for security, logic, dependencies, and performance context

Commands used included targeted `grep`, `sed`, `nl`, `git status --short`, and existing report/test inspection. `rg` is not installed in this Codespace, so `grep` was used.

## Existing observability surfaces

- `record_dataset_tracker_event` at `reminders_app_v3.py:4325`
- `record_settings_audit_event` at `reminders_app_v3.py:4360`
- `record_error_tracker_event` at `reminders_app_v3.py:4385`
- `record_performance_tracker_event` at `reminders_app_v3.py:4408`
- `upsert_user_tracker` at `reminders_app_v3.py:4711`
- `record_settings_account_event` at `reminders_app_v3.py:4758`
- `record_action_tracker` at `reminders_app_v3.py:3606`

These are helpful, but most callers ignore the returned success/failure value.

## Findings

### P1: Error tracker stores raw exception messages

Evidence:

- `reminders_app_v3.py:4385` in `record_error_tracker_event`
- `reminders_app_v3.py:4395` builds `error_message` from exception text, now through `sanitize_diagnostic_message`
- `reminders_app_v3.py:4403` writes that sanitized message to the Error tracker sheet
- Callers pass exceptions from dataset load, upload parsing, and publishing at `reminders_app_v3.py:2083`, `reminders_app_v3.py:2150`, `reminders_app_v3.py:7205`, `reminders_app_v3.py:7233`, `reminders_app_v3.py:7301`, and `reminders_app_v3.py:7341`

Impact:

Exception strings from Google APIs and auth paths can include URL query parameters, bearer-like tokens, file IDs, email addresses, uploaded filenames, or credential-shaped fragments. The Error tracker is useful, but it should not become a secondary secret store.

Recommended fix:

- Add a small `sanitize_diagnostic_message` helper.
- Redact obvious sensitive key/value pairs such as `password`, `token`, `credential`, `secret`, `api_key`, and `remember`.
- Redact bearer tokens and long opaque URL-safe/base64-ish strings.
- Keep the error type, stage, source, and a capped sanitized message.

Regression test:

- Call `record_error_tracker_event` with an exception containing a password, bearer token, remember token, email, and Drive/file-shaped opaque string.
- Assert the tracker row contains `[redacted]`, does not contain the raw secret values, and still contains useful non-sensitive context.

Safe in isolation:

- Yes. This changes only diagnostic text written to tracker rows.

### P1: Account and profile failures lack diagnostic tracker detail

Evidence:

- `reminders_app_v3.py:4952` to `4953` catches unexpected Google onboarding creation failures and only shows a generic error.
- `reminders_app_v3.py:5152` to `5153` catches unexpected profile update failures and only shows a generic error.
- `reminders_app_v3.py:5247` to `5248` catches delete-account failures and only shows a generic error.
- `reminders_app_v3.py:5673` to `5674` catches manual account creation failures and only shows a generic error.
- `reminders_app_v3.py:5720` to `5728` changes passwords without a wrapper, so unexpected write failures can bubble into Streamlit's default exception path.

Impact:

Users get safe messages, which is good, but operators do not get structured details in the Error tracker for sensitive account flows. That makes support and incident review harder, especially for destructive account deletion.

Recommended fix:

- In each unexpected account-flow `except Exception as e`, call `record_error_tracker_event` with a stable event name, stage, sanitized exception detail, and source.
- For password change, catch unexpected exceptions and show a safe message while logging sanitized detail.
- Keep `ValueError` validation messages user-facing and do not log expected invalid input.

Regression test:

- Patch the affected helper to raise `RuntimeError("sheet denied")`, patch `record_error_tracker_event`, invoke the thin action helper or extracted wrapper, and assert the error is logged with the expected event/stage/source.

Safe in isolation:

- Yes, but the UI blocks are currently embedded in top-level Streamlit render code. Prefer extracting tiny action helpers before testing.

### P1: Tracker writes silently fail

Evidence:

- `reminders_app_v3.py:4241` to `4247` in `append_tracker_row` catches all exceptions and returns `False`.
- `reminders_app_v3.py:4250` to `4263` in `append_tracker_rows` catches all exceptions and returns `False`.
- `reminders_app_v3.py:4711` to `4755` in `upsert_user_tracker` catches all exceptions and returns with no signal.
- `reminders_app_v3.py:4758` to `4782` in `record_settings_account_event` catches all exceptions and returns with no signal.
- `reminders_app_v3.py:3606` to `3611` in `record_action_tracker` ignores the `append_tracker_row` return value.

Impact:

Audit events, reminder action events, error events, and performance events can be lost without a local marker. That weakens both compliance review and debugging of the "Sent" / "Decline" flows.

Recommended fix:

- Keep tracker writes non-blocking for user flows, but store the last tracker failure type/source in session state for diagnostics.
- For action tracker writes, consider queueing failed rows in session state and retrying on the next save/rerun.
- Add tests that a tracker append failure does not crash the user action and does record a local diagnostic marker.

Regression test:

- Patch `get_or_create_tracker_sheet` or `_gspread_retry` to raise.
- Assert `append_tracker_row` returns `False`.
- Assert a non-sensitive local diagnostic marker is set.
- Assert the user action still completes if tracker failure is intended to be non-blocking.

Safe in isolation:

- Yes for local diagnostic markers.
- Queue/retry should be a separate PR because it changes durability semantics.

### P1: Raw Google API response bodies are shown in the UI

Evidence:

- `reminders_app_v3.py:1909` to `1916` in `drive_download_bytes`
- `reminders_app_v3.py:2256` to `2262` in `drive_check_folder_access`
- Both display `e.content.decode("utf-8")` with `st.code(...)`.

Impact:

Google API error bodies may include file IDs, service account details, internal paths, quota/project metadata, or other diagnostic detail that is useful to operators but too raw for end users.

Recommended fix:

- Show only a user-safe summary and HTTP status in the UI.
- Log sanitized diagnostic detail through `record_error_tracker_event`.
- Put raw response-body display behind an explicit local debug flag if needed.

Regression test:

- Simulate `HttpError` content containing a token-like value.
- Assert the UI-facing helper emits a safe message and the tracker receives sanitized content.

Safe in isolation:

- Yes for removing raw UI response bodies.
- Debug-mode behavior can be separate.

### P2: External Google calls lack app-level timeouts

Evidence:

- `reminders_app_v3.py:1899` to `1916` downloads Drive bytes in a `while not done` loop with `downloader.next_chunk()`.
- `reminders_app_v3.py:2201` to `2235` uploads Drive bytes in a `while resp is None` loop with `req.next_chunk()`.
- `reminders_app_v3.py:2345` to `2367` retries Sheets `APIError` statuses but does not enforce elapsed-time budget.
- Many gspread calls are synchronous through `_gspread_retry`.

Impact:

A slow or stuck Google API call can hold the Streamlit request/run open and make the page look frozen. This is especially visible during upload, saved dataset load, settings save, and account flows.

Recommended fix:

- Add elapsed-time budgets around Drive upload/download loops.
- Add a max elapsed time to `_gspread_retry`.
- Log timeout failures through Error tracker and Performance tracker.

Regression test:

- Fake `next_chunk()` or a gspread function that never resolves within budget and assert the helper raises a user-safe timeout error.

Safe in isolation:

- Yes if default budgets are conservative.

### P2: Direct dataset publish can degrade to "save as new" after existing dataset load failure

Evidence:

- `reminders_app_v3.py:2724` to `2730` catches any existing dataset load failure, warns, and continues with `existing_df = None`.
- The UI path at `reminders_app_v3.py:7298` to `7318` is safer and stops when the existing dataset cannot be loaded.

Impact:

The helper behavior and UI behavior differ. A future direct caller could accidentally overwrite/replace history by publishing a new dataset after failing to load the existing one.

Recommended fix:

- Make the helper default to fail closed when `existing_file_id` is present and loading fails.
- If recovery behavior is needed, require an explicit `allow_publish_without_existing=True` parameter and log it.

Regression test:

- Patch `load_existing_shared_df` to raise when `existing_file_id` exists.
- Assert `publish_dataset_for_clinic` raises by default and does not call `drive_upsert_csv_bytes`.

Safe in isolation:

- Medium. This changes direct helper behavior and should be tested around upload replacement flows.

### P2: Some broad fallbacks erase useful diagnostic context

Evidence:

- `reminders_app_v3.py:2060` to `2070` falls back from row lookup to full-record scan without logging why.
- `reminders_app_v3.py:2770` to `2781` does the same in `load_settings`.
- `reminders_app_v3.py:2784` to `2787` swallows invalid settings JSON and uses defaults.
- `reminders_app_v3.py:6170` to `6173` ignores query-param deletion failures.
- `reminders_app_v3.py:10732` to `10737` returns `None` for feedback sheet connection failures.

Impact:

Fallbacks may be correct, but repeated fallback use can hide a broken cache, malformed settings row, credentials issue, or Streamlit API mismatch.

Recommended fix:

- Log fallback activation once per session per event source to avoid noisy logs.
- Keep recoverable behavior, but preserve sanitized error type and stage.

Regression test:

- Patch the primary path to fail and assert the fallback still succeeds while logging a single sanitized fallback event.

Safe in isolation:

- Yes, if logs are rate-limited per session.

### P2: Retry behavior is bounded but not observable enough

Evidence:

- `_gspread_retry` at `reminders_app_v3.py:2345` retries statuses `429`, `500`, `502`, `503`, and `504` up to three attempts.
- It sleeps with exponential backoff and jitter, then performs a final call after the loop at `reminders_app_v3.py:2367`.

Impact:

The retry count is bounded, which is good. However, transient retries are invisible unless the operation ultimately fails, so intermittent quota pressure can be hard to diagnose.

Recommended fix:

- Add optional source/context to `_gspread_retry` or wrap important calls so repeated retry exhaustion is logged.
- Avoid logging every transient retry unless a threshold is crossed.

Regression test:

- Fake two transient `APIError`s followed by success and assert the operation succeeds.
- Fake retry exhaustion and assert a sanitized error event is written by the caller.

Safe in isolation:

- Medium. `_gspread_retry` is central; start with call sites that already have explicit event names.

### P3: No unhandled promise rejection surface found

Evidence:

- This is a Python Streamlit app. No client JavaScript promise code or frontend build was found.

Impact:

Not applicable to the current codebase.

Recommended fix:

- None.

Regression test:

- None.

Safe in isolation:

- Not applicable.

### P3: Inconsistent error response formats are mostly not applicable

Evidence:

- No API route handlers were found. Errors are primarily Streamlit UI messages and tracker rows.

Impact:

The app does not need HTTP JSON error envelopes unless an API layer is added later.

Recommended fix:

- Standardize internal tracker event names and user-safe copy instead.

Regression test:

- Snapshot/characterization tests for helper-generated tracker rows and validation messages.

Safe in isolation:

- Yes.

## First fix category

Fix first: sensitive data in diagnostic logs.

Small patch:

- Add a diagnostic sanitizer helper.
- Apply it in `record_error_tracker_event`.
- Add CI tests for redaction and preserved context.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

## Recommended sequence

1. Redact sensitive diagnostic text in Error tracker rows.
2. Add diagnostic logging for unexpected account/profile/delete/password failures.
3. Add local diagnostics for tracker-write failures without making user actions fail.
4. Replace raw Drive `st.code(e.content...)` UI output with safe UI copy plus sanitized Error tracker rows.
5. Add conservative elapsed-time budgets around Drive upload/download and selected high-impact Sheets operations.
