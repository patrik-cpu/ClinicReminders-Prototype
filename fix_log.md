# Pilot Readiness Fix Log

Date started: 2026-05-22

## P0-001: Live Settings Sheet Contained Legacy MD5 Password Hashes

- Status: Fixed before this fix pass.
- Summary of change: With explicit approval, the 17 legacy MD5 password-account rows and matching tracker/audit rows were deleted from live Google Sheets. The audit document was updated to mark the P0 resolved.
- Files changed: `AUDIT_FINAL_PREPILOT.md`
- Validation performed:
  - `python scripts/auth_legacy_audit.py --show-clinics --fail-on-risk`
- Tests added/updated: None; existing `scripts/auth_legacy_audit.py` remains the release gate.
- Remaining risks: Future malformed password rows must still be caught by the release auth audit.

## P1-001: GitHub CI Can Pass While Pilot Release Gates Fail

- Status: Fixed.
- Summary of change: Removed the current Ruff bug-lint failure and expanded GitHub CI so pushes/PRs run the repo-owned release gates that do not require live credentials: bug lint, dependency security audit, pointer wrapper tests, and `scripts/pilot_release_check.sh`. Live Google smoke/auth audit remains conditional inside the pilot script and runs where credentials are available.
- Files changed:
  - `.github/workflows/ci.yml`
  - `reminders_app_v3.py`
  - `fix_plan.md`
  - `fix_log.md`
- Validation performed:
  - `bash scripts/bug_lint_check.sh`
  - `python -m unittest tests.test_ci_pilot_release_script`
  - `python -m py_compile reminders_app_v3.py settings_pointer_utils.py auth_password_utils.py scripts/live_google_smoke_check.py scripts/auth_legacy_audit.py`
  - `bash scripts/pre_merge_check.sh`
  - `bash scripts/pilot_release_check.sh`
- Tests added/updated: No new tests were needed; existing release-script tests cover the script wiring, and CI now executes the release gate directly.
- Remaining risks: GitHub CI still cannot run live Google smoke/auth audit unless credentials are deliberately configured for that environment. A protected/manual credentialed release workflow remains useful for production promotion.

## P1-002: No Browser-Level E2E Coverage For The Real Streamlit UI

- Status: Partially fixed.
- Summary of change: Added an authenticated Streamlit navigation smoke test using the existing CI-safe E2E layout mode. The test renders the app through `streamlit.testing.v1.AppTest`, clicks every main tab, and fails if any tab raises an uncaught Streamlit exception. This directly covers the recent class of widget/session-state crash while avoiding live Google credentials.
- Files changed:
  - `tests/test_ci_streamlit_navigation_smoke.py`
  - `fix_log.md`
- Validation performed:
  - `python -m unittest tests.test_ci_streamlit_navigation_smoke`
- Tests added/updated:
  - `tests.test_ci_streamlit_navigation_smoke.StreamlitNavigationSmokeTests.test_authenticated_main_tabs_render_without_uncaught_exception`
- Remaining risks: This is Streamlit component-level coverage, not a full real-browser Playwright/Selenium journey. It does not verify actual browser back/forward behavior, mobile viewport rendering, clipboard/WhatsApp deep links, or live Google persistence.

## P1-003: Shared Google Sheets/Drive Tenancy Is Application-Enforced

- Status: Partially fixed.
- Summary of change: Added helper-level tenant guards for saved dataset pointer reads and action tracker loads. A caller asking for another clinic's dataset pointer now fails before sheet access, and action tracker loading returns no records before tracker access when the requested clinic is not the authenticated clinic. This keeps existing storage architecture but makes two shared-backend helper boundaries safer by default.
- Files changed:
  - `reminders_app_v3.py`
  - `tests/test_ci_audit_characterization.py`
  - `fix_log.md`
- Validation performed:
  - `python -m unittest tests.test_ci_audit_characterization.AuditCharacterizationTests.test_dataset_pointer_read_requires_current_tenant_before_sheet_access tests.test_ci_audit_characterization.AuditCharacterizationTests.test_action_tracker_load_fails_closed_for_other_tenant_before_sheet_access`
  - `python -m unittest tests.test_ci_dataset_update tests.test_ci_settings_save_state`
  - `python -m py_compile reminders_app_v3.py settings_pointer_utils.py auth_password_utils.py scripts/live_google_smoke_check.py scripts/auth_legacy_audit.py`
  - `bash scripts/bug_lint_check.sh`
- Tests added/updated:
  - `tests.test_ci_audit_characterization.AuditCharacterizationTests.test_dataset_pointer_read_requires_current_tenant_before_sheet_access`
  - `tests.test_ci_audit_characterization.AuditCharacterizationTests.test_action_tracker_load_fails_closed_for_other_tenant_before_sheet_access`
- Remaining risks: Tenant isolation is still application-enforced over shared Google resources. Stronger storage boundaries or a central repository layer remain deferred; this pass only hardens confirmed helper boundaries.

## P1-004: Multi-Step Google Mutations Are Non-Transactional

- Status: Partially fixed.
- Summary of change: Added operation-level tracking to saved-upload removal. The remove flow now records a `started` event before remote mutation, records a structured `error` event with the failing stage when a Drive/settings write fails, and waits until the dataset pointer update succeeds before mutating local session dataset state. This improves support repairability and avoids showing a locally removed upload when the saved clinic pointer update failed.
- Files changed:
  - `reminders_app_v3.py`
  - `tests/test_ci_dataset_update.py`
  - `fix_log.md`
- Validation performed:
  - `python -m unittest tests.test_ci_dataset_update.DatasetUpdateTests.test_remove_upload_records_pointer_failure_before_local_state_changes tests.test_ci_dataset_update.DatasetUpdateTests.test_remove_overlapping_upload_keeps_rows_covered_by_remaining_history tests.test_ci_dataset_update.DatasetUpdateTests.test_remove_last_upload_clears_stale_uploader_selection tests.test_ci_dataset_update.DatasetUpdateTests.test_remove_last_upload_clears_undated_leftover_rows`
  - `python -m unittest tests.test_ci_dataset_update`
  - `python -m py_compile reminders_app_v3.py settings_pointer_utils.py auth_password_utils.py scripts/live_google_smoke_check.py scripts/auth_legacy_audit.py`
  - `bash scripts/bug_lint_check.sh`
- Tests added/updated:
  - `tests.test_ci_dataset_update.DatasetUpdateTests.test_remove_upload_records_pointer_failure_before_local_state_changes`
- Remaining risks: This is not a full transaction/rollback framework. If Drive upsert mutates an existing file and the settings pointer write fails, the app now records the failing operation clearly, but it cannot automatically restore the prior Drive file contents. A larger versioned-dataset or two-phase publish design remains deferred.

## P1-005: Initial Login/Account Lookup And Cold Action-History Load Scan Full Worksheets

- Status: Partially fixed.
- Summary of change: Added a bounded exact-row lookup path for settings-sheet account lookups. Password login, staff clinic-access login, direct clinic-row lookup, and Google identity lookup now try the relevant indexed column with `find(..., in_column=...)` plus `row_values(...)` before falling back to the existing full-sheet scan. The fallback keeps existing case-insensitive and older fake/client behavior intact.
- Files changed:
  - `reminders_app_v3.py`
  - `tests/test_ci_auth_session.py`
  - `fix_log.md`
- Validation performed:
  - `python -m unittest tests.test_ci_auth_session.AuthSessionTests.test_password_auth_uses_exact_row_lookup_before_full_sheet_scan tests.test_ci_auth_session.AuthSessionTests.test_clinic_access_auth_uses_exact_row_lookup_before_full_sheet_scan tests.test_ci_auth_session.AuthSessionTests.test_google_lookup_uses_exact_subject_lookup_before_full_sheet_scan tests.test_ci_auth_session.AuthSessionTests.test_clinic_row_lookup_handles_non_string_sheet_values tests.test_ci_auth_session.AuthSessionTests.test_successful_authentication_seeds_settings_row_cache tests.test_ci_auth_session.AuthSessionTests.test_google_clinic_lookup_seeds_settings_row_cache tests.test_ci_auth_session.AuthSessionTests.test_google_clinic_lookup_miss_does_not_seed_settings_row_cache`
  - `python -m unittest tests.test_ci_auth_session`
  - `python -m py_compile reminders_app_v3.py settings_pointer_utils.py auth_password_utils.py scripts/live_google_smoke_check.py scripts/auth_legacy_audit.py`
  - `bash scripts/bug_lint_check.sh`
- Tests added/updated:
  - `tests.test_ci_auth_session.AuthSessionTests.test_password_auth_uses_exact_row_lookup_before_full_sheet_scan`
  - `tests.test_ci_auth_session.AuthSessionTests.test_clinic_access_auth_uses_exact_row_lookup_before_full_sheet_scan`
  - `tests.test_ci_auth_session.AuthSessionTests.test_google_lookup_uses_exact_subject_lookup_before_full_sheet_scan`
- Remaining risks: Login still falls back to a full settings-sheet scan when the entered clinic name differs only by case, when the worksheet client does not support `find`, or when exact lookup cannot safely prove a match. Cold action-history loading still reads the shared action tracker worksheet and filters locally; fixing that fully needs a storage/indexing change beyond this focused pass.

## P1-006: Upload/Data Removal UX Allows High-Impact Changes Without Full Review/Rollback

- Status: Partially fixed.
- Summary of change: Added an inline confirmation step for removing a saved upload range. Clicking `Remove` now marks that exact row as pending; the active clinic dataset is changed only after a second `Confirm` click, and the pending confirmation is tied to both row index and row contents so it cannot silently apply to a different row after the upload history changes.
- Files changed:
  - `reminders_app_v3.py`
  - `tests/test_ci_dataset_update.py`
  - `fix_log.md`
- Validation performed:
  - `python -m unittest tests.test_ci_dataset_update.DatasetUpdateTests.test_dataset_upload_removal_requires_matching_pending_confirmation tests.test_ci_dataset_update.DatasetUpdateTests.test_remove_upload_records_pointer_failure_before_local_state_changes tests.test_ci_dataset_update.DatasetUpdateTests.test_remove_overlapping_upload_keeps_rows_covered_by_remaining_history tests.test_ci_dataset_update.DatasetUpdateTests.test_remove_last_upload_clears_stale_uploader_selection tests.test_ci_dataset_update.DatasetUpdateTests.test_remove_last_upload_clears_undated_leftover_rows`
  - `python -m unittest tests.test_ci_dataset_update`
  - `python -m py_compile reminders_app_v3.py settings_pointer_utils.py auth_password_utils.py scripts/live_google_smoke_check.py scripts/auth_legacy_audit.py`
  - `bash scripts/bug_lint_check.sh`
- Tests added/updated:
  - `tests.test_ci_dataset_update.DatasetUpdateTests.test_dataset_upload_removal_requires_matching_pending_confirmation`
- Remaining risks: This does not add a full rollback model or a comprehensive review screen for every upload/replace operation. Clear Clinic Data already has a confirmation checkbox; overlapping upload replacement/recovery still deserves a broader design pass.

## P1-007: Track/Identify Calculations Need Fixture-Level Confidence

- Status: Fixed for helper-level pilot fixture coverage.
- Summary of change: Added a canonical pilot fixture that exercises Identify and Track from the same underlying clinic scenario: three remindable item cycles, two reminder successes, one no-match, two team members, and an all-time Identify potential annual revenue lift total. The test asserts Track headline counts/revenue/team rows, item outcome rows, and Identify revenue-lift rows.
- Files changed:
  - `tests/test_ci_statistics.py`
  - `fix_log.md`
- Validation performed:
  - `python -m unittest tests.test_ci_statistics.StatisticsTests.test_canonical_pilot_fixture_matches_identify_and_track_headlines`
  - `python -m unittest tests.test_ci_statistics`
  - `python -m py_compile reminders_app_v3.py settings_pointer_utils.py auth_password_utils.py scripts/live_google_smoke_check.py scripts/auth_legacy_audit.py`
  - `bash scripts/bug_lint_check.sh`
- Tests added/updated:
  - `tests.test_ci_statistics.StatisticsTests.test_canonical_pilot_fixture_matches_identify_and_track_headlines`
- Remaining risks: This is still helper/harness-level fixture coverage, not a full browser/live Google journey. Browser validation with a disposable pilot clinic and uploaded fixture data remains valuable before wider rollout.

## Final Summary

- P0 fixed: 1
  - P0-001 legacy MD5 password-account rows were removed from live data with explicit approval, and the auth legacy audit now passes.
- P1 fixed: 2
  - P1-001 CI now runs the repo-owned pilot release gates.
  - P1-007 has canonical Identify/Track fixture coverage.
- P1 partially fixed: 5
  - P1-002 added Streamlit navigation smoke coverage, but not full real-browser E2E.
  - P1-003 hardened confirmed tenant helper boundaries, but storage remains shared and application-enforced.
  - P1-004 added dataset-removal operation diagnostics and safer local-state timing, but not full transaction rollback.
  - P1-005 bounded normal account lookups, but exact-lookup misses and cold action-history loads can still fall back to full worksheet scans.
  - P1-006 added confirmation for saved-upload removal, but not a full rollback/review model for every data mutation.
- Issues deferred, with reason: Full tenant-storage redesign, full transaction/versioned dataset model, full browser/live Google E2E suite, indexed action-history storage, and upload rollback UX were intentionally deferred as broad refactors or infrastructure work outside this focused pass.
- Tests run: Focused tests for each issue, dataset update suite, auth session suite, statistics suite, Streamlit navigation smoke, compile checks, bug lint, pre-merge/pilot release gates where noted above.
- Known remaining risks: Shared Google storage architecture, live write-path validation, Streamlit real-browser/mobile coverage, full rollback for data mutations, and action tracker scale.
- Recommendation: Ready with known risks.
