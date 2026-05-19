# Performance Streamlit Render Pass

Date: 2026-05-19

## 1. Streamlit Render Loops That Scale With Row Count

This pass rechecked the current code, not the stale line numbers in `PERFORMANCE_REPORT.md`. The old report's main concern is still real, but partially improved: active reminders and Stats now use 50-row pagination, while Actioned Reminders and several settings/list editors still render all rows as individual Streamlit widgets.

| Severity | Area | Current render loop | Affected tab/page | Evidence |
| --- | --- | --- | --- | --- |
| P1 | Actioned Reminders | Renders every filtered actioned row with `st.columns`, many markdown cells, and an Undo button. No pagination. | Reminders > Actioned Reminders | `render_actioned_reminders_tab()` loops over `rows` at `reminders_app_v3.py:11830`. |
| P1 | Active Reminders | Paginated to 50 rows, but each visible row renders row-specific CSS, `st.columns`, 8 markdown cells, and 3 buttons. | Reminders > Active Reminders | `render_table_with_buttons()` paginates at `reminders_app_v3.py:11858`, then loops at `reminders_app_v3.py:11918`. |
| P1 | Search Terms editor | Renders every rule as an 8-column widget row: text inputs, checkbox, delete button, markdown. | Search Terms | Current rules loop starts at `reminders_app_v3.py:15275`. |
| P2 | Exclusions lists | Renders every exclusion with columns, markdown, and remove buttons. There are separate loops for client, patient, client-specific item, general item, automatic keywords, and automatic patients. | Exclusions | Examples: `reminders_app_v3.py:15538`, `15682`, `15756`, `15846`, `15921`. |
| P2 | Saved upload summary | Renders every saved upload row with columns, markdown, hash generation, and a Remove button. Usually small. | Upload Data | `render_dataset_summary_box()` loops at `reminders_app_v3.py:9281`. |
| P2 | Statistics render preparation | Uses `st.dataframe` and pagination, but prepares/export-converts full frames and builds column configs on render. | Stats | `render_outcome_dataframe()` paginates at `reminders_app_v3.py:14735`; CSV export prepares all rows before display. |
| P3 | Factoids metric cards | Loops over metric card groups and creates `st.columns(5)` per row of cards. Count is bounded by metric definitions, not uploaded row count. | Legacy/factoids area | `cardgroup()` starts at `reminders_app_v3.py:16920`. |

## 2. Per-Row Calls

### Active Reminders

`render_table_with_buttons()`:

- Sorts and paginates the full DataFrame: `reminders_app_v3.py:11857-11858`.
- Converts the visible page with `iterrows()`/`to_dict()`: `reminders_app_v3.py:11859`, `11918-11920`.
- Per visible row:
  - `render_reminder_action_button_styles()` emits a `<style>` block: `reminders_app_v3.py:11927`.
  - `st.columns(col_widths, gap="small")`: `reminders_app_v3.py:11929`.
  - 8 markdown cell writes: `reminders_app_v3.py:11932-11936`.
  - 3 buttons: WhatsApp, Sent, Decline at `reminders_app_v3.py:11939`, `11948`, `11957`.
- At 50 rows this is roughly 50 style blocks, 50 column rows, 400 markdown cells, and 150 row buttons, plus header and footer controls.

### Actioned Reminders

`render_actioned_reminders_tab()`:

- Filters and sorts list records in Python: `reminders_app_v3.py:11759-11763`.
- Does not call `paginate_dataframe()`.
- Per row:
  - `st.columns(col_widths, gap="small")`: `reminders_app_v3.py:11831`.
  - 9 markdown cell writes: `reminders_app_v3.py:11832-11844`.
  - 1 Undo button: `reminders_app_v3.py:11846`.
- The "All" period can scale with the whole action history in session.

### Search Terms

`render_search_terms_editor()`:

- Current rules loop: `reminders_app_v3.py:15275`.
- Per rule:
  - `st.columns(rule_col_widths, gap="small")`: `reminders_app_v3.py:15279`.
  - one markdown cell for term text.
  - four reminder-day text inputs.
  - one checkbox.
  - one visible-text input.
  - one delete button.
- This is useful for editing, but it is expensive for clinics with large rule sets.

### Exclusions

The Exclusions tab has several all-row editor lists:

- Client exclusions: `reminders_app_v3.py:15538-15545`.
- Patient exclusions: `reminders_app_v3.py:15598-15611`.
- Client-specific item exclusions: `reminders_app_v3.py:15682-15695`.
- General item exclusions: `reminders_app_v3.py:15756-15763`.
- Automatic death keywords: `reminders_app_v3.py:15846-15856`.
- Automatically added patients: `reminders_app_v3.py:15921-15932`.

Each visible item creates a row of columns, at least one markdown block, and one remove button. These are lower traffic than active reminders, but automatic patient exclusions can grow after uploads.

### Stats

Stats is better than the hand-built tables:

- Main outcome tables use `st.dataframe`, column config tooltips, and pagination through `paginate_dataframe()`: `reminders_app_v3.py:14735-14743`.
- Item Actioning and Team also paginate before `st.dataframe`: `reminders_app_v3.py:14965-15008`.
- CSV export intentionally covers every row, not just the visible page. That is correct behavior, but it does convert full frames before rendering the download button.

## 3. Tabs/Pages Affected

- Reminders: Active Reminders and Actioned Reminders are the highest-impact manual render paths.
- Search Terms: the current rules editor can become widget-heavy.
- Exclusions: all exclusion subsections are unpaginated widget lists.
- Upload Data: saved upload summary is row-based but usually small.
- Stats: mostly safe due to `st.dataframe` plus pagination; the render cost is more from data preparation and CSV conversion than DOM/widget count.
- Legacy/factoids area: bounded card rendering; not currently a top concern.

## 4. Estimated User-Visible Impact

These are qualitative estimates based on Streamlit widget count and DOM payload, not measured timings.

| Rows visible/rendered | Active Reminders | Actioned Reminders | Search Terms | Exclusions | Stats |
| --- | --- | --- | --- | --- | --- |
| 25 | Usually acceptable, but still injects 25 style blocks and 75 row buttons. | Usually acceptable. | Fine unless autosave callbacks fire often. | Fine. | Fine. |
| 100 | Active page still shows 50 due to pagination, so visible DOM is capped; full-frame sort still runs. | Noticeable delay and heavier browser DOM; 100 Undo buttons. | Noticeable if every rule has editable widgets. | Noticeable with many subsections. | Fine if page size remains 50; data prep may dominate. |
| 250 | Active visible DOM remains capped, but repeated per-row CSS still wasteful. | Likely sluggish, especially "All"; 250 column rows and 250 buttons. | Likely sluggish; hundreds of text inputs/check boxes. | Can be sluggish for automatic exclusions. | Acceptable for render; may need data-prep profiling. |
| 500 | Active table still capped but each page is widget-heavy; navigation should remain usable. | High risk of slow reruns and browser jank. | High risk if 500 rules, though unlikely. | High risk for automatic exclusions after many matches. | `st.dataframe` should cope better; full export conversion may become noticeable. |

## 5. Safe Pagination, Show-More, Or Row Limits

Safe candidates:

- Actioned Reminders: add `paginate_dataframe()` or an equivalent list paginator after sorting and before row rendering. This is the safest large win because it preserves the selected period and sort, but caps widgets per render.
- Search Terms: add pagination or an "Edit all / show first 50" pattern only if clinics can realistically exceed 50 rules. Because this is an editor, test carefully to avoid losing unsaved widget state.
- Exclusions: add simple pagination per subsection or collapse long sections behind expanders. This is safest for automatic patient exclusions and client-specific exclusions.
- Saved upload summary: likely no pagination needed unless upload history is allowed to grow without bound.
- Active Reminders: already paginated at 50 rows; keep the current behavior.
- Stats: already paginated at 50 rows for visible tables. Keep export as all rows because user explicitly requested that.

Risk notes:

- Active Reminder button keys currently use the DataFrame index after pagination. Changing pagination or row construction can affect widget identity, so tests should assert stable action callbacks.
- Search Terms and Exclusions write settings on small edits. Pagination must not hide rows with pending widget changes or change delete-key identity.

## 6. Static CSS That Can Be Injected Once

Highest-confidence CSS cleanup:

- `render_reminder_action_button_styles()` injects a large `<style>` block once per active reminder row at `reminders_app_v3.py:11567-11631`.
- Most of that CSS is static button styling. Only selected/disabled visual state varies by row.
- Small safe direction:
  - Inject static classes once per table render for WhatsApp/Sent/Decline button base styling.
  - Keep a very small per-row style or add row-specific classes only for selected sent/declined state.

Already reasonable:

- Active and actioned header sort button CSS is injected once per table render, not per row: `reminders_app_v3.py:11780` and `11863`.
- App-wide CSS is injected near module setup, not inside row loops.

Other possible CSS cleanups:

- Exclusion chip/list styling appears mostly app-wide or section-level; no obvious large repeated style block was found there.
- Factoid card HTML uses inline styles per card, but card count is bounded and not a priority.

## 7. Findings Ranked

### P1: Actioned Reminders Renders All Rows

Evidence: `render_actioned_reminders_tab()` loops over all filtered rows at `reminders_app_v3.py:11830` and creates `st.columns`, markdown cells, and an Undo button for each row.

Why it matters: the "All" period can include a clinic's full action history. This creates many widgets and DOM nodes and slows reruns.

Smallest safe fix: paginate `rows` after `sort_actioned_reminders()` and before rendering headers/rows. Use the existing `TABLE_PAGE_SIZE` of 50 and copy the caption/buttons pattern from `paginate_dataframe()` or add a list paginator helper.

Validation:

- Unit test that a 120-row actioned list renders page 1 with stable first/last visible row after sorting.
- Unit test or source check that actioned pagination uses 50 rows.
- Manual Streamlit check: Daily/Weekly/Monthly/All periods, Previous/Next buttons, Undo still works.

### P1: Active Reminder Rows Inject Per-Row CSS

Evidence: `render_table_with_buttons()` calls `render_reminder_action_button_styles()` inside the visible row loop at `reminders_app_v3.py:11927`; that function emits a full `<style>` block at `reminders_app_v3.py:11567`.

Why it matters: active reminders are capped to 50 visible rows, but 50 duplicate style blocks per rerun is still unnecessary DOM/websocket payload and makes the most-used page heavier than needed.

Smallest safe fix: split static action-button CSS into one table-level injection and keep only dynamic selected-state styling per row. A second step could replace selected-state per-key CSS with CSS classes if Streamlit key selectors remain reliable.

Validation:

- Source-level regression test that the row loop no longer calls the full style helper.
- Manual active reminder check: WhatsApp icon, sent/decline styling, selected hidden-reminder state, Send All, and mobile width.

### P1: Search Terms Editor Renders Every Rule As Widgets

Evidence: current rules loop starts at `reminders_app_v3.py:15275` and builds an 8-column editor row with multiple inputs per search term.

Why it matters: text inputs and checkboxes are heavier than display-only cells. If clinics add many search terms, the Search Terms tab can become slow and visually dense.

Smallest safe fix: add a search/filter box or paginate current rules at 50 per page. Keep add-new controls outside pagination.

Validation:

- Characterization test for delete/edit callback keys.
- Manual check with 75+ rules: edit visible row, delete row, navigate pages, refresh.

### P2: Exclusion Lists Are Unpaginated Widget Lists

Evidence: multiple loops render all exclusions with `st.columns`, markdown, and remove buttons: `reminders_app_v3.py:15538`, `15682`, `15756`, `15846`, `15921`.

Why it matters: exclusions are less frequently used, but automatic patient exclusions can grow with upload size and death-keyword matches.

Smallest safe fix: paginate the automatic patient exclusions first, then client-specific item exclusions. Leave tiny lists alone.

Validation:

- Unit tests around normalization/delete behavior.
- Manual check that deleting an item on page 2 deletes the correct exclusion and preserves sorting.

### P2: Stats Export Conversion Runs For Full View On Render

Evidence: `render_stats_csv_export()` copies/prepares the full frame and builds CSV bytes before showing the download button.

Why it matters: this is correct for full-table export, but it means viewing a Stats tab pays export-prep cost even if the user does not click export.

Smallest safe fix: measure first. If needed, cache `prepare_stats_csv_export_frame()`/CSV bytes by frame hash and active view, or place CSV generation behind an explicit "Prepare CSV" button. Do not change export content.

Validation:

- Existing CSV formatting tests plus manual export.
- Timing around `render_stats_csv_export()` for 50, 500, 5,000 rows.

### P2: Saved Upload Summary Is Row-Based

Evidence: `render_dataset_summary_box()` loops at `reminders_app_v3.py:9281`, creating columns and a Remove button per saved upload row.

Why it matters: normally small, but can grow if many partial uploads are retained.

Smallest safe fix: no immediate code change. Add a soft display cap only if real histories exceed 25 rows.

Validation: manual upload/remove checks.

### P3: Factoid Metric Cards Use Repeated Inline HTML

Evidence: `cardgroup()` creates `st.columns(5)` and markdown cards at `reminders_app_v3.py:16927-16933`.

Why it matters: bounded metric count and not likely user-visible compared with reminders/stats.

Smallest safe fix: leave alone until larger structural work.

## 8. Smallest Safe Render Improvement

First recommended patch: paginate Actioned Reminders to 50 rows.

Reasoning:

- It addresses the only current high-risk unbounded reminder-history widget loop.
- It reuses the app's existing 50-row convention.
- It preserves period filtering, sorting, and per-row Undo behavior.
- It does not alter Google I/O, auth, data formats, or business logic.

Expected before/after:

- 25 rows: no visible change except optional caption if implemented consistently.
- 100 rows: visible widgets drop from 100 row layouts/100 Undo buttons to 50 row layouts/50 Undo buttons.
- 250 rows: visible widgets drop from 250 to 50.
- 500 rows: visible widgets drop from 500 to 50.

Second patch after that: split active reminder button CSS so static CSS is injected once per table render.

## 9. Tests And Manual Checks Needed

Automated tests to add before/following fixes:

- Actioned pagination helper test with 0, 1, 50, 51, and 120 rows.
- Actioned sort + pagination test: sorting applies before pagination.
- Actioned Undo key/callback test: row identity remains correct after paging.
- Source or monkeypatch test for active reminder CSS: full style block is not emitted once per row after the CSS cleanup.
- Search Terms pagination/edit characterization before changing that editor.
- Exclusions delete characterization for each subsection before adding pagination.

Manual checks:

- Reminders tab with 25, 100, 250, 500 active rows.
- Actioned Reminders Daily/Weekly/Monthly/All with 25, 100, 250, 500 rows.
- Browser devtools: compare DOM node count and websocket payload before/after actioned pagination.
- Verify visual styling for WhatsApp/Sent/Decline buttons after any CSS cleanup.
- Stats CSV export still exports all rows, not just the current page.
- Mobile/narrow viewport for active reminders and actioned reminders.

Useful existing commands:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
python -m unittest tests.test_ci_statistics tests.test_ci_reminder_actions tests.test_ci_streamlit_startup
```

Proposed manual profiling steps:

1. Add temporary timing around `render_table_with_buttons()` and `render_actioned_reminders_tab()` using `time.perf_counter()`.
2. Record row count, visible row count, and elapsed render section time.
3. In browser devtools, record DOM node count and time-to-interactive after rerun.
4. Test with synthetic session rows at 25, 100, 250, and 500.

