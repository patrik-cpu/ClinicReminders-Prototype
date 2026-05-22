# Auth And Settings Audit

Focused scope: password login, Google login, logout, keep-me-logged-in, session restoration, saved settings, staff access, user switching in one browser, clinic isolation, and Google Sheets/settings read/write performance.

Only P0/P1 issues are listed.

## Findings

### AUTH-001

Severity: P0

Impact: Logout can immediately restore the previous persistent session, so a user who clicks Logout may remain logged in or be logged back into the same clinic. On a shared browser, this is a broken logout and clinic data exposure risk.

Exact current behavior: Logout calls `clear_remember_login_token()` and `clear_account_session_state()`, then reruns the app unless Google logout is invoked. The cookie deletion is only queued into `st.session_state`. On the next run, `render_pending_remember_login_cookie_update()` emits browser JavaScript to delete the cookie, but server-side code then calls `restore_remembered_login_session()` in the same run. That restore reads `st.context.cookies` / request headers from the current request, which can still contain the old cookie because the deletion JavaScript has not executed in the browser yet.

Expected behavior: After Logout, no remember-token restore should happen until the server can observe a later request without the old token, or the old token should be invalidated server-side before any restore attempt.

Evidence with file/function/location:
- `reminders_app_v3.py:10150-10158`: Logout queues token clearing and immediately reruns/logs out.
- `reminders_app_v3.py:8412-8414`: `clear_remember_login_token()` only clears query params and queues a cookie update.
- `reminders_app_v3.py:9847-9883`: app renders the pending cookie update, then still calls `restore_remembered_login_session()` in the same run.
- `reminders_app_v3.py:8347-8375`: cookie clearing is client-side JavaScript emitted into the response.
- `reminders_app_v3.py:8384-8400`: restore reads cookies from the current server request/header.
- `reminders_app_v3.py:8453-8489`: restore validates the stale token and calls `finish_authenticated_session()`.

Affected scenario:
- keep-me-logged-in checked then logout
- logout then refresh
- switching users in the same browser after a remembered login

Likely root cause: Cookie deletion is asynchronous client-side work, while session restoration is synchronous server-side work in the same rerun. There is no server-side logout barrier or revoked-token state to suppress restoration after a logout request.

Safest fix approach: Add a server-side logout/restore suppression flag that survives the immediate rerun, e.g. `REMEMBER_LOGIN_RESTORE_BLOCKED_KEY`, and make `restore_remembered_login_session()` return `False` while that flag is set. Clear the flag only after a run has rendered the logged-out page and queued cookie deletion, or after the cookie/query token is absent. Stronger fix: include an issued-at/session nonce in remember tokens and store per-clinic/user revocation/version in settings so logout and password changes can invalidate old tokens server-side.

Test needed: Characterization/integration test for: create valid remember cookie, click/logout path queues deletion, next run still sees old cookie, verify `restore_remembered_login_session()` is not called and `logged_in` remains `False`.

Performance impact: The bug also causes unnecessary auth restore work after logout. If the stale cookie is restored, it triggers repeated settings/data loading and tracker writes.

---

### AUTH-002

Severity: P0

Impact: Logging into another clinic with "Keep me logged in" unchecked does not clear an existing remember cookie from a previous clinic. After refresh/reopen or logout, the browser can return to the earlier remembered clinic, exposing the wrong clinic on a shared machine.

Exact current behavior: Password login passes `remember_session=bool(keep_logged_in)` to `finish_authenticated_session()`. If unchecked, no new token is written, but the existing cookie is not cleared. Staff access has an explicit clear path when unchecked, but password login does not. Google login also does not clear an existing password/staff remember cookie before finishing a Google session.

Expected behavior: Any successful login with keep-me-logged-in unchecked should clear any existing remember cookie/query token before the new session starts. Any login as a different auth provider/clinic should replace or clear stale persistent credentials.

Evidence with file/function/location:
- `reminders_app_v3.py:9944-9948`: password login checkbox defaults to checked.
- `reminders_app_v3.py:9963-9969`: password login only creates/replaces remember token when `keep_logged_in` is true; there is no `else: clear_remember_login_token()`.
- `reminders_app_v3.py:10050-10064`: staff access does clear the token when keep-me-logged-in is unchecked, showing the intended behavior exists for one auth path.
- `reminders_app_v3.py:9854-9868`: Google auto-login finishes a Google session without clearing any existing remember token from a prior password/staff login.
- `reminders_app_v3.py:8424-8433`: remember token is only written/cleared when explicitly called.

Affected scenario:
- different clinic user logs in on same browser with keep-me-logged-in unchecked
- keep-me-logged-in unchecked then refresh/reopen
- Google login after a remembered password/staff session exists
- logout after switching users in the same browser

Likely root cause: Password and Google login paths treat "unchecked" as "do not write a new persistent token", not "remove any old persistent token". Staff access has the explicit clearing branch, but the owner password path and Google path do not.

Safest fix approach: On every successful password login with `keep_logged_in == False`, call `clear_remember_login_token()` before or inside `finish_authenticated_session()`. On Google login, either clear existing app remember tokens or issue a provider-specific token for the Google clinic if persistent app-level remember is desired. Also make `finish_authenticated_session()` centralize this behavior so all auth flows are consistent.

Test needed: Start with a valid remember cookie for Clinic A, successfully password-login Clinic B with keep unchecked, simulate browser reopen, and assert Clinic A is not restored. Repeat with Google login after a remembered password/staff token.

Performance impact: Stale-cookie restoration can trigger extra full settings-sheet reads and full login startup for the wrong clinic.

---

### AUTH-003

Severity: P1

Impact: Login/session restoration makes repeated full Google Sheets reads and tracker writes on hot auth paths. This can slow login, increase quota pressure, and make keep-me-logged-in/session restore feel unreliable under Sheets latency.

Exact current behavior:
- Password login calls `authenticate_user()`, which reads the full settings worksheet with `get_all_values()`.
- Remember-token validation calls `get_clinic_row()`, which reads all settings records with `get_all_records()`.
- After restore succeeds, `restore_remembered_login_session()` calls `remember_authenticated_session()` / `remember_clinic_access_session()` without passing the row just fetched, causing `create_remember_login_token()` / `create_clinic_access_remember_token()` to call `get_clinic_row()` again.
- `finish_authenticated_session()` loads settings and shared dataset, then writes account/user tracker data.
- `save_settings()` performs a fresh remote settings read before most writes.

Expected behavior: Auth/session restore should reuse the row snapshot already read during authentication/validation and avoid multiple full-sheet scans for the same clinic in one login. Settings saves should still preserve remote changes, but hot login paths should not repeatedly scan the full settings sheet unless necessary.

Evidence with file/function/location:
- `reminders_app_v3.py:8034-8062`: `authenticate_user()` reads `sheet.get_all_values()`.
- `reminders_app_v3.py:8065-8093`: `authenticate_clinic_access()` reads `sheet.get_all_values()`.
- `reminders_app_v3.py:8095-8103`: `get_clinic_row()` reads `sheet.get_all_records()`.
- `reminders_app_v3.py:8216-8230`: remember-token validation calls `get_clinic_row()`.
- `reminders_app_v3.py:8473-8489`: restore finishes auth and then refreshes the remember token.
- `reminders_app_v3.py:8169-8172` and `8188-8190`: token creation reads `get_clinic_row()` if no row is passed.
- `reminders_app_v3.py:9654-9681`: `finish_authenticated_session()` loads settings and shared dataset.
- `reminders_app_v3.py:5329-5338`: `save_settings()` locates settings row and usually reads remote settings before writing.

Affected scenario:
- keep-me-logged-in checked then refresh/reopen
- staff access keep-me-logged-in checked then refresh/reopen
- password login
- staff access login
- owner saves settings then logs back in
- Google login if present

Likely root cause: Authentication helpers return inconsistent row/cache data, and remember-token validation returns only session metadata, not the row it already fetched. Token refresh after restore repeats row lookup. The settings repository cache helps after a row is found, but it does not eliminate all full-sheet scans on login/restore.

Safest fix approach: Return a row snapshot from `validate_remember_login_session()` and pass it through `restore_remembered_login_session()` into `finish_authenticated_session()` and remember-token refresh. Prefer `_get_settings_row_for_clinic()`/cached row values over full `get_all_records()` where possible. Consider a single `load_auth_row_for_clinic()` helper that seeds `_settings_row_cache` consistently for password, staff, Google, and remembered sessions.

Test needed: Mock the settings worksheet and assert remembered-login restore performs at most one full settings-sheet read before `finish_authenticated_session()`. Add separate call-count tests for password login, staff access login, and remember-token restore.

Performance impact: High on every remembered login and staff/password auth path as clinic count grows. Full-sheet reads are O(number of clinics), and repeated reads increase latency and quota risk.

## Top 3 Highest-Impact Fixes

1. Add a server-side restore suppression/revocation mechanism so Logout cannot immediately restore the stale remember cookie.
2. Clear stale remember tokens on every successful login where keep-me-logged-in is unchecked, and when switching auth provider/clinic.
3. Reuse auth/settings row snapshots through remember-token validation and session finish to remove repeated full Google Sheets reads.

## Suggested Fix Order

1. Fix logout restore suppression first because it is a P0 broken-logout/data-exposure risk.
2. Fix stale remember-token clearing on password/Google login next because it is the same cross-clinic exposure class.
3. Optimize auth/settings row reuse after the security behavior is stable.

## Validation Commands Available In This Repo

- `python -m py_compile reminders_app_v3.py`
- `python -m unittest tests.test_ci_auth_session`
- `python -m unittest tests.test_ci_audit_characterization`
- `python -m unittest tests.test_ci_settings_save_state`
- `python -m unittest tests.test_ci_reminder_workflows`
- `python -m unittest`
- `git diff --check`
