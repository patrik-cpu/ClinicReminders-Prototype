# Pre-Merge Checklist (Before Behavior Changes)

Run these commands from repo root:

1) Syntax check
```bash
python -m py_compile reminders_app_v3.py settings_pointer_utils.py
```

2) Unit tests
```bash
python -m unittest tests.test_settings_pointer_helpers tests.test_reminders_pointer_wrapper
```

3) Optional full discover
```bash
python -m unittest discover -s tests
```

## Intentional behavior-change workflow
- Add/adjust baseline fixture(s) first.
- Run tests before code changes.
- Make behavior change in small commit(s).
- Re-run tests and compare baseline outputs.
