# Audit Fix Progress

Date started: 2026-05-22

## P1: Direct Dataset Publish Can Continue After Existing Dataset Load Failure

Status: fixed.

Files changed: none for runtime behavior; current code already fails closed in `publish_dataset_for_clinic()` unless `allow_publish_without_existing_dataset=True` is explicitly passed.

Tests added: none in this pass. Existing coverage:

- `tests.test_ci_dataset_update.DatasetUpdateTests.test_publish_dataset_fails_closed_when_existing_dataset_load_fails`
- `tests.test_ci_dataset_update.DatasetUpdateTests.test_publish_dataset_recovery_flag_allows_new_copy_when_existing_load_fails`

Commands run:

```bash
python -m unittest tests.test_ci_dataset_update.DatasetUpdateTests.test_publish_dataset_fails_closed_when_existing_dataset_load_fails tests.test_ci_dataset_update.DatasetUpdateTests.test_publish_dataset_recovery_flag_allows_new_copy_when_existing_load_fails
python -m py_compile reminders_app_v3.py settings_pointer_utils.py scripts/*.py
```

Remaining risk: broader upload/pointer/Drive operations are still multi-step and non-transactional. This entry only covers the focused fail-closed behavior when the existing saved dataset cannot be loaded.

## P1: Login/Account Lookup Should Avoid Repeated Full Settings-Sheet Scans

Status: partially fixed.

Files changed:

- `tests/test_ci_auth_session.py`

Tests added:

- `tests.test_ci_auth_session.AuthSessionTests.test_password_login_setup_reuses_authenticated_settings_row`

Commands run:

```bash
python -m unittest tests.test_ci_auth_session.AuthSessionTests.test_password_login_setup_reuses_authenticated_settings_row tests.test_ci_auth_session.AuthSessionTests.test_successful_authentication_seeds_settings_row_cache tests.test_ci_auth_session.AuthSessionTests.test_restore_remembered_password_login_reuses_validated_row_for_token_refresh
python -m py_compile reminders_app_v3.py settings_pointer_utils.py scripts/*.py
```

Remaining risk: the initial password/staff/Google lookup still scans the settings worksheet once because the current Google Sheets storage model has no indexed account lookup. This pass locked in the existing no-repeat-scan behavior after successful password auth; a broader indexed lookup path should be split into a separate storage/indexing task.

## P1: Tracker Write Failures Should Produce Sanitized Diagnostics

Status: fixed.

Files changed:

- `reminders_app_v3.py`
- `tests/test_ci_error_handling.py`

Tests added:

- `tests.test_ci_error_handling.ErrorHandlingObservabilityTests.test_tracker_write_failure_records_sanitized_local_diagnostic`
- `tests.test_ci_error_handling.ErrorHandlingObservabilityTests.test_tracker_batch_write_failure_records_sanitized_row_count`

Commands run:

```bash
python -m unittest tests.test_ci_error_handling.ErrorHandlingObservabilityTests.test_tracker_write_failure_records_sanitized_local_diagnostic tests.test_ci_error_handling.ErrorHandlingObservabilityTests.test_tracker_batch_write_failure_records_sanitized_row_count tests.test_ci_error_handling.ErrorHandlingObservabilityTests.test_dataset_and_performance_tracker_messages_are_sanitized
python -m py_compile reminders_app_v3.py settings_pointer_utils.py scripts/*.py
```

Remaining risk: failed tracker rows are not retried or durably queued. The fix keeps user flows non-blocking and records a sanitized in-session diagnostic marker for support/debugging.

## P1: Account/Profile/Delete/Password Failures Should Produce Structured Sanitized Diagnostics

Status: partially fixed.

Files changed:

- `reminders_app_v3.py`
- `tests/test_ci_error_handling.py`

Tests added:

- `tests.test_ci_error_handling.ErrorHandlingObservabilityTests.test_account_flow_unexpected_failures_record_error_diagnostics`

Commands run:

```bash
python -m unittest tests.test_ci_error_handling.ErrorHandlingObservabilityTests.test_account_flow_unexpected_failures_record_error_diagnostics tests.test_ci_error_handling.ErrorHandlingObservabilityTests.test_error_tracker_event_writes_sanitized_message_with_context
python -m py_compile reminders_app_v3.py settings_pointer_utils.py scripts/*.py
```

Remaining risk: this pass covers the visible unexpected exception paths for Google onboarding, profile update, manual sign-up, and password update, while preserving user-safe messages. Delete-account failures were already logging diagnostics. Some lower-level helper failures may still need more granular stages in future targeted passes.

## P1: Outcome Success Should Handle Multiple Sent Reminder Steps In One Purchase Cycle

Status: fixed.

Files changed: none for runtime behavior; current code already preserves all sent dates for a purchase cycle through `_OutcomeSentDates` while reporting one deduped sent reminder row.

Tests added: none in this pass. Existing coverage:

- `tests.test_ci_statistics.StatisticsTests.test_grouped_reminder_outcomes_count_later_sent_step_post_reminder_successes`
- `tests.test_ci_statistics.StatisticsTests.test_outcomes_count_multiple_sent_steps_for_same_purchase_once`

Commands run:

```bash
python -m unittest tests.test_ci_statistics.StatisticsTests.test_grouped_reminder_outcomes_count_later_sent_step_post_reminder_successes tests.test_ci_statistics.StatisticsTests.test_outcomes_count_multiple_sent_steps_for_same_purchase_once
python -m py_compile reminders_app_v3.py settings_pointer_utils.py scripts/*.py
```

Remaining risk: outcome logic is still complex and should stay covered by focused regression tests for new edge cases. This specific later-sent-step success case is covered.
