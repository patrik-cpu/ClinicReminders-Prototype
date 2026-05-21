#!/usr/bin/env bash
set -euo pipefail

python -m ruff check --select=F,E9 reminders_app_v3.py settings_pointer_utils.py scripts tests
