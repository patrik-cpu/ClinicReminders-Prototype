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
            '.data-assurance-box',
        ]:
            with self.subTest(selector=selector):
                self.assertIn(selector, source)

        self.assertIn("color-scheme: light !important;", source)
        self.assertIn("background: #ffffff !important;", source)
        self.assertIn("-webkit-text-fill-color: #101828 !important;", source)
        self.assertIn(".st-key-login_password_input input", source)
        self.assertNotIn(".st-key-login_password_input button {\n        display: none !important;", source)
        self.assertNotIn(".st-key-login_password_input [data-baseweb=\"base-input\"] > div:has(button)", source)
        self.assertNotIn("text-security: disc !important;", source)
        self.assertIn("padding-top: 3.45rem !important;", source)
        self.assertIn("padding-bottom: max(10rem, 74vh) !important;", source)
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
            ".exclusion-chip",
            "exclusion_chip_html",
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
        self.assertIn("min(2.9, len(tab_name) / 7", source)
        self.assertIn("display: inline-flex !important;", source)
        self.assertIn("align-items: center !important;", source)
        self.assertIn("vertical-align: middle !important;", source)
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
        self.assertIn("A success is one matching repeat purchase either near the due date or soon after the reminder was sent.", source)
        self.assertIn("Multiple reminder steps for the same purchase cycle still count once.", source)
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
        self.assertIn("cols = st.columns([1, 0.12], gap=\"small\")", source)
        self.assertIn('[class*="st-key-auto_death_keyword_row_"]', source)
        self.assertIn("max-width: min(100%, 42rem);", source)
        self.assertIn("margin-top: 0;", source)
        self.assertIn("align-items: center;\n        display: flex;", source)
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

        self.assertIn('MAIN_SECTION_TABS = ["Reminders", "Get Started", "Upload Data", "Search Terms", "Exclusions", "Stats", "Graphs"]', source)
        self.assertIn('"outcomes": "Stats"', source)
        self.assertIn('"statistics": "Stats"', source)
        self.assertIn('st.markdown("## 📊 Stats")', source)
        self.assertIn("See which reminders were sent, which ones led to repeat purchases", source)
        self.assertIn('STATS_SUBTABS = ["Items", "Item Activity", "Team", "Sent Reminders", "Successes"]', source)
        self.assertIn("def render_stats_subtab_selector", source)
        self.assertIn("def stats_subtab_button_key", source)
        self.assertIn("cr-stats-subtab-rule", source)
        self.assertIn("st.button(\n                tab_name", source)
        self.assertIn('STATS_SENT_REMINDER_PERIODS = ["Today", "Previous 7 days", "Previous 30 days", "All-time", "Custom"]', source)
        self.assertIn('"Sent reminders period"', source)
        self.assertIn("filtered by Sent Date", source)
        self.assertIn(".stats-summary-card", source)
        self.assertIn("stats-summary-value", source)
        self.assertIn("stats-summary-tab-gap", source)
        self.assertIn('div[data-baseweb="tooltip"]', source)
        self.assertIn("animation: none !important;", source)
        self.assertIn("transition: none !important;", source)
        self.assertNotIn("animation-delay: 75ms", source)
        self.assertNotIn("transition-delay: 75ms", source)
        self.assertIn("build_stats_team_frame", source)
        self.assertIn("All time; generated reminders and saved actions by actual item.", source)
        self.assertIn("All time; outcome results by sender plus reminder actions by actioned date.", source)
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
        self.assertIn("Check back soon", source)

    def test_search_term_headers_bottom_align_wrapped_labels(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn(".search-term-column-header", source)
        self.assertIn('div[data-testid="stHorizontalBlock"]:has(.search-term-column-header)', source)
        self.assertIn("justify-content: flex-end !important;", source)
        self.assertIn("align-items: flex-end;", source)
        self.assertIn("min-height: 3.1rem;", source)

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

        self.assertIn("add_rule_col_widths = [2.2, 1.35, 0.9, 0.9, 1.1, 1.1, 0.45, 1.95, 0.65]", source)
        self.assertIn("current_rule_col_widths = [2.25, 0.9, 0.95, 1.05, 1.05, 0.45, 1.75", source)

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
        self.assertIn("width: 9rem !important;", source)
        self.assertNotIn("reset_col, _ = st.columns([0.85, 5]", checklist_source)


if __name__ == "__main__":
    unittest.main()
