#!/usr/bin/env bash
set -euo pipefail

echo "== Pilot release local gates =="
python -m pip install --dry-run -r requirements.txt >/tmp/clinic_pilot_pip_dry_run.log
python -m py_compile reminders_app_v3.py settings_pointer_utils.py auth_password_utils.py scripts/live_google_smoke_check.py scripts/auth_legacy_audit.py
python -m pip check
if python -c "import pip_audit" >/dev/null 2>&1; then
  bash scripts/dependency_security_audit.sh
else
  echo "Skipping dependency security audit: install dev requirements with python -m pip install -r requirements-dev.txt."
fi
if python -c "import ruff" >/dev/null 2>&1; then
  bash scripts/bug_lint_check.sh
else
  echo "Skipping bug-only lint check: install dev requirements with python -m pip install -r requirements-dev.txt."
fi
env -u WORKSHEET_NAME_SUFFIX python -m unittest discover -s tests -p "test_ci_*.py"
env -u WORKSHEET_NAME_SUFFIX python -m unittest tests.test_ci_streamlit_startup
env -u WORKSHEET_NAME_SUFFIX python -m unittest tests.test_settings_pointer_helpers tests.test_reminders_pointer_wrapper
git diff --check

echo "== Live Google smoke =="
if [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" || -f "google-credentials.json" || -f ".streamlit/secrets.toml" ]]; then
  python scripts/live_google_smoke_check.py
  python scripts/auth_legacy_audit.py --fail-on-risk
  if [[ -n "${PILOT_TEST_CLINIC_ID:-}" ]]; then
    python scripts/live_google_smoke_check.py --clinic-id "${PILOT_TEST_CLINIC_ID}"
  else
    echo "Skipping clinic pointer smoke: set PILOT_TEST_CLINIC_ID to enable it."
  fi
else
  echo "Skipping live Google smoke: no GOOGLE_APPLICATION_CREDENTIALS, google-credentials.json, or .streamlit/secrets.toml found."
fi

echo "Pilot release local checks completed."
