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
            '.st-key-login_password_input [data-baseweb="base-input"] > div',
            '.data-assurance-box',
        ]:
            with self.subTest(selector=selector):
                self.assertIn(selector, source)

        self.assertIn("color-scheme: light !important;", source)
        self.assertIn("background: #ffffff !important;", source)
        self.assertIn("-webkit-text-fill-color: #101828 !important;", source)
        self.assertIn("padding-top: 3.45rem !important;", source)
        self.assertIn("padding-bottom: max(7rem, 42vh) !important;", source)
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
        ]:
            with self.subTest(selector=selector):
                self.assertIn(selector, source)

    def test_streamlit_theme_defaults_to_light(self):
        config = (REPO_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")

        self.assertIn('base = "light"', config)
        self.assertIn('backgroundColor = "#f6faf7"', config)

    def test_main_section_selected_tab_has_visible_state(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

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
        self.assertIn("nav_spacer_width = 7.8", source)
        self.assertIn("[*widths, nav_spacer_width]", source)
        self.assertIn("min(2.9, len(tab_name) / 7", source)
        self.assertNotIn('<a class="cr-main-section-tab"', source)
        self.assertNotIn('href="?{MAIN_SECTION_TAB_QUERY_PARAM}', source)
        self.assertIn("font-size: 1.18rem", source)
        self.assertIn("min-height: 2.85rem", source)
        self.assertIn("box-shadow: 0 0 0 1px var(--cr-primary-dark), 0 1px 0 var(--cr-primary) !important;", source)
        self.assertNotIn("box-shadow: inset 0 4px 0 var(--cr-primary-dark)", source)
        self.assertIn("background: var(--cr-primary) !important;", source)
        self.assertIn("flex: 0 0 auto !important;", source)

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
        self.assertIn("Reset keywords", source)
        self.assertNotIn('", ".join(f"`{keyword}`"', source)

    def test_stats_page_folds_outcomes_and_actioning_tabs(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn('MAIN_SECTION_TABS = ["Reminders", "Get Started", "Upload Data", "Search Terms", "Exclusions", "Stats"]', source)
        self.assertIn('"outcomes": "Stats"', source)
        self.assertIn('"statistics": "Stats"', source)
        self.assertIn('st.markdown("## 📊 Stats")', source)
        self.assertIn("See which reminders were sent, which ones led to repeat purchases", source)
        self.assertIn('["Items", "Item Actioning", "Team", "Sent Reminders", "Successes"]', source)
        self.assertIn('STATS_SENT_REMINDER_PERIODS = ["Today", "Previous 7 days", "Previous 30 days", "All-time"]', source)
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
        self.assertIn("All time; generated reminders and saved actions grouped by item.", source)
        self.assertIn("All time; outcome results by sender plus reminder actions by actioned date.", source)
        self.assertNotIn('st.segmented_control(\n            "Statistics period"', source)
        self.assertNotIn('["Overview", "Team", "Items", "Completion"]', source)
        self.assertIn('STATISTICS_SCHEDULED_REMINDERS_LABEL = "Scheduled reminders"', source)


if __name__ == "__main__":
    unittest.main()
