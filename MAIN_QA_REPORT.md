# Main Pilot QA Report

Date: 2026-05-17

## Executive Summary

The repository is in a reasonable state for a limited main-branch pilot, assuming
the live Google OAuth and Google Sheets/Drive smoke checks pass in the deployed
environment.

This is not yet a broad production approval. The app is still a large Streamlit
monolith backed by Google Sheets/Drive, with app-level tenant isolation and no
true browser automation suite. The current local QA pass does confirm that the
recent security, Google-login, worksheet-suffix, upload, reminder-action, and UI
changes are covered by the available automated tests and scripts.

## Current Release Decision

Allow a limited pilot with known users and active operator support.

Do not treat this as a general production launch until browser-level E2E tests,
live Google smoke results, backup/restore drills, and tighter Google resource
isolation are in place.

## Automated Validation Run

Commands run from the repo root:

```bash
python -m py_compile reminders_app_v3.py settings_pointer_utils.py scripts/live_google_smoke_check.py scripts/auth_legacy_audit.py
python -m pip check
python -m unittest discover -s tests -p "test_ci_*.py"
python -m unittest discover -s tests
bash scripts/pre_merge_check.sh
bash scripts/pilot_release_check.sh
python scripts/auth_legacy_audit.py --fail-on-risk
```

Results:

- Compile passed.
- Dependency consistency passed: `No broken requirements found.`
- CI-pattern tests passed: 144 tests.
- Full local test discovery passed: 151 tests.
- `scripts/pre_merge_check.sh` passed.
- `scripts/pilot_release_check.sh` passed local checks and skipped live Google
  smoke because no service-account credentials are present in this workspace.
- `python scripts/auth_legacy_audit.py --fail-on-risk` failed only because no
  Google service-account credentials were available locally.

Known warning noise:

- Streamlit bare-mode `ScriptRunContext` warnings appear during direct unittest
  imports. They are expected in these tests and are not failures.

## User-Facing QA Areas Rechecked

- Login screen renders through the login smoke tests.
- Google login configuration is guarded when missing and subject matching is
  enforced for Google-linked accounts.
- Google-linked profile email is read-only, avoiding identity desynchronization.
- Production Streamlit URL defaults to `-live` worksheet tabs when no explicit
  worksheet suffix is configured.
- Upload summary now presents total rows and total date range across uploaded
  CSVs.
- Saved dataset health checks are restored: supported PMS, previous 30-365 day
  coverage, and no 3+ day CSV gaps.
- Upload removal clears stale upload state from the visible upload widget.
- Reminder Sent/Declined/Undo actions remain on the Reminders tab instead of
  navigating back to Upload Data.
- Privacy and deletion copy has been strengthened in user-facing account and
  upload surfaces.
- Light/system theme styling regressions around inputs, checkboxes, password
  fields, and bottom scroll padding have current regression coverage.

## Updated Risk Assessment

### P0

No current local automated P0 failures were found in this QA pass.

Residual P0-class deployment risk remains if the live app is pointed at the
wrong worksheets or if Google credentials have broader access than intended.
The code now defaults the production URL to `-live` tabs, but the deployed
environment still needs a live smoke check with credentials.

### P1

- No real browser automation is present. Current tests cover pure functions,
  workflow helpers, startup/login smoke behavior, and release scripts, but they
  do not click through the deployed UI in a browser.
- Google Sheets/Drive remain the production datastore and are not
  transactional. Backup/restore procedures remain operationally important.
- Tenant isolation is still mostly application-enforced over a shared Google
  service account, despite added helper checks and live worksheet separation.
- The app remains a large monolith, so small UI changes can affect Streamlit
  rerun behavior in surprising ways.

### P2/P3

- Streamlit deprecation warnings for `st.components.v1.html` and
  `use_container_width` should be addressed in a future maintenance pass.
- Formal lint, typecheck, static security scan, secret scan, and dependency
  vulnerability gates are still not installed.

## Manual Main-Pilot Checklist

Before relying on main with real clinic financial data, run these checks in the
deployed app:

1. Confirm Google OAuth works on `https://clinic-reminders.streamlit.app`.
2. Confirm the app writes to `Clinic settings-live`, `Action tracker-live`,
   `Dataset tracker-live`, `User tracker-live`, `Settings audit-live`,
   `Performance tracker-live`, and `Error tracker-live`.
3. Create a disposable Google-login clinic.
4. Upload a small known CSV and confirm total row/date summary and data checks.
5. Click Sent, Declined, and Undo on reminders and confirm the app stays on
   Reminders and rows land in `Action tracker-live`.
6. Remove one uploaded CSV and confirm both saved-data summary and upload widget
   clear stale references.
7. Clear clinic data and confirm the dataset pointer and saved upload history
   are removed for that clinic only.
8. Delete the disposable clinic account and confirm the setup/recreate path is
   understandable.
9. Take a backup of live worksheet tabs and active Drive dataset files.

## Recommendation

Proceed with a controlled pilot only after the manual live checklist passes.
Keep a rollback path: backup the settings spreadsheet tabs and Drive dataset
folder before onboarding real clinics or pushing further main changes.
