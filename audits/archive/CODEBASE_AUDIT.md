# Codebase Audit

Date: 2026-05-17

Scope: static inspection of the repository plus current local verification commands. This audit does not fix application code.

## Executive summary

ClinicReminders is a Streamlit application that turns uploaded veterinary sales exports into reminder workflows. It normalizes PMS exports, persists each clinic's dataset in Google Drive, stores clinic settings and trackers in Google Sheets, generates active/actioned reminder tables, prepares WhatsApp message text, and shows setup/statistics views.

The main engineering risk is concentration: `reminders_app_v3.py` is about 10,975 lines and contains UI, auth, Google I/O, ETL, persistence, reminder rules, analytics, and dormant admin/export code. The app has meaningful tests for important helper behavior, but no true end-to-end tests around login, upload, Drive/Sheets failure modes, or Streamlit UI flows.

The most urgent concerns are security and data isolation around long-lived remember-login tokens in query params, hard-coded Google resource IDs, all-clinic service-account access, account update/delete operations across every worksheet, and user-provided strings rendered with `unsafe_allow_html=True` in several places. Reliability risks cluster around Google API retries/timeouts, partial multi-step writes, broad cache/state invalidation, and several hidden/dead blocks that are still imported and parsed.

## 1. App purpose inferred from code

The app is a clinic reminder tool for veterinary practices. It:

- Accepts CSV/XLS/XLSX sales exports from supported PMS systems.
- Normalizes those exports into a canonical dataframe with dates, clients, animals, item names, quantity, and amount.
- Saves the active clinic dataset to Google Drive and stores a pointer in a Google Sheet.
- Lets clinics configure reminder search terms, reminder intervals, exclusions, sender name, and WhatsApp template.
- Generates reminder rows, grouped by client/window when configured.
- Lets users prepare WhatsApp copy, mark reminders sent, decline reminders, and undo actioned reminders.
- Tracks action, settings, dataset, error, performance, and user events in Google Sheets.
- Shows setup progress and statistics for generated/actioned reminders.

Evidence:

- Branding copy describes "Turn sales data into clear follow-up reminders and prepare WhatsApp messages" in `reminders_app_v3.py:193`.
- Main tabs are `Reminders`, `Get Started`, `Upload Data`, `Search Terms`, `Exclusions`, and `Statistics` in `reminders_app_v3.py:59`.
- Upload, reminder, action, statistics, settings, and tracker helpers are all in `reminders_app_v3.py`.

## 2. Main entry points

- `reminders_app_v3.py`: Streamlit app entry point. Run with `python -m streamlit run reminders_app_v3.py`.
- `settings_pointer_utils.py`: small helper module for batching dataset pointer writes.
- `.github/workflows/ci.yml`: GitHub Actions entry point for compile and CI unit tests.
- `scripts/pre_merge_check.sh`: small local pre-merge helper for pointer-related tests.
- Tests under `tests/`, especially `test_ci_*.py`, are the current automated confidence suite.

There are no Flask/FastAPI routes, package entry points, CLI commands, Celery jobs, or background worker definitions.

## 3. Routes, screens, API handlers, jobs, or commands

Streamlit screens:

- Login/sign-up screen: password login, Google login, manual sign-up in `reminders_app_v3.py:5507`.
- Account popover: profile, data/privacy, password change, delete account, logout in `reminders_app_v3.py:5611`.
- Get Started tab: six-step setup checklist in `reminders_app_v3.py:7060`.
- Upload Data tab: upload files, saved dataset summary, clear clinic data in `reminders_app_v3.py:7065`.
- Reminders tab: sender name, date/window/group controls, active/actioned reminder tables, WhatsApp composer in `reminders_app_v3.py:9061`.
- Search Terms tab: add/edit/delete reminder matching rules in `reminders_app_v3.py:8755`.
- Exclusions tab: client, patient, and item exclusions in `reminders_app_v3.py:9209`.
- Statistics tab: overview/team/items/completion tabs in `reminders_app_v3.py:8638`.

Dormant screens/features:

- Factoids analytics block is hidden behind `if False` in `reminders_app_v3.py:9411`.
- Admin account tools are hidden behind `if False` in `reminders_app_v3.py:10721`.
- Admin keyword debugging and quarterly LLM export are hidden behind `if False` in `reminders_app_v3.py:10772`.
- Feedback helpers exist, but feedback UI is noted as hidden around `reminders_app_v3.py:10714`.

External API handlers:

- Google Sheets access through `gspread`.
- Google Drive access through `google-api-python-client`.
- Google login through Streamlit OIDC / Authlib.
- No internal HTTP API handlers are present.

## 4. Data models and storage

Primary in-memory models:

- Canonical sales dataframe in `st.session_state["working_df"]`.
- Prepared reminders dataframe from `get_prepared_df` in `reminders_app_v3.py:6758`.
- Reminder rules in `st.session_state["rules"]`, seeded by `DEFAULT_RULES` in `reminders_app_v3.py:1826`.
- Deleted/actioned reminders in `st.session_state["deleted_reminders"]`.
- Recent WhatsApp reminder log in `st.session_state["wa_reminder_log"]`.
- Dataset upload history in `st.session_state["dataset_upload_history"]`.

Persistent Google Sheets models:

- Settings worksheet columns include clinic ID, password hash, JSON settings, dataset pointer, Google identity, country, login metadata, and account status in `reminders_app_v3.py:201`.
- Settings JSON includes rules, exclusions, sender/template settings, reminder windows, setup flags, upload history, country, and migration state in `reminders_app_v3.py:3099`.
- Tracker worksheets: user, action, dataset, settings audit, error, and performance trackers in `reminders_app_v3.py:271`.
- Action tracker rows include clinic ID, actor, action, client, animals, items, dates, message, source, and reminder key in `reminders_app_v3.py:251`.

Persistent Google Drive models:

- One saved CSV dataset per clinic, named like `<clinic_id>_shared_dataset.csv`, under a hard-coded Drive folder ID in `reminders_app_v3.py:198`.
- Dataset pointer fields are stored back to the settings sheet.

## 5. External services and dependencies

Runtime services:

- Google Sheets for settings, account rows, and trackers.
- Google Drive for saved clinic datasets.
- Google OIDC via Streamlit `st.login("google")`.
- Optional feedback Google Sheet.

Dependencies from `requirements.txt`:

- `streamlit==1.56.0`
- `pandas`, `numpy`, `altair`, `openpyxl`
- `gspread`, `oauth2client`
- `google-api-python-client`, `google-auth`, `google-auth-httplib2`, `google-auth-oauthlib`
- `authlib==1.6.11`, `httpx==0.27.2`
- `chardet`

Notable configuration files:

- `.streamlit/secrets.example.toml` documents OIDC secrets.
- `GOOGLE_AUTH_SETUP.md` documents Google sign-up configuration.

## 6. Auth, session, and permission model

Password auth:

- Clinic ID plus password against the settings sheet in `authenticate_user` at `reminders_app_v3.py:4513`.
- New password hashes use PBKDF2-SHA256 with 260,000 iterations in `reminders_app_v3.py:4420`.
- Legacy MD5 hashes are still accepted in `verify_password` at `reminders_app_v3.py:4433`.

Google auth:

- Streamlit `st.login("google")` starts OIDC login in `reminders_app_v3.py:4492`.
- Google identity is matched by subject or email in `google_identity_matches_row` at `reminders_app_v3.py:4504`.
- Google-created clinics store Google email, subject, name, and auth provider fields in `reminders_app_v3.py:4774`.

Remember-login:

- A base64 JSON token is stored in the URL query param `remember` in `reminders_app_v3.py:4564` and `reminders_app_v3.py:4630`.
- Default validity is 3650 days in `reminders_app_v3.py:1873`.
- Token signature is derived from the clinic ID, expiry, and password hash in `reminders_app_v3.py:4546`.

Authorization model:

- The app relies on the active `st.session_state["clinic_id"]`.
- All Google Sheets and Drive operations use a service account with broad app-level access.
- Object-level isolation is implemented in application code by filtering/matching clinic IDs and dataset pointers.
- There is no separate role/permission model for normal users versus admins in active UI. Admin blocks are currently disabled with `if False`.

## 7. Trust boundaries

Important trust boundaries:

- Browser/user input to Streamlit: login forms, sign-up forms, profile edits, search rules, exclusions, sender name, WhatsApp template, date/window controls.
- File upload boundary: CSV/XLS/XLSX files parsed into pandas and later saved to Drive.
- Google OIDC boundary: `st.user` identity fields are trusted after Streamlit login.
- Google Sheets boundary: settings and tracker rows are treated as authoritative and are mutable by the service account.
- Google Drive boundary: saved datasets are loaded by file ID/pointer and treated as clinic data.
- Rendered HTML boundary: many UI snippets use `unsafe_allow_html=True`, so user-controlled strings must be escaped before insertion.
- URL boundary: remember-login token is carried in query params and therefore can appear in browser history, screenshots, logs, referrers, or shared URLs.

## 8. Configuration and environment variables

Hard-coded configuration:

- `DATASETS_FOLDER_ID` is hard-coded in `reminders_app_v3.py:198`.
- `SETTINGS_SHEET_ID` is hard-coded in `reminders_app_v3.py:1871`.
- `FEEDBACK_SHEET_ID` is hard-coded in `reminders_app_v3.py:10656`.
- `DEV_AUTO_LOGIN` is hard-coded false in `reminders_app_v3.py:1881`.

Secrets/config expected at runtime:

- `st.secrets["gcp_service_account"]` for Google Drive/Sheets in `reminders_app_v3.py:1892` and `reminders_app_v3.py:4205`.
- Fallback local file `google-credentials.json` in `reminders_app_v3.py:1895` and `reminders_app_v3.py:4207`.
- Streamlit auth secrets documented in `.streamlit/secrets.example.toml`.

Environment variables:

- No direct `os.environ` reads were found during inspection.

## 9. Test coverage summary

Current tests:

- 12 test files, 64 CI-discovered tests under `tests/test_ci_*.py`.
- Covered areas include auth/session helpers, password hashing and legacy MD5 compatibility, Google identity normalization/matching, settings row values, account deletion row ordering, dataset merge/update history, reminder grouping/exclusions, reminders badge behavior, settings save merge behavior, action tracker behavior, and statistics helper outputs.
- Non-CI helper tests cover settings pointer batching wrappers.

Current gaps:

- No browser/UI automation for Streamlit flows.
- No integration tests against mocked Google Drive and Google Sheets workflows end to end.
- No tests for Google API quota/retry timing beyond a quiet settings-save error path.
- No upload tests for realistic multi-file workbook edge cases across every supported PMS.
- No security tests for query-param remember token handling, unauthorized clinic switching, or account deletion boundaries.
- No performance regression harness for large datasets.
- No lint/type/static-security/vulnerability audit in CI.

Verification run during this audit:

- `python -m py_compile reminders_app_v3.py`: passed.
- `python -m unittest discover -s tests -p "test_ci_*.py"`: passed, 64 tests. Existing `datetime.utcnow()` deprecation warnings were emitted.
- `python -m pip check`: passed.

## 10. Build, lint, typecheck, and test commands

Documented or working:

- Run app: `python -m streamlit run reminders_app_v3.py`
- Compile app: `python -m py_compile reminders_app_v3.py`
- Compile app and helper: `python -m py_compile reminders_app_v3.py settings_pointer_utils.py`
- CI tests: `python -m unittest discover -s tests -p "test_ci_*.py"`
- Full local discover: `python -m unittest discover -s tests`
- Pointer helper checks: `bash scripts/pre_merge_check.sh`
- Dependency consistency: `python -m pip check`

Missing:

- No formatter command.
- No lint command.
- No typecheck command.
- No production build command, because this is a Streamlit app.
- No dependency vulnerability audit command.
- No static security scan command.
- No end-to-end test command.

## 11. Top 20 risks ranked P0 to P3

### P0-1: Remember-login token is long-lived and stored in the URL

Evidence: `REMEMBER_LOGIN_DAYS = 3650` at `reminders_app_v3.py:1873`; token is read/written through query params at `reminders_app_v3.py:4564` and `reminders_app_v3.py:4630`.

Why it matters: URLs are commonly copied, logged, screenshotted, and included in browser history. A ten-year bearer-style login token can become account access if exposed.

Suggested fix: Move remember-login to a secure cookie/session mechanism if Streamlit supports it, shorten lifetime, add rotation/revocation, and clear query params immediately after use.

Validation plan: Add tests for token expiry, rotation on password change, query-param clearing, and invalid token rejection.

Split? Separate security PR.

### P0-2: All clinic data is protected mainly by app-level filtering over broad Google service-account access

Evidence: service account opens one settings spreadsheet in `reminders_app_v3.py:4202`; account/data operations scan every worksheet in `delete_clinic_account_and_data` at `reminders_app_v3.py:5021`.

Why it matters: A bug in clinic ID matching, profile rename, delete, or pointer handling can cross tenant boundaries.

Suggested fix: Add explicit tenant-boundary helpers and tests for every cross-worksheet operation before changing behavior.

Validation plan: Mock worksheets containing multiple clinics and verify update/delete/load paths only touch the active clinic.

Split? Separate security/data-isolation PR.

### P1-1: Hard-coded production Google resource IDs

Evidence: dataset folder ID in `reminders_app_v3.py:198`; settings sheet ID in `reminders_app_v3.py:1871`; feedback sheet ID in `reminders_app_v3.py:10656`.

Why it matters: Dev/prod separation, secret rotation, and accidental writes to production are harder.

Suggested fix: Move IDs into Streamlit secrets with clear local examples and validation errors.

Validation plan: Unit-test config loading fallback and missing-config messages.

Split? Safe as a small config PR if defaults are preserved during migration.

### P1-2: Monolithic 10,975-line app file with mixed concerns

Evidence: `reminders_app_v3.py` contains 308 functions/classes and all UI/auth/ETL/persistence/statistics logic.

Why it matters: Small fixes require understanding unrelated code, making regressions more likely.

Suggested fix: Extract one low-risk module at a time, starting with pure helpers that already have tests.

Validation plan: Characterization tests before each extraction; run CI tests after each PR.

Split? Must be split into many small PRs.

### P1-3: User-controlled strings are rendered with `unsafe_allow_html=True` in active screens

Evidence: repeated `unsafe_allow_html=True`; examples include rule names at `reminders_app_v3.py:8979`, client exclusions at `reminders_app_v3.py:9221`, patient exclusions at `reminders_app_v3.py:9287`, and item exclusions at `reminders_app_v3.py:9355`.

Why it matters: Any unescaped user-controlled value inserted into raw HTML can become XSS in Streamlit.

Suggested fix: Audit each active unsafe markdown call and escape all interpolated user-controlled strings or replace with safe Streamlit elements.

Validation plan: Add tests for HTML escaping helpers and manually verify malicious strings render as text.

Split? Separate security PR.

### P1-4: Partial write and recovery risk in multi-step Google mutations

Evidence: dataset publish uploads Drive CSV, updates settings pointer, updates session state/history, records trackers, and saves settings across multiple calls around `reminders_app_v3.py:2699` and `reminders_app_v3.py:7274`.

Why it matters: Network failure between steps can leave Drive data, settings pointer, upload history, and UI state inconsistent.

Suggested fix: Document state machine, make operations idempotent, and add repair/retry tests before refactoring.

Validation plan: Mock failures after each external call and assert recoverable state.

Split? Separate reliability PR.

### P1-5: Password login still accepts legacy MD5 hashes

Evidence: `hash_pw` returns MD5 in `reminders_app_v3.py:4415`; `verify_password` falls back to MD5 in `reminders_app_v3.py:4453`.

Why it matters: Legacy hashes are weak if the settings sheet is exposed.

Suggested fix: On successful legacy login, transparently rehash to PBKDF2 and track remaining legacy rows.

Validation plan: Add regression tests for migration and legacy compatibility until removed.

Split? Separate auth-hardening PR.

### P1-6: Account delete operates across all worksheets

Evidence: `delete_clinic_account_and_data` loops through every worksheet and deletes matching clinic IDs in `reminders_app_v3.py:5021`.

Why it matters: This is intentionally powerful and could delete wrong tenant data if clinic ID normalization or profile rename state is wrong.

Suggested fix: Add a dry-run/delete plan helper and tests before performing deletion.

Validation plan: Mock worksheets with near-match clinic IDs, case variants, and missing headers.

Split? Separate safety PR.

### P1-7: External API calls lack explicit timeouts and many broad exception catches hide failure details

Evidence: Google client calls rely on library defaults; tracker append helpers catch `Exception` and return false in `reminders_app_v3.py:4240`.

Why it matters: UI can hang or silently lose audit/error/performance events.

Suggested fix: Centralize Google calls, add bounded retries/timeouts where supported, and surface structured warnings for critical failures.

Validation plan: Mock slow/failing Google calls and assert user-visible warnings or retry behavior.

Split? Separate reliability PR.

### P1-8: File upload parsing can handle large files synchronously in the Streamlit request path

Evidence: upload processing and publish happen directly in the Upload Data tab around `reminders_app_v3.py:7097` and `reminders_app_v3.py:7249`.

Why it matters: Large workbooks can freeze the UI and increase rerun instability.

Suggested fix: Add size/row limits, clearer progress, and performance tests before deeper async/background work.

Validation plan: Characterize runtime on representative large files.

Split? Separate performance PR.

### P1-9: No end-to-end tests for the core clinic workflow

Evidence: unit tests cover helpers, but there is no Playwright/Selenium/Streamlit test suite.

Why it matters: Login, upload, reminder action, and settings persistence are where regressions are most user-visible.

Suggested fix: Add one smoke E2E or Streamlit app-test path with mocked external services.

Validation plan: CI runs the smoke path without real Google credentials.

Split? Separate test-infrastructure PR.

### P1-10: Dormant admin/export code remains in the main runtime file

Evidence: disabled blocks at `reminders_app_v3.py:9411`, `reminders_app_v3.py:10721`, and `reminders_app_v3.py:10772`.

Why it matters: Disabled code still adds parse/import risk, dependencies, cognitive load, and possible accidental reactivation.

Suggested fix: Move dormant code to archival docs or separate guarded modules after verifying no active references.

Validation plan: Compile and test after extraction; confirm no behavior change.

Split? Safe as one or more cleanup PRs.

### P2-1: Deprecated `datetime.utcnow()` is used broadly

Evidence: current test run emits deprecation warnings at several lines, including `reminders_app_v3.py:3123`, `reminders_app_v3.py:3353`, `reminders_app_v3.py:4325`, `reminders_app_v3.py:7535`, and `reminders_app_v3.py:7552`.

Why it matters: Future Python versions may require changes; timezone semantics are already easy to mix up.

Suggested fix: Add a small UTC helper and replace call sites incrementally.

Validation plan: Date/time tests around tokens, trackers, and reminder periods.

Split? Safe as a focused cleanup PR after tests.

### P2-2: Cache/state invalidation is broad and implicit

Evidence: `reset_uploaded_data_state` can clear all Streamlit cache data in `reminders_app_v3.py:369`; several session keys invalidate data versions manually.

Why it matters: Broad clears can cause slow reruns and stale-state bugs.

Suggested fix: Create named version keys per data product and avoid global cache clears except for explicit reset.

Validation plan: Tests for upload replacement, rule refresh, and saved dataset reload.

Split? Separate reliability/performance PR.

### P2-3: Data schema is implicit rather than typed

Evidence: canonical columns are created in `ensure_min_canonical_schema` at `reminders_app_v3.py:1942`, then assumed across reminder/statistics paths.

Why it matters: PMS schema drift can produce silent incorrect reminders.

Suggested fix: Define canonical schema constants and validation helpers with clear errors.

Validation plan: Negative tests for missing/ambiguous columns.

Split? Small pure-helper PR.

### P2-4: Google Sheets tracker writes can silently fail

Evidence: `append_tracker_row` catches all exceptions and returns false in `reminders_app_v3.py:4240`.

Why it matters: Missing audit/action/error rows reduce diagnosability and may hide critical failures.

Suggested fix: Distinguish optional telemetry from critical action writes; queue or surface failures where needed.

Validation plan: Mock tracker failures for sent/declined/settings changes.

Split? Separate reliability PR.

### P2-5: Query-param mutation is spread across helpers and flows

Evidence: query param helpers at `reminders_app_v3.py:4601`; dataset removal also reads/deletes a query param at `reminders_app_v3.py:6114`.

Why it matters: URL state can accidentally trigger actions or preserve stale tokens.

Suggested fix: Centralize URL state and require explicit confirmation for action-like params.

Validation plan: Unit tests for malformed/empty query params and repeated reruns.

Split? Small cleanup PR.

### P2-6: Rules and keyword definitions are code, not data

Evidence: `DEFAULT_RULES` and many keyword groups live in `reminders_app_v3.py`.

Why it matters: Rule changes require code deploys and can be hard to review separately from logic.

Suggested fix: Move static defaults to a data/config module with validation.

Validation plan: Snapshot test default rules and existing reminder generation.

Split? Separate config extraction PR.

### P2-7: Business logic is nested inside UI blocks

Evidence: upload save flow defines `save_uploaded_dataset` inside the Upload Data tab around `reminders_app_v3.py:7249`; search editor defines many inner save callbacks around `reminders_app_v3.py:8755`.

Why it matters: Logic is harder to test and reuse without Streamlit state.

Suggested fix: Extract pure decision helpers first; keep UI wrappers thin.

Validation plan: Unit tests for extracted helpers.

Split? Multiple small PRs.

### P2-8: Current CI excludes some non-CI tests

Evidence: CI runs only `test_ci_*.py`; `tests/test_settings_pointer_helpers.py`, `tests/test_reminders_pointer_wrapper.py`, and `tests/test_behavior_baseline_scaffold.py` are outside that pattern.

Why it matters: Some tests may not protect PRs unless run manually.

Suggested fix: Decide which tests are intended for CI and rename or update workflow.

Validation plan: Run full discover in CI or document excluded tests.

Split? Small CI PR.

### P2-9: Dependency pinning is uneven

Evidence: `streamlit`, `authlib`, and `httpx` are pinned; `pandas`, `numpy`, Google libraries, and `gspread` are broad/unpinned.

Why it matters: Transitive updates can break parsing/auth/Google access unexpectedly.

Suggested fix: Add constraints or lockfile strategy after current versions are recorded.

Validation plan: Fresh environment install plus CI tests.

Split? Separate dependency PR.

### P3-1: Existing docs are partly stale relative to current size/scope

Evidence: `CODE_ASSESSMENT.md` references about 4k lines, while `reminders_app_v3.py` is now about 10,975 lines.

Why it matters: Old assessments can mislead prioritization.

Suggested fix: Treat this `CODEBASE_AUDIT.md` as the current map and archive/update older docs later.

Validation plan: Documentation-only review.

Split? Optional docs PR.

### P3-2: Mixed comment style and drift markers

Evidence: comments such as "Refactor #1", "unchanged UI", and "temporarily hidden" appear in production code.

Why it matters: They make it harder to tell current design from historical patch notes.

Suggested fix: Remove stale commentary only when touching nearby code for functional reasons.

Validation plan: Compile only.

Split? Opportunistic cleanup.

## 12. Files or modules that look AI-generated, duplicated, fragile, or overcomplicated

- `reminders_app_v3.py`: highly overgrown monolith. It contains app runtime, CSS, auth, Google clients, ETL, upload publishing, reminder generation, UI tables, statistics, hidden admin code, and hidden analytics/export code.
- `reminders_app_v3.py:9411`: dormant Factoids analytics block is large and disabled.
- `reminders_app_v3.py:10721`: dormant admin account management block is disabled.
- `reminders_app_v3.py:10772`: dormant admin/debug/LLM export block is disabled.
- `reminders_app_v3.py:8755`: Search Terms editor has nested callbacks and repeated save/audit logic.
- `reminders_app_v3.py:7065`: Upload Data tab contains parsing, persistence, error handling, tracker writes, and rerun behavior in one UI block.
- `reminders_app_v3.py:4202` and nearby Google helpers: Google Sheets/Drive access is spread across the app instead of behind a narrow repository/service layer.
- `settings_pointer_utils.py`: useful small helper, but it duplicates naming concepts from in-file settings helpers. It should become part of a clearer persistence module later.
- `CODE_ASSESSMENT.md`: now stale and should not be treated as the current code map.

AI-generated/code-drift signals:

- Many large inline HTML/CSS strings and generated-looking UI fragments.
- Patch-history comments such as "Refactor #1" and "unchanged UI; behavior preserved".
- Multiple large disabled blocks preserved in production file.
- Repeated Streamlit table layout code with per-row CSS injection.

## 13. Recommended next 5 cleanup tasks, each one small PR

### PR 1: Add security tests around remember-login token behavior

Scope:

- Add tests only. Do not change auth behavior yet.
- Cover token expiry, malformed tokens, password-hash dependency, query-param clearing expectation, and password-change invalidation.

Files likely touched:

- `tests/test_ci_auth_session.py`

Validation:

- `python -m py_compile reminders_app_v3.py`
- `python -m unittest discover -s tests -p "test_ci_*.py"`

Why first:

- It creates a safety net before changing the highest-risk auth behavior.

### PR 2: Audit and escape active `unsafe_allow_html` user-controlled values

Scope:

- Create a tiny helper or use `html_lib.escape` at active call sites that render rule names, client names, patient names, item exclusions, and profile/dialog values.
- Do not touch dormant `if False` blocks in this PR.

Files likely touched:

- `reminders_app_v3.py`
- `tests/test_ci_auth_session.py` or a new focused `test_ci_html_escape.py`

Validation:

- Compile and CI unit tests.
- Manual spot check with values like `<script>alert(1)</script>` in rules/exclusions.

### PR 3: Move hard-coded Google IDs behind config helpers with backwards-compatible defaults

Scope:

- Add `get_config_value` or similar helper that reads `st.secrets` first and falls back to current constants.
- Keep existing IDs as fallback for zero behavior change.
- Document expected secrets in `.streamlit/secrets.example.toml`.

Files likely touched:

- `reminders_app_v3.py`
- `.streamlit/secrets.example.toml`
- `GOOGLE_AUTH_SETUP.md` or a short config doc section
- New tests for config fallback

Validation:

- Compile and CI unit tests.
- `python -m pip check`

### PR 4: Extract pure dataset history helpers to a small module

Scope:

- Move only pure functions such as `normalize_dataset_upload_history`, `upload_summary_rows_to_history`, `merge_dataset_upload_history`, `parse_history_date`, and `parse_history_int`.
- No Google, Streamlit UI, or behavior changes.

Files likely touched:

- New module such as `dataset_history.py`
- `reminders_app_v3.py` imports
- `tests/test_ci_dataset_update.py`

Validation:

- CI unit tests, especially dataset update tests.

### PR 5: Remove or quarantine dormant `if False` admin/factoids/export blocks

Scope:

- Move disabled code to an archival markdown file or separate non-imported module.
- Do not re-enable features.
- Keep any actively referenced helpers in place.

Files likely touched:

- `reminders_app_v3.py`
- New archival doc if desired

Validation:

- Compile and CI unit tests.
- Confirm app still imports and visible tabs are unchanged.

## Final recommendation

Start with tests and security hardening, not broad refactors. The safest sequence is:

1. Add auth/token characterization tests.
2. Fix active HTML escaping.
3. Make Google resource config explicit.
4. Extract one pure helper cluster.
5. Quarantine dormant code.

Avoid large modularization until the auth, tenant-boundary, and upload/persistence behavior has stronger characterization coverage.

## 2026-05-17 Main Pilot Addendum

This audit file predates several targeted hardening and QA passes. The original
risks should still be read as useful historical evidence, but the current
release-readiness picture has changed.

Current validation evidence:

```bash
python -m py_compile reminders_app_v3.py settings_pointer_utils.py scripts/live_google_smoke_check.py scripts/auth_legacy_audit.py
python -m pip check
python -m unittest discover -s tests -p "test_ci_*.py"
python -m unittest discover -s tests
bash scripts/pre_merge_check.sh
bash scripts/pilot_release_check.sh
```

Results:

- Compile passed.
- Dependency consistency passed.
- CI-pattern tests passed: 144 tests.
- Full local test discovery passed: 151 tests.
- Local pre-merge and pilot release scripts passed.
- Live Google smoke was skipped locally because this workspace has no
  service-account credentials.

Key current behavior changes since the original audit:

- Production Streamlit URL defaults to `-live` worksheet tabs.
- Google-linked identity is locked to `GoogleSubject`; editable profile email
  no longer changes the login identity.
- Authlib is pinned at `1.6.12`.
- Remember-login URL behavior, upload limits, password policy, exception
  leakage, action-like query params, profile rename, and privacy/deletion copy
  have targeted fixes and tests.
- User-facing Upload Data now summarizes total rows and total date range across
  all uploaded CSVs and restores the dataset health checks.
- Reminder action buttons no longer navigate the user away from Reminders.

Current top risks:

- P1: No true browser-level E2E suite exists yet.
- P1: Tenant isolation still depends heavily on application code over shared
  Google Sheets/Drive resources.
- P1: Backup/restore is operationally required because Sheets and Drive writes
  are not transactional.
- P2: The app remains an oversized Streamlit monolith.
- P2: Formal lint/type/security scan/secret scan gates are still deferred.

For current release guidance, use `MAIN_QA_REPORT.md`, `FINAL_REVIEW.md`, and
`LIVE_GOOGLE_SMOKE_TEST.md` before relying on older risk rankings in this file.
