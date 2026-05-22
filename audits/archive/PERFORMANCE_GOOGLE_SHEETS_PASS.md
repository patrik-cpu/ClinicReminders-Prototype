# Performance Google Sheets Pass

Date: 2026-05-19

Scope: Google Sheets read/write reduction only. This pass re-checks the current code and does not propose or apply broad rewrites.

## Executive Summary

The previous performance concern is still real: several auth, account, settings, and upload flows still use full Google Sheets reads on hot paths. The code now has some useful row caching (`_settings_row_cache`) and batch updates for settings and tracker writes, but the main bottlenecks remain:

- Login/account lookup reads the full settings sheet with `get_all_records()`.
- `load_settings()` reads settings and then cold-loads the full Action tracker sheet.
- Google sign-up performs multiple full settings-sheet reads in one flow.
- Profile edit and delete-account flows scan one or more full worksheets.
- Upload save repeats settings-row reads around dataset pointer updates and then appends several tracker rows individually.

The safest first wins are not architectural rewrites. They are small call-count reductions: reuse settings rows already found in the current action, combine duplicate sign-up scans, batch upload tracker rows, avoid repeated tracker header reads after `ensure_tracking_sheets_once()`, and add test fakes that count Sheets calls.

## 1. Current Google Sheets Read/Write Paths

| Function | Location | Current API calls | Used by | Notes |
| --- | --- | --- | --- | --- |
| `get_settings_spreadsheet()` | `reminders_app_v3.py:6467` | `gspread.authorize()`, `client.open_by_key()` once per Streamlit resource cache | all Sheets flows | Resource cached, not a repeated hot-path call after first use. |
| `get_settings_sheet()` / `get_or_create_settings_worksheet()` | `reminders_app_v3.py:6480`, `reminders_app_v3.py:835` | `spreadsheet.worksheet()`, possible `add_worksheet()`, `worksheet.get_all_values()`, possible legacy worksheet reads, possible `worksheet.update()` and `batch_update()` | first settings access | The first settings access may do schema/legacy repair work. Cached afterward by `st.cache_resource`. |
| `ensure_settings_sheet_columns()` | `reminders_app_v3.py:765` | `get_all_values()` if headers not provided; `update()` if columns missing | settings writes/create | Usually cheap if headers are passed; expensive if called without headers. |
| `clear_legacy_plain_password_column()` | `reminders_app_v3.py:788` | `get_all_values()`, optional `batch_update()` | first settings worksheet creation | Only first cached settings-sheet setup, but can scan all accounts. |
| `_get_settings_row_for_clinic()` | `reminders_app_v3.py:968` | full `sheet.get_all_values()` on cache miss | load/save settings, dataset pointer, profile, password | Finds row index by scanning all settings rows. Caches row index and values in session. |
| `get_fresh_settings_row_values()` | `reminders_app_v3.py:1094` | `_get_settings_row_for_clinic()`, then `sheet.row_values(row_idx)` | dataset load, access-code update, pointer checks | Better than full scan after cache warm, but still a network row read. |
| `update_settings_row_fields()` / `_raw_update_settings_row_fields()` | `reminders_app_v3.py:1078`, `reminders_app_v3.py:1024` | `_get_settings_row_for_clinic()`, optional `ensure_settings_sheet_columns()`, `sheet.batch_update()` | account status, dataset pointer, profile, access code | Uses a batch update for fields, then invalidates settings row cache. |
| `read_remote_settings_from_row()` | `reminders_app_v3.py:4966` | `sheet.row_values(row)` | `save_settings()`, remote merge | Correctly reads one row, but happens on many autosaves when `refresh_remote=True`. |
| `load_settings()` | `reminders_app_v3.py:4346` | `_get_settings_row_for_clinic()` plus cached row or `row_values()`; fallback `get_all_records()`; then `load_action_tracker_records_for_clinic()` | login, staff access, Google login, sign-up, profile reload, app session init | Cold path can be one full settings scan plus one full action tracker scan. |
| `save_settings()` | `reminders_app_v3.py:4593` | `_get_settings_row_for_clinic()`, optional `row_values()` via `read_remote_settings_for_save()`, `batch_update()` or `append_row()`, optional extra `update_settings_row_fields()`, optional `upsert_user_tracker()` | autosaves, search terms, exclusions, templates, upload history, reminder controls | Existing row path can perform a settings JSON batch update and then a second settings batch update for country/status. |
| `load_action_tracker_records_for_clinic()` | `reminders_app_v3.py:5235` | `get_or_create_tracker_sheet()`, full `sheet.get_all_values()` | `load_settings()`, stats sync, recent reminder log | Full Action tracker scan when session cache is cold or invalidated. |
| `get_or_create_tracker_sheet()` | `reminders_app_v3.py:6486` | `spreadsheet.worksheet()` or `add_worksheet()`, `row_values(1)`, optional header `update()` | every tracker append/load first per sheet | Cached in session after first access, but `ensure_tracking_sheets_once()` does not populate this cache. |
| `append_tracker_row()` | `reminders_app_v3.py:6506` | `append_row()` after tracker sheet/header lookup | dataset/settings/error/performance/account/action tracker events | Single-row append. Good for single events, noisy for loops. |
| `append_tracker_rows()` | `reminders_app_v3.py:6517` | `append_rows()` after tracker sheet/header lookup; fallback loop of `append_row()` | bulk mark reminders sent, legacy action migration | Already the preferred batched path. |
| `record_dataset_tracker_event()` | `reminders_app_v3.py:6594` | one tracker `append_row()` | upload parse/save/publish/clear/remove | Called multiple times during one upload save. |
| `record_settings_audit_event()` | `reminders_app_v3.py:6633` | one tracker `append_row()` | settings/search/exclusion audit paths | Many settings UI changes can trigger one append each. |
| `record_error_tracker_event()` | `reminders_app_v3.py:6662` | one tracker `append_row()` | failure paths | Error-only hot path. |
| `record_performance_tracker_event()` | `reminders_app_v3.py:6685` | one tracker `append_row()` | upload parse/publish/load timing | Useful, but can add calls to already-slow paths. |
| `record_account_lifecycle_event()` | `reminders_app_v3.py:6725` | one tracker `append_row()` | signup/delete account | Low-volume. |
| `repair_account_lifecycle_sheet()` | `reminders_app_v3.py:6842` | account lifecycle `get_all_values()`, and if repair needed settings/user tracker `get_all_values()`, `batch_update()` | `ensure_tracking_sheets_once()` | Runs once per process/cache, but can be expensive when repair is needed. |
| `ensure_tracking_sheets_once()` | `reminders_app_v3.py:6877` | `spreadsheet.worksheets()`, each tracker `row_values(1)`, optional `update()` | logged-in app startup/session | Cached resource, but first logged-in session can touch every tracker sheet. |
| `authenticate_user()` | `reminders_app_v3.py:7069` | full `sheet.get_all_records()` | password login | P1 hot path as account count grows. |
| `authenticate_clinic_access()` | `reminders_app_v3.py:7081` | `get_clinic_row()` full `get_all_records()` | staff access login | Same scan as password login, then settings JSON parse. |
| `get_clinic_row()` | `reminders_app_v3.py:7089` | full `sheet.get_all_records()` | login, signup uniqueness, profile, delete, remember token | General full-scan lookup helper. |
| `get_clinic_row_by_google_identity()` | `reminders_app_v3.py:7100` | full `sheet.get_all_records()` | Google login/signup | Scans every account row to match Google identity. |
| `validate_remember_login_token()` | `reminders_app_v3.py:7142` | `get_clinic_row()` full scan | legacy remember-token handling | Current app discards remember query param, but helper remains a potential scan path. |
| `upsert_user_tracker()` | `reminders_app_v3.py:7246` | tracker `get_all_values()`, then `update()` or `append_row()` | login, signup, password change, settings save when `track_user=True` | Full User tracker scan on each call. |
| `record_settings_account_event()` | `reminders_app_v3.py:7293` | `update_settings_row_fields()` batch update after row discovery | login/session events | Often happens immediately after `load_settings()`, so row data can be reused. |
| `create_clinic_account()` | `reminders_app_v3.py:7320` | `get_clinic_row()` full scan, `sheet.get_all_values()`, `append_row()`, `upsert_user_tracker()`, lifecycle `append_row()` | password signup | Does a duplicate settings scan: one for uniqueness and one for headers. |
| `create_google_clinic_account()` | `reminders_app_v3.py:7361` | `get_clinic_row()` full scan, `get_clinic_row_by_google_identity()` full scan, `sheet.get_all_values()`, `append_row()`, user/lifecycle tracker writes | Google signup | Does three settings reads before writing. |
| `get_clinic_profile()` | `reminders_app_v3.py:7532` | `get_clinic_row()` full scan | profile dialog | Reads full settings sheet just to show current clinic profile. |
| `update_rows_with_clinic_id()` | `reminders_app_v3.py:7541` | `spreadsheet.worksheets()`, each worksheet `get_all_values()`, per-sheet `batch_update()` | clinic rename | Intentionally broad write. High cost but low-volume. |
| `update_clinic_profile()` | `reminders_app_v3.py:7570` | `get_clinic_row(new)`, `get_clinic_row(old)`, `update_settings_row_fields()`, optional full workbook scan for rename | profile save | Repeats full scans in one profile save. |
| `delete_rows_matching_clinic_id()` | `reminders_app_v3.py:7625` | worksheet `get_all_values()`, `client.batch_update()` or `delete_rows()` | delete account | Full worksheet scans are expected for account deletion. |
| `delete_clinic_account_and_data()` | `reminders_app_v3.py:7694` | `get_clinic_row()` full scan, `spreadsheet.worksheets()`, each worksheet full scan/delete, lifecycle append | delete account | Low-frequency but expensive. |
| `update_clinic_password()` | `reminders_app_v3.py:8127` | `_get_settings_row_for_clinic()`, `batch_update()` | change password | Uses one settings row lookup/update; password form first calls `authenticate_user()` full scan. |
| `update_clinic_access_code_hash()` | `reminders_app_v3.py:8149` | `get_authorized_fresh_settings_row_values()` then `update_authorized_settings_row_fields()` | clinic access admin | Reads fresh row then updates settings JSON. |
| `finish_authenticated_session()` | `reminders_app_v3.py:8210` | calls `load_settings()`, `load_shared_dataset_for_clinic()`, `record_settings_account_event()`, `upsert_user_tracker()` | Google/staff login | One of the densest post-auth call chains. |
| `load_shared_dataset_for_clinic()` | `reminders_app_v3.py:3277` | fresh settings row read; fallback full settings records; optional tracker appends | login/session dataset load | Also does Drive download, outside this Sheets pass. |
| `get_existing_dataset_pointer()` | `reminders_app_v3.py:3643` | `_get_settings_row_for_clinic()`, `ensure_settings_sheet_columns()`, `row_values()` | upload save/remove/clear | Single row read after cache warm, but repeated around publish. |
| `update_clinic_dataset_pointer()` | `reminders_app_v3.py:3576` | `update_settings_row_fields()` then `get_authorized_fresh_settings_row_values()` | upload publish/remove | Writes pointer, then reads row back to verify. |
| `publish_dataset_for_clinic()` | `reminders_app_v3.py:4006` | dataset tracker append start/success/error; settings pointer update | upload save/remove | Drive-heavy plus tracker writes. |
| `remove_dataset_upload_at_index()` | `reminders_app_v3.py:9185` | pointer read, possible pointer clear/update, `save_settings_quietly()`, dataset tracker append | removing uploaded CSV range | Repeats pointer/settings reads. |
| Reminder actions | `reminders_app_v3.py:11098`, `11120`, `11167`, `11182` | single `append_row()` for sent/declined/undo; `append_rows()` for send-all; undo also `save_settings_quietly()` | reminder action buttons | Send-all already batches Action tracker writes. |
| `refresh_outcome_results_state()` | `reminders_app_v3.py:14560` | normally no Sheets; if pending search changes then `apply_search_criteria_changes()` can save settings; if `sync_remote=True`, full action tracker read and possible shared dataset load | Stats refresh | Current button calls without `sync_remote`, so normal refresh should not scan Sheets. |

## 2. Flow Map

### App Startup

Before login, the app does not normally touch Google Sheets unless a Google OIDC session is already active. It reads Google identity state, discards legacy remember-login query params, and renders login UI.

If a Google session is active and the user is not logged in, `get_clinic_row_by_google_identity()` runs a full settings-sheet read. If a row is found, `finish_authenticated_session()` runs the post-login chain.

Expected improved calls: no change before login; for Google-returning users, replace the full settings scan with a reusable indexed lookup or a single shared settings scan reused by session setup.

Behavior risk: low if only reusing the row found in the same flow; medium if adding a new index.

### Password Login

Current calls:

- `authenticate_user()` reads all settings records.
- `load_settings()` then finds/loads the settings row and cold-loads Action tracker records.
- `load_shared_dataset_for_clinic()` reads the settings row again to get dataset pointer.
- `record_settings_account_event()` updates account metadata in Settings.
- `upsert_user_tracker()` reads all User tracker rows, then updates/appends one row.

Repeated full reads: settings full scan for auth, then settings row discovery/read during settings load, plus full Action tracker read.

Expected improved calls: authenticate and load settings should share one settings row payload; Action tracker load should be lazy or split into a compact current-action index for login.

Behavior risk: low for row reuse, medium for action-tracker lazy loading.

### Staff Access Login

Current calls:

- `authenticate_clinic_access()` calls `get_clinic_row()` full settings read.
- `finish_authenticated_session()` then runs the same post-login chain as Google login.

Repeated full reads: same as password login, except auth verifies a code stored inside SettingsJSON.

Expected improved calls: reuse the matched row from `authenticate_clinic_access()` in session setup.

Behavior risk: low if authorization checks remain unchanged.

### Google Login

Current calls:

- `get_clinic_row_by_google_identity()` full settings read.
- `finish_authenticated_session()` loads settings, shared dataset, settings account event, and User tracker.

Repeated full reads: the Google identity row is found, then the settings row is rediscovered/read in `load_settings()`.

Expected improved calls: pass/cache the found row and row index from Google lookup into `load_settings()`.

Behavior risk: low if the cached row is used only for that authenticated clinic.

### Password Signup

Current calls:

- `create_clinic_account()` calls `get_clinic_row()` full settings read for uniqueness.
- Reads `sheet.get_all_values()` again for headers.
- Appends settings row.
- Calls `upsert_user_tracker()` full User tracker read then update/append.
- Appends Account lifecycle event.
- Login continuation calls `load_settings()`.

Repeated full reads: uniqueness and headers both scan settings.

Expected improved calls: one settings `get_all_values()` can validate uniqueness and provide headers.

Behavior risk: low.

### Google Signup

Current calls:

- `create_google_clinic_account()` calls `get_clinic_row()` full settings read.
- Calls `get_clinic_row_by_google_identity()` full settings read.
- Calls `sheet.get_all_values()` for headers.
- Appends settings row.
- Calls `upsert_user_tracker()` and Account lifecycle tracker append.

Repeated full reads: three settings reads in one sign-up action.

Expected improved calls: one settings `get_all_values()` can check clinic id, Google email/subject, and headers.

Behavior risk: low-to-medium because uniqueness checks are auth-sensitive; add regression tests before changing.

### Profile Save

Current calls:

- Profile dialog display uses `get_clinic_profile()` -> `get_clinic_row()` full scan.
- `update_clinic_profile()` reads `get_clinic_row(new_clinic_id)` and `get_clinic_row(old_clinic_id)`.
- It writes settings fields.
- If clinic id changes, `update_rows_with_clinic_id()` scans every worksheet and batch-updates matching ClinicID cells.
- Dialog then calls `load_settings()`.

Repeated full reads: the old clinic row is scanned more than once, and profile display/save do not share row state.

Expected improved calls: profile save can reuse the old row and only do a second lookup when the clinic id is changing.

Behavior risk: medium because clinic rename touches multiple sheets.

### Delete Account

Current calls:

- `delete_clinic_account_and_data()` calls `get_clinic_row()` full settings read.
- Scans all worksheets with `get_all_values()` and deletes matching rows.
- Trashes Drive dataset if present.
- Appends Account lifecycle event.

Repeated full reads: full settings read before scanning all worksheets. This is less important because delete-account is rare and intentionally broad.

Expected improved calls: not a top optimization target. Keep broad scan until tests cover account deletion thoroughly.

Behavior risk: high. Do not optimize first.

### Upload Save

Current calls:

- Upload parse failure/success may append Dataset, Error, and Performance tracker rows.
- Before saving, `get_existing_dataset_pointer()` reads settings row.
- Existing dataset may be downloaded from Drive.
- `publish_dataset_for_clinic()` appends Dataset tracker start event.
- `update_clinic_dataset_pointer()` batch-updates pointer fields, then reads the settings row again to verify.
- `publish_dataset_for_clinic()` appends Dataset tracker success or error.
- `save_uploaded_dataset()` loops over saved upload summary rows and appends one Dataset tracker row per file.
- It appends Performance tracker success.
- `save_settings_quietly()` reads remote settings and writes SettingsJSON.

Repeated reads: settings pointer read before publish, settings row read after pointer update, and remote settings read during `save_settings_quietly()`.

Batchable writes: per-file `upload_saved` Dataset tracker rows can use `append_tracker_rows()`.

Expected improved calls: batch per-file tracker writes; reuse pointer row data where safe; consider making pointer verification optional only after a successful batch update test proves consistency.

Behavior risk: low for tracker batching, medium for pointer verification changes.

### Reminder Refresh

Current calls:

- Normal reminder rendering uses session state and DataFrames, not Sheets.
- If reminder search/filter settings are changed, `apply_search_criteria_changes()` can save settings.
- Sending or declining one reminder appends one Action tracker row.
- Send-all uses `append_tracker_rows()`.
- Undo appends an Action tracker row and saves settings.

Repeated reads: not usually from refresh itself. Settings saves can still read remote settings.

Expected improved calls: no first target beyond settings-save improvements.

Behavior risk: low for preserving existing action writes.

### Statistics Tab

Current calls:

- Normal render reads from session DataFrames/action history and should not call Sheets.
- `Refresh Stats` calls `refresh_outcome_results_state()` with `sync_remote=False`, so it clears local caches and recalculates.
- If pending search changes exist, it applies/saves them.
- If called with `sync_remote=True`, it invalidates and fully reloads Action tracker records and may reload the shared dataset.

Repeated reads: only with pending search saves or remote sync.

Expected improved calls: keep normal refresh local; if adding a remote-sync option later, show it as explicit “Sync saved actions” because it can scan the Action tracker.

Behavior risk: low.

### Action Tracker Load

Current calls:

- `load_action_tracker_records_for_clinic()` cold path reads all Action tracker values and filters by ClinicID in Python.
- Cache key includes clinic and timezone, so changing timezone/user session can reload.
- Appending to Action tracker invalidates this cache.

Repeated full reads: login loads tracker through `load_settings()`, then stats remote sync can reload after invalidation.

Expected improved calls: split current action state from full history, or use an action tracker index/partition per clinic. This is a big win but needs tests first.

Behavior risk: medium-to-high because reminders, outcomes, and actioned reminders rely on action history semantics.

### Settings Save / Autosave

Current calls:

- `_get_settings_row_for_clinic()` full scan on row-cache miss.
- `read_remote_settings_for_save()` reads one row when `refresh_remote=True`.
- Existing row write uses `batch_update()` for SettingsJSON/UpdatedAt.
- If country is present, a second `update_settings_row_fields()` batch update writes Country/AccountStatus.
- If `track_user=True`, `upsert_user_tracker()` scans User tracker and updates/appends.

Repeated reads/writes: row lookup plus row read; two settings batch updates in some saves.

Expected improved calls: combine settings JSON and metadata in one batch update; add no-op guard for unchanged settings; use `track_user=False` for autosaves unless a real user-tracker event is required.

Behavior risk: medium because merge-on-save protects multi-user settings edits.

## 3. Repeated Full-Sheet Reads In The Same Flow

| Flow | Repeated reads | Current API calls | Expected improved API calls | Behavior risk | Smallest safe fix |
| --- | --- | --- | --- | --- | --- |
| Password login | `authenticate_user()` full settings records, then `load_settings()` row discovery/read, then full Action tracker | 1 full settings records + 0/1 full settings values + 1 row read + 1 full Action tracker + User tracker full scan | 1 settings row lookup shared into `load_settings()`; defer or avoid full Action tracker on login | Medium | Return row metadata from auth helper and pass/cache it before `load_settings()`. |
| Staff access login | `get_clinic_row()` full settings records, then post-login settings/action reads | 1 full settings records + post-login chain | Shared row + post-login row reuse | Low | Cache matched clinic row after access-code verification. |
| Google login | `get_clinic_row_by_google_identity()` full records, then post-login row discovery/read | 1 full settings records + post-login chain | Shared row + post-login row reuse | Low | Have Google lookup cache row/index for the authenticated clinic. |
| Password signup | `get_clinic_row()` full records, then `sheet.get_all_values()` for headers | 2 settings reads before append | 1 `get_all_values()` for uniqueness and headers | Low | Replace uniqueness helper call with a single local scan in create flow. |
| Google signup | `get_clinic_row()`, `get_clinic_row_by_google_identity()`, `sheet.get_all_values()` | 3 settings reads before append | 1 `get_all_values()` for clinic id, Google identity, and headers | Low-medium | Single helper that validates both uniqueness rules from one values snapshot. |
| Profile save | profile display full scan, new id scan, old id scan, possible all-worksheet scans | 2-3 settings full scans plus rename scan | Reuse current profile row; only lookup new id if changed | Medium | Pass old profile row into save flow or cache it in session with clinic key. |
| Upload save | pointer row read before publish, pointer update then fresh read verification, settings save row read | 2-3 settings row reads plus tracker appends | 1 pointer row read + 1 update; keep verification only if needed | Medium | First safe patch is tracker batching, not pointer verification removal. |
| Tracker first use | `ensure_tracking_sheets_once()` checks tracker headers, then `get_or_create_tracker_sheet()` checks header again | worksheets list + header row per tracker, then header row again per tracker used | cache worksheet handles/headers during ensure | Low | Populate `_tracker_sheet_cache` from `ensure_tracking_sheets_once()`. |

## 4. Reads Reusable Within One User Action

- The row returned by `authenticate_user()`, `authenticate_clinic_access()`, and `get_clinic_row_by_google_identity()` can be reused by `load_settings()` and `record_settings_account_event()` in the same login action.
- The settings `get_all_values()` snapshot in password and Google signup can be reused for uniqueness checks and header generation.
- The old clinic row used by `get_clinic_profile()` can be reused by `update_clinic_profile()` if the profile dialog remains open for the same clinic.
- The dataset pointer from `get_existing_dataset_pointer()` can be passed through the upload publish/clear/remove flow. This is already partly done in `publish_dataset_for_clinic()`, but the pointer update path still does a fresh verification read.
- The Action tracker values loaded during `load_settings()` can be reused by the Stats tab until invalidated by an Action tracker append.
- Tracker worksheet/header checks performed by `ensure_tracking_sheets_once()` can populate the same cache used by `get_or_create_tracker_sheet()`.

## 5. Writes That Can Be Batched

- Upload-save per-file `upload_saved` Dataset tracker rows are written in a loop with `record_dataset_tracker_event()`; these can be converted to a single `append_tracker_rows()` call.
- Settings JSON and Country/AccountStatus writes in `save_settings()` can be combined into one `batch_update()` for existing rows.
- Multiple settings audit events triggered by bulk edits could be appended with `append_tracker_rows()` if the UI supports grouped edits.
- Account deletion already batches row deletion through spreadsheet `client.batch_update()` when available; keep this.
- Send-all reminders already uses `append_tracker_rows()`; no change needed there.

## 6. Top 5 Safest Changes To Reduce Google API Calls

### 1. Batch upload saved tracker rows

- Function/location: `save_uploaded_dataset()` inside upload handling at `reminders_app_v3.py:10841`.
- Current API calls: one Dataset tracker `append_row()` per saved upload summary row.
- Expected improved API calls: one Dataset tracker `append_rows()` for all summary rows.
- Behavior risk: low. Tracker rows are append-only diagnostics.
- Smallest safe fix: add a helper that builds Dataset tracker row values and uses `append_tracker_rows()` for the loop.
- Tests needed: fake tracker worksheet that asserts one `append_rows()` call for multiple files and identical row content.

### 2. Reuse settings row found during login

- Function/location: `authenticate_user()` at `reminders_app_v3.py:7069`, `authenticate_clinic_access()` at `7081`, `get_clinic_row_by_google_identity()` at `7100`, `load_settings()` at `4346`.
- Current API calls: full settings scan during auth, then row discovery/read during `load_settings()`.
- Expected improved API calls: one settings read in the login action before shared dataset load.
- Behavior risk: low-to-medium. Must preserve password and tenant checks.
- Smallest safe fix: when an auth helper finds a row, store a short-lived `_settings_row_cache` payload or return row metadata to `finish_authenticated_session()`.
- Tests needed: password login and staff access fake-sheet tests proving one settings scan and unchanged auth failure behavior.

### 3. Collapse duplicate sign-up scans

- Function/location: `create_clinic_account()` at `reminders_app_v3.py:7320`, `create_google_clinic_account()` at `7361`.
- Current API calls: password signup does two settings reads; Google signup does three settings reads before append.
- Expected improved API calls: one settings `get_all_values()` before append.
- Behavior risk: low for password signup, medium for Google signup because identity uniqueness is security-sensitive.
- Smallest safe fix: create a helper that reads settings values once and validates ClinicID and Google identity from that snapshot.
- Tests needed: duplicate clinic, duplicate Google email/subject, successful signup, and call-count assertions.

### 4. Populate tracker sheet cache during tracking-sheet ensure

- Function/location: `ensure_tracking_sheets_once()` at `reminders_app_v3.py:6877`, `get_or_create_tracker_sheet()` at `6486`.
- Current API calls: first logged-in run reads tracker headers; later first append/load for each tracker may read the same header again.
- Expected improved API calls: zero extra header reads for tracker sheets already verified during ensure.
- Behavior risk: low.
- Smallest safe fix: write verified worksheets into `st.session_state["_tracker_sheet_cache"]` with the same key used by `get_or_create_tracker_sheet()`.
- Tests needed: fake spreadsheet that ensures `row_values(1)` is not called again after ensure for a tracker append.

### 5. Combine existing-row settings updates in `save_settings()`

- Function/location: `save_settings()` at `reminders_app_v3.py:4593`.
- Current API calls: one settings `batch_update()` for SettingsJSON/UpdatedAt, then another `batch_update()` through `update_settings_row_fields()` when country is set.
- Expected improved API calls: one settings `batch_update()` for JSON, UpdatedAt, Country, and AccountStatus.
- Behavior risk: medium. Settings merge logic is important for multi-user safety.
- Smallest safe fix: extend `_update_settings_cells()` to accept optional metadata fields and update cached row values after one batch.
- Tests needed: save with country set writes same final row with one batch call; no regression in dirty-key handling.

## 7. Tests Needed To Prove Call Count Reduction

Add tests before or with each patch:

- `tests/test_ci_google_sheets_call_counts.py` with fake worksheet/spreadsheet classes that count `get_all_records`, `get_all_values`, `row_values`, `append_row`, `append_rows`, `update`, and `batch_update`.
- Password login characterization: successful login should not require a second full settings scan after auth once row reuse is implemented.
- Staff access characterization: valid and invalid access codes preserve behavior and count settings reads.
- Google signup characterization: duplicate ClinicID and duplicate Google identity are detected from one settings snapshot.
- Upload tracker batching: multiple upload summary rows produce one `append_rows()` call and no per-row `append_row()` calls.
- Tracker cache characterization: `ensure_tracking_sheets_once()` followed by `record_dataset_tracker_event()` should not re-read the header row for the same worksheet.
- `save_settings()` characterization: final settings row values are unchanged while batch-update count is reduced.
- Negative tests for stale cache: if cached clinic key does not match current clinic, code must still read the correct row.

## 8. Exact Validation Commands

Existing commands to run after a Sheets-call patch:

```bash
python -m py_compile reminders_app_v3.py settings_pointer_utils.py
python -m unittest discover -s tests -p "test_ci_*.py"
bash scripts/pre_merge_check.sh
python -m pip check
```

Useful targeted commands if adding call-count tests:

```bash
python -m unittest tests.test_ci_google_sheets_call_counts
python -m unittest tests.test_ci_auth_session tests.test_ci_settings_save_state tests.test_ci_dataset_update
```

Release-oriented validation, when credentials and environment are available:

```bash
bash scripts/pilot_release_check.sh
```

Manual validation checklist:

- Password login succeeds and loads saved settings/data.
- Staff access login succeeds with a valid code and fails with an invalid code.
- Google login finds the linked clinic.
- Password signup rejects duplicate clinic names.
- Google signup rejects duplicate Google-linked accounts.
- Uploading multiple CSVs saves once and creates expected Dataset tracker rows.
- Stats and Reminders still show actioned/sent reminders after a fresh login.

## 9. Recommended Patch Order

1. Add fake Google Sheets call-count tests for auth, signup, upload tracker, and save settings.
2. Batch upload `upload_saved` Dataset tracker rows.
3. Populate tracker worksheet cache from `ensure_tracking_sheets_once()`.
4. Collapse password signup duplicate settings reads.
5. Collapse Google signup duplicate settings reads.
6. Reuse authenticated settings rows during password/staff/Google login.
7. Combine existing-row settings JSON and metadata writes in `save_settings()`.
8. Defer or split Action tracker full reads from `load_settings()`.

The last item is likely the biggest user-visible win for login latency, but it should not be first because Action tracker semantics affect reminders, actioned reminders, warnings, and stats.
