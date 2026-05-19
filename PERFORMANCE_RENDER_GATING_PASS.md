# Performance Render Gating Pass

Date: 2026-05-19

## Executive Summary

Main-section gating is mostly healthy. Upload parsing runs only in Upload Data, Reminders preparation runs only in Reminders/Stats, Stats rendering runs only in Stats, and the remote action tracker is only loaded for Reminders/Stats when a pending-load marker exists.

The main remaining render cost is inside active sections. Streamlit executes all `st.tabs()` bodies during a rerun, so the Reminders view renders both Active and Actioned Reminders work, and the Stats view builds all five subviews, CSV exports, sorts, pagination controls, and display frames every time Stats renders. Recent passes reduced shared DataFrame work, but not the fact that inactive subtabs still do table/export/widget work.

The safest next fixes are not architectural rewrites. Prefer small gates and reuse:

- Add no-data/no-action early returns before rendering inactive/heavy tab bodies.
- Reuse already-computed active/actioned rows within Reminders.
- Avoid building export bytes for tables the user has not requested if the UI can preserve behavior with a stable download trigger.
- Add render-time measurements before replacing `st.tabs()` with a selected subview control.

## 1. Main-Section And Subtab Render Gates

### Main section gate

- Location: `reminders_app_v3.py:10918-10924`.
- Current behavior: `active_main_section` is derived from session/query state, then only the selected section body is rendered.
- Cost status: good. Inactive main sections do not render their full bodies.
- Caveat: `render_main_section_nav()` always calls `main_section_tab_label()` for every main tab, and the Reminders label may call `get_active_reminder_badge_count()`.
- Safest fix: keep nav behavior, but continue strengthening badge early returns and cache keys rather than hiding badge computation.
- Behavior risk: low.
- Tests needed: nav labels and badge still match existing behavior.
- Validation command: `python -m unittest tests.test_ci_reminders_badge tests.test_ci_get_started_badge`.

### Upload Data gate

- Location: `reminders_app_v3.py:10932-11374`.
- Current behavior: Upload UI and upload parsing only run when `active_main_section == "Upload Data"`.
- Cost status: good. File parsing is inside `if files:`.
- Caveat: saved dataset summary rendering runs on every Upload Data render and can repair history by loading a shared dataset if row counts are missing.
- Safest fix: cache/early-return summary repair attempts by existing `_row_count_repair_load_attempted_for`, which already exists, and avoid repeated summary box work when no saved rows/data exist.
- Behavior risk: low.
- Tests needed: saved dataset summary still repairs missing row counts once; no-data Upload Data view still shows empty-state caption.
- Validation command: `python -m unittest tests.test_ci_dataset_update`.

### Reminders section gate

- Location: `reminders_app_v3.py:15886-16018`.
- Current behavior: Reminders controls, prepared reminder rows, active reminder count, active window grouping, and reminder table render only run on Reminders.
- Cost status: good at main-section level.
- Caveat: `render_table()` uses `st.tabs(["Active Reminders", "Actioned Reminders"])`, and both tab bodies are executed.
- Safest fix: add cheap no-action early return around actioned reminder tab data work or move actioned rows into a precomputed context reused by the active/actioned views.
- Behavior risk: low for no-action early return; medium for replacing tabs.
- Tests needed: Active table and Actioned table outputs remain unchanged with sent, declined, and empty action states.
- Validation command: `python -m unittest tests.test_ci_reminders_badge tests.test_ci_reminder_workflows`.

### Stats section gate

- Location: `reminders_app_v3.py:16020-16021`; `render_stats_tab()` at `reminders_app_v3.py:15278-15535`.
- Current behavior: Stats setup and rendering run only on Stats.
- Cost status: good at main-section level.
- Caveat: `st.tabs()` renders Items, Item Actioning, Team, Sent Reminders, and Successes every Stats run.
- Safest fix: continue extracting a `StatsRenderContext` and add targeted no-data skips; defer subview-level render gating until a UI decision is made.
- Behavior risk: medium if tab mechanics change; low for shared-context/no-data skips.
- Tests needed: all five Stats tables remain identical.
- Validation command: `python -m unittest tests.test_ci_statistics`.

### Search Terms and Exclusions gates

- Locations: `reminders_app_v3.py:15871` and `16023-16445`.
- Current behavior: editor sections only render when active.
- Cost status: mostly good.
- Caveat: Search Terms renders paginated current rules and many widgets on that section; Exclusions renders all exclusion groups when active.
- Safest fix: leave unless user-reported latency appears. Current pagination already limits Search Terms rows.
- Behavior risk: low.
- Tests needed: settings save-state and audit tests.
- Validation command: `python -m unittest tests.test_ci_settings_save_state tests.test_ci_audit_characterization`.

## 2. Inactive Tabs/Subviews Still Building Heavy Work

### Finding P1: Stats subtabs all build frames and exports on every Stats render

- Function/location: `render_stats_tab()` at `reminders_app_v3.py:15406-15535`.
- Repeated render work:
  - Items builds item outcome group frame, export bytes, sort/page controls, display frame.
  - Item Actioning builds generated/action item frame, export bytes, sort/page controls, display frame.
  - Team builds sender group frame, merged team frame, export bytes, sort/page controls, display frame.
  - Sent Reminders filters/sorts sent rows, export bytes, sort/page controls, display frame.
  - Successes filters/sorts success rows, export bytes, sort/page controls, display frame.
- Expected UI/server cost: high on large histories because all subviews render even if only one tab is visible. CSV export hashing/serialization and `st.dataframe` display prep add cost.
- Safest fix: keep `st.tabs()` for now but build shared inputs once, then add no-data skips before exports/display prep. Larger fix is a selected subview control outside tabs or a stable render-mode state, but that changes UI mechanics.
- Behavior risk: low for no-data skips; medium for tab replacement.
- Tests needed: export bytes and displayed frames unchanged for all five views; empty views still show same messages.
- Validation command: `python -m unittest tests.test_ci_statistics`.

### Finding P1: Reminders tabs render actioned data while user is on Active Reminders

- Function/location: `render_table()` at `reminders_app_v3.py:11380-11400`; `render_actioned_reminders_tab()` at `reminders_app_v3.py:11998`.
- Repeated render work: active reminders table is filtered/rendered, then actioned reminder period selector, actioned rows, sorting, pagination, header buttons, and undo buttons are also built during the same rerun.
- Expected UI/server cost: medium. Actioned histories are capped, but each render parses action timestamps and builds row widgets for the selected actioned period.
- Safest fix: compute `actioned_rows = get_actioned_reminders_for_period(selected_period)` once and return early before header/style/widget construction when empty. Larger fix is replacing tabs with a selected control or separate main subview.
- Behavior risk: low for empty early return; medium for tab replacement.
- Tests needed: empty actioned tab still shows same info; sent/declined actioned rows still sort/render.
- Validation command: `python -m unittest tests.test_ci_reminder_workflows tests.test_ci_reminders_badge`.

### Finding P2: Search Terms current rules render still builds all visible row widgets

- Function/location: `render_search_terms_editor()` at `reminders_app_v3.py:15748-15839`.
- Repeated render work: current Search Terms rows are paginated, but each visible row creates multiple text inputs, checkbox, delete button, markdown labels, and autosave callbacks.
- Expected UI/server cost: medium for users with many rules, though pagination limits the visible row count.
- Safest fix: no immediate change; widget construction is required for edit behavior. Consider a collapsed edit mode per row only if users report latency.
- Behavior risk: medium if edit workflow changes.
- Tests needed: save-state/audit tests for all editable fields.
- Validation command: `python -m unittest tests.test_ci_settings_save_state tests.test_ci_audit_characterization`.

## 3. Reminder Table Per-Row Render Work

### Finding P1: Active reminder rows still build many widgets per visible page

- Function/location: `render_table_with_buttons()` at `reminders_app_v3.py:12135-12255`.
- Repeated render work:
  - Sorts the full active frame.
  - Paginates to visible rows.
  - Converts each visible row to dict.
  - Looks up hidden action state.
  - Builds per-row column layouts, markdown cells, WhatsApp/Sent/Decline buttons.
  - Builds one batch CSS block for all row action states.
- Expected UI/server cost: high for visible page size because Streamlit widgets are expensive. Current pagination and CSS batching help.
- Safest fix: keep pagination and keys. Next small win is reusing a hidden-reminder index passed into `render_table_with_buttons()` so per-row `get_hidden_reminder_record()` does not refetch the session cache repeatedly.
- Behavior risk: low if optional arg defaults preserve current behavior.
- Tests needed: sent/declined selected styling and action state still match; widget keys unchanged.
- Validation command: `python -m unittest tests.test_ci_reminders_badge tests.test_ci_reminder_workflows`.

### Finding P2: Actioned reminder rows parse dates repeatedly

- Function/location: `get_actioned_reminders_for_period()`, `sort_actioned_reminders()`, `format_actioned_reminder_date()` at `reminders_app_v3.py:11924-12120`.
- Repeated render work: actioned timestamp is parsed for filtering, sorting, and display.
- Expected UI/server cost: medium on large action histories.
- Safest fix: similar to Stats action parsing: add an internal parsed timestamp key to copied actioned rows, use it for filter/sort/display, and strip/avoid displaying helper keys.
- Behavior risk: low if fallback parsing remains.
- Tests needed: actioned rows sort and dates match before/after.
- Validation command: `python -m unittest tests.test_ci_reminder_workflows tests.test_ci_reminders_badge`.

## 4. Upload Tab Render/Re-Render Work When No Files Change

### Finding P2: Saved dataset summary may repair row counts during render

- Function/location: `get_saved_dataset_summary_rows()` at `reminders_app_v3.py:9374-9401`; Upload Data caller at `reminders_app_v3.py:10944`.
- Repeated render work: when history rows exist with missing/zero row counts and no working DataFrame is loaded, the render path can trigger `load_shared_dataset_for_clinic()` once per history fingerprint.
- Expected UI/server cost: potentially high Drive read/parse on Upload Data render, but guarded by `_row_count_repair_load_attempted_for`.
- Safest fix: preserve repair behavior, but surface a pending repair state or background-style prompt rather than doing Drive load in a render helper. If not changing behavior, keep current guard.
- Behavior risk: medium if repair timing changes.
- Tests needed: row count repair still happens once and saved summary appears.
- Validation command: `python -m unittest tests.test_ci_dataset_update`.

### Finding P2: Dataset summary table rebuilds markdown/button rows each render

- Function/location: `render_dataset_summary_box()` at `reminders_app_v3.py:9316-9368`.
- Repeated render work: each saved upload row creates columns, markdown cells, row hash, and Remove button.
- Expected UI/server cost: low-to-medium. Upload history is usually small.
- Safest fix: no immediate change; remove buttons require stable per-row keys. If history grows, add display limit/pagination.
- Behavior risk: low for pagination if keys remain stable.
- Tests needed: remove button still removes correct upload row.
- Validation command: `python -m unittest tests.test_ci_dataset_update`.

### Finding P2: File-name set comparison misses duplicate same-name changes

- Function/location: Upload file-change detection at `reminders_app_v3.py:10991-11010`.
- Repeated render work: not directly a performance cost, but current `set(current_files)` ignores duplicate filenames and ordering.
- Expected UI/server cost: possible stale upload state if two selected files share names or contents change under same names.
- Safest fix: use upload fingerprints from `_to_blob()` rather than just names, but this requires reading bytes before change detection.
- Behavior risk: medium.
- Tests needed: same file name with changed bytes triggers refresh; duplicate names handled.
- Validation command: `python -m unittest tests.test_ci_dataset_update`.

## 5. Stats Tab Subview Work And Export Preparation

### Finding P1: CSV exports are prepared during render for every non-empty Stats subview

- Function/location: `render_stats_csv_export()` at `reminders_app_v3.py:15117`; calls in `render_stats_tab()` at `15416`, `15440`, `15481`, `15510`, `15529`.
- Repeated render work: each export call computes a frame fingerprint, prepares display/export values, formats numeric/currency values, serializes CSV bytes, and creates a download button.
- Expected UI/server cost: high on large Stats tables. Recent multi-entry cache avoids repeated serialization across reruns, but initial render still prepares all exports.
- Safest fix: add an explicit "Prepare CSV" button per table, or lazy-create export bytes only after a per-table session flag is set. This changes interaction by one click, so it should be split and approved.
- Behavior risk: medium because download availability changes.
- Tests needed: export bytes unchanged after prepare; widget keys stable; empty exports hidden.
- Validation command: `python -m unittest tests.test_ci_statistics`.

### Finding P1: Outcome group frames are still built for inactive Stats tabs

- Function/location: item group at `reminders_app_v3.py:15412`; sender group inside team at `15466`.
- Repeated render work: groupby + summarize for Items and Team every Stats render.
- Expected UI/server cost: medium-to-high depending on outcome row count.
- Safest fix: build both group frames once in the Stats busy block and pass them into tab bodies. This does not stop inactive tab work, but avoids mixing heavy compute with widget render and makes future gating easier.
- Behavior risk: low if frames compare identical.
- Tests needed: item and sender group frames unchanged.
- Validation command: `python -m unittest tests.test_ci_statistics`.

### Finding P2: Sent and Successes tables sort full outcome subsets on every Stats render

- Function/location: sent rows at `reminders_app_v3.py:15507`; success rows at `15524`.
- Repeated render work: full subset sorting before pagination/display.
- Expected UI/server cost: medium for large histories.
- Safest fix: precompute sorted sent/success rows once after `period_rows` is known, or add a display limit before export/display. Preserve full export behavior if adding display limits.
- Behavior risk: low for precompute; medium for display limits.
- Tests needed: row order and exports unchanged.
- Validation command: `python -m unittest tests.test_ci_statistics`.

## 6. Google Sheets/Drive Calls Triggered During Render

### Finding P1: Action tracker load can happen before Reminders/Stats body render

- Function/location: main gate at `reminders_app_v3.py:10919-10920`; `ensure_action_tracker_loaded_for_current_clinic()` at `4495`; `load_action_tracker_records_for_clinic()` at `5303`.
- Render-time API calls: if `_action_tracker_pending_load_for` matches the clinic, opening Reminders or Stats calls Google Sheets `get_all_values()` for the action tracker.
- Expected UI/server cost: high for large tracker sheets; currently session-cached by clinic/timezone and only pending-load gated.
- Safest fix: keep current gate, but avoid setting `_action_tracker_pending_load_for` except when login/refresh truly needs it. Longer-term: split current reminder action state from long-term Stats history.
- Behavior risk: medium for load timing changes.
- Tests needed: login/load settings still populates deleted reminders; refresh stats still syncs remote actions.
- Validation command: `python -m unittest tests.test_ci_auth_session tests.test_ci_reminder_workflows tests.test_ci_statistics`.

### Finding P1: Upload summary repair can trigger Drive download during render

- Function/location: `get_saved_dataset_summary_rows()` at `reminders_app_v3.py:9374-9401`; `load_shared_dataset_for_clinic()` at `3289`.
- Render-time API calls: missing row-count metadata can call Drive lookup/download and upload parsing from within the Upload Data render path.
- Expected UI/server cost: high but guarded to one attempt per clinic/history fingerprint.
- Safest fix: leave guard in place unless repair latency is visible; otherwise move repair behind a user-visible "Repair summary" action.
- Behavior risk: medium.
- Tests needed: existing summary repair tests plus upload startup.
- Validation command: `python -m unittest tests.test_ci_dataset_update tests.test_ci_streamlit_startup`.

### Finding P2: Tracker worksheet setup can happen during event recording

- Function/location: `append_tracker_row()` / `append_tracker_rows()` at `reminders_app_v3.py:6590-6615`; `get_or_create_tracker_sheet()` at `6566`.
- Render-time API calls: normal render does not append, but render-triggered warnings/repairs/errors can record tracker events and set up worksheet headers.
- Expected UI/server cost: low during normal render, high during first tracker use.
- Safest fix: keep `ensure_tracking_sheets_once()` resource cache. Avoid adding tracker writes to pure render helpers.
- Behavior risk: low.
- Tests needed: tracker append failure remains fail-safe.
- Validation command: `python -m unittest tests.test_ci_error_handling`.

## 7. Low-Risk Opportunities To Defer, Reuse, Or Early-Return Render Work

### 1. Precompute actioned reminder timestamps once per Reminders render

- Function/location: `get_actioned_reminders_for_period()`, `sort_actioned_reminders()`, `format_actioned_reminder_date()`.
- Repeated render work: parses action timestamps multiple times for the Actioned Reminders tab.
- Expected benefit: less CPU on actioned histories.
- Safest fix: copied rows get internal `_ActionedDateTime` used by filter/sort/display.
- Behavior risk: low.
- Tests needed: actioned sort/date output unchanged.
- Validation command: `python -m unittest tests.test_ci_reminder_workflows tests.test_ci_reminders_badge`.

### 2. Pass hidden reminder index into active reminder row rendering

- Function/location: `render_table_with_buttons()` and `get_hidden_reminder_record()`.
- Repeated render work: each visible active row calls into the hidden reminder index lookup path.
- Expected benefit: small-to-medium depending on page size.
- Safest fix: optional `hidden_index` arg with default fallback; widget keys unchanged.
- Behavior risk: low.
- Tests needed: active row action state/styling unchanged.
- Validation command: `python -m unittest tests.test_ci_reminders_badge tests.test_ci_reminder_workflows`.

### 3. Build Stats item/sender group frames inside the shared busy block

- Function/location: `render_stats_tab()`.
- Repeated render work: grouping work is performed inside individual tab bodies.
- Expected benefit: easier future gating, clearer single compute phase, same output.
- Safest fix: compute `stats_item_outcome_frame` and `stats_sender_outcome_frame` once after `stats_outcome_rows`.
- Behavior risk: low.
- Tests needed: group frame outputs unchanged.
- Validation command: `python -m unittest tests.test_ci_statistics`.

### 4. Add no-data guards before Stats export preparation

- Function/location: `render_stats_tab()` calls to `render_stats_csv_export()`.
- Repeated render work: mostly already guarded by `render_stats_csv_export()`, but callers still build/sort some empty frames.
- Expected benefit: small.
- Safest fix: branch before sorting/exporting sent/success rows when `period_rows.empty`.
- Behavior risk: low.
- Tests needed: empty Stats views still show existing info text.
- Validation command: `python -m unittest tests.test_ci_statistics`.

### 5. Measure render phases before changing `st.tabs()`

- Function/location: `render_table()`, `render_table_with_buttons()`, `render_stats_tab()`.
- Repeated render work: uncertain distribution between DataFrame compute, CSV export, and widget construction.
- Expected benefit: guides next changes and avoids speculative UI work.
- Safest fix: use existing performance tracker only for coarse timings, avoiding sensitive data.
- Behavior risk: low if measurement only.
- Tests needed: tracker event sanitization/failure tests.
- Validation command: `python -m unittest tests.test_ci_error_handling tests.test_ci_statistics`.

### 6. Consider a selected Stats subview after measurement

- Function/location: `render_stats_tab()`.
- Repeated render work: all five `st.tabs()` bodies.
- Expected benefit: potentially largest render reduction.
- Safest fix: replace tabs with a segmented control only if preserving UX is acceptable; keep widget keys for each table unchanged.
- Behavior risk: medium.
- Tests needed: all table outputs and widget keys still available after switching views.
- Validation command: `python -m unittest tests.test_ci_statistics tests.test_ci_streamlit_startup`.

### 7. Consider a selected Reminders subview after measurement

- Function/location: `render_table()`.
- Repeated render work: active and actioned tab bodies.
- Expected benefit: medium.
- Safest fix: selected control or stable session flag; preserve Active Reminders default.
- Behavior risk: medium.
- Tests needed: active/actioned workflows, undo, sent, decline, Send All.
- Validation command: `python -m unittest tests.test_ci_reminder_workflows tests.test_ci_reminders_badge`.

## Recommended Patch Order

1. Precompute actioned reminder timestamps once and reuse for filter/sort/display.
2. Pass the hidden reminder index into active reminder row rendering.
3. Precompute Stats item/sender group frames once in the shared Stats compute block.
4. Add empty `period_rows` guards before sent/success sorting and export prep.
5. Add coarse render timing measurements for Reminders and Stats.
6. After measurement, decide whether replacing `st.tabs()` with selected subview controls is worth the UI behavior change.

## Validation Commands

```bash
python -m py_compile reminders_app_v3.py settings_pointer_utils.py
python -m unittest tests.test_ci_reminders_badge
python -m unittest tests.test_ci_reminder_workflows
python -m unittest tests.test_ci_statistics
python -m unittest tests.test_ci_dataset_update
python -m unittest tests.test_ci_error_handling
python -m unittest discover -s tests -p "test_ci_*.py"
bash scripts/pre_merge_check.sh
```
