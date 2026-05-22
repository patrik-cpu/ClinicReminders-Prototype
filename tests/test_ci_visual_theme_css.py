import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class VisualThemeCssTests(unittest.TestCase):
    def test_light_widget_overrides_cover_deployed_streamlit_controls(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        for selector in [
            'div[data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"]',
            '[data-baseweb="base-input"]',
            'div[data-testid="stNumberInput"] [data-baseweb="input"]',
            'div[data-testid="stCheckbox"] label',
            'div[data-testid="stHorizontalBlock"]:has(.cr-brand-card) div[data-testid="stPopover"] button',
            ".cr-account-login-context",
            '.data-assurance-box',
        ]:
            with self.subTest(selector=selector):
                self.assertIn(selector, source)

        self.assertIn("color-scheme: light !important;", source)
        self.assertIn("background: #ffffff !important;", source)
        self.assertIn("-webkit-text-fill-color: #101828 !important;", source)
        self.assertIn(".st-key-login_password_input input", source)
        self.assertNotIn(".st-key-login_password_input [data-baseweb=\"base-input\"] > div:has(button)", source)
        self.assertIn("-webkit-text-security: disc;", source)
        self.assertIn("text-security: disc;", source)
        self.assertIn('password = st.text_input("Password", value="", key="login_password_input")', source)
        self.assertNotIn('password = st.text_input("Password", value="", type="password", key="login_password_input")', source)
        self.assertIn("padding-top: 3.45rem !important;", source)
        self.assertIn("padding-bottom: max(10rem, 74vh) !important;", source)
        self.assertIn(".st-key-login_password_input [data-baseweb=\"base-input\"] button", source)
        self.assertIn("display: none !important;", source)
        self.assertIn("--cr-login-input-bg: #ffffff;", source)
        self.assertIn("background: var(--cr-login-input-bg) !important;", source)
        self.assertIn("flex: 1 1 auto !important;", source)
        self.assertIn("width: 100% !important;", source)
        self.assertIn("background: transparent !important;", source)
        self.assertIn("border-radius: 0 !important;", source)
        self.assertIn("Logged in to Clinic:", source)
        self.assertIn('[data-baseweb="checkbox"] input[type="checkbox"]', source)
        self.assertRegex(
            source,
            r'div\[data-testid="stCheckbox"\] \[data-baseweb="checkbox"\] \{\s+background: transparent !important;',
        )
        self.assertRegex(
            source,
            r'div\[data-testid="stCheckbox"\] label div\[data-testid="stMarkdownContainer"\] \{\s+background: transparent !important;',
        )
        self.assertNotIn(
            'div[data-testid="stCheckbox"] [data-baseweb="checkbox"] {\n        background: #ffffff !important;',
            source,
        )

    def test_all_exclusion_delete_buttons_share_red_x_styling(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        for key_prefix in [
            "st-key-del_client_excl_",
            "st-key-del_patient_excl_",
            "st-key-del_client_item_excl_",
            "st-key-del_excl_",
            "st-key-top_unreminded_",
            "st-key-del_passaway_keyword_",
            "st-key-del_auto_patient_excl_",
        ]:
            with self.subTest(key_prefix=key_prefix):
                self.assertIn(f'[class*="{key_prefix}"] button', source)
                self.assertIn(f'[class*="{key_prefix}"] button:hover', source)
                self.assertIn(f'[class*="{key_prefix}"] button p', source)

        for selector in [
            ".auto-death-keyword-panel-title",
            ".auto-death-keyword-panel-copy",
            ".auto-death-keyword-chip",
            ".auto-death-patient-section-title",
            '[class*="st-key-del_passaway_keyword_"] button',
            "keyword_panel = st.container(border=True)",
            "st-key-client_exclusions_list_box",
            "st-key-patient_exclusions_list_box",
            "st-key-client_item_exclusions_list_box",
            "st-key-item_exclusions_list_box",
            "background: transparent !important;",
            "border-color: transparent !important;",
            "border: 0 !important;",
            ".exclusion-chip",
            "transform: translateY(-0.12rem);",
            "exclusion_chip_html",
            "row_cols = st.columns([2.15, 5.85], gap=\"small\")",
            "chip_cols = st.columns([0.82, 0.08, 0.1], gap=\"small\")",
        ]:
            with self.subTest(selector=selector):
                self.assertIn(selector, source)
        self.assertNotIn("exclusion-chip-tag", source)

    def test_streamlit_theme_defaults_to_light(self):
        config = (REPO_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")

        self.assertIn('base = "light"', config)
        self.assertIn('backgroundColor = "#f6faf7"', config)

    def test_main_section_selected_tab_has_visible_state(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")
        main_nav_css = source[
            source.index('div[data-testid="stHorizontalBlock"]:has([class*="st-key-main_section_nav_"])')
            : source.index('.st-key-main_section_tab {')
        ]

        for selector in [
            ".cr-main-section-nav-rule",
            '[class*="st-key-main_section_nav_"] button',
            'div[data-testid="stHorizontalBlock"]:has([class*="st-key-main_section_nav_"]) > div[data-testid="column"]',
            ".st-key-{active_button_key} button",
            '.st-key-main_section_tab [data-baseweb="button-group"] [aria-checked="true"]',
            '.st-key-main_section_tab [data-baseweb="button"][aria-checked="true"]',
            '.st-key-main_section_tab [aria-checked="true"]:hover',
        ]:
            with self.subTest(selector=selector):
                self.assertIn(selector, source)

        self.assertIn("st.button(", source)
        self.assertIn("on_click=set_main_section_tab", source)
        self.assertIn("render_main_section_nav(active_main_section)", source)
        self.assertIn("nav_spacer_width = 6.8", source)
        self.assertIn("[*widths, nav_spacer_width]", source)
        self.assertIn("min(2.9, len(display_tab_name) / 7", source)
        self.assertIn("display: inline-flex !important;", source)
        self.assertIn("align-items: center !important;", source)
        self.assertIn("vertical-align: middle !important;", source)
        self.assertIn("cr-upload-tab-pulse", source)
        self.assertIn(".st-key-main_section_nav_upload_data button", source)
        self.assertIn("background: #fee2e2 !important;", source)
        self.assertNotIn('<a class="cr-main-section-tab"', source)
        self.assertNotIn('href="?{MAIN_SECTION_TAB_QUERY_PARAM}', source)
        self.assertIn("font-size: 1.18rem", source)
        self.assertIn("min-height: 2.85rem", source)
        self.assertIn("flex-wrap: wrap !important;", source)
        self.assertIn("white-space: normal;", source)
        self.assertIn("max-width: 8.5rem !important;", source)
        self.assertIn("font-size: 0.92rem !important;", source)
        self.assertIn("padding: 0.35rem 0.5rem;", source)
        self.assertNotIn("min-width: fit-content !important;", main_nav_css)
        self.assertIn("box-shadow: 0 0 0 1px var(--cr-primary-dark), 0 1px 0 var(--cr-primary) !important;", source)
        self.assertNotIn("box-shadow: inset 0 4px 0 var(--cr-primary-dark)", source)
        self.assertIn("background: var(--cr-primary) !important;", source)
        self.assertIn("flex: 0 1 auto !important;", source)

    def test_outcome_success_window_label_matches_due_date_logic(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn("Success window around due date", source)
        self.assertIn("Success window after sent date", source)
        self.assertIn("st.columns([0.8, 0.8, 3.4]", source)
        self.assertIn("within this many days before or after the due date", source)
        self.assertIn("within this many days after the reminder is sent", source)
        self.assertIn("A reminder is successful when the matching sale is within this many days before or after the due date.", source)
        self.assertIn("Also counts as successful when a matching sale happens within this many days after the reminder is sent.", source)
        self.assertIn("Multiple reminder steps for the same item cycle count once.", source)
        self.assertIn("on_change=save_outcome_due_date_window_days", source)
        self.assertIn("on_change=save_outcome_post_reminder_window_days", source)
        self.assertIn("on_change=save_reminder_lookback_days", source)
        self.assertIn("on_change=save_reminder_window_days", source)
        self.assertIn("on_change=save_reminder_group_days", source)
        self.assertIn("on_change=save_reminder_warning_days", source)
        self.assertIn(
            'st.session_state["outcome_due_date_window_days"] = normalized_outcome_due_date_window_days()\n'
            '        due_date_window_days = st.number_input',
            source,
        )
        self.assertIn(
            'st.session_state["outcome_post_reminder_window_days"] = normalized_outcome_post_reminder_window_days()\n'
            '        post_reminder_window_days = st.number_input',
            source,
        )
        self.assertIn("min_value=1", source)
        self.assertNotIn("Days to define success", source)

    def test_busy_overlay_is_self_styled_for_callbacks(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")
        overlay_fn = source[source.index("def render_busy_overlay") : source.index("@contextmanager", source.index("def render_busy_overlay"))]

        self.assertIn("<style>", overlay_fn)
        self.assertIn(".cr-busy-overlay", overlay_fn)
        self.assertIn("position: fixed;", overlay_fn)
        self.assertIn(".cr-busy-spinner", overlay_fn)

    def test_reminder_range_tooltips_explain_stepper_pattern(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn("0 shows the selected day only. 1 includes the selected day plus the previous day, and so on.", source)
        self.assertIn("0 shows the selected day only. 1 includes the selected day plus the next day, and so on.", source)
        self.assertIn("1 groups same-day reminders; 2 groups reminders within 2 days, and so on.", source)

    def test_redundant_all_reminders_actioned_info_box_removed(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn("Good job! All due reminders have been actioned.", source)
        self.assertNotIn('st.info("All reminders have been actioned.")', source)

    def test_death_keyword_panel_does_not_render_inline_keyword_summary(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn("auto-death-keyword-chip", source)
        self.assertIn("auto_death_keyword_row_", source)
        self.assertIn("Reset keywords", source)
        self.assertIn("chip_cols = st.columns([1.1, 0.16, 6.74], gap=\"small\")", source)
        self.assertIn('[class*="st-key-auto_death_keyword_row_"]', source)
        self.assertIn("background: transparent !important;", source)
        self.assertIn("border-color: transparent !important;", source)
        self.assertIn("display: flex;\n        align-items: center;", source)
        self.assertNotIn("cols = st.columns([1, 0.12], gap=\"small\")", source)
        self.assertNotIn("max-width: min(100%, 42rem);", source)
        self.assertNotIn("st.columns([0.58, 0.18, 6.84]", source)
        self.assertNotIn('", ".join(f"`{keyword}`"', source)

    def test_login_google_button_sits_above_staff_and_signup_buttons(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn("google_signup_col = st.columns(1)[0]", source)
        self.assertIn("staff_access_col, manual_signup_col = st.columns(2, gap=\"small\")", source)
        self.assertIn(
            'div[data-testid="stHorizontalBlock"]:has(.st-key-toggle_staff_access):has(.st-key-toggle_create_account)',
            source,
        )

    def test_stats_page_folds_outcomes_and_actioning_tabs(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn('MAIN_SECTION_TABS = ["Reminders", "Search Terms", "Exclusions", "Stats", "Upload Data", "Get Started", "Graphs"]', source)
        self.assertIn('"Reminders": "Send Reminders"', source)
        self.assertIn('"Search Terms": "Configure Reminders"', source)
        self.assertIn('"Stats": "Identify & Track"', source)
        self.assertIn('"outcomes": "Stats"', source)
        self.assertIn('"statistics": "Stats"', source)
        self.assertIn('st.markdown("## 📊 Stats")', source)
        self.assertIn('STATS_REVENUE_SUBTAB = "Revenue"', source)
        self.assertIn('STATS_PERIOD_FILTERED_SUBTABS = ["Items", "Successes", "Reminders", "Team"]', source)
        self.assertIn('"Reminders": "Reminder Outcomes"', source)
        self.assertIn("STATS_SUBTABS = [STATS_REVENUE_SUBTAB, *STATS_PERIOD_FILTERED_SUBTABS]", source)
        self.assertIn("def render_stats_subtab_selector", source)
        self.assertIn("def stats_subtab_button_key", source)
        self.assertIn("cr-stats-subtab-rule", source)
        self.assertIn("st.button(\n                tab_name", source)
        self.assertIn('[class*="st-key-reminders_subtab_"] button,', source)
        self.assertIn('[class*="st-key-reminders_subtab_"] button p,', source)
        self.assertIn('STATS_SENT_REMINDER_PERIODS = ["Today", "Past", "All-time", "Calendar", "Custom"]', source)
        self.assertIn('STATS_PAST_PERIODS = ["Past week", "Past month", "Past 3 months", "Past 6 months", "Past year", "Past 2 years"]', source)
        self.assertIn("stats-period-selector-title", source)
        self.assertIn('"Sent reminders period"', source)
        self.assertNotIn("filtered by Sent Date", source)
        self.assertNotIn("filtered by Success Date", source)
        self.assertIn(".stats-summary-card", source)
        self.assertIn("stats-summary-value", source)
        self.assertIn("stats-summary-tab-gap", source)
        self.assertIn("start_col, lookback_col, window_col, group_col, warning_col = st.columns([2, 2, 2, 2, 2])", source)
        self.assertNotIn("today_button_col", source)
        self.assertNotIn("cr-today-button-spacer", source)
        self.assertIn('div[data-baseweb="tooltip"]', source)
        self.assertIn("animation: none !important;", source)
        self.assertIn("transition: none !important;", source)
        self.assertNotIn("animation-delay: 75ms", source)
        self.assertNotIn("transition-delay: 75ms", source)
        self.assertIn("build_stats_team_frame", source)
        self.assertNotIn("All time; generated reminders and saved actions by actual item.", source)
        self.assertNotIn("All time; outcome results by sender plus reminder actions by actioned date.", source)
        self.assertNotIn('st.segmented_control(\n            "Stats view"', source)
        self.assertNotIn('st.segmented_control(\n            "Statistics period"', source)
        self.assertNotIn('["Overview", "Team", "Items", "Completion"]', source)
        self.assertIn('STATISTICS_SCHEDULED_REMINDERS_LABEL = "Scheduled reminders"', source)

    def test_graphs_tab_is_coming_soon_placeholder(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn('"graphs": "Graphs"', source)
        self.assertIn('"Graphs": "graphs"', source)
        self.assertIn("def graphs_badge_label", source)
        self.assertIn("Graphs coming soon", source)
        self.assertIn("def render_graphs_coming_soon", source)
        self.assertNotIn('st.error("Coming soon")', source)
        self.assertIn("graphs-coming-soon-art", source)

    def test_search_terms_reset_configurations_is_separated_and_warned(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        top_unreminded_start = source.index("render_top_unreminded_items_section()")
        reset_block_start = source.index("reset-config-warning")
        section_end = source.index("# --------------------------------", reset_block_start)
        reset_block = source[reset_block_start:section_end]

        self.assertLess(top_unreminded_start, reset_block_start)
        self.assertIn("st.divider()", source[top_unreminded_start - 80:top_unreminded_start])
        self.assertIn("st.divider()", source[reset_block_start - 80:reset_block_start])
        self.assertIn("Warning: resetting will remove all added search terms and settings.", reset_block)
        self.assertIn('"Reset all Configurations"', reset_block)
        self.assertIn('key="reset_all_configurations"', reset_block)
        self.assertIn("min-width: 18rem;", reset_block)
        self.assertNotIn("use_container_width=True", reset_block)
        self.assertIn(".st-key-reset_all_configurations button", reset_block)
        self.assertIn('st.session_state["show_reset_configurations_dialog"] = True', reset_block)
        self.assertIn("render_reset_configurations_dialog()", reset_block)
        self.assertNotIn('"Reset defaults"', reset_block)
        self.assertIn("Coming Soon", source)

        dialog_start = source.index("def render_reset_configurations_dialog")
        dialog_end = source.index("def save_rule_category", dialog_start)
        dialog_block = source[dialog_start:dialog_end]

        self.assertIn('@st.dialog("Reset all Configurations")', dialog_block)
        self.assertIn("This will remove all added search terms and settings.", dialog_block)
        self.assertIn('"Yes, reset everything"', dialog_block)
        self.assertIn("reset_all_configurations()", dialog_block)

    def test_floating_whatsapp_support_widget_is_available(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn('SUPPORT_WHATSAPP_NUMBER = "+97142416777"', source)
        self.assertIn('SUPPORT_WHATSAPP_URL = "https://wa.me/97142416777"', source)
        self.assertIn("def render_floating_whatsapp_support_widget", source)
        self.assertIn("textwrap.dedent", source)
        self.assertIn("support_link_html = (", source)
        self.assertIn("cr-whatsapp-support", source)
        self.assertIn('<svg viewBox="0 0 32 32"', source)
        self.assertIn(".cr-whatsapp-support-icon svg", source)
        self.assertIn(".cr-whatsapp-support-icon path", source)
        self.assertIn('target="_blank"', source)
        self.assertIn('rel="noopener noreferrer"', source)
        self.assertIn("WhatsApp support", source)
        self.assertIn("render_floating_whatsapp_support_widget()", source)
        self.assertIn("bottom: 4.75rem;", source)
        self.assertIn("right: 1.25rem;", source)
        self.assertIn("height: 3rem;", source)
        self.assertIn("width: 3rem;", source)
        self.assertIn("height: 2.85rem;", source)
        self.assertIn("width: 2.85rem;", source)
        self.assertNotIn('aria-hidden="true">WA</span>', source)
        self.assertNotIn("cr-whatsapp-support-text", source)

    def test_search_term_headers_bottom_align_wrapped_labels(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn(".search-term-column-header", source)
        self.assertIn('div[data-testid="stHorizontalBlock"]:has(.search-term-column-header)', source)
        self.assertIn("justify-content: flex-end !important;", source)
        self.assertIn("align-items: flex-end;", source)
        self.assertIn("min-height: 3.1rem;", source)
        self.assertIn("HELP_ICON_HTML = (", source)
        self.assertIn("column-help-svg", source)
        self.assertIn("flex: 0 0 auto;", source)
        self.assertIn("flex-shrink: 0;", source)
        self.assertIn("viewBox='-24 -24 560 560'", source)
        self.assertIn("min-width: 1.08em;", source)
        self.assertIn("max-width: 1.08em;", source)
        self.assertIn("overflow: visible;", source)
        self.assertIn("border: 0;", source)
        self.assertIn("white-space: nowrap;", source)
        self.assertNotIn(">?</span>", source)
        self.assertNotIn(">i</span>", source)

    def test_top_unreminded_bulk_exclude_buttons_have_button_affordance(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn('[class*="st-key-top_unreminded_"][class*="_exclude_all"] button', source)
        self.assertIn("border: 1px solid rgba(217, 45, 32, 0.36) !important;", source)
        self.assertIn("border-radius: 8px !important;", source)
        self.assertIn("font-size: 0.98rem !important;", source)
        self.assertIn("margin-left: auto !important;", source)
        self.assertIn("width: fit-content !important;", source)
        self.assertIn("Exclude all 10", source)

    def test_whatsapp_composer_heading_has_pen_icon(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn('st.write("### 🖊️ WhatsApp Composer")', source)
        self.assertIn('st.markdown("### 🧩 WhatsApp Template Editor")', source)

    def test_search_term_categories_render_as_wrapped_button_tabs(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn("def render_search_term_category_selector", source)
        self.assertIn("SEARCH_TERM_CATEGORIES[:8]", source)
        self.assertIn("SEARCH_TERM_CATEGORIES[8:]", source)
        self.assertIn('class="cr-search-term-category-rule"', source)
        self.assertNotIn("category_tabs = st.tabs", source)
        self.assertIn("Dental", source)
        self.assertIn("Medications", source)
        self.assertIn("Mobility & Pain", source)

    def test_search_term_quantity_column_uses_short_label_with_example_help(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn('column_header("Use Qty", "Use quantity to extend the due date, for example 2 x 30 days becomes 60 days.")', source)
        self.assertNotIn('column_header("Multiply by quantity"', source)

    def test_search_term_current_columns_keep_second_reminder_help_inline(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn("add_rule_col_widths = [2.2, 1.35, 0.9, 0.9, 1.1, 1.1, 1.95, 0.45, 0.65]", source)
        self.assertIn("current_rule_col_widths = [2.25, 0.9, 0.95, 1.05, 1.05, 1.75, 0.45", source)

    def test_search_term_due_date_reminder_copy_marks_add_field_required(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn('column_header("Due date reminder (Required)"', source)
        self.assertIn('column_header("Due date reminder"', source)
        self.assertIn('"Due date reminder", value=str(settings["days"])', source)
        self.assertNotIn('column_header("Due after days"', source)

    def test_reminder_table_sort_headers_can_wrap_on_narrow_screens(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")
        actioned_css = source[
            source.index('[class*="st-key-{safe_key_prefix}_actioned_sort_"] button')
            : source.index("</style>", source.index('[class*="st-key-{safe_key_prefix}_actioned_sort_"] button'))
        ]
        active_css = source[
            source.index('[class*="st-key-{safe_key_prefix}_sort_"] button')
            : source.index("</style>", source.index('[class*="st-key-{safe_key_prefix}_sort_"] button'))
        ]

        for selector in [
            '[class*="st-key-{safe_key_prefix}_sort_"] button',
            '[class*="st-key-{safe_key_prefix}_sort_"] button p',
            '[class*="st-key-{safe_key_prefix}_actioned_sort_"] button',
            '[class*="st-key-{safe_key_prefix}_actioned_sort_"] button p',
        ]:
            with self.subTest(selector=selector):
                self.assertIn(selector, source)
        for css_block in [actioned_css, active_css]:
            with self.subTest(css_block=css_block[:50]):
                self.assertIn("white-space: normal !important;", css_block)
                self.assertIn("overflow-wrap: anywhere !important;", css_block)
                self.assertNotIn("white-space: nowrap !important;", css_block)

    def test_get_started_reset_button_stays_inside_setup_panel(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")
        checklist_source = source[
            source.index("def render_setup_checklist")
            : source.index("def render_graphs_coming_soon")
        ]

        self.assertIn('with st.container(key="get_started_reset_row"):', checklist_source)
        self.assertIn('[class*="st-key-get_started_reset_row"]', source)
        self.assertIn("width: 100% !important;", source)
        self.assertIn("width: 9rem !important;", source)
        self.assertNotIn("reset_col, _ = st.columns([0.85, 5]", checklist_source)


if __name__ == "__main__":
    unittest.main()
