# SECURITY_AUDIT.md

## Executive summary

This Streamlit app is a clinic-reminder workflow that stores tenant data in Google Drive/Sheets and relies on app-level filtering by `ClinicID`. The largest risks are not classic SQL or shell injection; they are tenant isolation, long-lived URL-bearing sessions, unsafe HTML rendering, weak legacy password handling, and broad Google API side effects.

Top issues:

- P0: Long-lived remember-login tokens are placed in the URL and remain valid for 10 years.
- P0: Tenant isolation and destructive data operations rely on application code and one broad Google service account.
- P1: Several stored user-controlled strings are rendered through `unsafe_allow_html=True` without escaping.
- P1: `authlib==1.6.11` is pinned to a version affected by `GHSA-r95x-qfjj-fjj2` / `CVE-2026-44681`.
- P1: Password login and signup lack rate limiting, lockout, and strong password requirements.
- P1: Legacy MD5 password hashes are still accepted.

I did not edit application code. This report is the only file created.

## Scope and method

Reviewed:

- `reminders_app_v3.py`
- `requirements.txt`
- `.github/workflows/ci.yml`
- `.streamlit/secrets.example.toml`
- `.gitignore`
- Existing characterization tests under `tests/`

Checks performed:

- Searched for auth/session code, unsafe HTML, upload parsing, Google API writes, query-param state, credential loading, dependency pins, subprocess/eval/deserialization sinks, and route/action boundaries.
- Ran dependency environment checks:
  - `python -m pip check`: no broken installed requirements.
  - `python -m pip_audit --version`: unavailable in this environment.
  - Queried OSV for pinned direct dependencies in `requirements.txt`.

Dependency advisory source:

- OSV / GitHub advisory for Authlib: https://api.osv.dev/v1/vulns/GHSA-r95x-qfjj-fjj2
- Upstream advisory reference: https://github.com/authlib/authlib/security/advisories/GHSA-r95x-qfjj-fjj2

## Findings

### P0: Remember-login tokens are long-lived bearer credentials in the URL

Evidence:

- `reminders_app_v3.py:1873`: `REMEMBER_LOGIN_DAYS = 3650`
- `reminders_app_v3.py:4564` in `create_remember_login_token`
- `reminders_app_v3.py:4577` in `validate_remember_login_token`
- `reminders_app_v3.py:4631` in `set_remember_login_token`
- `reminders_app_v3.py:5428` to `5453` in auto-login handling
- `reminders_app_v3.py:5567` and `reminders_app_v3.py:5614` set the remember token after login/signup

Exploit scenario:

Anyone who obtains a copied URL, browser history entry, screenshot, proxy log, referrer leak, or shared support transcript containing `?remember=...` can authenticate as that clinic until the token expires or the clinic password changes. The token lasts about 10 years and is refreshed back into the URL after successful validation.

Recommended fix:

- Move remember tokens out of query params and into an HTTP-only, secure, same-site cookie if the deployment platform supports it.
- Shorten lifetime substantially, for example 7 to 30 days.
- Add server-side revocation or a per-user/session nonce stored in the settings sheet.
- Rotate the token on use and clear query-param credentials immediately after migration.
- Consider removing the remember feature until it can be stored outside URLs.

Regression test to add:

- A login test that asserts no `remember` token remains in `st.query_params` after authentication.
- A token-expiry test that asserts expired tokens fail.
- A revocation test that asserts password change or explicit logout invalidates prior tokens.

Safe in isolation:

- Yes for shortening lifetime and clearing query params.
- Cookie-backed storage and revocation should be split into a focused auth PR with manual deployment validation.

### P0: Tenant isolation depends on app-level filtering and broad Google service-account access

Evidence:

- `reminders_app_v3.py:1888` to `1897` in `get_drive_service`
- `reminders_app_v3.py:2201` to `2235` in `drive_upsert_csv_bytes`
- `reminders_app_v3.py:4513` in `authenticate_user`
- `reminders_app_v3.py:4524` in `get_clinic_row`
- `reminders_app_v3.py:4966` to `4998` in `update_clinic_profile`
- `reminders_app_v3.py:5021` to `5042` in `delete_clinic_account_and_data`

Exploit scenario:

A logic bug, stale session state value, compromised session token, or accidental `ClinicID` mismatch can update, rename, trash, or delete another clinic's data because the app uses one Google credential and enforces tenancy in Python code. The delete flow trashes the Drive file first, then removes matching rows from every worksheet, so partial failure can leave inconsistent state.

Recommended fix:

- Centralize all tenant-scoped Drive/Sheets operations behind a small authorization helper that requires an authenticated `clinic_id` and validates the target object belongs to that clinic immediately before mutation.
- Make destructive flows idempotent and transactional where possible: mark pending deletion, delete sheet rows, then trash Drive files, with rollback or repair metadata.
- Store dataset file ownership metadata and validate it before rename/trash/download.
- Add explicit object-level authorization checks to profile rename, dataset upload, dataset download, and account deletion.

Regression test to add:

- Tests where session clinic A attempts to mutate clinic B's Drive file ID or sheet row and the operation is denied.
- A partial-failure delete test that simulates Drive trash failure and verifies sheet rows are not deleted.
- A profile rename failure test that verifies ClinicID and pointer state remain consistent.

Safe in isolation:

- Individual ownership checks are safe in isolation.
- Transactional deletion and data migration should be split into a separate PR.

### P1: Stored XSS through unescaped strings rendered with `unsafe_allow_html=True`

Evidence:

- `reminders_app_v3.py:8979`: `rule` inserted directly into an HTML string.
- `reminders_app_v3.py:9221`: `client_name` inserted directly into an HTML string.
- `reminders_app_v3.py:9287`: `client_name` and `patient_name` inserted directly into an HTML string.
- `reminders_app_v3.py:9355`: `term` inserted directly into an HTML string.
- App-wide pattern: many `st.markdown(..., unsafe_allow_html=True)` calls.

Exploit scenario:

A clinic user stores a search term, exclusion rule, client name, or patient name such as `<script>...</script>` or an event-handler payload. When the page later renders that value, the browser executes attacker-controlled JavaScript in the app context. This can steal visible PHI, perform actions as the user, or capture the remember-login token from the URL.

Recommended fix:

- Escape every user-controlled value with `html_lib.escape(str(value))` before interpolating into unsafe HTML.
- Prefer Streamlit native elements for user-provided text.
- Add a small local helper for safe HTML text interpolation and use it consistently.

Regression test to add:

- Render each affected UI helper with payloads like `<img src=x onerror=alert(1)>` and assert the returned/generated markup contains escaped text, not raw tags.
- Add a grep-style test for known unsafe interpolation sites if UI helpers are hard to unit test.

Safe in isolation:

- Yes. Escaping these display strings is a small, behavior-preserving fix.

### P1: Pinned Authlib version has a published OIDC vulnerability

Evidence:

- `requirements.txt:4`: `authlib==1.6.11`
- `reminders_app_v3.py:5397`: `st.login("google")`
- Advisory: `GHSA-r95x-qfjj-fjj2` / `CVE-2026-44681`, fixed in Authlib `1.6.12` and `1.7.1`.

Exploit scenario:

The advisory affects Authlib OIDC implicit/hybrid authorization open redirect behavior. This app appears to use Authlib through Streamlit as an OIDC client rather than as an OIDC provider, so direct exploitability is not confirmed from this code alone. However, the deployed dependency is known vulnerable and auth-adjacent, so it should not remain pinned.

Recommended fix:

- Upgrade to at least `authlib==1.6.12`, or to the current compatible Streamlit-supported version.
- Run login regression tests against Google OIDC after the upgrade.
- Add dependency audit to CI.

Regression test to add:

- A dependency policy test or CI audit step that fails on known high/moderate advisories in direct auth dependencies.
- Existing login characterization should still pass after the version bump.

Safe in isolation:

- Usually yes, but validate Google login in the deployed environment.

### P1: Login and signup lack rate limiting, lockout, and abuse controls

Evidence:

- `reminders_app_v3.py:5530` to `5572` handles password login attempts.
- `reminders_app_v3.py:5591` to `5614` handles signup.
- `reminders_app_v3.py:5650` to `5676` handles password changes.

Exploit scenario:

An attacker can brute-force clinic passwords, enumerate likely clinic IDs, or repeatedly create accounts and write to the shared Google Sheets/Drive backend. Google API quotas can be exhausted, and weak passwords become practical to guess.

Recommended fix:

- Add per-username and per-IP throttling at the deployment edge if possible.
- Add application-level failed-attempt counters with short lockouts.
- Normalize error responses so login failures do not reveal whether a clinic exists.
- Add signup throttling or an invitation/approval flow if public signup is not intended.

Regression test to add:

- Failed login attempts beyond the threshold are rejected.
- Successful login resets the failure counter.
- Signup rate limit rejects repeated attempts.

Safe in isolation:

- Edge rate limiting is safe.
- App-level counters need careful UX and support flow design but can be added in a focused PR.

### P1: Password policy is weak

Evidence:

- `reminders_app_v3.py:5600` to `5605`: signup password minimum length is 6.
- `reminders_app_v3.py:5658` to `5664`: password change minimum length is 6.

Exploit scenario:

A clinic account can choose a short password that is easy to brute-force, especially because login has no rate limiting. If the settings sheet is exposed, weak passwords are easier to recover even when hashed.

Recommended fix:

- Require at least 12 characters.
- Block common passwords and clinic-name-derived passwords.
- Consider passphrase guidance instead of complex composition rules.
- Add a migration path that prompts existing users to upgrade weak passwords at next login.

Regression test to add:

- Signup rejects short/common passwords.
- Password change rejects short/common passwords.
- Existing valid long passwords continue to work.

Safe in isolation:

- Yes for new passwords.
- Enforcing upgrades for existing users should be a separate UX-aware PR.

### P1: Legacy MD5 password hashes are still accepted

Evidence:

- `reminders_app_v3.py:4415` to `4417` in `legacy_hash_pw`
- `reminders_app_v3.py:4433` to `4455` in `verify_password`
- `reminders_app_v3.py:5217` to `5235` in `update_clinic_password`

Exploit scenario:

If the settings sheet or an export is exposed, legacy MD5 hashes are fast to crack. The app continues to accept them, preserving risk for any account not yet migrated.

Recommended fix:

- On successful login with an MD5 hash, immediately rehash the password with PBKDF2 and clear legacy material.
- Add an administrative migration report for any remaining legacy hashes.
- Consider moving to Argon2id or bcrypt if acceptable for the runtime.

Regression test to add:

- Legacy MD5 login succeeds once and rewrites the stored hash to PBKDF2.
- Legacy hash no longer remains after migration.
- Invalid legacy password still fails.

Safe in isolation:

- Yes if implemented as login-time migration with tests.

### P1: Upload handling lacks explicit size, row, and resource limits

Evidence:

- `reminders_app_v3.py:4083`: CSV parsing with `pd.read_csv`.
- `reminders_app_v3.py:4091`: Excel parsing with `pd.read_excel`.
- `reminders_app_v3.py:4038` to `4046` validates required columns and date readability.
- `reminders_app_v3.py:7093` to `7097`: upload widget accepts `csv`, `xls`, and `xlsx`.

Exploit scenario:

A large CSV, compressed spreadsheet, or high-row-count workbook can consume memory/CPU and make the app unavailable. Extension checks alone do not prevent malformed files, oversized payloads, or spreadsheet structures that stress parsers.

Recommended fix:

- Enforce upload byte limits before parsing.
- Enforce maximum row and column counts after parsing.
- Reject unsupported MIME types where available.
- Parse only the first sheet and only required columns unless more is needed.
- Add clear user-facing validation errors without raw exception details.

Regression test to add:

- Oversized file is rejected before parser invocation.
- Excessive row count is rejected.
- Missing required columns and invalid date formats still return the current validation messages.

Safe in isolation:

- Yes, if limits are chosen to cover existing real clinic datasets.

### P1: Raw exception details can leak implementation and data identifiers

Evidence:

- `reminders_app_v3.py:1909` to `1914` displays Google HTTP status and response content.
- `reminders_app_v3.py:7145` to `7199` records raw upload errors with `str(e)`.
- `reminders_app_v3.py:7262` to `7265` displays dataset load exceptions.
- `reminders_app_v3.py:7280` to `7300` records raw save exceptions.

Exploit scenario:

Errors from Google APIs, parsers, or sheet operations can expose file IDs, sheet IDs, backend structure, request details, or PHI in UI messages, logs, or tracker rows. A malicious upload can intentionally trigger verbose parser errors.

Recommended fix:

- Display generic user-facing error messages.
- Store detailed diagnostics only in restricted logs, with sensitive values redacted.
- Redact Google file IDs, sheet IDs, access tokens, email addresses, and clinic/patient identifiers from tracker rows.

Regression test to add:

- Simulated Google API and parser errors do not render raw exception text to the user.
- Tracker rows redact known sensitive patterns.

Safe in isolation:

- Yes. Error-message sanitization can be done in small patches.

### P2: Query parameters are used for action-like state

Evidence:

- `reminders_app_v3.py:4602` to `4637` manages query-param state for remember-login.
- `reminders_app_v3.py:6114` to `6123` in `consume_dataset_upload_removal` removes upload items based on `remove_dataset_upload`.

Exploit scenario:

If action-like query parameters are active in a browser session, a crafted link can cause state changes or remove in-progress upload data when the page loads. The most serious query-param issue is the remember token, already listed as P0.

Recommended fix:

- Keep query params for navigation or shareable filters only.
- Require form submissions or explicit button actions for mutations.
- Add nonce confirmation for any action triggered from URL state.

Regression test to add:

- Loading a page with mutation query params does not change upload/session state unless a matching nonce is present.
- Invalid indices are ignored without mutation.

Safe in isolation:

- Yes for removing or gating URL-triggered mutations.

### P2: Plain password legacy column remains part of the settings schema

Evidence:

- `reminders_app_v3.py:204`: `PlainPassword`
- `reminders_app_v3.py:4755`: new local account writes `PlainPassword` as blank.
- `reminders_app_v3.py:5230`: password update clears `PlainPassword`.

Exploit scenario:

Current writes appear to clear or leave the column blank, but if old records still contain plaintext passwords, anyone with sheet access or leaked exports can recover account credentials directly.

Recommended fix:

- Add a one-time migration that clears `PlainPassword` for all rows.
- Remove all code references to plaintext password storage after confirming no legacy dependency.
- Add a startup or CI check that rejects nonblank plaintext password values in fixtures.

Regression test to add:

- Account creation and password change never write plaintext passwords.
- Migration clears nonblank `PlainPassword`.

Safe in isolation:

- Yes for validation and clearing blanks.
- Removing the column entirely should be split from the migration.

### P2: Profile rename can desynchronize identity and dataset pointers

Evidence:

- `reminders_app_v3.py:4966` to `4998` in `update_clinic_profile`
- `reminders_app_v3.py:4986` to `4993` swallows Drive rename failure.
- `reminders_app_v3.py:4995` to `4997` updates settings and tracker rows after the Drive rename attempt.

Exploit scenario:

If Drive rename fails but sheet updates continue, the clinic identity, dataset file name, and tracker rows can diverge. In a multi-tenant system where object ownership is mostly inferred by `ClinicID` and naming conventions, inconsistent state can contribute to accidental data exposure or loss.

Recommended fix:

- Treat Drive rename failure as a blocking error before updating sheet identity.
- Revalidate dataset pointer ownership before and after the rename.
- Add a repair path for partially renamed accounts.

Regression test to add:

- Simulated Drive rename failure leaves `ClinicID`, settings, and tracker rows unchanged.
- Successful rename updates all expected rows.

Safe in isolation:

- Yes, as a focused consistency patch.

### P2: Destructive delete is not transactional

Evidence:

- `reminders_app_v3.py:5021` to `5042` in `delete_clinic_account_and_data`
- `reminders_app_v3.py:5030` to `5032` trashes the Drive dataset file.
- `reminders_app_v3.py:5034` to `5037` then deletes matching rows from every worksheet.

Exploit scenario:

A mid-operation exception can trash the dataset while leaving settings rows, or delete sheet rows after a partial Drive operation. This can produce unrecoverable account/data loss or orphaned records.

Recommended fix:

- Add a pending-deletion marker first.
- Validate all target objects before deleting anything.
- Delete noncritical tracker rows before final destructive Drive trash, or maintain a restore pointer until completion.
- Add retry-safe behavior and explicit audit logs.

Regression test to add:

- Drive trash failure leaves all sheet rows intact.
- Sheet delete failure leaves a recoverable dataset pointer and pending-deletion state.
- Re-running delete after partial failure is safe.

Safe in isolation:

- Basic preflight validation is safe.
- Full transactional behavior should be a separate PR.

### P2: No explicit CSRF model for cookie/session-backed browser actions

Evidence:

- `reminders_app_v3.py:5397`: Google login is available through Streamlit.
- `reminders_app_v3.py:5530` to `5572`: login form.
- `reminders_app_v3.py:5143` to `5185`: delete-account confirmation flow.
- `reminders_app_v3.py:5650` to `5676`: change-password flow.

Exploit scenario:

Streamlit manages form mechanics and session state, so this is not automatically exploitable from the code alone. However, if deployment cookies are sent cross-site and actions are reachable without a framework CSRF guard, a malicious site could try to trigger authenticated state-changing requests.

Recommended fix:

- Confirm Streamlit deployment cookie `SameSite` and CSRF behavior for the hosted environment.
- Put the app behind a proxy that sets secure cookie attributes and security headers.
- For highly destructive actions, keep typed confirmation and add a short-lived nonce stored in session state.

Regression test to add:

- Destructive actions require a session nonce created by rendering the form.
- Direct POST/action replay without the nonce is rejected.

Safe in isolation:

- Deployment header/cookie hardening is safe.
- App-level nonce tests should be added with the action helpers.

### P2: Security logging and audit trail failures are silent

Evidence:

- `reminders_app_v3.py:4241` to `4247` in `append_tracker_row`
- `reminders_app_v3.py:4250` to `4262` in `append_tracker_rows`

Exploit scenario:

Tracker writes can fail silently, leaving no audit trail for failed uploads, deletions, profile changes, or other security-relevant events. This makes incident response and abuse detection harder.

Recommended fix:

- Return structured failure states to callers for security-relevant events.
- Surface restricted admin warnings for tracker failures.
- Add a fallback local or deployment log with redaction.

Regression test to add:

- Simulated tracker append failure is recorded in a fallback logger.
- User-facing flows do not claim audit success when tracking failed.

Safe in isolation:

- Yes, if user-facing behavior remains stable and only restricted diagnostics change.

### P2: Hard-coded Google resource IDs increase environment and access-control risk

Evidence:

- `reminders_app_v3.py:198`: `DATASETS_FOLDER_ID`
- `reminders_app_v3.py:1871`: `SETTINGS_SHEET_ID`
- `reminders_app_v3.py:10655`: `FEEDBACK_SHEET_ID`

Exploit scenario:

These IDs are not secrets, but hard-coding production-like resource identifiers makes it easier to accidentally run local/test code against live data, share IDs in screenshots, or mix staging and production tenants.

Recommended fix:

- Move all Google resource IDs to secrets/configuration.
- Validate required config at startup.
- Use separate IDs per environment.

Regression test to add:

- App refuses to start data-mutating flows without required resource IDs.
- Tests can inject fake resource IDs without editing source code.

Safe in isolation:

- Yes, if defaults are preserved briefly during migration.

### P2: Dependency security auditing is absent from CI and some dependency ranges are broad

Evidence:

- `requirements.txt`: direct dependencies include broad ranges such as `pandas>=1.5`, plus unpinned packages like `numpy`, `altair`, `openpyxl`, `gspread`, and Google libraries.
- `.github/workflows/ci.yml`: CI compiles and runs tests but does not run a vulnerability audit.

Exploit scenario:

A future install can resolve to vulnerable or incompatible versions, and known advisories may go unnoticed. Spreadsheet parsers and auth libraries are especially security-sensitive in this app.

Recommended fix:

- Pin direct dependencies or use a lock file.
- Add `pip-audit` or an equivalent advisory check in CI.
- Review auth, parser, and Google client updates first.

Regression test to add:

- CI dependency audit fails on known vulnerable direct dependencies.
- CI continues to run the existing unit test suite after dependency resolution.

Safe in isolation:

- Adding audit as nonblocking is safe.
- Making it blocking and pinning all transitive dependencies should be staged.

### P3: Local credential-file fallback can surprise deployments

Evidence:

- `reminders_app_v3.py:1888` to `1897` loads `st.secrets["gcp_service_account"]`, then falls back to `google-credentials.json`.
- `.gitignore:9` ignores `google-credentials.json`.

Exploit scenario:

The fallback is useful in development, but a misplaced credential file in a deployment environment could silently become the active production credential. This can make credential rotation and environment separation harder to reason about.

Recommended fix:

- Require explicit configuration to enable local credential fallback.
- Log which credential source is used without exposing secret values.
- Prefer deployment secrets for hosted environments.

Regression test to add:

- In production mode, local credential fallback is rejected.
- In development mode, fallback works only when explicitly enabled.

Safe in isolation:

- Yes, behind a compatibility flag.

### P3: Security headers and CORS are deployment-dependent

Evidence:

- No app-level CORS or security-header configuration was found in the repository.
- The app is Streamlit-based, so headers are likely controlled by Streamlit hosting or an upstream proxy.

Exploit scenario:

Missing `Content-Security-Policy`, `X-Frame-Options` or `frame-ancestors`, `Referrer-Policy`, and strict cookie attributes can make XSS, clickjacking, URL-token leaks, and cross-origin abuse more damaging.

Recommended fix:

- Configure deployment/proxy headers:
  - `Content-Security-Policy`
  - `frame-ancestors 'none'` or known allowed origins
  - `Referrer-Policy: no-referrer` or `strict-origin-when-cross-origin`
  - `X-Content-Type-Options: nosniff`
  - secure cookie attributes
- Avoid allowing arbitrary origins.

Regression test to add:

- A deployment smoke test that fetches the app and asserts required headers.

Safe in isolation:

- Yes at the proxy/deployment layer, after validating Google login still works.

### P3: Disabled admin code would be unsafe if re-enabled as written

Evidence:

- `reminders_app_v3.py:10721`: admin block is disabled with `if False and st.session_state.get("clinic_id") == "Admin"`.
- `reminders_app_v3.py:10729` to `10752`: disabled admin form can add or update clinic passwords.

Exploit scenario:

The block is currently unreachable, so this is not an active vulnerability. If someone re-enables it by removing `False and`, admin access would depend on `clinic_id == "Admin"` rather than a separate role or permission check, creating a fragile admin-only action boundary.

Recommended fix:

- Delete the disabled admin block if it is not needed.
- If admin tooling is needed, add explicit role claims, separate admin auth, audit logging, and tests.

Regression test to add:

- Non-admin clinic cannot access admin actions even with `clinic_id` manipulation.
- Admin actions are audited and require a verified admin role.

Safe in isolation:

- Removing dead disabled code is safe if product confirms it is unused.

## Reviewed areas with no active finding

### SQL and NoSQL injection

No SQL or NoSQL database access was found. The app stores data in Google Sheets and Drive.

### Shell injection

No runtime use of `subprocess`, `os.system`, or shell command execution was found in `reminders_app_v3.py`.

### Unsafe deserialization

No `pickle`, `yaml.load`, or equivalent unsafe deserialization sink was found. JSON parsing uses `json.loads` for token payloads and settings-like data.

### SSRF

No user-provided URL fetch was found. External calls are to Google APIs through configured clients and file IDs.

### Drive query injection

`drive_query_literal` escapes backslashes and single quotes before Drive search queries, and Drive folder/name search uses that helper. No immediate Drive query injection finding was identified.

### Prompt injection

No LLM or prompt-processing runtime path was found in the application code.

## Recommended fix sequence

1. P0 auth/session PR: remove remember tokens from URLs, shorten token lifetime, add expiry/revocation tests.
2. P1 XSS PR: escape the four identified unsafe HTML interpolation sites and add regression tests.
3. P1 dependency/auth PR: upgrade Authlib, add dependency audit, validate Google login.
4. P1 login hardening PR: add rate limiting, stronger password requirements for new passwords, and MD5 login-time migration.
5. P0/P2 tenant isolation PR series: centralize ownership checks first, then make rename/delete flows transactional and repairable.

## Validation commands for future fixes

At minimum, run:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

For security-related dependency changes, also add and run a dependency audit command such as:

```bash
python -m pip_audit -r requirements.txt
```

## 2026-05-17 Remediation Status Addendum

This addendum records the current state after the main-pilot hardening work. The
original findings above are retained as audit history, but several are no
longer active in the same form.

Fixed or materially mitigated:

- P0 remember-login URL bearer token: query-param remember tokens are discarded,
  remember-token lifetime is shortened, and regression coverage exists for
  blocking URL-based login persistence.
- P0 tenant/resource configuration: Google resource IDs can be configured from
  secrets/environment, clinic-owned Drive file metadata is checked, and the
  production Streamlit redirect URL defaults to `-live` worksheets. Residual
  shared-service-account risk remains.
- P1 stored XSS: known user-controlled HTML interpolation paths were escaped or
  rendered through constrained helpers, with regression tests.
- P1 Authlib advisory: `requirements.txt` now pins `authlib==1.6.12`, and
  dependency consistency passes with `python -m pip check`.
- P1 login/signup abuse controls: local rate-limit and lockout behavior was
  added for password login/signup paths, with tests.
- P1 weak password policy: new password paths now require stronger passwords,
  with tests.
- P1 upload limits: upload size, row, and resource limits were added, with
  tests.
- P1 raw exception leakage: user-facing errors are sanitized while diagnostic
  details are routed to internal trackers where available, with tests.
- P2 action-like query parameters: unsafe action-like query state was removed or
  neutralized for the known active paths, with tests.
- P2 plain password legacy column: legacy plain-password behavior was removed
  from active settings handling, with tests.
- P2 profile rename and Google identity desynchronization: Google-linked
  profile email is read-only and Google login uses `GoogleSubject` for linked
  accounts.

Current security posture for the limited pilot:

- No local automated P0 failures were found in the 2026-05-17 QA run.
- The app is still not approved for broad production because Google Sheets and
  Drive remain shared backend resources and tenant isolation is mostly enforced
  by application code.
- The deployed app still needs live Google OAuth validation and confirmation
  that main writes to `-live` tabs only.
- Browser cookies/session behavior is still primarily Streamlit-managed; no
  separate web security proxy/header layer has been verified.

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
- Pre-merge and pilot local gates passed.
- Live Google smoke and legacy auth audit could not be proven in this workspace
  because service-account credentials are not present.

Remaining security work before broad production:

1. Run `scripts/pilot_release_check.sh` in an environment with live Google
   credentials and confirm `-live` tabs.
2. Review and narrow service-account access to the minimum spreadsheet and
   Drive folder needed for production.
3. Add browser-level E2E coverage for login, upload, Sent/Declined/Undo, clear
   data, and delete-account flows.
4. Add secret scanning and a dependency vulnerability scanner to CI.
5. Decide whether the app needs a stronger deployment layer for security
   headers, rate limiting, and audit retention.
