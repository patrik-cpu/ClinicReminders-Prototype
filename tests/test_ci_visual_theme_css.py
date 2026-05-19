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
        self.assertIn("padding-bottom: 7rem !important;", source)
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

    def test_streamlit_theme_defaults_to_light(self):
        config = (REPO_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")

        self.assertIn('base = "light"', config)
        self.assertIn('backgroundColor = "#f6faf7"', config)

    def test_main_section_selected_tab_has_visible_state(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        for selector in [
            ".cr-main-section-nav-rule",
            '[class*="st-key-main_section_nav_"] button',
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
        self.assertNotIn('<a class="cr-main-section-tab"', source)
        self.assertNotIn('href="?{MAIN_SECTION_TAB_QUERY_PARAM}', source)
        self.assertIn("box-shadow: inset 0 4px 0 var(--cr-primary-dark), 0 1px 0 var(--cr-primary) !important;", source)
        self.assertIn("background: var(--cr-primary) !important;", source)

    def test_outcome_success_window_label_matches_due_date_logic(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn("Success window around due date", source)
        self.assertIn("within this many days before or after the due date", source)
        self.assertNotIn("Days to define success", source)

    def test_statistics_explains_mixed_date_filters(self):
        source = (REPO_ROOT / "reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertIn("Overview, Items, Completion, and the daily chart use Reminder Date", source)
        self.assertIn("Team uses Actioned Date", source)
        self.assertIn("Filtered by Reminder Date: reminders scheduled in the selected period.", source)
        self.assertIn("Filtered by Actioned Date: reminders marked sent or declined in the selected period.", source)


if __name__ == "__main__":
    unittest.main()
