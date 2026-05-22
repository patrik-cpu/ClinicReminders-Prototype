# Performance Statistics Pass

Date: 2026-05-19

## Executive Summary

The Stats tab is mostly gated behind the active main section: the app only prepares the Stats `prepared` DataFrame and calls `render_stats_tab()` when `active_main_section == "Stats"`. Action tracker loading is also limited to the Reminders and Stats sections. That prevents the heaviest statistics work from running on Upload Data, Get Started, Exclusions, Settings, and similar views.

The remaining performance risks are inside a single Stats render. Streamlit renders all `st.tabs()` bodies during a run, so Items, Item Actioning, Team, Sent Reminders, and Successes are all built together. The code computes the all-time outcome table once, which is good, but it repeatedly converts DataFrames to row dictionaries, re-filters action histories, re-parses reminder/action dates, rebuilds grouped summary frames, and prepares/export-copies full frames before pagination. Large action histories are capped at `MAX_SETTINGS_LOG_ENTRIES`, but that capped list is reduced, expanded, filtered, and copied multiple times in one render.

The safest next work is to compute a small Stats render context once inside `render_stats_tab()` and pass derived artifacts into helpers: reduced action records, expanded generated rows, period-filtered rows, parsed date fields, outcome group frames, and display/export frames. Larger architectural work should split current reminder state from long-term action/outcome history so the Reminders tab does not need the same reduced action list shape as all-time statistics.

## 1. Functions Used To Render The Statistics Tab

Entry and gating:

- `main` section render gate at `reminders_app_v3.py:10898-10912`
- Stats-only working/prepared setup at `reminders_app_v3.py:15745-15746`
- `render_stats_tab()` at `reminders_app_v3.py:15175-15409`
- `ensure_action_tracker_loaded_for_current_clinic()` at `reminders_app_v3.py:4495`
- `load_action_tracker_records_for_clinic()` at `reminders_app_v3.py:5303`
- `statistics_current_action_records()` at `reminders_app_v3.py:12977`

Generated reminder helpers:

- `statistics_exclusion_fp()` at `reminders_app_v3.py:12774`
- `filter_prepared_for_statistics_period()` at `reminders_app_v3.py:12908`
- `build_statistics_generated_rows()` at `reminders_app_v3.py:12931`
- `cached_statistics_generated_rows()` at `reminders_app_v3.py:12954`
- `filter_generated_for_statistics_period()` at `reminders_app_v3.py:12984`
- `expand_rows_for_statistics_item_period()` at `reminders_app_v3.py:13008`
- `build_statistics_item_frame()` at `reminders_app_v3.py:13159`

Action/date helpers:

- `parse_statistics_date_part()` at `reminders_app_v3.py:12829`
- `parse_statistics_dates()` at `reminders_app_v3.py:12857`
- `statistics_row_dates()` at `reminders_app_v3.py:12875`
- `statistics_primary_reminder_date()` at `reminders_app_v3.py:12879`
- `statistics_actioned_date()` at `reminders_app_v3.py:12884`
- `statistics_date_in_period()` at `reminders_app_v3.py:12889`
- `statistics_row_in_reminder_period()` at `reminders_app_v3.py:12899`
- `filter_actions_by_reminder_period()` at `reminders_app_v3.py:12994`
- `filter_actions_by_actioned_period()` at `reminders_app_v3.py:13001`
- `build_statistics_team_frame()` at `reminders_app_v3.py:13130`
- `build_stats_team_frame()` at `reminders_app_v3.py:14531`

Outcome helpers:

- `outcome_as_of_date()` at `reminders_app_v3.py:13620`
- `prepare_sales_for_outcomes()` at `reminders_app_v3.py:13598`
- `build_reminder_outcomes()` at `reminders_app_v3.py:13894`
- `build_outcome_item_match_map()` at `reminders_app_v3.py:13750`
- `build_average_sales_purchase_gap_map()` at `reminders_app_v3.py:13785`
- `filter_outcomes_for_period()` at `reminders_app_v3.py:14259`
- `filter_sent_outcomes_for_period()` at `reminders_app_v3.py:14272`
- `filter_stats_sent_tab_rows()` at `reminders_app_v3.py:14282`
- `summarize_outcomes()` at `reminders_app_v3.py:14314`
- `build_outcome_group_frame()` at `reminders_app_v3.py:14462`
- `build_outcome_time_frame()` at `reminders_app_v3.py:14605`

Render/display/export helpers:

- `render_statistics_metric_card()` at `reminders_app_v3.py:13202`
- `prepare_statistics_display_frame()` at `reminders_app_v3.py:13222`
- `prepare_outcome_dataframe_for_display()` at `reminders_app_v3.py:14682`
- `stats_sort_dataframe()` at `reminders_app_v3.py:14718`
- `apply_stats_global_sort_controls()` at `reminders_app_v3.py:14749`
- `outcome_display_column_config()` at `reminders_app_v3.py:14836`
- `prepare_stats_team_display_frame()` at `reminders_app_v3.py:14873`
- `stats_export_csv_bytes_for_render()` at `reminders_app_v3.py:14997`
- `render_stats_csv_export()` at `reminders_app_v3.py:15021`
- `render_outcome_dataframe()` at `reminders_app_v3.py:15089`
- `render_stats_sent_reminders_period_selector()` at `reminders_app_v3.py:15105`

## 2. Repeated Filtering, Conversion, And Grouping Within One Render

### Finding P1: Stats subtabs rebuild full frames even when only one tab is visible

- Function/location: `render_stats_tab()` at `reminders_app_v3.py:15286-15409`.
- Repeated work: Streamlit executes every `with item_tab`, `with item_actioning_tab`, `with team_tab`, `with sent_tab`, and `with success_tab` block during one render. This builds item outcome groups, item actioning groups, team groups, sent rows, success rows, CSV exports, sort controls, paginated frames, and display frames every time the Stats tab renders.
- Proposed fix: Compute shared base artifacts once, then add a selected-subview control outside `st.tabs()` for heavy tables or use a lightweight per-tab guard if current Streamlit state exposes active tab. If preserving `st.tabs()` exactly is required, still build a `StatsRenderContext` once and cache/persist derived frames by `(data_version, action_fp, rules_fp, windows, selected_sent_period)`.
- Risk: Medium. Changing tab mechanics can affect UI behavior; a context/cache-only change is lower risk.
- Tests needed: Stats tab renders all five views; widget keys remain stable; each table’s row counts and columns match current behavior; changing success windows invalidates outcome results.
- Validation command: `python -m py_compile reminders_app_v3.py settings_pointer_utils.py && python -m unittest tests.test_ci_statistics tests.test_ci_streamlit_startup`.

### Finding P1: Generated reminder rows are converted to records and date-filtered repeatedly

- Function/location: `filter_generated_for_statistics_period()` at `reminders_app_v3.py:12984`, `build_statistics_item_frame()` at `reminders_app_v3.py:13159`, and unused-but-ready helpers `statistics_summary_for_period()` / `build_statistics_daily_frame()` at `reminders_app_v3.py:13050` and `reminders_app_v3.py:13085`.
- Repeated work: `generated_df.to_dict("records")` happens inside period filters and item-frame creation. Each row then calls `statistics_row_in_reminder_period()`, which reparses reminder-date text through `parse_statistics_dates()`. For All time, `statistics_period_start()` returns `None`, but the code still parses row dates before `statistics_date_in_period()` returns true.
- Proposed fix: For `period == "All time"`, skip reminder-date parsing and return a shallow copy or record list directly. For non-all-time periods, precompute `ReminderDateParsed`/`ReminderDateList` once in the generated frame or in a render context and pass filtered records to item/daily/summary helpers.
- Risk: Low for the All time fast path; medium for adding parsed helper columns if display/export paths accidentally expose them.
- Tests needed: All-time generated filter preserves row count and columns; Today/7 days/30 days filters match current results for grouped reminder dates containing `|`; helper columns are not displayed/exported.
- Validation command: `python -m unittest tests.test_ci_statistics`.

### Finding P1: Action records are reduced, expanded, copied, and date-filtered multiple times

- Function/location: `statistics_current_action_records()` at `reminders_app_v3.py:12977`, `build_reminder_outcomes()` at `reminders_app_v3.py:13916-13926`, `filter_actions_by_reminder_period()` at `reminders_app_v3.py:12994`, `filter_actions_by_actioned_period()` at `reminders_app_v3.py:13001`, `build_statistics_item_frame()` at `reminders_app_v3.py:13177`, and `build_statistics_team_frame()` at `reminders_app_v3.py:13130`.
- Repeated work: `statistics_current_action_records()` reduces `deleted_reminders`. `build_reminder_outcomes()` reduces the same list again, expands sent grouped records, dedupes sent records, and builds sent-date maps. Item Actioning expands all action records again. Team filters action records again by actioned date and reparses `ActionedAt`/`DeletedAt`.
- Proposed fix: Build one action-derived context per Stats render: `reduced_action_records`, `expanded_action_records`, `expanded_sent_records`, `sent_records`, `actioned_at_parsed`, `reminder_dates_parsed`, and per-period filtered lists. Pass these into outcome, item, and team builders or add optional precomputed arguments while preserving current public helper behavior.
- Risk: Medium. Action dedupe order and grouped reminder expansion are behavior-sensitive.
- Tests needed: Sent/declined counts by item and team remain unchanged; grouped `ReminderDetails` records still expand correctly; undo/active rows stay excluded; latest-action dedupe still wins.
- Validation command: `python -m unittest tests.test_ci_statistics tests.test_ci_reminders_badge`.

### Finding P2: Outcome group frames recalculate numeric summaries independently for Items and Team

- Function/location: `build_outcome_group_frame()` at `reminders_app_v3.py:14462`, called for Items at `reminders_app_v3.py:15292` and again for Sender inside Team at `reminders_app_v3.py:15338-15339`.
- Repeated work: The helper copies `outcomes_df`, precomputes numeric columns, groups, then calls `summarize_outcomes()` per group. Items and Sender summaries repeat numeric conversion and outcome summary logic over the same `period_rows`.
- Proposed fix: Precompute numeric outcome helper columns once for `period_rows` after `build_reminder_outcomes()`, then either pass that prepared frame to both group builders or build both item/sender group frames in a single `build_stats_outcome_groups()` helper.
- Risk: Low if helper columns remain internal and column output is characterized.
- Tests needed: Item group and sender group frames match current values for successes, pending, no match, revenue, and percentages.
- Validation command: `python -m unittest tests.test_ci_statistics`.

### Finding P2: Display and CSV export preparation duplicate frame copies

- Function/location: `render_stats_csv_export()` / `stats_export_csv_bytes_for_render()` at `reminders_app_v3.py:15021` and `reminders_app_v3.py:14997`; `render_outcome_dataframe()` at `reminders_app_v3.py:15089`; display preparers at `reminders_app_v3.py:14682`, `13222`, and `14873`.
- Repeated work: For each table, CSV export copies the full frame, optionally selects columns, applies a display preparer, applies CSV numeric formatting, and serializes. Rendering then sorts/paginates and applies a display preparer again to the visible page. This is behaviorally correct but repeats conversion for visible rows and export rows.
- Proposed fix: Keep export full-frame behavior, but compute display-prepared paged frames once per table and reuse column configs. For export, cache multiple CSVs per render rather than the current single-entry `_stats_export_csv_cache`, because a full Stats render creates up to five exports and each can evict the previous one.
- Risk: Low for display reuse; medium for multi-entry cache if cache invalidation keys are incomplete.
- Tests needed: Export bytes remain unchanged; displayed page values remain unchanged; switching sort/page invalidates only display, not export contents.
- Validation command: `python -m unittest tests.test_ci_statistics`.

## 3. Generated Reminders And Action Tracker Recompute Status

### Finding P1: Generated reminders are cached, but action-derived work is not shared

- Function/location: `cached_statistics_generated_rows()` at `reminders_app_v3.py:12954` and `render_stats_tab()` at `reminders_app_v3.py:15249-15270`.
- Repeated work: Generated reminders are cached with data/rules/exclusion/version inputs. Action records are loaded into session and reduced, but no equivalent action context cache exists. `build_reminder_outcomes()` is `st.cache_data(max_entries=8)`, but its key includes the full action-record list and sales DataFrame, while item/team action summaries still rebuild from `action_records` outside that cache.
- Proposed fix: Add a lightweight action fingerprint from reduced records and memoize expanded/deduped action artifacts in session for the current Stats render. Use the same fingerprint for item actioning, team actioning, and outcome matching.
- Risk: Medium. Stale action state would be user-visible.
- Tests needed: Mark sent/declined/undo invalidates action context; remote action tracker refresh invalidates context; stats counts update after action changes.
- Validation command: `python -m unittest tests.test_ci_statistics tests.test_ci_auth_session`.

## 4. Whether Statistics Data Is Loaded When The Tab Is Not Used

### Finding P2: Stats outcomes are gated, but action tracker loads for Reminders too

- Function/location: active section gate at `reminders_app_v3.py:10906-10907`; Stats render gate at `reminders_app_v3.py:15745-15746` and `reminders_app_v3.py:15884`.
- Repeated work: `render_stats_tab()` only runs on Stats, and `prepared` is only built for Stats in the main preamble. However, `ensure_action_tracker_loaded_for_current_clinic()` runs for both Reminders and Stats because Reminders needs current action state. This is not Stats-only waste, but it means a large remote action history may be pulled before Stats is opened if the Reminders tab is active.
- Proposed fix: Split action tracker load modes: current reminder state for Reminders and full long-term action history for Stats. Reminders can load only the latest action per current reminder key, while Stats can load/reduce the full capped history.
- Risk: High unless the data source supports keyed/ranged reads; current Google Sheets API path reads all rows.
- Tests needed: Reminders hide/show state matches current behavior; Stats all-time history remains complete; remote action tracker failures remain fail-safe.
- Validation command: `python -m unittest tests.test_ci_reminders_badge tests.test_ci_statistics tests.test_ci_error_handling`.

## 5. Whether Large Histories Are Processed Unnecessarily

### Finding P1: Long action history is globally capped but still processed several times

- Function/location: `MAX_SETTINGS_LOG_ENTRIES = 1000` at `reminders_app_v3.py:5118`; `reduce_action_tracker_records()` at `reminders_app_v3.py:5268`; `load_action_tracker_records_for_clinic()` at `reminders_app_v3.py:5303`.
- Repeated work: The remote tracker read scans all sheet rows for the clinic, converts each row to a dict, then reduces to the last capped action records. During Stats render, the capped records are reduced again, expanded, copied, and parsed by several helper paths.
- Proposed fix: Preserve the cap but store a session-level reduced action context keyed by `(clinic_id, timezone, action_records_fp)`. Later, if Google Sheets schema allows it, add server-side date filtering or a separate current-state worksheet for Reminders.
- Risk: Medium for in-app context cache; high for changing remote storage/query patterns.
- Tests needed: Large synthetic action history produces identical reduced action records; action tracker cache invalidates after record writes and refresh.
- Validation command: `python -m unittest tests.test_ci_statistics tests.test_ci_error_handling`.

## 6. Opportunities To Compute Once And Pass Derived Data Into Helpers

### Finding P1: Add a Stats render context

- Function/location: `render_stats_tab()` at `reminders_app_v3.py:15238-15409`.
- Repeated work: The render function currently passes raw `sales_df`, `prepared`, `rules`, and `action_records` into independent helpers. Each helper owns conversion/filter/grouping.
- Proposed fix: Create a private `build_stats_render_context()` helper that returns:
  - `today` and `outcomes_as_of_date`
  - `action_records`, `expanded_action_records`, `expanded_sent_records`, `actioned_records`
  - `outcome_rows`
  - `generated_df` and optional generated record list
  - `item_outcome_frame`, `sender_outcome_frame`, `item_actioning_frame`, `team_frame`
  - `sent_rows_by_period` for the selected Sent Reminders filter
- Risk: Medium. It changes dataflow but can preserve output exactly with characterization tests.
- Tests needed: Context-built frames equal existing helper outputs on representative sent, declined, grouped, pending, success, and no-match records.
- Validation command: `python -m unittest tests.test_ci_statistics`.

### Finding P2: Precompute parsed dates in record dicts

- Function/location: date helpers at `reminders_app_v3.py:12857-12904`, action team parsing at `reminders_app_v3.py:13147-13149`, outcome date parsing at `reminders_app_v3.py:13935-13940`.
- Repeated work: Reminder Date, Due Date, Charge Date, ActionedAt, and DeletedAt are parsed repeatedly in item actioning, team actioning, outcome matching, sent filtering, and sorting.
- Proposed fix: Keep original fields unchanged, but add internal keys such as `_StatsReminderDates`, `_StatsPrimaryReminderDate`, and `_StatsActionedDate` to copied records inside the Stats render context. Update filter helpers to use these keys when present.
- Risk: Low if helper keys are stripped before display/export and existing helpers retain fallback parsing.
- Tests needed: Existing helpers still accept plain records; pre-parsed records produce identical filters and sort order; helper keys are not rendered/exported.
- Validation command: `python -m unittest tests.test_ci_statistics`.

## 7. Opportunities To Split Current Reminder State From Long-Term Statistics History

### Finding P2: One action list serves two different workloads

- Function/location: `deleted_reminders` session state usage around `reminders_app_v3.py:9579`, `10469`, `11927`, and `12977`.
- Repeated work: Reminders need current action state to hide/undo active reminders. Stats need long-term sent/declined history for outcomes, item actioning, team metrics, and exports. Both currently flow through `deleted_reminders`, `reduce_action_tracker_records()`, and `hidden_reminder_key()` keyed records.
- Proposed fix: Split internal concepts without changing persisted format first:
  - `current_action_index`: latest action by hidden reminder key, optimized for Reminders.
  - `statistics_action_history`: reduced but longer action records, optimized for Stats.
  - Build both from the same persisted tracker data until a storage migration is justified.
- Risk: Medium. The same action can affect both current hiding and historical stats, so invalidation must be exact.
- Tests needed: Reminders hidden/actioned state, undo behavior, Stats sent/declined counts, and outcome matching all match current behavior after split.
- Validation command: `python -m unittest tests.test_ci_reminders_badge tests.test_ci_statistics tests.test_ci_auth_session`.

## Recommended Patch Order

1. Add an All-time fast path for generated/action period filters so Stats avoids parsing dates when the selected period is all time.
2. Add a private Stats action context that reduces/expands/parses action records once per render.
3. Precompute outcome numeric helper columns once and pass the prepared outcome frame to item/sender group builders.
4. Convert the single-entry Stats CSV cache to a small multi-entry cache keyed per export view.
5. Split current reminder action index from long-term statistics action history inside session state, still using the same persisted tracker rows.

## Validation Commands

```bash
python -m py_compile reminders_app_v3.py settings_pointer_utils.py
python -m unittest tests.test_ci_statistics
python -m unittest tests.test_ci_reminders_badge
python -m unittest tests.test_ci_error_handling
python -m unittest discover -s tests -p "test_ci_*.py"
bash scripts/pre_merge_check.sh
```
