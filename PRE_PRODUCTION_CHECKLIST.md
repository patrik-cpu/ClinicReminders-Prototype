# Pre-Production Checklist

Run this before promoting `main` to production.

## Local Gates

- Confirm the release branch is `main` and the working tree is clean.
- Run `bash scripts/pre_merge_check.sh`.
- Run `bash scripts/pilot_release_check.sh`.
- Run `bash scripts/dependency_security_audit.sh` after installing dev tooling with `python -m pip install -r requirements-dev.txt`.
- Run `bash scripts/bug_lint_check.sh` after installing dev tooling with `python -m pip install -r requirements-dev.txt`.

## Live Google Smoke

- Confirm `GOOGLE_APPLICATION_CREDENTIALS`, `google-credentials.json`, or `.streamlit/secrets.toml` points at the intended production resources.
- Run `python scripts/live_google_smoke_check.py`.
- Run `python scripts/auth_legacy_audit.py --fail-on-risk`.
- For a known test clinic, run `PILOT_TEST_CLINIC_ID="<clinic id>" bash scripts/pilot_release_check.sh`.

## Backup And Rollback

- Confirm the settings sheet and tracker sheets have a recent backup or restorable version history.
- Confirm the active deployed commit SHA.
- Record the previous known-good commit SHA for rollback.
- Confirm no deploy is pointed at `main-reminders` or any archived branch.

## Final Smoke

- Log in with a password clinic.
- Log in with Google if enabled for the clinic.
- Log in with staff access.
- Upload a small known-good sales export to a test clinic.
- Generate active reminders and action one reminder as sent.
- Check Configure Reminders, Exclusions, Identify & Track, Upload Data, and Get Started after refresh.
