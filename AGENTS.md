# AGENTS.md

## Scope
This file applies to the entire repository.

## CI expectations
- Keep `.github/workflows/ci.yml` green.
- At minimum, ensure these commands pass before opening a PR:
  - `python -m py_compile reminders_app_v3.py`
  - `python -m unittest discover -s tests`

## Change policy
- Prefer minimal, targeted changes.
- Do not refactor unrelated app logic when fixing bugs.
