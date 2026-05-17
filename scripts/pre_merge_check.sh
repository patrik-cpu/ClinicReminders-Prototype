#!/usr/bin/env bash
set -euo pipefail

python -m py_compile reminders_app_v3.py settings_pointer_utils.py
python -m pip check
python -m unittest discover -s tests -p "test_ci_*.py"
python -m unittest tests.test_settings_pointer_helpers tests.test_reminders_pointer_wrapper
