# UX/UI Audit

Audit date: 2026-05-20  
Scope: Streamlit UI/UX review of `reminders_app_v3.py` from code inspection. No product fixes were implemented.

## Executive Summary

Clinic Reminders has the right core product shape: upload sales data, maintain reminder rules, generate active reminders, prepare WhatsApp messages, mark outcomes, and review stats. The biggest UX risk is not missing functionality. It is that the app asks clinic staff to understand too many concepts at once, especially in Search Terms, Reminders, Upload Data, and Stats.

The strongest parts are the new-account welcome dialog, data/privacy language, saved dataset summary, confirmation for full account deletion, and the active/actioned reminder split. The weakest parts are the desktop-style table layouts, unclear ordering of WhatsApp versus Sent, automatic upload saving without an explicit review step, dense reminder rule terminology, and broad destructive actions that need clearer separation.

No P0 issue was confirmed from static review, but there are multiple P1 issues likely to cause wrong workflow actions, abandonment, or support requests.

## Top 10 UX Issues

1. P1: Active reminder rows make `WhatsApp`, `Sent`, and `Decline` equally close and visually compact, increasing the chance of marking a reminder sent before contacting the client.
2. P1: Uploads are parsed and saved automatically after file selection, so users do not get a clear review/confirm moment before clinic data changes.
3. P1: Search Terms exposes advanced scheduling fields (`Reminder 1`, `Reminder 2`, `Reminder 3 (Due Date)`, `Overdue Reminder`, `Use Qty`) in a wide spreadsheet-like editor that is hard for non-technical clinic staff.
4. P1: Reminder and actioned reminder tables rely on many narrow Streamlit columns, which will be difficult on tablets, small laptops, and mobile.
5. P1: Stats uses outcome/accounting terms (`capturable revenue`, `success window`, `purchase cycle`, `actioning`) that need simpler clinic-facing framing.
6. P1: `Send All` sits in the active reminder table footer and marks all currently listed reminders as sent without an explicit confirmation or WhatsApp review.
7. P2: Empty states say what is empty, but often do not tell the user the next best action.
8. P2: Account popover contains routine, privacy, access, password, logout, and destructive delete actions in one vertical list.
9. P2: Exclusions require exact manual names and phrases, with limited affordance to create exclusions from reminder rows.
10. P2: Custom CSS/HTML and icon-only buttons create accessibility and Streamlit brittleness risk.

## Top 10 Quick Wins

1. Rename `Reminder 3 (Due Date)` to `Due after days` everywhere, with helper text `Main reminder interval`.
2. Change active row action labels to `Prepare`, `Mark sent`, and `Decline`, keeping icons secondary.
3. Add a confirmation step for `Send All`: show count and require `Mark listed as sent`.
4. Add a review panel after upload parse: file count, PMS, rows, date range, and an explicit `Save clinic data` button.
5. Add next-action copy to empty states: upload data, add search terms, refresh reminders, or change date range.
6. Move `Delete account and data` into a separated danger section within Account.
7. Add short explanatory captions above Search Terms and Stats using plain clinic language.
8. Replace `Actioned Reminders` period labels with `Today`, `This week`, `This month`, `All time`.
9. Add mobile-friendly card rendering for reminders below a breakpoint or behind a `Compact list` mode.
10. Confirm template deletion with a second click or typed template name.

## Findings

### 1. Active Reminder Actions Are Too Easy To Misfire

- Severity: P1
- Screen/tab/flow: Reminders > Active Reminders
- Current issue: The table renders `WhatsApp`, `Sent`, and `Decline` as adjacent narrow action columns. `Sent` is a checkmark-only button and `Decline` is an X-only button.
- Evidence: `render_table_with_buttons()` in `reminders_app_v3.py`; headers and buttons around lines 12268-12379.
- Why it matters: Clinic staff may mark a reminder sent before opening WhatsApp or may decline the wrong reminder in a dense row.
- Suggested UX fix: Make the primary action `Prepare message`; show `Mark sent` only after a message has been prepared or place it in a secondary row/action menu. Use text labels, not only symbols.
- Implementation complexity: Medium
- Whether behavior changes: Yes, workflow ordering becomes safer.
- Files/functions likely involved: `reminders_app_v3.py` `render_table_with_buttons()`, `prepare_whatsapp_action()`, `mark_reminder_sent_action()`.
- Validation/manual test needed: Upload sample data, prepare one reminder, verify message composer updates, then mark sent; verify accidental one-click sent is harder.

### 2. `Send All` Can Mark Reminders Sent Without Message Review

- Severity: P1
- Screen/tab/flow: Reminders > Active Reminders
- Current issue: `Send All` marks every listed active reminder as sent from the table footer.
- Evidence: `render_table_with_buttons()` footer button around line 12370; `mark_all_listed_reminders_sent_action()` around lines 11632-11676.
- Why it matters: A clinic can record outreach that did not happen, affecting action history and Stats.
- Suggested UX fix: Add a confirmation dialog or inline confirm state showing the count and current date range. Consider renaming to `Mark listed as sent`.
- Implementation complexity: Small/Medium
- Whether behavior changes: Yes, adds a confirmation step.
- Files/functions likely involved: `render_table_with_buttons()`, `mark_all_listed_reminders_sent_action()`.
- Validation/manual test needed: Confirm cancel does nothing; confirm marks only currently listed rows.

### 3. Upload Auto-Saves Without A Clear Review Moment

- Severity: P1
- Screen/tab/flow: Upload Data
- Current issue: Selecting files triggers parsing and, when valid, saves automatically with busy overlay.
- Evidence: upload handling and `save_uploaded_dataset()` around lines 11077-11372.
- Why it matters: Users may not realize they changed the clinic dataset, especially when uploading multiple files or overlapping exports.
- Suggested UX fix: Split upload into `Choose files` -> `Review detected data` -> `Save clinic data`. Show rows, PMS, date ranges, overlap note, and whether existing data will be merged or replaced.
- Implementation complexity: Medium/Large
- Whether behavior changes: Yes, adds explicit confirmation before saving.
- Files/functions likely involved: Upload Data block, `summarize_uploads()`, `save_uploaded_dataset()`, dataset history helpers.
- Validation/manual test needed: Upload valid files, invalid files, duplicate files, mixed PMS files, and overlapping date ranges.

### 4. Search Terms Editor Is Too Dense For Clinic Staff

- Severity: P1
- Screen/tab/flow: Search Terms
- Current issue: The editor behaves like a wide spreadsheet with eight columns and technical scheduling labels.
- Evidence: `render_search_terms_editor()` around lines 15683-16005.
- Why it matters: Reminder rules are core setup. If staff misunderstand days, quantity, or overdue logic, reminders will be wrong.
- Suggested UX fix: Use a guided add/edit form for one rule at a time. Show defaults in a compact list. Rename fields in plain language: `Item text to match`, `First reminder after`, `Second reminder after`, `Due after`, `Overdue after`, `Multiply by quantity`.
- Implementation complexity: Large
- Whether behavior changes: No intended behavior change, but UI structure changes.
- Files/functions likely involved: `render_search_terms_editor()`, rule save helpers.
- Validation/manual test needed: Add, edit, delete, duplicate, reset defaults, invalid days, and refresh reminders after rule edits.

### 5. Reminder Tables Are Not Responsive Enough

- Severity: P1
- Screen/tab/flow: Reminders, Actioned Reminders, Search Terms, Exclusions
- Current issue: Many views use `st.columns()` as tables with 8-11 columns and fixed width ratios.
- Evidence: `render_table_with_buttons()` col widths around line 12269; `render_actioned_reminders_tab()` around line 12162; Search Terms widths around line 15719.
- Why it matters: On tablets and smaller laptops, columns will crowd, wrap unpredictably, or hide important row context.
- Suggested UX fix: Add a compact card/list layout for reminders and search terms, or switch to `st.dataframe` for read-only tables plus row-level action expanders.
- Implementation complexity: Medium/Large
- Whether behavior changes: No intended behavior change.
- Files/functions likely involved: reminder table renderers, search terms editor, exclusions render block.
- Validation/manual test needed: Manual viewport checks at 390px, 768px, 1024px, and 1366px.

### 6. Empty States Need Next Actions

- Severity: P2
- Screen/tab/flow: Upload Data, Reminders, Actioned Reminders, Stats, Exclusions
- Current issue: Several empty states say `No ... yet` or `No reminders...` without a direct next step.
- Evidence: `render_dataset_status()` around line 9390; `render_table()` around lines 11482-11493; `render_actioned_reminders_tab()` around line 12149; exclusions block around lines 16178-16581.
- Why it matters: First-time users need to know what to do next and whether the empty state is good or a problem.
- Suggested UX fix: Add specific next-action copy and buttons: `Upload clinic data`, `Add a search term`, `Change date range`, `Open Active Reminders`.
- Implementation complexity: Small
- Whether behavior changes: No
- Files/functions likely involved: Empty-state branches in the functions above.
- Validation/manual test needed: New account with no data; account with data but no reminders; no actioned reminders; no exclusions.

### 7. Stats Language Is Too Product-Internal

- Severity: P1
- Screen/tab/flow: Stats
- Current issue: Copy and labels include `success window`, `capturable revenue`, `actioning`, `purchase cycles`, and multiple time interpretations.
- Evidence: `render_stats_tab()` around lines 15419-15675; stats column help constants around lines 12719-12934 and 15270-15298.
- Why it matters: Clinic managers may not trust metrics they cannot quickly explain.
- Suggested UX fix: Add a plain-language stats primer: `Sent reminders`, `Repeat sales found`, `Still waiting`, `No sale found yet`. Rename `Item Actioning` to `Reminder activity by item`.
- Implementation complexity: Medium
- Whether behavior changes: No
- Files/functions likely involved: `render_stats_tab()`, stats display labels/help constants.
- Validation/manual test needed: Review Stats with sent, pending, success, and no-match cases; compare labels to exported CSV headers.

### 8. Account Actions Mix Routine And Dangerous Choices

- Severity: P2
- Screen/tab/flow: Account popover
- Current issue: Profile, privacy, clinic access, password, delete, and logout are in one list. Delete is styled separately but still near routine actions.
- Evidence: Account popover around lines 9016-9069; delete dialog around lines 8342-8477.
- Why it matters: Destructive account deletion should feel structurally separate, not just color-separated.
- Suggested UX fix: Group Account into `Clinic`, `Access`, and `Danger zone`. Keep delete at bottom behind a separator and use sentence-case title `Delete account and data`.
- Implementation complexity: Small
- Whether behavior changes: No
- Files/functions likely involved: Account popover block, `delete_account_dialog_html()`.
- Validation/manual test needed: Open account menu as Google, password, and staff access users.

### 9. Clear Clinic Data Confirmation Could Be More Concrete

- Severity: P2
- Screen/tab/flow: Upload Data > Clear Clinic Data
- Current issue: Confirmation says data is removed, but does not summarize what currently exists or whether the Drive file is trashed.
- Evidence: Clear Clinic Data block around lines 11392-11475.
- Why it matters: Users need confidence about the difference between clearing active clinic data and deleting the whole account.
- Suggested UX fix: Show current dataset summary in the confirm state and say `This keeps search terms, templates, exclusions, and action history`.
- Implementation complexity: Small
- Whether behavior changes: No
- Files/functions likely involved: Upload Data clear block, `render_dataset_date_range()`.
- Validation/manual test needed: Clear data with one saved upload, multiple uploads, and no saved data.

### 10. Template Deletion Has No Confirmation

- Severity: P2
- Screen/tab/flow: Reminders > WhatsApp Template Editor
- Current issue: Custom templates can be deleted with one click. The default template is protected, but custom template deletion is immediate.
- Evidence: `Delete template` button around lines 12611-12622.
- Why it matters: Message templates are clinic work product and can be accidentally lost.
- Suggested UX fix: Add an inline confirm state: `Delete "Template Name"?` with `Cancel` and `Delete template`.
- Implementation complexity: Small
- Whether behavior changes: Yes, adds confirmation.
- Files/functions likely involved: `render_whatsapp_tools()`.
- Validation/manual test needed: Delete custom template, cancel deletion, verify default template cannot be deleted.

### 11. Google/Auth Errors Are Graceful But Generic

- Severity: P2
- Screen/tab/flow: Login/signup
- Current issue: Google setup and account creation errors are generally non-technical, but they do not always give a next support action.
- Evidence: `begin_google_login()` around line 7276; login/signup UI around lines 8833-9020; Google onboarding around lines 7795-7850.
- Why it matters: Authentication blocks all app use. Users need a clear recovery path.
- Suggested UX fix: Add `Try password sign-in`, `Try another Google account`, and `Contact support` copy where appropriate.
- Implementation complexity: Small
- Whether behavior changes: No
- Files/functions likely involved: Login block, `render_google_onboarding_dialog()`.
- Validation/manual test needed: Authlib missing, failed Google login, existing Google account, duplicate clinic name.

### 12. New-Account Flow Is Good But Not Anchored After Dialog

- Severity: P2
- Screen/tab/flow: First-time user onboarding
- Current issue: The welcome dialog gives four good steps and navigates to Upload Data, but the persistent Get Started checklist is text-heavy and not action-button driven.
- Evidence: `new_account_welcome_dialog_html()` around lines 5808-5960; `render_setup_checklist()` around lines 9642-9685.
- Why it matters: First-time users benefit from a checklist that takes them directly to the next unfinished step.
- Suggested UX fix: Add one primary button near the checklist for the next incomplete step. Keep cards shorter.
- Implementation complexity: Medium
- Whether behavior changes: No
- Files/functions likely involved: `render_setup_checklist()`, setup checklist helpers.
- Validation/manual test needed: New account, after upload, after adding terms, after template save, after marking sent.

### 13. Exclusions Require Exact Manual Data Entry

- Severity: P2
- Screen/tab/flow: Exclusions and Reminders
- Current issue: Exclusions ask users to type exact client/patient/item names rather than creating them from reminder rows.
- Evidence: Exclusion inputs around lines 16161-16425.
- Why it matters: Exact typing is error-prone and hard when PMS names are long or inconsistently cased.
- Suggested UX fix: Add row-level `Hide client`, `Hide patient`, or `Hide item` actions from reminder rows, or add autocomplete/select options from current data.
- Implementation complexity: Medium
- Whether behavior changes: Yes, adds creation path.
- Files/functions likely involved: `render_table_with_buttons()`, exclusions state updates.
- Validation/manual test needed: Create each exclusion type from a reminder row; verify hidden reminders and undo/remove.

### 14. Actioned Reminder Filters Use Operational Labels

- Severity: P3
- Screen/tab/flow: Reminders > Actioned Reminders
- Current issue: Period options are `Daily`, `Weekly`, `Monthly`, `All`.
- Evidence: `render_actioned_reminders_tab()` around lines 12122-12149.
- Why it matters: Users think in `Today`, `This week`, `This month`, `All time`, not reporting interval nouns.
- Suggested UX fix: Rename labels while preserving internal values.
- Implementation complexity: Small
- Whether behavior changes: No
- Files/functions likely involved: `render_actioned_reminders_tab()`, period mapping helpers.
- Validation/manual test needed: Verify each period returns same rows as before.

### 15. Upload Help Is Useful But Hidden Behind A Button

- Severity: P2
- Screen/tab/flow: Upload Data
- Current issue: Upload guidance is good, but most specifics are in a dialog opened by `What should uploaded sales data look like?`
- Evidence: `upload_sales_data_help_html()` around lines 5677-5950; Upload Data help button around line 11066.
- Why it matters: Users may upload the wrong export before reading the guidance.
- Suggested UX fix: Put a short always-visible checklist beside the uploader: `Date, client, patient, item`. Keep the detailed dialog.
- Implementation complexity: Small
- Whether behavior changes: No
- Files/functions likely involved: Upload Data uploader container.
- Validation/manual test needed: Upload page without opening dialog; verify required fields are visible.

### 16. Privacy Copy Is Solid But Long For In-Flow Use

- Severity: P3
- Screen/tab/flow: Account > Data & Privacy
- Current issue: The privacy dialog is comprehensive but dense, with a four-column grid on desktop.
- Evidence: `data_privacy_policy_content()` around lines 5603-5669 and `data_privacy_dialog_html()` around lines 5959-6045.
- Why it matters: Users may skim past important retention/deletion distinctions.
- Suggested UX fix: Add a short summary at top: `Saved: uploaded dataset, settings, action history. Not saved: Google passwords. Delete paths: Clear data or Delete account`.
- Implementation complexity: Small
- Whether behavior changes: No
- Files/functions likely involved: `data_privacy_policy_content()`, `data_privacy_dialog_html()`.
- Validation/manual test needed: Open privacy dialog on desktop and mobile widths.

### 17. Custom HTML Buttons Risk Accessibility Gaps

- Severity: P2
- Screen/tab/flow: WhatsApp Composer, Clinic Access copy button
- Current issue: Some actions use `components.html()` custom buttons and JavaScript.
- Evidence: `render_clipboard_button()` around lines 8154-8215; WhatsApp composer buttons around lines 12467-12500.
- Why it matters: Custom iframes may not inherit Streamlit accessibility, focus order, disabled states, or status messaging.
- Suggested UX fix: Add visible status text outside the iframe where possible and ensure button labels are complete without emoji.
- Implementation complexity: Medium
- Whether behavior changes: No
- Files/functions likely involved: `render_clipboard_button()`, `render_whatsapp_tools()`.
- Validation/manual test needed: Keyboard-only tab through composer and copy controls; verify screen-reader-friendly text.

### 18. UI May Jump After File Selection And Dialog Closure

- Severity: P2
- Screen/tab/flow: Upload Data, dialogs
- Current issue: File changes trigger `st.toast()`, state resets, and immediate `st.rerun()`. Dialogs close if uploader has files.
- Evidence: file change block around lines 11092-11108; `upload_widget_has_files() and account_dialog_is_open()` around line 9077.
- Why it matters: Users can lose context or see dialogs disappear unexpectedly while uploading.
- Suggested UX fix: Avoid closing unrelated account dialogs automatically, or show a short explanation. Keep upload processing state anchored in the upload panel.
- Implementation complexity: Medium
- Whether behavior changes: Yes, state behavior changes.
- Files/functions likely involved: file change block, account dialog guard.
- Validation/manual test needed: Open Account dialog, select upload files, remove files, verify expected persistence/closure.

### 19. Search Term Changes Require Manual Refresh Elsewhere

- Severity: P2
- Screen/tab/flow: Search Terms -> Reminders/Stats
- Current issue: Search term edits autosave, but Reminders/Stats require refresh notices to apply latest rules.
- Evidence: `search_criteria_have_pending_changes()` around line 9280; refresh notices around lines 11708-11724 and 15437-15442.
- Why it matters: Users may think saved changes are already reflected everywhere.
- Suggested UX fix: After editing rules, show a persistent top-level badge/action: `Rules changed. Refresh reminders and stats`.
- Implementation complexity: Medium
- Whether behavior changes: No, unless auto-refresh is introduced.
- Files/functions likely involved: `render_main_section_nav()`, `render_search_criteria_refresh_notice()`, `render_stats_tab()`.
- Validation/manual test needed: Edit a rule, navigate to Reminders and Stats, confirm notice placement and refresh behavior.

### 20. Destructive Row Removes Use Small `×` Buttons

- Severity: P2
- Screen/tab/flow: Exclusions and automatic keywords
- Current issue: Delete/remove actions are often tiny `×` buttons in narrow columns.
- Evidence: Exclusions and keyword delete buttons around lines 16171-16568.
- Why it matters: Small targets are hard on tablets and may be unclear to assistive technology users.
- Suggested UX fix: Use `Remove` text buttons or row action menus with clear labels and larger targets.
- Implementation complexity: Small/Medium
- Whether behavior changes: No
- Files/functions likely involved: Exclusions render block.
- Validation/manual test needed: Keyboard and touch-style manual pass for removing every exclusion type.

## Copywriting Suggestions

| Current copy | Suggested copy |
| --- | --- |
| `Reminder 3 (Due Date)` | `Due after days` |
| `Use Qty` | `Multiply by quantity` |
| `Actioned Reminders` | `Completed reminders` |
| `Daily / Weekly / Monthly / All` | `Today / This week / This month / All time` |
| `Search criteria have changed. Refresh reminders to apply the latest changes.` | `Reminder rules changed. Refresh to update this list.` |
| `No reminders in the selected date range.` | `No reminders for this date range. Try Today, widen the date window, or check Search Terms.` |
| `Clear Clinic Data` | `Clear uploaded clinic data` |
| `Send All` | `Mark listed as sent` |
| `Item Actioning` | `Reminder activity by item` |
| `Success window after sent date` | `Days after message to count a repeat sale` |

## Recommended Patch Order

1. Title: Safer reminder action labels  
   Goal: Reduce accidental sent/declined actions.  
   Scope: Rename active row buttons and make text labels visible.  
   Risk: Low/Medium.  
   Files likely touched: `reminders_app_v3.py` reminder table CSS/rendering.  
   Validation steps: Prepare, sent, decline, undo, pagination, mobile width smoke.

2. Title: Confirm bulk sent action  
   Goal: Prevent accidental `Send All`.  
   Scope: Add inline/dialog confirmation with listed count.  
   Risk: Low.  
   Files likely touched: `render_table_with_buttons()`, `mark_all_listed_reminders_sent_action()`.  
   Validation steps: Confirm and cancel paths; filtered date range; no rows case.

3. Title: Improve empty states  
   Goal: Tell users what to do next.  
   Scope: Upload, Reminders, Actioned Reminders, Stats, Exclusions empty copy.  
   Risk: Low.  
   Files likely touched: empty-state branches in `reminders_app_v3.py`.  
   Validation steps: Manual states for no data, no reminders, no actioned reminders, no exclusions.

4. Title: Plain-language Search Terms copy  
   Goal: Reduce rule setup confusion without restructuring.  
   Scope: Rename labels/help text only.  
   Risk: Low.  
   Files likely touched: `render_search_terms_editor()`, related help constants.  
   Validation steps: Add/edit/delete rules; verify saved settings keys unchanged.

5. Title: Upload review before save  
   Goal: Make dataset changes explicit.  
   Scope: Add review state and `Save clinic data` button after parsing.  
   Risk: Medium.  
   Files likely touched: Upload Data block, upload state keys, save helper.  
   Validation steps: Valid upload, invalid upload, duplicate upload, mixed PMS, existing data merge.

6. Title: Account menu grouping  
   Goal: Separate routine settings from dangerous actions.  
   Scope: Add section headings/separator and sentence-case delete dialog title.  
   Risk: Low.  
   Files likely touched: Account popover, delete dialog title/copy.  
   Validation steps: Password, Google, and staff access account menus.

7. Title: Confirm template deletion  
   Goal: Prevent accidental loss of custom WhatsApp templates.  
   Scope: Add confirm/cancel state for non-default template deletion.  
   Risk: Low.  
   Files likely touched: `render_whatsapp_tools()`.  
   Validation steps: Create, select, delete, cancel, default template disabled.

8. Title: Stats wording pass  
   Goal: Make metrics understandable to clinic managers.  
   Scope: Rename tab labels, captions, and column help where behavior is unchanged.  
   Risk: Low/Medium because exports may share labels.  
   Files likely touched: `render_stats_tab()`, stats labels/help/export display labels.  
   Validation steps: Compare UI and CSV exports; verify tests expecting labels.

9. Title: Exclusion action clarity  
   Goal: Make remove actions accessible and easier to tap.  
   Scope: Replace `×` buttons with `Remove` or clearer row actions.  
   Risk: Low.  
   Files likely touched: Exclusions block.  
   Validation steps: Remove each exclusion/keyword type; keyboard pass.

10. Title: Reminder compact layout  
    Goal: Make core reminder workflow usable on tablet/mobile.  
    Scope: Add compact card/list rendering for active and actioned reminders.  
    Risk: Medium/Large.  
    Files likely touched: `render_table_with_buttons()`, `render_actioned_reminders_tab()`, CSS.  
    Validation steps: Manual responsive pass at mobile/tablet/desktop, plus action workflow tests.

11. Title: Upload help always-visible checklist  
    Goal: Prevent wrong first uploads.  
    Scope: Add short required-field checklist near uploader; keep detailed dialog.  
    Risk: Low.  
    Files likely touched: Upload Data uploader container.  
    Validation steps: First-time Upload Data screen; no file selected; invalid file selected.

12. Title: Rule refresh visibility  
    Goal: Clarify when saved Search Terms are not yet applied to Reminders/Stats.  
    Scope: Add persistent top-level refresh notice or badge.  
    Risk: Medium.  
    Files likely touched: nav badge helpers, reminders/stats refresh notices.  
    Validation steps: Edit rules, navigate tabs, refresh Reminders, refresh Stats.

## Validation Plan For Future UX Fixes

- Desktop manual pass: 1366x768 and 1440x900.
- Tablet/manual pass: 768x1024.
- Mobile/manual pass: 390x844, especially Reminders, Search Terms, Exclusions.
- Core task script: create account, upload file, add search term, refresh reminders, prepare WhatsApp, mark sent, undo, decline, view Stats.
- Safety script: clear clinic data cancel/confirm, delete account wrong confirmation/cancel/confirm, template delete cancel/confirm.
- Accessibility basics: keyboard tab order through login, active reminders, template editor, account dialogs; verify all icon buttons have visible or accessible labels.

