# Pilot Readiness Fix Log

Date started: 2026-05-22

## P0-001: Live Settings Sheet Contained Legacy MD5 Password Hashes

- Status: Fixed before this fix pass.
- Summary of change: With explicit approval, the 17 legacy MD5 password-account rows and matching tracker/audit rows were deleted from live Google Sheets. The audit document was updated to mark the P0 resolved.
- Files changed: `AUDIT_FINAL_PREPILOT.md`
- Validation performed:
  - `python scripts/auth_legacy_audit.py --show-clinics --fail-on-risk`
- Tests added/updated: None; existing `scripts/auth_legacy_audit.py` remains the release gate.
- Remaining risks: Future malformed password rows must still be caught by the release auth audit.

## P1-001: GitHub CI Can Pass While Pilot Release Gates Fail

- Status: Fixed.
- Summary of change: Removed the current Ruff bug-lint failure and expanded GitHub CI so pushes/PRs run the repo-owned release gates that do not require live credentials: bug lint, dependency security audit, pointer wrapper tests, and `scripts/pilot_release_check.sh`. Live Google smoke/auth audit remains conditional inside the pilot script and runs where credentials are available.
- Files changed:
  - `.github/workflows/ci.yml`
  - `reminders_app_v3.py`
  - `fix_plan.md`
  - `fix_log.md`
- Validation performed:
  - `bash scripts/bug_lint_check.sh`
  - `python -m unittest tests.test_ci_pilot_release_script`
  - `python -m py_compile reminders_app_v3.py settings_pointer_utils.py auth_password_utils.py scripts/live_google_smoke_check.py scripts/auth_legacy_audit.py`
  - `bash scripts/pre_merge_check.sh`
  - `bash scripts/pilot_release_check.sh`
- Tests added/updated: No new tests were needed; existing release-script tests cover the script wiring, and CI now executes the release gate directly.
- Remaining risks: GitHub CI still cannot run live Google smoke/auth audit unless credentials are deliberately configured for that environment. A protected/manual credentialed release workflow remains useful for production promotion.

## P1-002: No Browser-Level E2E Coverage For The Real Streamlit UI

- Status: Partially fixed.
- Summary of change: Added an authenticated Streamlit navigation smoke test using the existing CI-safe E2E layout mode. The test renders the app through `streamlit.testing.v1.AppTest`, clicks every main tab, and fails if any tab raises an uncaught Streamlit exception. This directly covers the recent class of widget/session-state crash while avoiding live Google credentials.
- Files changed:
  - `tests/test_ci_streamlit_navigation_smoke.py`
  - `fix_log.md`
- Validation performed:
  - `python -m unittest tests.test_ci_streamlit_navigation_smoke`
- Tests added/updated:
  - `tests.test_ci_streamlit_navigation_smoke.StreamlitNavigationSmokeTests.test_authenticated_main_tabs_render_without_uncaught_exception`
- Remaining risks: This is Streamlit component-level coverage, not a full real-browser Playwright/Selenium journey. It does not verify actual browser back/forward behavior, mobile viewport rendering, clipboard/WhatsApp deep links, or live Google persistence.
