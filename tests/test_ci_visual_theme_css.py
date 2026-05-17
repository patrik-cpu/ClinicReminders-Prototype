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
        ]:
            with self.subTest(selector=selector):
                self.assertIn(selector, source)

        self.assertIn("color-scheme: light !important;", source)
        self.assertIn("background: #ffffff !important;", source)
        self.assertIn("-webkit-text-fill-color: #101828 !important;", source)
        self.assertIn('[data-baseweb="checkbox"] input[type="checkbox"]', source)
        self.assertRegex(
            source,
            r'div\[data-testid="stCheckbox"\] \[data-baseweb="checkbox"\] \{\s+background: transparent !important;',
        )
        self.assertNotIn(
            'div[data-testid="stCheckbox"] [data-baseweb="checkbox"] {\n        background: #ffffff !important;',
            source,
        )

    def test_streamlit_theme_defaults_to_light(self):
        config = (REPO_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")

        self.assertIn('base = "light"', config)
        self.assertIn('backgroundColor = "#f6faf7"', config)


if __name__ == "__main__":
    unittest.main()
