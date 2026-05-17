#!/usr/bin/env bash
set -euo pipefail

echo "== Pilot release local gates =="
python -m pip install --dry-run -r requirements.txt >/tmp/clinic_pilot_pip_dry_run.log
python -m py_compile reminders_app_v3.py settings_pointer_utils.py scripts/live_google_smoke_check.py scripts/auth_legacy_audit.py
python -m pip check
python -m unittest discover -s tests -p "test_ci_*.py"
python -m unittest tests.test_ci_streamlit_startup
python -m unittest tests.test_settings_pointer_helpers tests.test_reminders_pointer_wrapper
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
