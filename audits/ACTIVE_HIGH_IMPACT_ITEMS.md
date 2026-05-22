# Active High-Impact Audit Items

Date: 2026-05-22

Scope: consolidated list of P0, P1, and otherwise high-impact items still treated as open after reviewing the audit/report markdowns in this repository. Older findings that later reports mark fixed or materially mitigated are not repeated here.

## Executive Summary

No active local P0 finding is confirmed by the latest reconciliation reports. The remaining high-impact work is mostly structural: shared Google Sheets/Drive tenancy, non-transactional Google mutations, missing browser/live smoke gates, a large Streamlit monolith, selected performance hot paths, and several UX flows that can cause user mistakes.

Important caveat: `reminders_app_v3.py` and `tests/test_ci_statistics.py` already had uncommitted changes before this documentation cleanup. The statistics/outcome item below may be in progress in those local edits and should be rechecked before implementation.

## Open P0 Items

None confirmed as active in the latest local reports.

Previously reported P0s that should not be re-opened without new evidence:

- Remember-login URL bearer tokens: marked fixed or materially mitigated by `SECURITY_AUDIT.md`, `AUTH_SETTINGS_FIX_RESULTS.md`, `MAIN_QA_REPORT.md`, and `SECOND_PASS_AUDIT.md`.
- Logout/stale remembered login restore: marked fixed by `AUTH_SETTINGS_FIX_RESULTS.md`.

## Open P1 / High-Impact Items

### P1: Shared Google backend tenant isolation remains application-enforced

Evidence: `SECOND_PASS_AUDIT.md`, `FINAL_REVIEW.md`, `CODEBASE_AUDIT.md`, `SECURITY_AUDIT.md`.

Why it matters: one broad Google service account and shared Sheets/Drive resources mean any missed clinic-id guard or stale session state can expose or mutate another clinic's data.

Suggested fix: split into a data-isolation hardening series. Centralize tenant-boundary checks, add delete/update dry-run plans, add multi-clinic mock tests for destructive paths, and evaluate stronger per-tenant storage boundaries.

Safe to do now? Split into separate security/data-isolation tasks.

### P1: Multi-step Google mutations are not transactional

Evidence: `SECOND_PASS_AUDIT.md`, `FINAL_REVIEW.md`, `CODEBASE_AUDIT.md`.

Why it matters: upload publish, dataset pointer updates, account deletion, and settings/tracker writes can partially complete across Drive, Sheets, and session state.

Suggested fix: document the state machine, add failure-injection tests around each external call boundary, make operations idempotent where possible, and add repair/retry paths before broader refactors.

Safe to do now? Split by operation, starting with dataset publish or account deletion.

### P1: Direct dataset publish can continue after existing dataset load failure

Evidence: `SECOND_PASS_AUDIT.md`.

Why it matters: a publish path that proceeds after failing to load existing saved data can overwrite or fork clinic data unexpectedly.

Suggested fix: add a regression test for existing-dataset load failure and fail closed unless the user explicitly chooses a recovery/replace path.

Safe to do now? Yes as a focused reliability fix.

### P1: No browser-level E2E suite or credentialed live Google CI gate

Evidence: `SECOND_PASS_AUDIT.md`, `MAIN_QA_REPORT.md`, `QUALITY_GATES_REPORT.md`, `CODEBASE_AUDIT.md`.

Why it matters: current tests cover helpers and some startup/login smoke paths, but not the full deployed login, upload, reminder action, stats, and Google persistence workflow.

Suggested fix: add one browser smoke path with mocked services for CI, then a separate credentialed live Google smoke gate for protected environments.

Safe to do now? Yes, but split mocked E2E and live credentialed checks.

### P1: Main Streamlit app remains too large and mixed-concern

Evidence: `SECOND_PASS_AUDIT.md`, `FINAL_REVIEW.md`, `CODEBASE_AUDIT.md`, `ARCHITECTURE_REFACTOR_PLAN.md`.

Why it matters: one large file owns auth, UI, Google I/O, upload ETL, reminders, analytics, CSS, and dormant code, increasing regression risk for small changes.

Suggested fix: extract tested pure helpers first, one module at a time, with characterization tests before each move.

Safe to do now? Only as small refactor tasks.

### P1: Outcome success may be undercounted for later sent reminder steps

Evidence: `SECOND_PASS_AUDIT.md`.

Why it matters: when multiple sent reminder steps exist for one item purchase cycle, deduping can select the wrong sent date and miss a repeat purchase inside the later post-reminder success window.

Suggested fix: revalidate against current uncommitted statistics changes, then add regression coverage for multiple sent steps in one purchase cycle and adjust dedupe/success matching semantics.

Safe to do now? Verify current dirty statistics work first.

### P1: Login/account lookup still relies on full settings-sheet scans

Evidence: `PERFORMANCE_SPEED_AUDIT.md`, `PERFORMANCE_GOOGLE_SHEETS_PASS.md`, `PERFORMANCE_REPORT_SECOND_PASS.md`.

Why it matters: password login, staff access, Google identity lookup, and remembered-session restore can become slow and quota-heavy as clinic count grows.

Suggested fix: add fake-sheet call-count tests for each login mode, then reuse authenticated row payloads and introduce safer indexed lookup paths without changing auth behavior.

Safe to do now? Yes as a focused performance task.

### P1: Cold Action tracker loads still read full tracker history

Evidence: `PERFORMANCE_SPEED_AUDIT.md`, `PERFORMANCE_REPORT_SECOND_PASS.md`, `PERFORMANCE_GOOGLE_SHEETS_PASS.md`.

Why it matters: large action histories can make first Reminders or Stats render slow because the app reads and filters the full tracker worksheet client-side.

Suggested fix: split current reminder state loading from full historical analytics loading, with call-count and large-history tests.

Safe to do now? Split into measurement first, then loader separation.

### P1: Upload publish still rewrites the full clinic dataset synchronously

Evidence: `PERFORMANCE_SPEED_AUDIT.md`, `PERFORMANCE_UPLOAD_PASS.md`, `PERFORMANCE_REPORT_SECOND_PASS.md`.

Why it matters: large clinics can hit long blocking saves and high memory use while the app downloads, merges, serializes, and uploads one full CSV file.

Suggested fix: measure parse/merge/serialize/upload phases and reduce duplicate in-memory copies first. Treat storage redesign as a separate project.

Safe to do now? Measurement and copy-lifetime reductions are safe; storage redesign should be separate.

### P1: Stats still performs expensive base calculations on selected views

Evidence: `PERFORMANCE_SPEED_AUDIT.md`, `PERFORMANCE_REPORT_SECOND_PASS.md`, `PERFORMANCE_STATISTICS_PASS.md`.

Why it matters: Stats has improved from older eager `st.tabs()` rendering, but selected Stats views can still compute broad generated/action/outcome/grouping artifacts before rendering.

Suggested fix: add phase timing and a `StatsRenderContext`, then lazily compute selected-view-only artifacts where summary cards do not need them.

Safe to do now? Measurement and extracted context are safe with tests.

### P1: Reminder badge/window work can duplicate table derivation

Evidence: `PERFORMANCE_SPEED_AUDIT.md`, `PERFORMANCE_DATAFRAME_PASS.md`, `PERFORMANCE_REPORT_SECOND_PASS.md`.

Why it matters: large DataFrame preparation and active-window grouping can happen more than once around one Reminders rerun.

Suggested fix: add call-count tests and pass the visible active-window result into badge/table rendering where semantics match.

Safe to do now? Yes with characterization tests.

### P1: Top Unreminded Items can scan large datasets on Configure Reminders

Evidence: `PERFORMANCE_SPEED_AUDIT.md`.

Why it matters: cache misses can run full item matching and grouping over the uploaded dataset whenever Configure Reminders renders after rule or exclusion changes.

Suggested fix: add timing and row/rule counts, then consider an aggregate-level cache if it matches current row-level behavior.

Safe to do now? Measurement first.

### P1: Account/profile/delete/password failures need more structured diagnostics

Evidence: `ERROR_HANDLING_REPORT.md`.

Why it matters: users may see safe generic messages while operators lose the sanitized failure context needed to support account and destructive flows.

Suggested fix: add sanitized `record_error_tracker_event` calls to unexpected account-flow exceptions and test the extracted action helpers.

Safe to do now? Yes, one account flow at a time.

### P1: Tracker write failures can still disappear silently

Evidence: `ERROR_HANDLING_REPORT.md`, `SECOND_PASS_AUDIT.md`.

Why it matters: audit, action, error, and performance events can be lost without local visibility.

Suggested fix: keep tracker writes non-blocking, but record a local diagnostic marker and consider bounded retry/queueing for action tracker writes.

Safe to do now? Yes as a focused observability task.

### P1: UX flows can cause incorrect reminder actions or setup mistakes

Evidence: `UX_UI_AUDIT.md`.

Why it matters: adjacent WhatsApp/Sent/Decline actions, `Send All` without confirmation, auto-saving uploads, dense Search Terms controls, narrow table layouts, and internal Stats terminology can lead to wrong action history or user abandonment.

Suggested fix: prioritize `Send All` confirmation, safer active reminder actions, upload review-before-save, and responsive reminder/search-term layouts.

Safe to do now? Split by user flow because several changes alter workflow behavior.

## Items Marked Fixed Or Materially Mitigated

- Authlib advisory: `requirements.txt` pins `authlib==1.6.12`.
- Remember-login token lifetime/URL behavior: current tests assert a 30-day maximum and query-param discard behavior.
- Weak new-password policy: password minimum and validation now live in `auth_password_utils.py`.
- Legacy MD5 login acceptance: current tests assert MD5 hashes are rejected by `verify_password`.
- Upload file/row/column/count limits: current code defines explicit limits and tests cover oversize cases.
- Raw user-facing exception leakage: later security addendum says user-facing errors were sanitized, with diagnostic details routed internally where available.
- Profile rename failure and delete ordering logic-edge findings: later reports/tests mark the original direct logic issues fixed.

## Validation Plan

- Re-run local gates after any code fix: `python -m py_compile reminders_app_v3.py settings_pointer_utils.py scripts/*.py`.
- Run focused tests for the touched area first, then `python -m unittest discover -s tests -p "test_ci_*.py"`.
- Run `bash scripts/pre_merge_check.sh` and `bash scripts/pilot_release_check.sh` for release-sensitive changes.
- Run live Google smoke only in an environment with credentials and disposable live data.
