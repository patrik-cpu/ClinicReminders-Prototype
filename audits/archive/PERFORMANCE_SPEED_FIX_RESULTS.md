# Performance Speed Fix Results

## Summary

Fixed three high-impact performance issues from `PERFORMANCE_SPEED_AUDIT.md` with focused, behavior-preserving changes:

1. `SPEED-001` partial fix: avoid a duplicate settings-row read when a cached authenticated settings row already contains the shared dataset pointer.
2. `SPEED-002` partial fix: avoid loading the Action Tracker on empty Reminders/Stats renders before any dataset is present.
3. `SPEED-003` fix: skip no-op settings writes when the remote settings payload and relevant metadata already match.

No live Google credentials were used. Tests use mocks/fakes and existing test helpers.

## Issues Fixed

### SPEED-001: Duplicate Settings Reads During Login / Dataset Restoration

- Fix: `load_shared_dataset_for_clinic()` now reuses `_settings_row_cache` when it belongs to the active clinic and includes a non-empty `DatasetFileId`.
- Safety boundary: if the cached row is absent or has no dataset pointer, the existing fresh row read and legacy fallback stay in place.
- Before: successful auth could cache the settings row, then shared dataset loading still performed another fresh settings row read.
- After: clinics with a cached dataset pointer avoid that extra settings `row_values` call before Drive download.
- Remaining risk: full-sheet auth lookups and fallback scans are not removed in this patch.

### SPEED-002: Action Tracker Loading Before Data Exists

- Fix: added `should_load_action_tracker_for_main_section()` so Reminders/Stats only trigger Action Tracker loading when `working_df` exists and is non-empty.
- Safety boundary: the pending action tracker marker is preserved, so the tracker still loads after data becomes available.
- Before: first Reminders/Stats render could load the Action Tracker even when there was no clinic dataset to render.
- After: no-data renders avoid the expensive tracker load.
- Remaining risk: large Action Tracker reads still occur when data exists.

### SPEED-003: No-Op Settings Saves Still Writing to Sheets

- Fix: added `settings_save_is_noop()` and skip the settings `batch_update`/`UpdatedAt` update when the normalized settings payload and relevant metadata match the fresh remote row/cache.
- Safety boundary: if metadata cannot be verified, the existing write path is used.
- Before: unchanged settings still wrote `SettingsJSON` and `UpdatedAt`, creating unnecessary Google Sheets writes.
- After: unchanged settings perform the existing fresh remote read but skip the write.
- Remaining risk: strict equality means saves still write when defaults normalize differently or metadata is unknown.

## Tests Added or Updated

- `tests/test_ci_dataset_update.py`
  - `test_shared_dataset_load_reuses_cached_pointer_row`
  - Proves cached dataset pointer reuse avoids `get_fresh_settings_row_values()`.

- `tests/test_ci_auth_session.py`
  - `test_action_tracker_load_gate_skips_empty_dataset_sections`
  - Proves Action Tracker load gating for empty and non-empty datasets.

- `tests/test_ci_settings_save_state.py`
  - `test_save_settings_skips_batch_update_when_remote_payload_is_unchanged`
  - Adds `FakeSettingsSheet.row_values_calls` measurement and proves no-op saves do not call `batch_update()`.

## Files Changed

- `reminders_app_v3.py`
- `tests/test_ci_dataset_update.py`
- `tests/test_ci_auth_session.py`
- `tests/test_ci_settings_save_state.py`
- `PERFORMANCE_SPEED_AUDIT.md`
- `PERFORMANCE_SPEED_FIX_RESULTS.md`

## Validation Results

- `python -m py_compile reminders_app_v3.py settings_pointer_utils.py scripts/*.py`
  - Passed.
- `python -m unittest tests.test_ci_dataset_update tests.test_ci_auth_session`
  - Passed: 134 tests.
- `python -m unittest tests.test_ci_auth_session tests.test_ci_streamlit_startup tests.test_ci_reminders_badge`
  - Passed: 95 tests.
- `python -m unittest tests.test_ci_settings_save_state`
  - Passed: 53 tests.
- `python -m unittest discover -s tests -p "test_ci_*.py"`
  - Passed: 439 tests, 1 skipped.
- `python -m unittest discover -s tests -p "test*.py"`
  - Passed: 447 tests, 1 skipped.
- `bash scripts/pre_merge_check.sh`
  - Passed.
- `bash scripts/pilot_release_check.sh`
  - Passed. Live Google smoke skipped because no credentials were present.
- `python -m pip check`
  - Passed: no broken requirements found.

## Remaining Reviewed Issues Not Fixed

- `SPEED-001`: full-sheet auth scans and fallback settings scans still need deeper measurement and a separate safer design.
- `SPEED-002`: Action Tracker still loads in full once data exists.
- `SPEED-004`: upload still rewrites the full shared dataset artifact; not changed because it needs dedicated storage/write-path design.
- `SPEED-005`: Stats render path still needs phase timing before changing grouped calculations.
- `SPEED-006`: Reminders badge/window reuse still needs call-count coverage before changing render behavior.
- `SPEED-007`: Top Unreminded item matching still needs aggregate correctness and performance tests before optimization.

## Follow-Up Risks

- Cached pointer reuse relies on `_settings_row_cache` being for the same normalized clinic and containing a non-empty `DatasetFileId`; otherwise the old fresh-read path remains.
- No-op settings save deliberately skips only when the remote payload and cached metadata match exactly.
- Validation was local and mocked; live Google smoke was skipped due missing credentials.
- Streamlit bare-mode warnings continue to appear in tests and are pre-existing.
