# Apply conflict-resolution patch

Use this from your local clone that is on the latest `dev-reminders`:

```bash
git checkout dev-reminders
git pull
git apply --3way CONFLICT_RESOLUTION_PATCH.diff
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests
git add reminders_app_v3.py tests .github/workflows/ci.yml AGENTS.md
git commit -m "Apply conflict-resolved updates (safe reset, CI, tests, bundling)"
```

If `git apply --3way` reports conflicts, resolve only the marked conflict blocks and rerun tests.
