# Clinic Reminders Prototype

Streamlit prototype for turning clinic sales exports into reminder workflows, WhatsApp message preparation, and outcome tracking.

## Repository Map

- `reminders_app_v3.py` - main Streamlit application entry point.
- `auth_password_utils.py` - password hashing and password-policy helpers used by the app and tests.
- `settings_pointer_utils.py` - small helper module for dataset pointer updates.
- `tests/` - unittest-based characterization, CI, and workflow coverage.
- `scripts/` - local release, audit, lint, and live Google smoke helpers.
- `audits/` - current high-impact audit backlog plus archived historical audits.
- `docs/operations/` - setup and operational runbooks.
- `.streamlit/` - checked-in Streamlit config and example secrets only.

## Common Commands

```bash
python -m streamlit run reminders_app_v3.py
python -m py_compile reminders_app_v3.py settings_pointer_utils.py auth_password_utils.py
python -m unittest discover -s tests -p "test_ci_*.py"
bash scripts/pre_merge_check.sh
```

For release-sensitive work, use `PRE_PRODUCTION_CHECKLIST.md` and `bash scripts/pilot_release_check.sh`.

## Documentation

- Current audit backlog: `audits/ACTIVE_HIGH_IMPACT_ITEMS.md`
- Merged audit index: `audits/MERGED_AUDIT_INDEX.md`
- Backup/restore runbook: `docs/operations/BACKUP_RESTORE_RUNBOOK.md`
- Google auth setup: `docs/operations/GOOGLE_AUTH_SETUP.md`
- Pre-production checklist: `PRE_PRODUCTION_CHECKLIST.md`

## Local Secrets

Do not commit real credentials. Use `.streamlit/secrets.toml` or `google-credentials.json` locally; both are ignored by git. Keep `.streamlit/secrets.example.toml` updated when expected secret keys change.
