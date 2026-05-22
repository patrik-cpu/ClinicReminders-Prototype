# Merged Audit Index

Date: 2026-05-22

This index de-duplicates the audit markdowns moved into `audits/archive/`. It does not delete the historical reports; it explains which files are the current source of truth for each topic and which older files are superseded or partially superseded.

## Current Source Of Truth

- Active high-impact backlog: `ACTIVE_HIGH_IMPACT_ITEMS.md`
- Latest broad reconciliation: `archive/SECOND_PASS_AUDIT.md`
- Pilot/release posture: `archive/MAIN_QA_REPORT.md`, `archive/FINAL_REVIEW.md`, `../PRE_PRODUCTION_CHECKLIST.md`, `archive/LIVE_GOOGLE_SMOKE_TEST.md`
- Auth-specific closure notes: `archive/AUTH_SETTINGS_FIX_RESULTS.md`
- Security history plus remediation addendum: `archive/SECURITY_AUDIT.md`
- Latest speed reconciliation: `archive/PERFORMANCE_SPEED_AUDIT.md`, `archive/PERFORMANCE_SPEED_FIX_RESULTS.md`

## Merged Groups

### Security, Auth, And Release Readiness

Use these together:

- `archive/SECURITY_AUDIT.md`
- `archive/AUTH_SETTINGS_AUDIT.md`
- `archive/AUTH_SETTINGS_FIX_RESULTS.md`
- `archive/SECOND_PASS_AUDIT.md`
- `archive/MAIN_QA_REPORT.md`
- `archive/FINAL_REVIEW.md`

Merged conclusion:

- No active local P0 is confirmed by the latest reports.
- Remember-login URL/stale-restore findings are fixed or materially mitigated.
- Authlib is patched to `1.6.12`.
- Remaining high-impact security/release concerns are shared-backend tenant isolation, non-transactional Google mutations, live Google validation, and the absence of browser-level E2E.

### Performance

Use `archive/PERFORMANCE_SPEED_AUDIT.md` as the current performance triage. It already reviewed and reconciled the older performance reports:

- `archive/PERFORMANCE_REPORT.md`
- `archive/PERFORMANCE_REPORT_SECOND_PASS.md`
- `archive/PERFORMANCE_GOOGLE_SHEETS_PASS.md`
- `archive/PERFORMANCE_RENDER_GATING_PASS.md`
- `archive/PERFORMANCE_STREAMLIT_RENDER_PASS.md`
- `archive/PERFORMANCE_DATAFRAME_PASS.md`
- `archive/PERFORMANCE_STATISTICS_PASS.md`
- `archive/PERFORMANCE_CACHE_EARLY_RETURN_PASS.md`
- `archive/PERFORMANCE_UPLOAD_PASS.md`
- `archive/PERFORMANCE_SPEED_FIX_RESULTS.md`

Merged conclusion:

- Old eager Stats `st.tabs()` rendering and unpaginated actioned-reminder rendering are no longer current in the same form.
- The remaining performance backlog is login/account full-sheet scans, full Action tracker loads, synchronous full-dataset upload publish, selected-view Stats base cost, duplicate reminder badge/window work, and Top Unreminded Items cache-miss cost.

### Error Handling, Logic, UX, And Maintainability

Use these for targeted follow-up tasks:

- `archive/ERROR_HANDLING_REPORT.md`
- `archive/LOGIC_EDGE_CASE_REPORT.md`
- `archive/UX_UI_AUDIT.md`
- `archive/DEAD_CODE_REPORT.md`
- `archive/DUPLICATION_REPORT.md`
- `archive/ARCHITECTURE_REFACTOR_PLAN.md`
- `archive/CODEBASE_AUDIT.md`

Merged conclusion:

- The original direct logic-edge P1s around helper validation, profile rename, delete ordering, and malformed statistics records were later marked fixed or covered by tests.
- Error-handling follow-up remains around structured diagnostics for account flows and visible/local handling for tracker write failures.
- UX P1s remain product-flow work, especially safer reminder actions, `Send All` confirmation, upload review-before-save, responsive layouts, and simpler Search Terms/Stats language.
- Maintainability remains dominated by the large mixed-concern Streamlit module and dormant/duplicate code.

### Dependencies And Quality Gates

Use these together:

- `archive/DEPENDENCY_AUDIT.md`
- `archive/QUALITY_GATES_REPORT.md`
- `../PRE_PRODUCTION_CHECKLIST.md`

Merged conclusion:

- The specific Authlib advisory called out by the dependency audit is fixed in `requirements.txt`.
- Reproducible dependency locking, formal formatting/linting/type/security/secret-scan gates, and a dependency vulnerability audit remain deferred quality work.
- Do not make broad formatting or lint gates blocking until a cleanup/configuration pass is done.

## Historical Reports Kept For Evidence

The older reports remain in this folder because they contain evidence, line references, and validation history. Prefer the merged conclusions above when an older finding conflicts with a later fix/result report.

When starting a new fix, copy only the relevant current item from `ACTIVE_HIGH_IMPACT_ITEMS.md` into the task plan, then validate against current code before editing.
