# Pilot Readiness Fix Plan

Date started: 2026-05-22

Source of truth: `AUDIT_FINAL_PREPILOT.md` on `main`.

## Priority Order

No active P0 issues remain after the approved legacy-account cleanup on 2026-05-22. Fixes proceed through active P1 issues in audit order.

## P0-001: Legacy MD5 Password Rows

- Status: Resolved before this fix pass.
- Files likely affected: `AUDIT_FINAL_PREPILOT.md`, live Google Sheets data.
- Proposed fix: Keep the release auth audit in the pilot gate so malformed password rows cannot reappear unnoticed.
- Risk level: Low for code; live destructive cleanup already completed with explicit approval.
- Validation steps:
  - `python scripts/auth_legacy_audit.py --show-clinics --fail-on-risk`

## P1-001: GitHub CI Can Pass While Pilot Release Gates Fail

- Files likely affected: `.github/workflows/ci.yml`, `reminders_app_v3.py`, `tests/test_ci_pilot_release_script.py`, `fix_log.md`.
- Proposed fix: Clear the current Ruff bug-lint failure, add GitHub CI coverage for repo-owned release/lint scripts that do not require live credentials, and keep live Google smoke/auth audit as an explicit release gate.
- Risk level: Low. The runtime code change removes only an unused exception binding; CI changes add checks without changing product behavior.
- Validation steps:
  - `bash scripts/bug_lint_check.sh`
  - `bash scripts/pre_merge_check.sh`
  - `bash scripts/pilot_release_check.sh`
  - `python -m unittest tests.test_ci_pilot_release_script`

## P1-002: No Browser-Level E2E Coverage For The Real Streamlit UI

- Files likely affected: `tests/`, `.github/workflows/ci.yml`, possibly a new browser smoke script.
- Proposed fix: Add the smallest browser-level smoke that can run in CI without live clinic credentials, checking app startup/navigation/error-free render where practical.
- Risk level: Medium. New browser tooling can be brittle; avoid broad dependencies unless the existing stack supports the path.
- Validation steps:
  - New focused browser smoke command
  - Existing startup tests
  - Full `test_ci_*.py`

## P1-003: Shared Google Sheets/Drive Tenancy Is Application-Enforced

- Files likely affected: `reminders_app_v3.py`, tenant/destructive-path tests.
- Proposed fix: Add multi-clinic mock tests around destructive/update/read helpers and tighten any missing tenant checks found by those tests. Do not redesign storage in this pass.
- Risk level: Medium. Tenant checks are high value but must avoid breaking legitimate staff/admin flows.
- Validation steps:
  - Focused tenant-isolation tests
  - Auth/session tests
  - Compile and full CI tests

## P1-004: Multi-Step Google Mutations Are Non-Transactional

- Files likely affected: `reminders_app_v3.py`, dataset/account mutation tests, operational docs.
- Proposed fix: Split by operation. Start with failure-injection tests for upload publish/remove/clear and add minimal idempotency or repair messaging where a gap is confirmed.
- Risk level: Medium-high. These paths mutate live data; fixes must be incremental and heavily tested.
- Validation steps:
  - Focused failure-injection tests
  - Dataset update tests
  - Pilot release local gate

## P1-005: Initial Login/Account Lookup And Cold Action-History Load Scan Full Worksheets

- Files likely affected: `reminders_app_v3.py`, auth/session tests, performance/call-count tests.
- Proposed fix: Add call-count characterization first, then reuse cached/authenticated row snapshots and split current-state loads from historical analytics where safe.
- Risk level: Medium. Auth behavior must remain unchanged.
- Validation steps:
  - Focused auth lookup call-count tests
  - Staff/Google/password login tests
  - Reminder/action tracker tests

## P1-006: Upload/Data Removal UX Allows High-Impact Changes Without Full Review/Rollback

- Files likely affected: `reminders_app_v3.py`, upload UI/tests, operations docs.
- Proposed fix: Add targeted confirmation/review affordances for single-upload removal and overlapping replacement first; avoid a full storage redesign.
- Risk level: Medium. UX changes affect a core pilot workflow.
- Validation steps:
  - Upload valid/invalid/missing-column tests
  - Manual upload/remove walkthrough
  - Settings/data persistence checks

## P1-007: Track/Identify Calculations Need Fixture-Level Confidence

- Files likely affected: statistics tests, possible test fixture data.
- Proposed fix: Add a canonical pilot fixture test asserting headline cards/tables for Identify and Track helper outputs without broad UI rewrites.
- Risk level: Low-medium. Test-only characterization should be safe; any calculation changes must be separately justified.
- Validation steps:
  - Focused statistics tests
  - Full `test_ci_*.py`

