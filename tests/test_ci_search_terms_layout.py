import unittest
from pathlib import Path


class SearchTermsLayoutTests(unittest.TestCase):
    def test_add_new_search_term_examples_keep_layout_hooks(self):
        source = Path(__file__).resolve().parents[1].joinpath("reminders_app_v3.py").read_text(encoding="utf-8")
        add_term_start = source.index('st.markdown("### Add New Search Term")')
        add_term_end = source.index('if st.button("➕ Add"', add_term_start)
        add_term_source = source[add_term_start:add_term_end]

        self.assertIn("def field_examples(", add_term_source)
        for example_key in (
            "search-term",
            "category",
            "first-reminder",
            "second-reminder",
            "due-date",
            "overdue",
            "message-text",
            "use-qty",
        ):
            self.assertIn(f'example_key="{example_key}"', add_term_source)

        self.assertIn('"use-qty-examples"', add_term_source)
        self.assertIn('data-field-examples="{html_lib.escape(example_key, quote=True)}"', add_term_source)
        self.assertIn('data-example-line="1"', add_term_source)
        self.assertIn('data-example-line="2"', add_term_source)

    def test_use_qty_example_spacer_has_dedicated_css(self):
        source = Path(__file__).resolve().parents[1].joinpath("reminders_app_v3.py").read_text(encoding="utf-8")
        css_start = source.index(".field-examples {")
        css_end = source.index('div[data-testid="stHorizontalBlock"]:has(.search-term-column-header)', css_start)
        css_source = source[css_start:css_end]

        self.assertIn(".field-examples.use-qty-examples", css_source)
        self.assertIn("min-height: 3.15rem;", css_source)
        self.assertIn("transform: translateY(0.18rem);", css_source)
