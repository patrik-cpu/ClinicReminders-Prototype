# Clinic Reminders Pilot Readiness Audit

## Scope

Audited the current `main` branch for real pilot clinic readiness across authentication, onboarding, upload, data removal, reminder execution, WhatsApp composer, navigation, Track/Identify reporting, settings persistence, data safety, responsive risk, error states, and performance risk.

Excluded by request: email verification and forgot-password flows.

This was a documentation-only audit after one emergency crash hotfix was applied and pushed separately because the deployed app was showing a Streamlit runtime error in the Send Reminders controls.

## Test Environment

- Branch: `main`
- Commit audited: `dd230d0`
- Date: 2026-05-22
- App type: Streamlit single-file app with Google Sheets/Drive backend.
- Local commands run:
  - `python -m py_compile reminders_app_v3.py settings_pointer_utils.py scripts/*.py`
  - `python -m unittest discover -s tests -p "test_ci_*.py"`: 492 tests passed
  - `bash scripts/pre_merge_check.sh`: passed
  - `bash scripts/pilot_release_check.sh`: failed at live auth legacy audit
  - `python -m pip install -r requirements-dev.txt`
  - `bash scripts/dependency_security_audit.sh`: no known vulnerabilities found
  - `bash scripts/bug_lint_check.sh`: failed on one unused exception variable
- Live Google checks:
  - Settings spreadsheet opened successfully.
  - Required settings columns present.
  - 7 tracker worksheets present with expected columns.
  - Datasets Drive folder opened and listed successfully.
  - Auth legacy audit inspected 19 live settings rows and found 17 legacy MD5 password hashes.
- Limitations:
  - No browser automation framework is present in CI.
  - No Playwright/Selenium end-to-end browser run was performed in this pass.
  - Mobile/tablet checks were code-driven and screenshot-informed, not device-browser verified.
  - Live destructive actions were not executed against production data.

## Executive Summary

`main` is stronger than earlier audit baselines: local unit coverage is broad, upload validation is much better, remembered-login and tenant checks have dedicated tests, and the app has safer user-facing errors in several paths.

However, the current live pilot posture is **not ready** because the release gate found legacy MD5 password hashes in the live settings sheet while current login intentionally rejects MD5 hashes. That means many existing password accounts may be unable to log in unless migrated or reset before pilots use the system.

The next largest risks are not single obvious code crashes; they are release/process and data-safety risks: GitHub CI does not run the pilot release/live auth gates, there is no browser-level E2E coverage for the Streamlit UI, Google Sheets/Drive tenant isolation remains application-enforced over shared resources, and large Google mutations remain non-transactional.

## P0 Issues

### P0-001: Live settings sheet contains legacy MD5 password hashes that current login rejects

- Impact: Existing clinic accounts with legacy MD5 password hashes will not be able to log in with the password flow. This blocks pilot usage for affected clinics and undermines trust immediately at first contact.
- Affected flow: Password login, remembered password login after token expiry, any pilot account still on old password storage.
- Steps to reproduce:
  1. Run `bash scripts/pilot_release_check.sh` with live Google credentials available.
  2. Observe `scripts/auth_legacy_audit.py --fail-on-risk` output.
  3. Attempt password login for one of the legacy-hash clinics.
- Expected behaviour: All password-login pilot accounts use supported `pbkdf2_sha256$...` hashes or have a safe migration/reset path before pilot.
- Actual behaviour: Live audit reports 17 legacy MD5 password hashes and 0 PBKDF2 password hashes across 19 settings rows.
- Evidence:
  - `bash scripts/pilot_release_check.sh` output: `FAIL Auth audit: legacy authentication data remains`.
  - Same output: `WARN Auth audit: legacy MD5 password hashes: 17`, `OK Auth audit: pbkdf2 password hashes: 0`, `OK Auth audit: blank password hashes: 2`.
  - [auth_password_utils.py](/workspaces/ClinicReminders-Prototype/auth_password_utils.py:45) rejects any stored hash that is not `pbkdf2_sha256$iterations$salt$digest`.
  - [tests/test_ci_auth_session.py](/workspaces/ClinicReminders-Prototype/tests/test_ci_auth_session.py:346) asserts legacy MD5 login is rejected.
  - [scripts/auth_legacy_audit.py](/workspaces/ClinicReminders-Prototype/scripts/auth_legacy_audit.py:37) treats MD5, unknown hashes, and plaintext cells as release-blocking risk.
- Recommended fix approach: Before pilot, migrate every password account to PBKDF2 using a controlled password reset/manual reset process, or create a one-time admin migration flow that never exposes plaintext and requires clinics to set a new password. Re-run `python scripts/auth_legacy_audit.py --fail-on-risk` until it passes.
- Suggested validation test: Add/keep a release checklist item that blocks production promotion unless `scripts/auth_legacy_audit.py --fail-on-risk` passes against the exact production settings sheet.

## P1 Issues

### P1-001: GitHub CI can pass while pilot release gates fail

- Impact: Developers can push a branch that appears green in GitHub while the actual pilot release script fails on live auth readiness. This already happened: local unit tests passed, but `pilot_release_check.sh` failed because live auth data is not pilot-safe.
- Affected flow: Release/promotion process, pilot confidence, regression response.
- Steps to reproduce:
  1. Inspect `.github/workflows/ci.yml`.
  2. Compare it with `scripts/pilot_release_check.sh`.
  3. Run `bash scripts/pilot_release_check.sh` locally with live credentials.
- Expected behaviour: The release branch has at least one protected release gate that runs or explicitly records live smoke/auth-audit status before pilot promotion.
- Actual behaviour: GitHub CI only installs production requirements, runs `pip check`, compiles two files, and runs `test_ci_*.py`. It does not run live Google smoke, auth legacy audit, dependency audit, bug lint, browser smoke, or the full pilot release script.
- Evidence:
  - [.github/workflows/ci.yml](/workspaces/ClinicReminders-Prototype/.github/workflows/ci.yml:1) contains only compile and unit test jobs.
  - [scripts/pilot_release_check.sh](/workspaces/ClinicReminders-Prototype/scripts/pilot_release_check.sh:23) includes live Google smoke and auth legacy audit.
  - `pilot_release_check.sh` failed locally after the GitHub-style local unit gates passed.
- Recommended fix approach: Add a separate protected/manual GitHub Actions workflow for pilot release validation, using dedicated test credentials and disposable test clinic data. At minimum, require the auth legacy audit result to be recorded before promoting `main`.
- Suggested validation test: CI should expose a distinct "Pilot Release Gate" status that cannot be confused with unit-only CI.

### P1-002: No browser-level E2E coverage for the real Streamlit UI

- Impact: Streamlit widget ordering/session-state regressions can crash the deployed app even when unit tests pass. This was observed immediately before this audit when Send Reminders controls raised a StreamlitAPIException in the browser.
- Affected flow: Login, tab navigation, Send Reminders, Configure, Exclude, Upload, Identify, Track, Learn, responsive layouts, WhatsApp composer.
- Steps to reproduce:
  1. Inspect tests and `.github/workflows/ci.yml`.
  2. Search for Playwright/Selenium/browser E2E tooling.
  3. Compare with recent browser-only crash in Send Reminders controls.
- Expected behaviour: At least one browser smoke path opens the app, logs in with a mock/test clinic, navigates each main tab, changes Streamlit widget values, and confirms no app exception appears.
- Actual behaviour: Tests are helper/unit/source-level plus a startup smoke, but no browser E2E is present.
- Evidence:
  - Search for `playwright`/`selenium` finds no browser E2E framework.
  - [tests/test_ci_streamlit_startup.py](/workspaces/ClinicReminders-Prototype/tests/test_ci_streamlit_startup.py:1) is startup-oriented, not an interactive browser journey.
  - Recent crash path was in [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:12695), where writing a widget-owned session key after render caused a browser runtime exception until hotfixed.
- Recommended fix approach: Add a minimal Playwright or Streamlit testing smoke that exercises login, navigation, Send Reminders numeric controls, Upload empty/error states, and WhatsApp composer. Keep it mocked first; add a separate live Google smoke later.
- Suggested validation test: Browser test fails if `.stException`, red traceback blocks, or console errors appear after navigating all main tabs.

### P1-003: Shared Google Sheets/Drive tenancy is still application-enforced

- Impact: A single missed tenant guard can expose, mutate, or delete another clinic's settings, tracker rows, or dataset file. This is a serious pilot data-safety risk even though many individual guards exist.
- Affected flow: All Google-backed data access: settings, dataset pointer, Drive dataset, action tracker, account deletion.
- Steps to reproduce:
  1. Inspect shared resource configuration.
  2. Inspect tenant guards.
  3. Inspect broad sheet scans and row deletes.
- Expected behaviour: Every backend operation is tenant-scoped by construction, with tests around destructive and cross-clinic paths.
- Actual behaviour: Shared resource IDs are used, with tenant safety mostly enforced by application code and row filtering.
- Evidence:
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:3582) defines one default settings spreadsheet ID.
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:391) defines one default datasets folder ID.
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:1362) checks the current session clinic before sensitive access.
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:1392) validates Drive file ownership/pointer for dataset access.
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:9362) deletes rows matching clinic IDs across worksheets.
- Recommended fix approach: Keep current guards, but add a multi-clinic threat-model test pack around every destructive/update path. Longer term, move toward stronger per-tenant storage boundaries or a central repository layer that makes unscoped calls impossible.
- Suggested validation test: For each update/delete/load function, add a mock sheet/Drive test proving Clinic A cannot read, update, or delete Clinic B data even with stale session state or hostile parameters.

### P1-004: Multi-step Google mutations are non-transactional and can leave partial state

- Impact: Upload publish, upload removal, clear clinic data, profile rename, and account deletion span multiple Google Sheets/Drive operations. A mid-operation failure can leave Drive files, pointers, upload history, tracker rows, or session state inconsistent.
- Affected flow: Upload Data, Clear Clinic Data, remove one uploaded file, profile rename, delete account and data.
- Steps to reproduce:
  1. Inspect `publish_dataset_for_clinic`.
  2. Inspect `remove_dataset_upload_at_index`.
  3. Inspect `clear_saved_clinic_data`.
  4. Inject failures after Drive upload but before settings/history save, or after pointer clear but before settings save.
- Expected behaviour: Operations are idempotent, fail closed, and have repair/retry paths with clear user messages.
- Actual behaviour: Several paths perform Drive updates, pointer updates, local session updates, settings JSON saves, and tracker writes in sequence.
- Evidence:
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:4759) uploads merged CSV then updates the dataset pointer; cleanup only covers the new-file orphan case when pointer update fails.
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:11588) removes one upload by rewriting or clearing the dataset, then updates session history and saves settings.
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:13762) clears clinic data by clearing the pointer and then local/session/settings state.
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:9431) deletes rows across worksheets and then trashes the Drive file.
- Recommended fix approach: Split by operation. Add failure-injection tests around each external-call boundary, record operation IDs, and add repair/retry helpers for pointer/history mismatches. Avoid broad storage redesign in one pass.
- Suggested validation test: Simulate failure after each Google call and assert user-visible state, saved settings, tracker events, and Drive cleanup are consistent or recoverable.

### P1-005: Initial login/account lookup and cold action-history load still scan full worksheets

- Impact: Pilot may feel slow or quota-prone as clinics/actions grow. Slow login or first Reminders/Track render harms day-to-day use and can look like the app is broken to non-technical staff.
- Affected flow: Login, staff access, Google login, remembered-login restore, first Reminders/Track render.
- Steps to reproduce:
  1. Inspect auth lookup helpers.
  2. Inspect action tracker load.
  3. Run with a large settings sheet or action tracker and count Google calls.
- Expected behaviour: Indexed or cached lookups are used where possible, with cold load bounded to relevant clinic/time windows.
- Actual behaviour: Initial account lookup and action tracker cold load use full worksheet reads, then filter client-side.
- Evidence:
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:8274) password auth calls `sheet.get_all_values()`.
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:8305) staff access also calls `sheet.get_all_values()`.
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:8376) Google identity lookup scans all settings rows.
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:6296) action tracker load calls `sheet.get_all_values()` and filters locally.
- Recommended fix approach: Add call-count/performance tests first. Then introduce safe indexed lookup or row cache paths without changing auth behavior. For action history, split current-state loading from full historical analytics.
- Suggested validation test: With fake sheets containing thousands of rows, assert login and actioned reminder load stay under a defined call and latency budget.

### P1-006: Upload/Data removal UX still allows high-impact data changes without a full review/rollback model

- Impact: Users can upload and save large clinic data directly, remove individual upload ranges, or clear all clinic data. There is confirmation for clearing all data, but not a full review/rollback model for every destructive or replacing operation.
- Affected flow: Upload Data, Remove saved data row, Clear Clinic Data.
- Steps to reproduce:
  1. Upload valid overlapping data.
  2. Remove a saved upload row.
  3. Clear clinic data.
  4. Interrupt or refresh during a save/remove operation.
- Expected behaviour: Users get an obvious review step for replacing/removing data, and support can clearly restore or explain the last known-good state.
- Actual behaviour: The code supports validation and summary rows, but save/remove operations still directly mutate the active clinic dataset and settings.
- Evidence:
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:13666) defines `save_uploaded_dataset`.
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:11518) reconstructs saved summary rows from session/data when history is missing.
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:11450) renders upload history rows with a `Remove` button.
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:13762) clears saved clinic data after a confirmation checkbox.
- Recommended fix approach: Add explicit review/confirm for range replacement and single-upload removal; record enough operation metadata for restore guidance; add interruption/failure tests for upload/remove/clear.
- Suggested validation test: Simulate remove/clear/upload failure and assert no stale badge/count/data summary remains and the user gets a safe recovery message.

### P1-007: Track/Identify calculations are complex and still need live/browser confirmation against clinic expectations

- Impact: Incorrect reminder-success or revenue-lift metrics can mislead clinics about ROI and staff performance. The code has many helper tests, but the full screen-level journey still lacks browser/live dataset validation.
- Affected flow: Identify, Track, date period selector, success windows, actioned reminders.
- Steps to reproduce:
  1. Upload a known fixture with expected reminder outcomes.
  2. Send/decline reminders.
  3. Change success windows and date periods.
  4. Compare cards/tables/export CSV with expected rows.
- Expected behaviour: Counts and revenue exactly match the known fixture across all period selectors and tabs.
- Actual behaviour: Unit coverage is broad, but full UI/browser validation is absent and the calculations depend on many moving parts.
- Evidence:
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:16796) builds reminder outcomes.
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:18397) renders Track and period/success-window controls.
  - [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:18766) persists custom/calendar period window preferences.
  - [tests/test_ci_statistics.py](/workspaces/ClinicReminders-Prototype/tests/test_ci_statistics.py:1) contains extensive helper-level characterization, but no browser E2E.
- Recommended fix approach: Add one canonical pilot fixture and a screen-level smoke test that verifies headline cards, item rows, actioned rows, and exports for Identify and Track.
- Suggested validation test: Browser or harness test logs into a test clinic, loads fixture data, actions reminders, and asserts the exact six Identify/Track headline values.

## P2 / Polish Issues

- `scripts/bug_lint_check.sh` fails on an unused exception variable in [reminders_app_v3.py](/workspaces/ClinicReminders-Prototype/reminders_app_v3.py:13773). This is low risk, but it means the documented bug-lint gate is not clean.
- The checked-in `requirements.txt` uses broad dependency ranges for several packages; `pip-audit` passed today, but reproducibility is weaker than a locked release environment.
- Mobile/responsive usability for wide Streamlit tables remains unverified by automated tests. The app has many custom column layouts, which are fragile on narrow screens.
- Several user-facing terms still map from older internal names (`Stats`, `Search Terms`, `Get Started`) to sleeker labels. The label mapping appears intentional, but future changes should keep old query params and saved tab names compatible.
- Live Google smoke is read-only by default. A disposable write-path smoke for upload/action/clear would increase confidence but must be carefully isolated.

## Flows Tested

- Authentication and session handling: Partial
  - Unit/source coverage exists for password login, Google login helpers, staff access, remembered-login tokens, logout cleanup, and rate limiting.
  - Live auth readiness failed due legacy MD5 hashes.
  - Browser refresh/close/reopen was not tested in this audit.
- First-time clinic setup: Partial
  - Code paths and Learn checklist reviewed.
  - No browser walkthrough with a brand-new clinic was performed.
- Data upload flow: Partial
  - Unit coverage and code review cover file count/size, row/column limits, missing columns, empty uploads, bad dates, date formats, duplicate/overlap behavior, and publish fail-closed behavior.
  - No live write upload was performed in this audit.
- Data removal/reset flow: Partial
  - Code reviewed for single upload removal and Clear Clinic Data.
  - Destructive live flow not executed.
- Reminder/item management: Partial
  - Configure/search-term editor and reminder action helpers reviewed.
  - Persistence tests exist for many settings.
  - Browser edit/delete/save/cancel journey not fully tested.
- Team member management: Partial
  - Team appears represented through sender/actioned-by stats rather than a separate full role-management system.
  - Staff access code flow reviewed at code level.
- Reminder execution / WhatsApp composer flow: Partial
  - Existing tests cover sent/declined/undo workflow and edited composer copy behavior.
  - Browser WhatsApp deep-link/clipboard behavior not tested here.
- Search and navigation: Partial
  - Query param/tab compatibility tests exist.
  - Browser back/forward and mobile navigation not tested.
- Dashboard / metrics / graphs: Partial
  - Identify/Track helper coverage is broad.
  - Full fixture-driven browser comparison not present.
- Settings and persistence: Partial
  - Many tests cover settings save/merge and recent reminder-window persistence.
  - Browser persistence after refresh/logout/login not fully tested.
- Permissions and data safety: Partial
  - Tenant guard tests exist for selected destructive paths.
  - Shared backend architecture remains a P1 risk.
- Responsive/mobile usability: Not tested
  - Reason: no browser/device automation was available in this pass.
- Error states and polish: Partial
  - Error handling reviewed; local/live checks run.
  - Network interruption and double-click race tests are incomplete.
- Performance risks: Partial
  - Existing audit backlog and code review identify full-sheet and full-history scans.
  - No measured large-clinic benchmark was run in this pass.

## Data Safety Review

The app has meaningful tenant guards in the current code: `require_authenticated_tenant_access()` checks the signed-in clinic before sensitive operations, dataset file access validates the active pointer and Drive `appProperties`, and destructive account deletion has tests around cross-tenant rejection.

The remaining concern is architectural: all clinics still share Google Sheets/Drive resources, and many operations are sequences of independent Google calls. That means data safety depends on every path remembering to apply the guard and on every multi-step mutation finishing cleanly. This is acceptable only with strong tests, backups, and a pilot runbook; it is not yet a robust long-term storage model.

Backup/restore documentation exists in `docs/operations/BACKUP_RESTORE_RUNBOOK.md`, and live smoke confirms the production-like Google resources are reachable. Before pilot, confirm recent Google Sheets/Drive version history or backups and decide who can perform account/data restoration.

## Pilot Go / No-Go View

Current view: **Not ready**.

Reason: the current live release gate fails because 17 live settings rows still contain legacy MD5 password hashes while current login rejects MD5. This can block real clinics from logging in. Fix or migrate the live auth data first, then re-run `bash scripts/pilot_release_check.sh` until it passes.

After P0-001 is resolved, the branch may become **Ready with known risks** for a controlled pilot if:

- A human completes a browser walkthrough of login, upload, reminders, WhatsApp, Identify, Track, clear data, and logout using a disposable pilot clinic.
- The pilot release gate result is recorded.
- Backups/rollback are confirmed.
- The team accepts the known P1 risks around shared Google tenancy, non-transactional mutations, and missing browser E2E.
