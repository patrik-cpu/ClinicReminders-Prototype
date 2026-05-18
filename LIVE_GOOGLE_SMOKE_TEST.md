# Live Google Smoke Test

## Purpose

Run this before merging to a production `main` branch or deploying a release
that touches auth, upload, Google Sheets, Google Drive, settings, or destructive
data flows.

This smoke test has two parts:

1. A read-only automated preflight for real Google Sheets/Drive access.
2. A manual UI checklist for flows that require a browser, OAuth, and a test
   clinic account.

Do not run destructive checks against a real clinic.

## Prerequisites

- A Google service account with access to the settings spreadsheet and datasets
  Drive folder.
- A test clinic account that can be safely created, modified, uploaded to, and
  deleted or cleared.
- OAuth test user access if Google login is being validated.
- A backup taken using `BACKUP_RESTORE_RUNBOOK.md` before any destructive
  production-adjacent validation.

## Automated Read-Only Preflight

For the full limited-pilot gate, run:

```bash
scripts/pilot_release_check.sh
```

That runs local compile/tests/dependency checks first. If Google credentials are
available, it also runs the live Google smoke check and the legacy auth audit.
Set `PILOT_TEST_CLINIC_ID` to include the clinic pointer check:

```bash
PILOT_TEST_CLINIC_ID="Test Clinic" scripts/pilot_release_check.sh
```

Run from the repo root:

```bash
python scripts/live_google_smoke_check.py
```

Credential lookup order:

1. `--credentials-json /path/to/service-account.json`
2. `GOOGLE_APPLICATION_CREDENTIALS`
3. `google-credentials.json`
4. `.streamlit/secrets.toml` with a `[gcp_service_account]` table

Optional clinic pointer check:

```bash
python scripts/live_google_smoke_check.py --clinic-id "Test Clinic"
```

Optional legacy auth data check:

```bash
python scripts/auth_legacy_audit.py --fail-on-risk --show-clinics
```

The auth audit reports counts only by default. It never prints password values.

Google resource IDs can be overridden through environment variables or
`[google_resources]` in `.streamlit/secrets.toml`:

- `SETTINGS_SHEET_ID`
- `DATASETS_FOLDER_ID`
- `FEEDBACK_SHEET_ID`
- `WORKSHEET_NAME_SUFFIX`

For the live app to share the same spreadsheet file but use separate tabs from
dev, set:

```toml
[google_resources]
WORKSHEET_NAME_SUFFIX = "-live"
```

That makes the app use tabs such as `Clinic settings-live`,
`Action tracker-live`, and `Dataset tracker-live`.

For `https://clinic-reminders.streamlit.app`, the app now defaults to `-live`
worksheet tabs when no explicit suffix is configured. Keeping
`WORKSHEET_NAME_SUFFIX = "-live"` in Streamlit secrets is still recommended so
the deployment intent is obvious.

What the script verifies:

- service-account credentials load
- settings spreadsheet opens
- configured settings worksheet exists, for example `Clinic settings-live` on
  the production Streamlit URL
- required settings columns exist
- configured tracker worksheets exist with expected columns, for example
  `Action tracker-live` and `Dataset tracker-live`
- datasets Drive folder opens
- datasets folder can be listed
- optional clinic row exists
- optional clinic `DatasetFileId` points to a non-trashed Drive file
- optional Drive filename matches `DatasetFileName`
- optional Drive `appProperties.clinic_id` matches the clinic if present

The script is intentionally read-only. It does not create, update, append, or
delete Sheets/Drive data.

## Manual UI Smoke Checklist

Record each result as pass/fail with timestamp, browser, app URL, and tester.

### 1. App Startup

1. Start the app:

```bash
python -m streamlit run reminders_app_v3.py
```

2. Open the app URL.
3. Confirm the login screen renders.
4. Confirm no unhandled exception is visible.

### 2. Password Login

1. Log in as the test clinic with clinic/password credentials.
2. Confirm the main tabs render:
   - Reminders
   - Get Started
   - Upload Data
   - Search Terms
   - Exclusions
   - Statistics
3. Log out.
4. Try an invalid password and confirm a safe failure message.

### 3. Google Login

1. Confirm `authlib` is installed through `requirements.txt`.
2. Confirm Streamlit secrets include `[auth]` and `[auth.google]`.
3. Start login with `Continue with Google`.
4. Complete OAuth as an allowed test user.
5. Confirm the app signs into the expected clinic row.
6. Log out and sign in again.

### 4. CSV Upload, Save, And Reload

Use a small test CSV with known dates and rows.

1. Log in as the test clinic.
2. Upload the CSV in Upload Data.
3. Confirm upload validation summary is plausible.
4. Save/publish the dataset.
5. In Google Sheets, confirm the test clinic row has:
   - `DatasetFileId`
   - `DatasetFileName`
   - `DatasetUpdatedAt`
6. In Google Drive, confirm the file exists in the datasets folder.
7. Refresh the app or log out/in.
8. Confirm saved data reloads without re-uploading.

### 5. XLSX Upload

Use a small test `.xlsx` with the same data shape as the CSV.

1. Upload the XLSX.
2. Confirm validation summary is plausible.
3. Save/publish the dataset.
4. Confirm the saved dataset reloads.

### 6. Settings Save And Reload

1. Change the sender name for the test clinic.
2. Change one harmless search term or add a temporary test-only term.
3. Save/apply as the UI requires.
4. Refresh or log out/in.
5. Confirm the settings persisted.
6. Revert the temporary setting.

### 7. Reminder Action Workflow

Use only a test clinic and test dataset.

1. Open Reminders.
2. Generate at least one active reminder.
3. Click prepare/send flow for a reminder.
4. Mark the reminder sent.
5. Confirm it moves out of Active Reminders.
6. Confirm the `Action tracker-live` tab has a row for the test clinic in the
   main pilot environment.
7. Undo the action.
8. Confirm the reminder returns or no longer appears as actioned.
9. Confirm the app remains on the Reminders tab after Sent, Declined, and Undo.

### 8. Clear Clinic Data

Use only a test clinic.

1. Take a backup first.
2. Clear clinic data through the UI.
3. Confirm the settings row dataset pointer cells are blank or intentionally
   cleared:
   - `DatasetFileId`
   - `DatasetFileName`
   - `DatasetUpdatedAt`
4. Confirm the app shows no saved dataset for the test clinic.
5. Restore the test dataset by uploading again or using the backup runbook.

### 9. Account Delete

Only run if the test account is disposable.

1. Create a fresh disposable clinic.
2. Upload and save a tiny dataset.
3. Delete the account through the UI.
4. Confirm the clinic row is removed from relevant worksheets.
5. Confirm the Drive dataset file is trashed only for that clinic.
6. Confirm other clinic rows/files are unchanged.

## Pass Criteria

Before production `main`, all of these must pass:

- `scripts/pilot_release_check.sh`
- `python scripts/live_google_smoke_check.py`
- `python scripts/live_google_smoke_check.py --clinic-id "<test clinic>"`
- `python scripts/auth_legacy_audit.py --fail-on-risk`
- app startup
- password login
- invalid password safe failure
- Google login if enabled for the target deployment
- CSV upload/save/reload
- XLSX upload/save/reload
- settings save/reload
- reminder sent/undo test
- clear-data test on a test clinic

Account delete can be recorded as skipped only if no disposable test clinic is
available. Do not skip it for a broad production launch.

## Result Template

```text
Date/time UTC:
Tester:
Branch/commit:
App URL:
Browser:
Credentials source:
Test ClinicID:

Automated preflight:
  command:
  result:

Password login:
Google login:
CSV upload/save/reload:
XLSX upload/save/reload:
Settings save/reload:
Reminder sent/undo:
Clear clinic data:
Account delete:

Observed issues:
Screenshots/log links:
Manual repairs needed:
Release decision:
```

## Known Limits

- The automated preflight is read-only; it does not prove writes.
- OAuth cannot be fully validated without browser interaction and valid deployed
  callback URLs.
- Manual UI checks should use test data only.
- Passing this smoke test does not replace backup/restore drills or broader E2E
  browser automation.
