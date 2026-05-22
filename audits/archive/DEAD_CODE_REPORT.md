# DEAD_CODE_REPORT.md

## Executive summary

This repository has a small file surface but one very large Streamlit app. I found several categories of dead or obsolete code:

- Unreachable UI blocks guarded by literal `if False`.
- Top-level helper functions with zero in-repo references.
- Feedback helpers whose UI is hidden and whose only dependency path appears unused.
- Legacy wrapper/constants left after WhatsApp action tracking moved to the Action tracker.
- Duplicate or scaffold-only tests outside the CI discovery pattern.
- A few dependency candidates with no direct import, but not all are safe to remove without runtime/deployment checks.

I did not delete anything. This report separates "proved unused/unreachable" from "suspicious, needs confirmation."

## Method

Commands and checks used:

- `find . -maxdepth 3 -type f | sort`
- `find . -maxdepth 3 -type d | sort`
- `git status --short`
- `grep -RInE ...` because `rg` is not installed in this Codespace
- Python AST parsing of all `*.py` files to count top-level function name loads and `app.function` attribute references across app/tests
- Manual inspection of the relevant line ranges

Baseline repo status before this report included existing modified/deleted/untracked files from earlier work. I did not revert or alter them.

## Files and folders

### Active or intentionally current

- `reminders_app_v3.py`: main app entry point.
- `settings_pointer_utils.py`: imported by `reminders_app_v3.py:10` and used by `_update_dataset_pointer_cells` at `reminders_app_v3.py:629`.
- `.github/workflows/ci.yml`: active CI workflow.
- `scripts/pre_merge_check.sh`: not used by CI, but manually runnable and referenced by `CODEBASE_AUDIT.md`.
- `AGENTS.md`: active repo guidance.
- `CODEBASE_AUDIT.md` and `SECURITY_AUDIT.md`: current audit docs.
- `GOOGLE_AUTH_SETUP.md`: manual setup documentation; not code-imported.
- `.streamlit/secrets.example.toml`: example config; not runtime-loaded as secrets, but useful documentation.

### Suspicious files/folders

- `tests/fixtures/.gitkeep`
  - Evidence: only referenced by `tests/test_behavior_baseline_scaffold.py:7`.
  - The fixture folder contains no real fixtures.
  - This is scaffold-only, not behavior coverage.
  - Safe deletion depends on whether the team still wants a placeholder for future baseline fixtures.

- `tests/test_behavior_baseline_scaffold.py`
  - Evidence: asserts only that `tests/fixtures` exists and that `True` is true.
  - Outside CI because CI runs `python -m unittest discover -s tests -p "test_ci_*.py"`.
  - Safe to remove if the empty fixture scaffold is no longer wanted.

## Routes, screens, and UI sections

This is a Streamlit app, so there are no conventional route files. Active screens are implemented through tabs and top-level Streamlit branches.

### Proved unreachable screens

#### Factoids section

Evidence:

- `reminders_app_v3.py:9408`: `st.session_state["factoids_unlocked"] = False`
- `reminders_app_v3.py:9411`: `if False and st.session_state["factoids_unlocked"]:`

Why it is dead:

- The branch is guarded by literal `False`, so Python will never enter it.
- The session flag is reset to `False` immediately before the branch.
- Large nested analytics functions inside this block are not defined at runtime.

Deletion safety:

- High confidence dead code.
- Risk is product/requirements risk only: deleting it removes dormant, hidden analytics code that someone may have intended to restore.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

#### Admin clinic account management

Evidence:

- `reminders_app_v3.py:10721`: `if False and st.session_state.get("clinic_id") == "Admin":`
- `reminders_app_v3.py:10761`: `elif False:`

Why it is dead:

- Both branches are guarded by literal `False`.
- The admin form cannot render or run.

Deletion safety:

- High confidence unreachable.
- Security upside: removes dormant password-reset UI that would be unsafe if re-enabled without a real role model.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

#### Nova Vet Family admin/debug/export section

Evidence:

- `reminders_app_v3.py:10767`: `st.session_state["admin_unlocked"] = False`
- `reminders_app_v3.py:10772`: `if False and st.session_state["admin_unlocked"]:`
- Hidden section includes "Keyword Debugging Export" and "Quarterly LLM Bundle".

Why it is dead:

- The branch is guarded by literal `False`.
- The session flag is reset to `False` immediately before the branch.

Deletion safety:

- High confidence unreachable.
- Risk is product/requirements risk only.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

## Unused functions

AST and grep checks found the following top-level functions with no in-repo call sites and no `app.<name>` test references.

### Strong deletion candidates

#### `drive_check_folder_access`

Evidence:

- Definition: `reminders_app_v3.py:2237`
- Grep found no references outside the definition.
- AST found `name_loads=0` and `attr_refs=0`.

Why it matters:

- Looks like a manual Drive diagnostic helper.
- It emits UI messages and raw Google errors, but there is no active button/call path.

Suggested fix:

- Delete the function in a small PR.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Safe now:

- Yes, if no external monkeypatching/import usage exists outside this repo.

#### `get_drive_service_uncached`

Evidence:

- Definition: `reminders_app_v3.py:2264`
- Grep found no references outside the definition.
- AST found `name_loads=0` and `attr_refs=0`.

Why it matters:

- Duplicates credential/service creation already handled by cached `get_drive_service`.

Suggested fix:

- Delete the function after confirming no manual console workflow imports it.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Safe now:

- Likely yes.

#### `merge_dedupe`

Evidence:

- Definition: `reminders_app_v3.py:2289`
- Grep found no references outside the definition.
- AST found `name_loads=0` and `attr_refs=0`.
- Current dataset merging uses `merge_dataset_update` at `reminders_app_v3.py:2669`.

Why it matters:

- Older Vetport-only merge helper appears superseded by current dataset-history merge flow.

Suggested fix:

- Delete `merge_dedupe` if current tests cover dataset merge/update behavior.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Safe now:

- Likely yes. Dataset tests already cover current merge behavior.

#### `format_date_bound`

Evidence:

- Definition: `reminders_app_v3.py:2424`
- Grep found no references outside the definition.
- AST found `name_loads=0` and `attr_refs=0`.

Why it matters:

- Formatting appears superseded by other dataset summary rendering helpers.

Suggested fix:

- Delete it with the other unused dataset-summary helpers.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Safe now:

- Yes.

#### `dataset_history_date_bounds`

Evidence:

- Definition: `reminders_app_v3.py:2547`
- Grep found no references outside the definition.
- AST found `name_loads=0` and `attr_refs=0`.

Why it matters:

- Dataset date range logic now appears to use `get_dataset_date_range`, `dataset_date_bounds`, and saved summary rows.

Suggested fix:

- Delete it with unused dataset-summary helpers.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Safe now:

- Yes.

#### `dataset_summary_checks`

Evidence:

- Definition: `reminders_app_v3.py:2606`
- Grep found no references outside the definition.
- AST found `name_loads=0` and `attr_refs=0`.

Why it matters:

- It computes checklist-style upload quality checks, but no active UI or test reads it.

Suggested fix:

- Delete it only after checking whether the product still wants these hidden setup checks restored.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Safe now:

- Technically yes; product intent is the only uncertainty.

#### `record_wa_button_tracker`

Evidence:

- Definition: `reminders_app_v3.py:3614`
- Grep found no references outside the definition.
- AST found `name_loads=0` and `attr_refs=0`.
- The docstring says: "Legacy wrapper; new writes go to Action tracker."
- `WA_TRACKER_WORKSHEET` at `reminders_app_v3.py:249` and `WA_TRACKER_HEADERS` at `reminders_app_v3.py:273` also appear unused.

Why it matters:

- This is an old compatibility wrapper after action tracking moved to `ACTION_TRACKER_WORKSHEET`.

Suggested fix:

- Delete `record_wa_button_tracker`, `WA_TRACKER_WORKSHEET`, and `WA_TRACKER_HEADERS` together in one tiny legacy-tracker cleanup PR.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Safe now:

- Likely yes. Keep legacy data migration functions that are actively used; only remove the unused wrapper/constants.

#### `consume_dataset_upload_removal`

Evidence:

- Definition: `reminders_app_v3.py:6110`
- Grep found no call site.
- AST found `name_loads=0` and `attr_refs=0`.
- Active UI removes uploads directly through button handling at `reminders_app_v3.py:5928` to `5933`.

Why it matters:

- Query-param removal path appears superseded by direct button handling.

Suggested fix:

- Delete `consume_dataset_upload_removal`.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Safe now:

- Yes, if no external URL workflow depends on `?remove_dataset_upload=...`.

#### `normalize_item_name`

Evidence:

- Definition: `reminders_app_v3.py:6255`
- Grep found no references outside the definition.
- AST found `name_loads=0` and `attr_refs=0`.

Why it matters:

- Item normalization is handled elsewhere by active helpers such as `_exclusion_key`, `normalize_display_case`, and rule matching paths.

Suggested fix:

- Delete it.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Safe now:

- Yes.

#### `_summarize_client_cluster`

Evidence:

- Definition: `reminders_app_v3.py:6322`
- Grep found no references outside the definition.
- AST found `name_loads=0` and `attr_refs=0`.
- Active code calls `_summarize_client_cluster_records` directly.

Why it matters:

- Thin wrapper around the active record-based summarizer.

Suggested fix:

- Delete only `_summarize_client_cluster`, not `_summarize_client_cluster_records`.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Safe now:

- Yes.

#### `reminder_row_has_date`

Evidence:

- Definition: `reminders_app_v3.py:6793`
- Grep found no references outside the definition.
- AST found `name_loads=0` and `attr_refs=0`.
- Active badge filtering uses `reminder_row_in_date_range` at `reminders_app_v3.py:6821`.

Why it matters:

- Looks superseded by range-based reminder date checks.

Suggested fix:

- Delete it.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Safe now:

- Yes.

#### `get_today_active_reminder_count`

Evidence:

- Definition: `reminders_app_v3.py:6859`
- Grep found no references outside the definition.
- AST found `name_loads=0` and `attr_refs=0`.
- Active badge label calls `get_active_reminder_badge_count` directly.

Why it matters:

- Thin alias that is no longer used.

Suggested fix:

- Delete it.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Safe now:

- Yes.

### Feedback helpers: unused because UI is hidden

Evidence:

- `reminders_app_v3.py:10653`: Feedback section starts.
- `reminders_app_v3.py:10659`: `get_feedback_sheet`
- `reminders_app_v3.py:10678`: `insert_feedback`
- `reminders_app_v3.py:10699`: `fetch_feedback`
- `reminders_app_v3.py:10710`: `fetch_feedback_cached`
- `reminders_app_v3.py:10714`: comment says "Feedback UI temporarily hidden; helper functions are kept above for easy restoration."
- Grep found no active call sites for `insert_feedback` or `fetch_feedback_cached`.
- `fetch_feedback` is only called by `fetch_feedback_cached`.
- `get_feedback_sheet` is only called by these unused feedback helpers.

Why it matters:

- This block also keeps `FEEDBACK_SHEET_ID`, `FEEDBACK_SCOPE`, and `oauth2client` usage alive.
- If the UI is not coming back, this is dead Google Sheets integration code.

Suggested fix:

- Do not delete in the first PR unless product confirms feedback is obsolete.
- If confirmed, remove the whole feedback block and then re-check whether `oauth2client` can be removed from `requirements.txt`.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
python -m pip check
```

Safe now:

- Code-reachability says yes.
- Product intent says confirm first because comments explicitly say "temporarily hidden" and "kept above for easy restoration."

## Unreachable branches and obsolete feature flags

### `PRECOMPUTE_ANALYTICS_BUNDLE = False`

Evidence:

- `reminders_app_v3.py:50`: flag is hard-coded `False`.
- `reminders_app_v3.py:5844`: heavy bundle precompute branch is guarded by this flag.
- `reminders_app_v3.py:5850`: active path deletes `bundle` and `bundle_key` when flag is false.

Assessment:

- The `True` branch is unreachable in the current checked-in build.
- `prepare_session_bundle` is called only from this unreachable branch.
- Some disabled factoids/export code also checks `st.session_state["bundle"]`, but those blocks are themselves guarded by literal `False`.

Suggested fix:

- Treat analytics bundle removal as part of the dormant analytics/admin cleanup, not as a tiny first deletion, because it touches feature history and several adjacent blocks.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Safe now:

- Likely, but split from smaller helper deletions.

## Duplicate config and helpers

### Duplicate `BytesIO` import

Evidence:

- `reminders_app_v3.py:46`: `from io import BytesIO`
- `reminders_app_v3.py:4077`: `from io import BytesIO` inside `process_file`

Assessment:

- The inner import is redundant because the same name is already imported at module scope.

Suggested fix:

- Remove the inner import in a tiny cleanup PR.

Validation:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Safe now:

- Yes.

### Duplicate pointer-helper tests

Evidence:

- `tests/test_settings_pointer_helpers.py` tests `_settings_col_index` and `_update_dataset_pointer_cells`.
- `tests/test_settings_batch_helpers.py` also tests `_update_dataset_pointer_cells` and `_update_settings_cells`.
- `tests/test_reminders_pointer_wrapper.py` separately tests wrapper argument forwarding.
- CI only runs `test_ci_*.py`, so these are not part of the required CI command.

Assessment:

- There is overlap, but not full duplication:
  - `test_settings_pointer_helpers.py` is mostly duplicated by `test_settings_batch_helpers.py` and `test_reminders_pointer_wrapper.py`, except for `_settings_col_index`.
  - `test_settings_batch_helpers.py` has unique coverage for `_update_settings_cells`.
  - `test_reminders_pointer_wrapper.py` has unique coverage for wrapper forwarding.

Suggested fix:

- Do not delete these until coverage is consolidated into a `test_ci_*.py` file or CI is expanded.

Validation:

```bash
python -m unittest tests.test_settings_pointer_helpers tests.test_settings_batch_helpers tests.test_reminders_pointer_wrapper
python -m unittest discover -s tests -p "test_ci_*.py"
```

Safe now:

- Not as a first deletion. Consolidate first.

## Unused dependencies

### No direct import found

The following dependencies in `requirements.txt` have no direct import in app/tests:

- `chardet>=5.1.0`
- `google-auth-oauthlib`
- `httpx==0.27.2`

Assessment:

- `chardet` has no direct code reference. It may be obsolete.
- `google-auth-oauthlib` has no direct code reference. It may be leftover from earlier Google auth setup.
- `httpx` has no direct code reference, but may be used by Streamlit/Authlib login internals. Do not remove without validating Google login.

Suggested fix:

- First candidate to test is `chardet`, because code does not import it and pandas CSV parsing does not reference it directly here.
- Validate in a clean environment before deleting from requirements.

Validation:

```bash
python -m pip install -r requirements.txt
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
python -m pip check
```

Safe now:

- Not proven safe solely from static analysis. Dependency deletion needs clean install validation.

### Direct or indirect active dependencies

- `streamlit`: direct import and runtime framework.
- `pandas`: direct import and tests.
- `numpy`: direct import.
- `altair`: direct import for charts.
- `openpyxl`: not directly imported, but needed by `pd.read_excel` for `.xlsx`.
- `gspread`: direct import in app and helper.
- `oauth2client`: directly imported, but only for currently hidden feedback helpers.
- `google-api-python-client`: direct Drive API usage.
- `google-auth`: direct service-account credential usage.
- `google-auth-httplib2`: likely transitive support for Google API client; do not remove without clean install validation.
- `authlib`: checked by `authlib_available` and needed for `st.login("google")`.

## Old compatibility shims

### Keep for now

- `rerun_app` at `reminders_app_v3.py:33`
  - Used by active flows.
  - Handles multiple Streamlit rerun APIs.

- Legacy settings worksheet migration around `reminders_app_v3.py:589` to `608`
  - Active startup path in `get_or_create_settings_worksheet`.
  - Do not remove until production data migration is confirmed complete.

- Legacy MD5 password support at `reminders_app_v3.py:4415` and legacy remember-login signature at `reminders_app_v3.py:4555`
  - Active auth compatibility behavior and currently covered by tests.
  - Security-sensitive migration should happen before deletion.

- Legacy action migration at `reminders_app_v3.py:2807` to `2828` and `migrate_legacy_actions_to_tracker` at `reminders_app_v3.py:3460`
  - Still active when loading settings.
  - Do not remove until all clinics have migration markers.

### Remove candidates

- `record_wa_button_tracker` plus `WA_TRACKER_WORKSHEET` and `WA_TRACKER_HEADERS`
  - No active references found.
  - New action tracker path is active.

## Tests for removed or nonexistent behavior

### Scaffold-only baseline test

Evidence:

- `tests/test_behavior_baseline_scaffold.py` does not exercise application behavior.
- It is outside the current CI pattern.

Suggested fix:

- Delete `tests/test_behavior_baseline_scaffold.py` and `tests/fixtures/.gitkeep` if baseline fixtures are not being added now.

Validation:

```bash
python -m unittest discover -s tests -p "test_ci_*.py"
python -m unittest discover -s tests -p "test*.py"
```

Safe now:

- Yes if no one is relying on the placeholder fixture directory.

## Not dead based on current evidence

- Main tabs and screens under `MAIN_SECTION_TABS`: active labels/rendering.
- `settings_pointer_utils.py`: active import from the main app.
- `scripts/pre_merge_check.sh`: not CI-invoked, but still a valid manual helper.
- `tests/test_ci_*.py`: active CI coverage.
- `tests/test_settings_batch_helpers.py` and `tests/test_reminders_pointer_wrapper.py`: outside CI, but contain unique helper coverage.
- `openpyxl`: required by Excel upload support through pandas.
- `authlib` and likely `httpx`: needed for Streamlit Google login path.

## Proposed deletion PR sequence

### PR 1: Remove the lowest-risk zero-reference helpers

Scope:

- Delete these functions only:
  - `drive_check_folder_access`
  - `get_drive_service_uncached`
  - `merge_dedupe`
  - `format_date_bound`
  - `dataset_history_date_bounds`
  - `normalize_item_name`
  - `_summarize_client_cluster`
  - `reminder_row_has_date`
  - `get_today_active_reminder_count`
- Leave feedback, admin/factoids/export blocks, dependency changes, and tests untouched.

Evidence:

- Each listed function has no grep call sites.
- AST found `name_loads=0`; for these functions, `attr_refs=0` as well.
- Active replacements exist for the risky areas:
  - Dataset merge uses `merge_dataset_update`.
  - Reminder filtering uses `reminder_row_in_date_range`.
  - Active badge code uses `get_active_reminder_badge_count`.
  - Client grouping uses `_summarize_client_cluster_records`.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Risk:

- Low. Main risk is an out-of-repo manual console import, not an in-app call path.

### PR 2: Remove legacy WhatsApp tracker wrapper/constants

Scope:

- Delete `record_wa_button_tracker`.
- Delete unused `WA_TRACKER_WORKSHEET`.
- Delete unused `WA_TRACKER_HEADERS`.

Evidence:

- No active references found.
- Wrapper docstring says new writes go to Action tracker.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Risk:

- Low, but keep active legacy migration code.

### PR 3: Remove query-param upload removal shim

Scope:

- Delete `consume_dataset_upload_removal`.

Evidence:

- No call site found.
- Active UI button calls `remove_dataset_upload_at_index` directly.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Risk:

- Low unless users have an undocumented URL-based removal workflow.

### PR 4: Remove scaffold-only baseline test and empty fixture placeholder

Scope:

- Delete `tests/test_behavior_baseline_scaffold.py`.
- Delete `tests/fixtures/.gitkeep`.
- Remove `tests/fixtures/` if empty.

Evidence:

- The test only asserts the folder exists and `True`.
- It is outside CI.
- No actual fixtures exist.

Validation commands:

```bash
python -m unittest discover -s tests -p "test_ci_*.py"
python -m unittest discover -s tests -p "test*.py"
```

Risk:

- Low if baseline fixture work is not planned immediately.

### PR 5: Remove dormant `if False` UI blocks

Scope:

- Delete hidden Factoids block.
- Delete hidden Admin clinic account management block.
- Delete hidden Nova Vet Family admin/debug/export block.
- Consider removing `PRECOMPUTE_ANALYTICS_BUNDLE` and `prepare_session_bundle` only if no active code remains.

Evidence:

- Literal `if False` guards make these branches unreachable.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Risk:

- Medium product-history risk because the blocks may contain ideas someone expected to restore.

### PR 6: Confirm and remove feedback integration if obsolete

Scope:

- Delete hidden feedback helpers and constants.
- Remove `oauth2client` if it becomes unused after feedback removal.

Evidence:

- Feedback UI is hidden.
- Helpers have no active call sites.

Validation commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
python -m pip check
```

Risk:

- Medium because comments say the helpers are kept for restoration.

### PR 7: Dependency cleanup after clean-environment validation

Scope:

- Test removal of direct requirements with no direct imports, starting with `chardet`.

Evidence:

- No direct imports found in app/tests.

Validation commands:

```bash
python -m pip install -r requirements.txt
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
python -m pip check
```

Risk:

- Medium until validated in a clean environment and with representative CSV/XLSX upload files.
