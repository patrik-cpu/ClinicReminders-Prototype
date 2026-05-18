# Backup And Restore Runbook

## Purpose

Use this runbook before moving changes to production and whenever a clinic's
saved data, settings, or tracker history may be inconsistent.

The app stores durable state in two Google services:

- Google Sheets: the shared settings spreadsheet and tracker worksheets.
- Google Drive: one saved CSV dataset file per clinic in the shared datasets
  folder.

The app is not transactional across Sheets and Drive. A failed upload, timeout,
manual edit, or delete flow can leave a clinic row pointing at the wrong file,
no file, or stale tracker data. Always take a backup before manual repair.

## Storage Map

Settings spreadsheet:

- Spreadsheet ID is configured in `reminders_app_v3.py` as
  `SETTINGS_SHEET_ID`.
- Main worksheet: `Clinic settings`.
- Legacy worksheet copied during migration if present: `Sheet1`.

Important `Clinic settings` columns:

- `ClinicID`: tenant identity.
- `PasswordHash`: password login hash.
- `SettingsJSON`: clinic rules, exclusions, template, upload history, and UI
  settings.
- `UpdatedAt`: settings row update timestamp.
- `DatasetFileId`: Google Drive file ID for the active saved clinic dataset.
- `DatasetFileName`: expected saved dataset filename.
- `DatasetUpdatedAt`: timestamp written when the dataset pointer was last saved.
- `AuthProvider`, `GoogleEmail`, `GoogleSubject`, `GoogleName`: Google login
  metadata.
- `Country`, `CreatedAtGST`, `LastLoginAtGST`, `LastLoginProvider`,
  `AccountStatus`: account metadata.

Tracker worksheets:

- `User tracker`
- `Action tracker`
- `Dataset tracker`
- `Settings audit`
- `Error tracker`
- `Performance tracker`

Main/live deployment note:

- The production Streamlit URL uses worksheet tabs with a `-live` suffix, for
  example `Clinic settings-live`, `User tracker-live`,
  `Action tracker-live`, and `Dataset tracker-live`.
- The app defaults to this suffix for `https://clinic-reminders.streamlit.app`,
  but an explicit `WORKSHEET_NAME_SUFFIX = "-live"` secret is still preferred.
- When backing up or restoring main, use the `-live` tabs. Do not mix them with
  the unsuffixed dev tabs.

Drive storage:

- Dataset folder ID is configured in `reminders_app_v3.py` as
  `DATASETS_FOLDER_ID`.
- Saved dataset filename format is currently
  `<ClinicID>_shared_dataset.csv`.
- Newer Drive files may have `appProperties.clinic_id` metadata.

## Backup Schedule

Minimum before production:

- Take a full backup immediately before merging or deploying changes that touch
  auth, upload, settings save/load, Drive, Sheets, tracker writes, account
  deletion, or profile rename.
- Take a full backup immediately before onboarding real clinic data.
- Take a full backup before any manual repair.

Suggested pilot cadence:

- Daily backup of the settings spreadsheet.
- Daily backup or Drive copy of the datasets folder.
- Keep at least 30 days of daily backups during pilot.
- Keep a permanent backup before every production deployment.

## Backup Procedure

### 1. Freeze Risky Activity

1. Ask users to stop uploading, deleting, renaming profiles, or changing
   settings while the backup runs.
2. Note the UTC time and operator name.
3. Do not edit live Sheets or Drive files until the backup is complete.

### 2. Back Up The Settings Spreadsheet

In Google Sheets:

1. Open the spreadsheet identified by `SETTINGS_SHEET_ID`.
2. Confirm these tabs exist:
   - For dev: `Clinic settings`, `User tracker`, `Action tracker`,
     `Dataset tracker`, `Settings audit`, `Error tracker`,
     `Performance tracker`.
   - For main/live: `Clinic settings-live`, `User tracker-live`,
     `Action tracker-live`, `Dataset tracker-live`, `Settings audit-live`,
     `Error tracker-live`, `Performance tracker-live`.
3. Use `File > Make a copy`.
4. Name the copy:
   - `ClinicReminders_Settings_Backup_YYYY-MM-DD_HHMM_UTC`
5. Store it in a restricted backup folder.
6. Also export an `.xlsx` copy for offline recovery if possible.

Record in the backup manifest:

- Backup timestamp.
- Original spreadsheet ID.
- Backup spreadsheet ID.
- Tab list.
- Operator.
- Reason for backup.

### 3. Back Up The Drive Dataset Folder

In Google Drive:

1. Open the folder identified by `DATASETS_FOLDER_ID`.
2. Create a backup folder named:
   - `ClinicReminders_Datasets_Backup_YYYY-MM-DD_HHMM_UTC`
3. Copy each active clinic dataset CSV into that backup folder.
4. If the folder is large, at minimum copy every file referenced by
   `DatasetFileId` in the current `Clinic settings` worksheet.

Record in the backup manifest for each dataset:

- ClinicID from the settings row.
- DatasetFileId from the settings row.
- DatasetFileName from the settings row.
- DatasetUpdatedAt from the settings row.
- Backup file ID or backup filename.
- Row count if quickly available.

### 4. Back Up Secrets Metadata

Do not copy secret values into the manifest.

Record only:

- Where Streamlit secrets are managed.
- Which Google service account is expected.
- Which OAuth project/client is expected.
- Who has permission to rotate credentials.

## Restore Principles

- Restore the smallest safe unit first.
- Prefer restoring a single clinic row or one Drive file over replacing the
  whole settings spreadsheet.
- Never paste a backup row over a different `ClinicID`.
- Never restore another clinic's `DatasetFileId` into the active clinic row.
- Before changing a pointer, verify the target Drive file belongs to that
  clinic by filename, folder location, known backup manifest, and, where
  available, `appProperties.clinic_id`.
- Keep a written incident note with before/after values.

## Manual Recovery: Bad Dataset Pointer

Symptoms:

- Login succeeds but saved data does not load.
- UI says the saved data record is missing its file link.
- `DatasetFileId` is blank, points to a trashed file, or points to a file that
  fails to parse.
- `DatasetFileName` does not match the clinic's expected saved CSV.

Steps:

1. Back up Sheets and Drive first.
2. In `Clinic settings`, find the exact row where `ClinicID` matches the
   affected clinic.
3. Copy the current values of:
   - `DatasetFileId`
   - `DatasetFileName`
   - `DatasetUpdatedAt`
   - `SettingsJSON`
4. In Drive, locate the intended CSV:
   - Prefer the file ID from a backup manifest.
   - Otherwise search in `DATASETS_FOLDER_ID` for
     `<ClinicID>_shared_dataset.csv`.
5. Verify ownership:
   - Filename matches the clinic.
   - File is in the expected datasets folder.
   - If Drive metadata is available, `appProperties.clinic_id` matches
     `ClinicID`.
   - Download/open a copy and confirm row count and date range are plausible.
6. Update only the pointer cells in the affected settings row:
   - `DatasetFileId`: verified Drive file ID.
   - `DatasetFileName`: verified filename.
   - `DatasetUpdatedAt`: current UTC timestamp or the timestamp from the
     backup if restoring an old point in time.
7. Reload the app as that clinic and confirm the saved dataset loads.
8. Add an incident note to the backup manifest or support log.

If no valid Drive file exists:

1. Restore the most recent backup CSV into the datasets folder.
2. Rename it to `<ClinicID>_shared_dataset.csv`.
3. Update the settings row pointer to the restored file.
4. Ask the clinic to re-upload any newer files that are not in the backup.

## Manual Recovery: Upload Succeeded But Pointer Failed

Likely state:

- A CSV exists or was updated in Drive.
- `DatasetFileId`, `DatasetFileName`, or `DatasetUpdatedAt` in Sheets did not
  update.

Steps:

1. Back up first.
2. Find the clinic row in `Clinic settings`.
3. Search the datasets folder for `<ClinicID>_shared_dataset.csv`.
4. Compare the Drive modified time and file contents to the user's attempted
   upload.
5. If the Drive file is correct, update the three dataset pointer cells in the
   clinic row.
6. If the Drive file is not correct or cannot be verified, leave the pointer as
   is and ask the clinic to re-upload after confirming the previous saved data
   still loads.
7. After repair, log into the app and confirm:
   - Saved dataset loads.
   - Upload history makes sense.
   - Active reminders can be generated.

## Manual Recovery: Pointer Updated But Drive File Is Missing Or Bad

Likely state:

- `DatasetFileId` points to a missing, trashed, inaccessible, or malformed file.

Steps:

1. Back up first.
2. Try to locate the file by ID in Drive, including Trash.
3. If it is in Trash and belongs to the clinic, restore it.
4. If the file cannot be restored, copy the latest backup CSV into the datasets
   folder and update the pointer to the restored file ID.
5. If no backup exists, clear the three dataset pointer cells and ask the clinic
   to re-upload. Only do this after confirming there is no recoverable file.

## Manual Recovery: Settings Row Was Damaged

Symptoms:

- Login fails for a known clinic.
- Rules, exclusions, WhatsApp template, or upload history disappeared.
- `SettingsJSON` is invalid JSON.

Steps:

1. Back up current live state first.
2. Open the most recent known-good settings backup.
3. Locate the row with the same `ClinicID`.
4. Copy only the damaged cells needed for recovery.
5. Avoid overwriting `PasswordHash`, Google auth metadata, or dataset pointer
   cells unless those are the cells being repaired.
6. If restoring `SettingsJSON`, validate that it is parseable JSON before
   saving.
7. Log in as the clinic and confirm settings, reminders, and saved data load.

## Manual Recovery: Tracker Rows Are Missing Or Corrupt

Tracker sheets are append-style support/audit data. They should not block normal
clinic login, but missing rows reduce auditability and statistics accuracy.

Steps:

1. Back up current live trackers first.
2. Confirm the header row still matches the expected tracker worksheet.
3. Restore missing rows from the backup by appending them below existing rows.
4. Do not sort live tracker sheets unless you have a separate backup.
5. For `Action tracker`, verify restored rows have the expected `ClinicID` and
   `ReminderKey`.
6. Reload the clinic and confirm actioned reminders and statistics are plausible.

## Manual Recovery: Account Delete Or Clear Data Partially Completed

Delete account and clear-data actions are destructive. Do not guess.

If sheet rows were deleted but the Drive file remains:

1. Back up the current Drive file before doing anything else.
2. Restore the `Clinic settings` row from the latest settings backup if the
   account should continue to exist.
3. Restore relevant tracker rows only if audit/statistics continuity matters.
4. If the account should stay deleted, verify the Drive file belongs to that
   clinic before trashing it.

If the Drive file was trashed but the settings row remains:

1. Restore the Drive file from Trash if it belongs to the clinic.
2. Verify or update `DatasetFileId`, `DatasetFileName`, and `DatasetUpdatedAt`.
3. If the file cannot be restored, clear the pointer cells and ask the clinic to
   re-upload.

If only the dataset pointer was cleared:

1. Locate the previous file ID from a settings backup, upload history, or Drive
   backup manifest.
2. Verify the file belongs to the clinic.
3. Restore the pointer cells.

## Post-Restore Validation

After every restore:

1. Run local automated checks:

```bash
python -m py_compile reminders_app_v3.py settings_pointer_utils.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

2. In the app, using a test or affected clinic:
   - Log in.
   - Confirm saved data loads without an error.
   - Confirm upload history is plausible.
   - Open Reminders and confirm rows generate.
   - Mark a test reminder sent only if using a test clinic.
   - Confirm tracker rows append for the test action.
3. In Sheets:
   - Confirm the affected `Clinic settings` row has the intended values.
   - Confirm tracker headers are still present.
4. In Drive:
   - Confirm the active dataset file is in the expected folder.
   - Confirm the file is not in Trash.
   - Confirm only the intended clinic points to that file.

## Recovery Drill

Run this drill before production and at least once per quarter during pilot:

1. Create or use a test clinic.
2. Upload a small CSV.
3. Back up Sheets and Drive using this runbook.
4. Break the test clinic's `DatasetFileId` in `Clinic settings`.
5. Confirm the app fails safely for that test clinic.
6. Restore the pointer from the backup manifest.
7. Confirm the app loads the saved dataset again.
8. Record the time required and any confusing steps.

Do not run the drill on a real clinic row.

## Incident Log Template

```text
Incident ID:
Date/time UTC:
Operator:
Affected ClinicID:
User-reported symptom:
Backup spreadsheet ID:
Backup dataset folder/file IDs:
Before values:
  DatasetFileId:
  DatasetFileName:
  DatasetUpdatedAt:
  SettingsJSON changed? yes/no
Action taken:
After values:
  DatasetFileId:
  DatasetFileName:
  DatasetUpdatedAt:
Validation performed:
Remaining risk:
Follow-up ticket:
```

## Known Limits

- This runbook does not make Sheets/Drive writes transactional.
- This runbook does not replace a real database backup system.
- OAuth behavior still needs separate live validation.
- Manual edits can create new incidents; use two-person review for production
  repairs whenever possible.
