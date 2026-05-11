# Quick PR Workflow (No Terminal Required)

If Codex has already edited files in your branch and you can see the diff in GitHub, you usually **do not need terminal commands**.

## What to do in GitHub UI

1. Open your branch (for example: `dev-reminders`).
2. Click **Compare & pull request**.
3. Verify:
   - **base** = `dev-reminders`
   - **compare** = your Codex branch
4. In the **Files changed** tab, confirm app files are included when expected (for this project, `reminders_app_v3.py` should appear for app behavior/refactor changes).
5. Create PR.

## When terminal commands are still needed

Only when the branch in GitHub is not current yet (for example local commits were never pushed), or when there are merge/rebase conflicts that must be resolved locally.

## Conflict tip

Do **not** always pick “Incoming change.”
Review each conflict and keep the version that matches intended behavior; then run tests before merging.
