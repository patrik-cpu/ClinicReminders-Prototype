# Auth Settings Fix Results

## Issues fixed

### AUTH-001 - P0 - Logout can restore stale remembered login

Fixed.

The logout path now queues remember-cookie deletion and sets a short-lived in-session restore block. While that block is present, `restore_remembered_login_session()` will not validate or restore a stale cookie/query token that the browser has not physically removed yet. The block clears automatically once no remember token is visible.

Files and locations:
- `reminders_app_v3.py`: `REMEMBER_LOGIN_RESTORE_BLOCKED_KEY`
- `reminders_app_v3.py`: `clear_remember_login_token(block_restore=False)`
- `reminders_app_v3.py`: `restore_remembered_login_session()`
- `reminders_app_v3.py`: account logout button path

Tests added:
- `test_restore_remembered_login_is_blocked_while_cookie_deletion_is_pending`
- `test_restore_block_clears_after_cookie_is_absent`

### AUTH-002 - P0 - Stale persistent login survives user switching / unchecked keep-me-logged-in / Google login

Fixed.

Successful login paths that should not inherit an old remember token now explicitly clear the existing remember session and block same-run restore. Remembered-login refresh remains unchanged so a valid keep-me-logged-in restore can still refresh its token.

Files and locations:
- `reminders_app_v3.py`: `finish_authenticated_session(..., clear_existing_remember_session=False)`
- `reminders_app_v3.py`: password login passes `clear_existing_remember_session=not bool(keep_logged_in)`
- `reminders_app_v3.py`: Google login and Google onboarding pass `clear_existing_remember_session=True`
- `reminders_app_v3.py`: staff access unchecked keep-me-logged-in clears with `block_restore=True`

Tests added:
- `test_finish_authenticated_session_can_clear_existing_remember_cookie`
- `test_finish_authenticated_session_keeps_restore_refresh_path_without_clear`
- `test_login_paths_clear_stale_remember_token_when_persistence_is_not_selected`

### AUTH-003 - P1 - Repeated Google Sheets reads during remember restore / auth settings lookup

Fixed.

`get_clinic_row()` now uses the lower-overhead `get_all_values()` path used by the other auth lookups and seeds `_settings_row_cache` for the matched clinic. Remember-token validation now carries the already-fetched row forward so token refresh does not fetch the same clinic row a second time.

Files and locations:
- `reminders_app_v3.py`: `get_clinic_row()`
- `reminders_app_v3.py`: `validate_remember_login_session()`
- `reminders_app_v3.py`: `restore_remembered_login_session()`

Tests added or updated:
- `test_get_clinic_row_seeds_settings_row_cache`
- `test_restore_remembered_password_login_reuses_validated_row_for_token_refresh`
- `test_restore_remembered_staff_login_reuses_validated_row_for_token_refresh`
- `test_clinic_row_lookup_handles_non_string_sheet_values`
- `test_clinic_access_remember_token_restores_staff_session_only`

Call-count coverage:
- Password remembered-login restore now asserts `get_clinic_row()` is called once.
- Staff remembered-login restore now asserts `get_clinic_row()` is called once.
- Clinic-row lookup tests assert `get_all_values()` is used and `get_all_records()` is not used when the sheet supports `get_all_values()`.

## Validation results

Passed:
- `python -m py_compile reminders_app_v3.py tests/test_ci_auth_session.py`
- `python -m unittest tests.test_ci_auth_session`
- `python -m py_compile reminders_app_v3.py settings_pointer_utils.py scripts/*.py`
- `python -m unittest discover -s tests -p "test_ci_*.py"`: 434 tests, 1 skipped
- `python -m unittest discover -s tests -p "test*.py"`: 442 tests, 1 skipped
- `bash scripts/pre_merge_check.sh`
- `bash scripts/pilot_release_check.sh`
- `python -m pip check`
- `git diff --check`

Notes:
- The broad unittest and release-script runs emit expected Streamlit bare-mode warnings.
- `scripts/pilot_release_check.sh` skipped live Google smoke because no Google credentials or Streamlit secrets were present.

## Remaining reviewed issues not fixed

No remaining P0/P1 issues from `AUTH_SETTINGS_AUDIT.md` were left unfixed.

## Follow-up risks

- These fixes do not change Google auth setup or data formats.
- Live Google smoke was not run because no credentials were available locally.
- The remember-token cookie write still depends on browser execution of the queued Streamlit component, but stale restore is now blocked during the dangerous same-run window.
