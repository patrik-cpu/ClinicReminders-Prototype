# AGENTS.md

## Scope
Applies to the whole repository.

## Goal
Keep PR changes small and verifiable.

## Required checks before merging
- `python -m py_compile reminders_app_v3.py`
- `python -m unittest discover -s tests -p "test_ci_*.py"`

## Change policy
- Do not refactor unrelated logic.
- Prefer minimal, targeted fixes.
